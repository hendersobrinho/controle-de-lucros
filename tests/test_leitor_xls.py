"""Leitura de planilha .xls antiga (BIFF8).

O formato é binário e cheio de detalhe — container OLE, tabela de textos
compartilhados, número comprimido, data que é número com formato de data. Cada
um desses detalhes tem seu caso aqui, porque errar qualquer um deles não
quebra a importação: faz entrar dado errado, que é pior.

Os arquivos são gerados pelo apoio_xls.py, que escreve .xls de verdade — testar
isto contra uma planilha falsa não provaria nada.
"""
import datetime as dt
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from controle_lucros.leitor_xls import XlsIlegivel, e_xls_antigo, ler_xls
from controle_lucros.relatorio_socios import RelatorioInvalido, ler_relatorio_de_planilha

from apoio_xls import escrever_xls

RELATORIO = [
    ["Empresa:", "METODOS SERVICOS CONTABEIS LTDA", "Página:", "1/1"],
    ["C.N.P.J.:", "02294442000113", "Emissão:", dt.date(2026, 9, 9)],
    [],
    ["CADASTRO DE SÓCIOS"],
    ["Código", "Nome", "Inscrição", "Participação(%)", "Data de ingresso", "Data saída"],
    ["Empresa:", "91 - ENDOGASTRO CLINICA MEDICA LTDA", "Data do quadro societário:",
     dt.date(2026, 5, 20)],
    [75, "ANDRE FRANZOTTI CARDOSO", "07692572755", 46.94, dt.date(2007, 3, 23), ""],
    [707, "LUIZA DIAS TORRES", "10328582735", 0.0, dt.date(2023, 3, 2), dt.date(2026, 5, 20)],
    [894, "SUELLEN SAMPAIO LAUER", "12255824744", 0.51, dt.date(2024, 9, 25), ""],
    [],
    ["Sistema licenciado para METODOS SERVICOS CONTABEIS LTDA"],
]


# ------------------------------------------------------------- o container --
@pytest.mark.parametrize("no_mini_fluxo", [False, True])
def test_le_a_planilha_nos_dois_lugares_onde_o_fluxo_pode_morar(tmp_path, no_mini_fluxo):
    """Fluxo pequeno deveria morar no "mini fluxo"; exportador desleixado
    grava nos setores normais assim mesmo. Os dois casos existem em arquivo de
    verdade."""
    caminho = escrever_xls(tmp_path / "r.xls", RELATORIO, no_mini_fluxo=no_mini_fluxo)

    linhas = ler_xls(caminho)

    assert linhas[6][1] == "ANDRE FRANZOTTI CARDOSO"
    assert linhas[7][5] == dt.date(2026, 5, 20)


def test_reconhece_xls_de_verdade_pela_assinatura(tmp_path):
    verdadeiro = escrever_xls(tmp_path / "bom.xls", RELATORIO)
    falso = tmp_path / "falso.xls"
    falso.write_text("Empresa;Sócio\nACME;FULANO\n", encoding="utf-8")

    assert e_xls_antigo(verdadeiro)
    assert not e_xls_antigo(falso)
    assert not e_xls_antigo(tmp_path / "nem_existe.xls")


def test_arquivo_renomeado_explica_o_que_fazer(tmp_path):
    caminho = tmp_path / "planilha.xls"
    caminho.write_text("isto aqui é um CSV com nome de xls", encoding="utf-8")

    with pytest.raises(XlsIlegivel, match="salve como"):
        ler_xls(caminho)


def test_arquivo_truncado_nao_derruba_o_programa(tmp_path):
    inteiro = escrever_xls(tmp_path / "r.xls", RELATORIO)
    pedaco = tmp_path / "pedaco.xls"
    pedaco.write_bytes(open(inteiro, "rb").read()[:900])

    with pytest.raises(XlsIlegivel):
        ler_xls(pedaco)


# ------------------------------------------------------------- as células --
def test_tipos_de_celula_saem_como_o_esperado(tmp_path):
    caminho = escrever_xls(tmp_path / "r.xls", RELATORIO)

    linhas = ler_xls(caminho)

    codigo, nome, inscricao, percentual, entrada, saida = linhas[6][:6]
    assert codigo == 75.0                     # número
    assert nome == "ANDRE FRANZOTTI CARDOSO"  # texto
    assert inscricao == "07692572755"         # texto que parece número
    assert percentual == 46.94
    assert entrada == dt.date(2007, 3, 23)    # número com formato de data
    assert saida == ""                        # célula vazia


