"""Geometria do mapa de vínculos.

O jeito de este recurso falhar feio é visual: caixa em cima de caixa, etiqueta
de percentual ilegível, desenho que estoura a página. Nada disso aparece num
teste que só verifica se a função rodou — então o que se testa aqui são as
posições, que é onde o erro mora.
"""
import pytest

from controle_lucros.mapa_vinculos import (
    CAIXA_ALTURA,
    ESPACO_VERTICAL,
    LARGURA_PADRAO,
    MARGEM,
    VAO_LATERAL,
    montar_mapa,
    nome_de_arquivo,
)


def _vinculo(nome, percentual=10.0, entrada="2020-01-15", saida=None):
    return {"empresa_nome": nome, "percentual": percentual, "data_entrada": entrada, "data_saida": saida}


def _mapa(*vinculos, **kwargs):
    return montar_mapa("FULANO DE TAL", "111.111.111-11", list(vinculos), **kwargs)


# ------------------------------------------------------------------- ordem --
def test_ativos_vem_antes_dos_encerrados_e_por_participacao():
    mapa = _mapa(
        _vinculo("PEQUENA LTDA", 5.0),
        _vinculo("SAIU EM 2023 LTDA", 40.0, saida="2023-12-31"),
        _vinculo("GRANDE LTDA", 60.0),
    )
    assert [e.nome for e in _por_ordem_de_leitura(mapa)] == [
        "GRANDE LTDA", "PEQUENA LTDA", "SAIU EM 2023 LTDA",
    ]


def _por_ordem_de_leitura(mapa):
    """As caixas na ordem em que foram distribuídas: esquerda e direita
    alternadas, de cima pra baixo."""
    esquerda = sorted((e for e in mapa.empresas if e.lado == "esquerda"), key=lambda e: e.caixa.y)
    direita = sorted((e for e in mapa.empresas if e.lado == "direita"), key=lambda e: e.caixa.y)
    ordenados = []
    for i in range(max(len(esquerda), len(direita))):
        if i < len(esquerda):
            ordenados.append(esquerda[i])
        if i < len(direita):
            ordenados.append(direita[i])
    return ordenados


def test_participacoes_maiores_sobem_nas_duas_colunas():
    """Alternar os lados mantém as maiores no topo das duas colunas, em vez de
    encher um lado inteiro antes de começar o outro."""
    mapa = _mapa(*[_vinculo(f"EMPRESA {i}", 100 - i) for i in range(6)])
    topo_esquerda = min((e for e in mapa.empresas if e.lado == "esquerda"), key=lambda e: e.caixa.y)
    topo_direita = min((e for e in mapa.empresas if e.lado == "direita"), key=lambda e: e.caixa.y)
    assert topo_esquerda.nome == "EMPRESA 0"
    assert topo_direita.nome == "EMPRESA 1"


def test_lados_ficam_equilibrados():
    mapa = _mapa(*[_vinculo(f"EMPRESA {i}") for i in range(7)])
    esquerda = [e for e in mapa.empresas if e.lado == "esquerda"]
    direita = [e for e in mapa.empresas if e.lado == "direita"]
    assert abs(len(esquerda) - len(direita)) <= 1


# --------------------------------------------------------------- geometria --
@pytest.mark.parametrize("quantidade", [1, 2, 5, 12, 24])
def test_caixas_nunca_se_sobrepoem(quantidade):
    mapa = _mapa(*[_vinculo(f"EMPRESA {i} LTDA") for i in range(quantidade)])
    for lado in ("esquerda", "direita"):
        coluna = sorted((e for e in mapa.empresas if e.lado == lado), key=lambda e: e.caixa.y)
        for anterior, seguinte in zip(coluna, coluna[1:]):
            assert seguinte.caixa.y >= anterior.caixa.y + CAIXA_ALTURA + ESPACO_VERTICAL - 0.01


@pytest.mark.parametrize("quantidade", [1, 3, 9, 24])
def test_tudo_cabe_dentro_da_tela_do_desenho(quantidade):
    mapa = _mapa(*[_vinculo(f"EMPRESA {i} LTDA") for i in range(quantidade)])
    for empresa in mapa.empresas:
        assert empresa.caixa.x >= MARGEM - 0.01
        assert empresa.caixa.direita <= mapa.largura - MARGEM + 0.01
        assert empresa.caixa.y > 0
        assert empresa.caixa.y + CAIXA_ALTURA <= mapa.altura


