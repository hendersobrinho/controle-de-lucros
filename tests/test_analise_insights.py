"""As duas leituras novas: distribuição sem pró-labore e desvio em reais.

São contas que viram conversa com o cliente ("o João recebeu R$ 300 mil além
dos 60% dele"), então errar por um fator ou por um caso de borda é pior do que
não ter a análise. Cada regra de exclusão tem seu caso aqui — sobretudo as que
evitam alarme falso, porque um painel que grita sempre deixa de ser lido.
"""
import pytest

from controle_lucros.analise import desvio_por_socio, resumo_sem_pro_labore, sem_pro_labore


def _linha(**campos):
    base = dict(
        socio_id=1, socio_nome="ANDRE", socio_cpf="076.925.727-55", socio_tipo_pessoa="fisica",
        empresa_id=1, empresa_nome="ACME LTDA", ano_base=2024,
        percentual_capital=60.0, valor_distribuido=300000.0, pro_labore=0.0,
    )
    base.update(campos)
    return base


# ------------------------------------------------- distribuição sem pró-labore
def test_lista_quem_recebeu_lucro_sem_pro_labore():
    (item,) = sem_pro_labore([_linha()])

    assert item.socio_nome == "ANDRE"
    assert item.valor_distribuido == 300000.0
    assert item.anos == (2024,)
    # Sem pró-labore nenhum não é razão "infinita": é outro caso, e o pior.
    assert item.razao is None


def test_quem_recebeu_pro_labore_no_ano_fica_de_fora():
    """Julgar se o pró-labore é compatível com o trabalho não é conta que o
    programa possa fazer — ele só aponta a ausência."""
    assert sem_pro_labore([_linha(pro_labore=5000.0)]) == []


def test_socio_pessoa_juridica_nunca_entra():
    """Holding sócia não tem pró-labore. Listá-la encheria o painel de casos
    que não são caso nenhum."""
    assert sem_pro_labore([_linha(socio_tipo_pessoa="juridica")]) == []


def test_quem_nao_recebeu_distribuicao_nao_e_caso():
    assert sem_pro_labore([_linha(valor_distribuido=0.0)]) == []


def test_soma_o_periodo_e_guarda_os_anos_sem_pro_labore():
    """Três anos seguidos sem pró-labore é uma história diferente de um ano
    isolado, e é isso que a lista precisa deixar ver."""
    (item,) = sem_pro_labore([
        _linha(ano_base=2022, valor_distribuido=100000.0),
        _linha(ano_base=2023, valor_distribuido=150000.0),
        _linha(ano_base=2024, valor_distribuido=200000.0, pro_labore=48000.0),
    ])

    assert item.valor_distribuido == 450000.0
    assert item.pro_labore == 48000.0
    assert item.anos == (2022, 2023)
    assert item.anos_sem_pro_labore == 2
    # A razão usa o período inteiro: 450 mil de lucro para 48 mil de pró-labore.
    assert item.razao == pytest.approx(450000 / 48000)


def test_mesmo_socio_em_duas_empresas_sao_dois_casos():
    itens = sem_pro_labore([
        _linha(empresa_id=1, empresa_nome="ACME LTDA", valor_distribuido=300000.0),
        _linha(empresa_id=2, empresa_nome="BETA LTDA", valor_distribuido=90000.0),
    ])

    assert [(i.empresa_nome, i.valor_distribuido) for i in itens] == [
        ("ACME LTDA", 300000.0), ("BETA LTDA", 90000.0)
    ]


def test_sai_do_maior_valor_para_o_menor():
    itens = sem_pro_labore([
        _linha(socio_id=1, socio_nome="PEQUENO", valor_distribuido=10000.0),
        _linha(socio_id=2, socio_nome="GRANDE", valor_distribuido=900000.0),
    ])

    assert [i.socio_nome for i in itens] == ["GRANDE", "PEQUENO"]


def test_resumo_em_uma_frase():
    assert "Nenhum sócio" in resumo_sem_pro_labore([])
    assert "300.000,00" in resumo_sem_pro_labore(sem_pro_labore([_linha()]))


# ------------------------------------------------------------ desvio em reais
def test_desvio_mede_quanto_saiu_do_eixo():
    """Capital 60/40, distribuição 90/10: o que um recebeu a mais o outro
    recebeu a menos, no mesmo valor."""
    andre, maria = desvio_por_socio([
        _linha(socio_id=1, socio_nome="ANDRE", percentual_capital=60.0, valor_distribuido=900000.0),
        _linha(socio_id=2, socio_nome="MARIA", percentual_capital=40.0, valor_distribuido=100000.0),
    ])

    assert andre.valor_proporcional == 600000.0
    assert andre.desvio == 300000.0
    assert maria.valor_proporcional == 400000.0
    assert maria.desvio == -300000.0
    assert andre.percentual_distribuido == 90.0


def test_distribuicao_proporcional_nao_tem_desvio():
    itens = desvio_por_socio([
        _linha(socio_id=1, percentual_capital=60.0, valor_distribuido=600000.0),
        _linha(socio_id=2, socio_nome="MARIA", percentual_capital=40.0, valor_distribuido=400000.0),
    ])

    assert all(item.desvio == pytest.approx(0) for item in itens)


def test_o_esperado_sai_do_total_daquele_ano():
    """Misturar anos daria um "esperado" que nunca existiu: o total de cada ano
    é o que a participação divide."""
    (item,) = desvio_por_socio([
        _linha(ano_base=2023, percentual_capital=50.0, valor_distribuido=100000.0),
        _linha(ano_base=2024, percentual_capital=50.0, valor_distribuido=300000.0),
    ])

    # Sócio único: recebeu tudo nos dois anos, e 50% de cada total é metade.
    assert item.valor_distribuido == 400000.0
    assert item.valor_proporcional == 200000.0


def test_empresa_que_nao_distribuiu_no_ano_nao_gera_desvio():
    assert desvio_por_socio([_linha(valor_distribuido=0.0)]) == []


def test_ordena_pelo_tamanho_do_desvio_nos_dois_sentidos():
    """Receber a menos está tão fora do eixo quanto receber a mais: o que
    ordena é o tamanho do desvio, não o sinal."""
    itens = desvio_por_socio([
        _linha(socio_id=1, socio_nome="NO EIXO", empresa_id=2, empresa_nome="BETA",
               percentual_capital=50.0, valor_distribuido=50000.0),
        _linha(socio_id=2, socio_nome="TAMBEM NO EIXO", empresa_id=2, empresa_nome="BETA",
               percentual_capital=50.0, valor_distribuido=50000.0),
        _linha(socio_id=3, socio_nome="RECEBEU A MENOS", percentual_capital=90.0, valor_distribuido=100000.0),
        _linha(socio_id=4, socio_nome="RECEBEU A MAIS", percentual_capital=10.0, valor_distribuido=900000.0),
    ])

    # Os dois maiores desvios vêm primeiro, um negativo e um positivo; quem
    # está no eixo fica por último.
    assert {round(i.desvio) for i in itens[:2]} == {800000, -800000}
    assert [round(i.desvio) for i in itens[2:]] == [0, 0]


def test_limite_corta_a_lista():
    linhas = [_linha(socio_id=i, socio_nome=f"S{i}", valor_distribuido=1000.0 * i) for i in range(1, 6)]
    assert len(sem_pro_labore(linhas, limite=3)) == 3
    assert len(desvio_por_socio(linhas, limite=2)) == 2