def test_data_so_e_data_quando_a_celula_esta_formatada_como_data(tmp_path):
    """No Excel, data é um número com uma roupa. Sem olhar o formato, toda
    data viraria um número de cinco dígitos no cadastro."""
    caminho = escrever_xls(tmp_path / "r.xls", RELATORIO, formato_data="0.00")

    linhas = ler_xls(caminho)

    assert linhas[6][4] == 39164.0  # o mesmo 23/03/2007, agora sem a roupa


def test_texto_acentuado_sobrevive(tmp_path):
    conteudo = [
        ["Empresa:", "91 - CLÍNICA MÉDICA LTDA"],
        [1, "BÁRBARA GONÇALVES SANT'ANA", "07692572755", 100.0, dt.date(2020, 1, 1)],
    ]
    caminho = escrever_xls(tmp_path / "r.xls", conteudo)

    assert ler_xls(caminho)[1][1] == "BÁRBARA GONÇALVES SANT'ANA"


def test_planilha_vazia_devolve_nada(tmp_path):
    assert ler_xls(escrever_xls(tmp_path / "vazia.xls", [[], []])) == []


# ---------------------------------------------- o relatório de ponta a ponta --
def test_relatorio_em_xls_da_no_mesmo_que_o_de_pdf(tmp_path):
    caminho = escrever_xls(tmp_path / "socios.xls", RELATORIO)

    leitura = ler_relatorio_de_planilha(ler_xls(caminho))

    (empresa,) = leitura.empresas
    assert empresa.numero == "91"
    assert empresa.nome == "ENDOGASTRO CLINICA MEDICA LTDA"
    assert empresa.data_quadro == "2026-05-20"
    assert [s.nome for s in empresa.socios] == [
        "ANDRE FRANZOTTI CARDOSO", "LUIZA DIAS TORRES", "SUELLEN SAMPAIO LAUER",
    ]

    andre, luiza, _suellen = empresa.socios
    # O CPF sai pontuado mesmo vindo cru da planilha: o cadastro não pode ficar
    # com dois jeitos de gravar o mesmo documento.
    assert andre.inscricao == "076.925.727-55"
    assert andre.percentual == 46.94
    assert andre.data_entrada == "2007-03-23"
    assert andre.data_saida is None
    assert luiza.data_saida == "2026-05-20"


def test_cabecalho_do_escritorio_na_planilha_nao_vira_socio(tmp_path):
    """A segunda linha tem o CNPJ do escritório e uma data de emissão — tudo
    de que um sócio precisa, menos ser um."""
    caminho = escrever_xls(tmp_path / "socios.xls", RELATORIO)

    leitura = ler_relatorio_de_planilha(ler_xls(caminho))

    assert leitura.total_socios == 3
    assert leitura.ignoradas == []
    nomes = [s.nome for e in leitura.empresas for s in e.socios]
    assert not any("C.N.P.J" in n or "METODOS" in n for n in nomes)


def test_participacao_antes_das_datas_e_lida_igual(tmp_path):
    """A planilha traz as colunas em ordem diferente da do PDF — participação
    antes das datas. Como a leitura se ancora no CPF, tanto faz."""
    conteudo = [
        ["Empresa:", "91 - ENDOGASTRO LTDA"],
        [75, "ANDRE FRANZOTTI CARDOSO", "07692572755", 46.94, dt.date(2007, 3, 23)],
    ]
    (empresa,) = ler_relatorio_de_planilha(ler_xls(escrever_xls(tmp_path / "r.xls", conteudo))).empresas

    (socio,) = empresa.socios
    assert socio.percentual == 46.94
    assert socio.data_entrada == "2007-03-23"


def test_cpf_guardado_como_numero_recupera_o_zero_da_frente(tmp_path):
    """Planilha que guarda CPF como número perde o zero: 076.925.727-55 vira
    7692572755. O dígito verificador é o que permite repor sem chutar."""
    conteudo = [
        ["Empresa:", "91 - ENDOGASTRO LTDA"],
        [75, "ANDRE FRANZOTTI CARDOSO", 7692572755, 46.94, dt.date(2007, 3, 23)],
    ]
    (empresa,) = ler_relatorio_de_planilha(ler_xls(escrever_xls(tmp_path / "r.xls", conteudo))).empresas

    assert empresa.socios[0].inscricao == "076.925.727-55"