def test_caixas_nunca_encostam_no_hub():
    """O vão entre a caixa e o hub é onde a etiqueta do percentual fica. Se
    encostar, a etiqueta cobre o nome da empresa."""
    mapa = _mapa(*[_vinculo(f"EMPRESA {i} LTDA") for i in range(8)])
    for empresa in mapa.empresas:
        if empresa.lado == "esquerda":
            assert mapa.hub.x - empresa.caixa.direita >= VAO_LATERAL - 0.01
        else:
            assert empresa.caixa.x - mapa.hub.direita >= VAO_LATERAL - 0.01


def test_hub_fica_centralizado_na_altura_das_colunas():
    mapa = _mapa(*[_vinculo(f"EMPRESA {i}") for i in range(6)])
    topos = [e.caixa.y for e in mapa.empresas]
    bases = [e.caixa.y + CAIXA_ALTURA for e in mapa.empresas]
    centro_das_caixas = (min(topos) + max(bases)) / 2
    assert abs(mapa.hub.centro_y - centro_das_caixas) < 1


def test_desenho_cresce_com_o_numero_de_empresas():
    pequeno = _mapa(_vinculo("UMA LTDA"))
    grande = _mapa(*[_vinculo(f"EMPRESA {i}") for i in range(12)])
    assert grande.altura > pequeno.altura
    assert pequeno.largura == grande.largura == LARGURA_PADRAO


def test_sem_vinculos_ainda_desenha_o_socio():
    mapa = _mapa()
    assert mapa.empresas == ()
    assert mapa.hub.altura > 0
    assert mapa.resumo() == "Sem vínculos societários registrados."


# ------------------------------------------------------------------ limite --
def test_muitos_vinculos_cortam_pelos_menores_e_avisam():
    mapa = _mapa(*[_vinculo(f"EMPRESA {i}", percentual=100 - i) for i in range(30)], maximo=10)
    assert len(mapa.empresas) == 10
    assert mapa.empresas_omitidas == 20
    assert "não cabem no desenho" in mapa.resumo()
    # Os que sobraram são os de maior participação, não os dez primeiros da lista.
    assert min(e.percentual for e in mapa.empresas) == 91


# -------------------------------------------------------------- conteúdo --
def test_periodo_do_vinculo_sai_em_data_brasileira():
    ativo, encerrado = _mapa(
        _vinculo("ATIVA LTDA", 60.0, entrada="2007-03-23"),
        _vinculo("FECHADA LTDA", 40.0, entrada="2010-01-05", saida="2023-12-31"),
    ).empresas
    assert ativo.periodo == "desde 23/03/2007"
    assert encerrado.periodo == "05/01/2010 — 31/12/2023"


def test_data_estranha_nao_derruba_o_desenho():
    """Um mapa com uma data torta ainda serve; um mapa que não abre, não."""
    (empresa,) = _mapa(_vinculo("ESTRANHA LTDA", entrada="sem data")).empresas
    assert "sem data" in empresa.periodo


def test_resumo_conta_ativos_e_encerrados():
    mapa = _mapa(
        _vinculo("A LTDA", 60.0),
        _vinculo("B LTDA", 30.0),
        _vinculo("C LTDA", 10.0, saida="2024-01-01"),
    )
    assert mapa.ativos == 2
    assert mapa.encerrados == 1
    assert mapa.resumo() == "2 vínculo(s) ativo(s) · 1 encerrado(s)"


def test_nome_de_arquivo_sem_acento_nem_espaco():
    # O acento sai da letra, sem virar "_": "joão" vira "joao", não "jo_o".
    assert nome_de_arquivo("JOÃO DA SILVA", "pdf") == "mapa_vinculos_joao_da_silva.pdf"
    assert nome_de_arquivo("MARIA DA CONCEIÇÃO", "svg") == "mapa_vinculos_maria_da_conceicao.svg"
    assert nome_de_arquivo("", "svg") == "mapa_vinculos_socio.svg"