def test_numero_qualquer_nao_vira_cpf(tmp_path):
    """O zero só é reposto quando o resultado tem dígito verificador válido —
    senão qualquer código de dez dígitos viraria CPF. (9999999999 não passa no
    dígito; 1234567890, por acaso, passa — é um CPF válido de verdade.)"""
    conteudo = [
        ["Empresa:", "91 - ENDOGASTRO LTDA"],
        [75, "ANDRE FRANZOTTI CARDOSO", 9999999999, 46.94, dt.date(2007, 3, 23)],
    ]
    leitura = ler_relatorio_de_planilha(ler_xls(escrever_xls(tmp_path / "r.xls", conteudo)))

    assert leitura.total_socios == 0


@pytest.mark.parametrize(
    "cabecalho",
    [
        ["Empresa:", "91 - ENDOGASTRO CLINICA MEDICA LTDA"],
        ["Empresa:", "91", "ENDOGASTRO CLINICA MEDICA LTDA"],   # colunas separadas
        ["Empresa:", "ENDOGASTRO CLINICA MEDICA LTDA"],         # sem número
        ["Cliente:", "91 - ENDOGASTRO CLINICA MEDICA LTDA"],
        ["Empresa: 91 - ENDOGASTRO CLINICA MEDICA LTDA"],       # tudo numa célula
    ],
)
def test_cabecalho_da_empresa_em_varias_formas_de_planilha(tmp_path, cabecalho):
    conteudo = [cabecalho, [75, "ANDRE FRANZOTTI CARDOSO", "07692572755", 46.94, dt.date(2007, 3, 23)]]

    (empresa,) = ler_relatorio_de_planilha(ler_xls(escrever_xls(tmp_path / "r.xls", conteudo))).empresas

    assert empresa.nome == "ENDOGASTRO CLINICA MEDICA LTDA"
    assert [s.nome for s in empresa.socios] == ["ANDRE FRANZOTTI CARDOSO"]


@pytest.mark.parametrize(
    "linha",
    [
        [75, "ANDRE FRANZOTTI CARDOSO", "07692572755", 46.94, dt.date(2007, 3, 23)],
        [75, "", "ANDRE FRANZOTTI CARDOSO", "", "07692572755", "", 46.94, "", dt.date(2007, 3, 23)],
        [75, "ANDRE FRANZOTTI CARDOSO", "07692572755", dt.date(2007, 3, 23), "", 46.94],
        ["ANDRE FRANZOTTI CARDOSO", "07692572755", 46.94, dt.date(2007, 3, 23)],
        [75, "ANDRE FRANZOTTI CARDOSO", "076.925.727-55", 46.94, dt.date(2007, 3, 23)],
        [75, "ANDRE FRANZOTTI CARDOSO", "07692572755", 46.94, "23/03/2007"],
        [75, "ANDRE FRANZOTTI CARDOSO", "07692572755", "46,94%", dt.date(2007, 3, 23)],
        [75, "ANDRE FRANZOTTI CARDOSO", "07692572755", 46.94, dt.date(2007, 3, 23), "", "Administrador"],
        [75, "ANDRE FRANZOTTI CARDOSO", "07692572755", 46.94, dt.date(2007, 3, 23), "", "R$ 1.000,00"],
        [75, "ANDRE FRANZOTTI CARDOSO 07692572755", 46.94, dt.date(2007, 3, 23)],
    ],
    ids=["padrão", "colunas vazias", "datas antes do %", "sem código", "CPF pontuado",
         "data como texto", "% como texto", "coluna de cargo", "valor em R$", "nome e CPF juntos"],
)
def test_linha_de_socio_em_varias_formas_de_planilha(tmp_path, linha):
    conteudo = [["Empresa:", "91 - ENDOGASTRO CLINICA MEDICA LTDA"], linha]

    (empresa,) = ler_relatorio_de_planilha(ler_xls(escrever_xls(tmp_path / "r.xls", conteudo))).empresas

    (socio,) = empresa.socios
    assert socio.nome == "ANDRE FRANZOTTI CARDOSO"
    assert socio.inscricao == "076.925.727-55"
    assert socio.percentual == 46.94
    assert socio.data_entrada == "2007-03-23"


def test_planilha_que_nao_e_o_relatorio_e_recusada_com_explicacao(tmp_path):
    conteudo = [["Balancete de verificação"], ["Conta", "Saldo"], ["1.1.01", 1500.0]]

    with pytest.raises(RelatorioInvalido, match="Cadastro de Sócios"):
        ler_relatorio_de_planilha(ler_xls(escrever_xls(tmp_path / "r.xls", conteudo)))
