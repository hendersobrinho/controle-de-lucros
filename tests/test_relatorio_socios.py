"""Leitura do relatório "Cadastro de Sócios" emitido por outro sistema.

Dois riscos opostos são testados aqui, e os dois custam caro:

- recusar um relatório legítimo só porque o layout tem uma coluna a mais, o
  cabeçalho quebrado em duas linhas ou "%" no percentual — a pessoa não tem
  como adivinhar o que no arquivo desagradou;
- aceitar o que não é sócio, e cadastrar o escritório que emitiu o relatório
  como se fosse gente do quadro societário.

Por isso cada variação de formato tem seu caso, e o cabeçalho e o rodapé têm
os deles.
"""
import pytest

from controle_lucros.relatorio_socios import (
    RelatorioInvalido,
    ler_relatorio_socios,
    linhas_para_importacao,
    resumo,
)

CABECALHO = "Empresa: 91 - ENDOGASTRO CLINICA MEDICA LTDA Data do quadro societário: 20/05/2026"
LINHA_PADRAO = "75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 23/03/2007 46,94"

RELATORIO = f"""
METODOS SERVICOS CONTABEIS LTDA
CNPJ: 12.345.678/0001-90
Cadastro de Sócios
{CABECALHO}
Código Nome Inscrição Ingresso Saída Participação
{LINHA_PADRAO}
707 LUIZA DIAS TORRES 103.285.827-35 02/03/2023 20/05/2026 0
1041 CAIO GUIMARAES ARAUJO 142.575.367-13 16/02/2024 0,51
1257 IGOR GONCALVES SANT’ANA 154.886.397-13 19/02/2026 1,5
Sistema licenciado para METODOS SERVICOS CONTABEIS LTDA
"""


def _socios(texto):
    return [s for e in ler_relatorio_socios(texto).empresas for s in e.socios]


def _um_socio(*linhas):
    """Lê uma linha de sócio sob um cabeçalho de empresa padrão."""
    socios = _socios("\n".join([CABECALHO, *linhas]))
    assert len(socios) == 1, f"esperava um sócio, veio {len(socios)}"
    return socios[0]


# --------------------------------------------------------- o layout de casa --
def test_le_empresa_e_socios_do_layout_real():
    (empresa,) = ler_relatorio_socios(RELATORIO).empresas

    assert empresa.numero == "91"
    assert empresa.nome == "ENDOGASTRO CLINICA MEDICA LTDA"
    assert empresa.data_quadro == "2026-05-20"
    assert len(empresa.socios) == 4


def test_campos_de_um_socio_ativo():
    socio = _socios(RELATORIO)[0]

    assert socio.codigo == "75"
    assert socio.nome == "ANDRE FRANZOTTI CARDOSO"
    assert socio.inscricao == "076.925.727-55"
    assert socio.tipo_pessoa == "fisica"
    assert socio.percentual == 46.94
    assert socio.data_entrada == "2007-03-23"
    assert socio.data_saida is None


def test_socio_que_saiu_traz_a_data_de_saida():
    socio = _socios(RELATORIO)[1]

    assert socio.nome == "LUIZA DIAS TORRES"
    assert socio.data_entrada == "2023-03-02"
    assert socio.data_saida == "2026-05-20"
    # O relatório zera a participação de quem saiu; é o que ele informa.
    assert socio.percentual == 0.0


def test_aspa_tipografica_do_nome_vira_reta():
    assert _socios(RELATORIO)[3].nome == "IGOR GONCALVES SANT'ANA"


def test_relatorio_limpo_nao_reporta_linha_perdida():
    assert ler_relatorio_socios(RELATORIO).ignoradas == []


# ------------------------------------------------- variações de cabeçalho --
@pytest.mark.parametrize(
    "cabecalho",
    [
        "Empresa: 91 - ENDOGASTRO CLINICA MEDICA LTDA",
        "Empresa 91 - ENDOGASTRO CLINICA MEDICA LTDA",
        "EMPRESA: 91 - ENDOGASTRO CLINICA MEDICA LTDA",
        "empresa: 91 - endogastro clinica medica ltda",
        "Empresa: 91 – ENDOGASTRO CLINICA MEDICA LTDA",
        "Empresa nº 91 - ENDOGASTRO CLINICA MEDICA LTDA",
        "Empresa: 91 - ENDOGASTRO CLINICA MEDICA LTDA Data do quadro societário: 20/05/2026",
    ],
)
def test_cabecalho_da_empresa_em_varios_formatos(cabecalho):
    (empresa,) = ler_relatorio_socios(f"{cabecalho}\n{LINHA_PADRAO}").empresas

    assert empresa.numero == "91"
    assert empresa.nome == "ENDOGASTRO CLINICA MEDICA LTDA"
    assert len(empresa.socios) == 1


def test_data_do_quadro_numa_linha_separada():
    """Papel estreito quebra o cabeçalho em duas linhas — e a data não pode se
    perder por causa disso."""
    texto = (
        "Empresa: 91 - ENDOGASTRO CLINICA MEDICA LTDA\n"
        "Data do quadro societário: 20/05/2026\n"
        f"{LINHA_PADRAO}\n"
    )
    (empresa,) = ler_relatorio_socios(texto).empresas

    assert empresa.nome == "ENDOGASTRO CLINICA MEDICA LTDA"
    assert empresa.data_quadro == "2026-05-20"
    assert len(empresa.socios) == 1


# ----------------------------------------------------- variações da linha --
@pytest.mark.parametrize(
    "linha",
    [
        "75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 23/03/2007 46,94",
        "ANDRE FRANZOTTI CARDOSO 076.925.727-55 23/03/2007 46,94",              # sem código
        "75   ANDRE FRANZOTTI CARDOSO   076.925.727-55   23/03/2007   46,94",   # espaços
        "75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 23/03/2007 46,94%",          # com %
        "75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 23/03/2007 46.94",           # ponto decimal
        "75 ANDRE FRANZOTTI CARDOSO 07692572755 23/03/2007 46,94",              # CPF sem pontos
        "75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 23-03-2007 46,94",           # data com hífen
        "75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 2007-03-23 46,94",           # data ISO
        "75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 23/03/07 46,94",             # ano com 2 dígitos
        "75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 46,94 23/03/2007",           # ordem trocada
        "75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 23/03/2007 46,94 Sócio-Administrador",
        "75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 Administrador 23/03/2007 46,94",
        "75 ANDRE FRANZOTTI CARDOSO CPF: 076.925.727-55 23/03/2007 46,94",      # rótulo colado
    ],
)
def test_linha_de_socio_em_varios_formatos(linha):
    socio = _um_socio(linha)

    assert socio.nome == "ANDRE FRANZOTTI CARDOSO"
    assert socio.inscricao.replace(".", "").replace("-", "") == "07692572755"
    assert socio.percentual == 46.94
    assert socio.data_entrada == "2007-03-23"


def test_valor_em_reais_na_linha_nao_vira_percentual():
    """Relatório que traz o valor da participação em dinheiro não pode fazer o
    capital virar percentual."""
    socio = _um_socio("75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 23/03/2007 46,94 R$ 1.000,00")

    assert socio.percentual == 46.94


def test_sem_coluna_de_percentual_o_socio_entra_com_zero():
    socio = _um_socio("75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 23/03/2007")

    assert socio.percentual == 0.0
    assert socio.data_entrada == "2007-03-23"


def test_socio_pessoa_juridica_e_reconhecido_pelo_cnpj():
    socio = _um_socio("3 HOLDING EXEMPLO LTDA 11.222.333/0001-81 10/01/2020 60")

    assert socio.tipo_pessoa == "juridica"
    assert socio.inscricao == "11.222.333/0001-81"
    assert socio.percentual == 60.0


def test_cnpj_alfanumerico_tambem_e_lido():
    """Formato novo da Receita, com letras nas oito primeiras posições."""
    socio = _um_socio("3 HOLDING EXEMPLO LTDA 12.ABC.345/01DE-35 10/01/2020 60")

    assert socio.tipo_pessoa == "juridica"
    assert socio.inscricao == "12.ABC.345/01DE-35"


def test_data_impossivel_nao_vira_socio_com_data_inventada():
    assert _socios(f"{CABECALHO}\n75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 32/13/2007 46,94") == []


# --------------------------------------------- o que NÃO pode virar sócio --
@pytest.mark.parametrize(
    "linha",
    [
        "CNPJ: 12.345.678/0001-90 - Emitido em 20/05/2026 por ADMIN",
        "CPF: 076.925.727-55 23/03/2007",
        "Inscrição: 076.925.727-55 23/03/2007",
        "Contrato nº 12345678901 firmado em 01/01/2020",   # 11 dígitos, CPF inválido
        "Total: 100,00",
        "Página 1 de 3 - Emitido em 20/05/2026",
        "Código Nome Inscrição Ingresso Saída Participação",
        "Sistema licenciado para METODOS SERVICOS CONTABEIS LTDA",
    ],
)
def test_decoracao_do_relatorio_nunca_vira_socio(linha):
    assert _socios(f"{CABECALHO}\n{linha}") == []


def test_decoracao_tambem_nao_vira_aviso_de_linha_perdida():
    """Aviso que aparece em toda importação ensina a pessoa a ignorar avisos."""
    texto = "\n".join([
        "CNPJ: 12.345.678/0001-90 - Emitido em 20/05/2026 por ADMIN",
        CABECALHO,
        "Código Nome Inscrição Ingresso Saída Participação",
        LINHA_PADRAO,
        "CNPJ: 12.345.678/0001-90 - Emitido em 20/05/2026 por ADMIN",
        "Total da empresa: 100,00",
        "Sistema licenciado para METODOS SERVICOS CONTABEIS LTDA",
    ])
    leitura = ler_relatorio_socios(texto)

    assert leitura.total_socios == 1
    assert leitura.ignoradas == []


def test_linha_com_documento_e_data_mas_sem_nome_e_relatada():
    """O aviso existe para isto: uma linha que era sócio e se perdeu na
    extração do PDF não pode sumir em silêncio."""
    leitura = ler_relatorio_socios(f"{CABECALHO}\n7 A 076.925.727-55 23/03/2007 46,94")

    assert leitura.total_socios == 0
    assert len(leitura.ignoradas) == 1


def test_cabecalho_do_escritorio_nao_vira_empresa():
    # O topo do relatório também fala em empresa, mas sem número.
    texto = (
        "Empresa: METODOS SERVICOS CONTABEIS LTDA\n"
        "Empresa: 7 - CLIENTE LTDA Data do quadro societário: 01/01/2025\n"
        "1 ANA SOUZA 111.111.111-11 01/01/2020 100\n"
    )
    empresas = ler_relatorio_socios(texto).empresas

    assert len(empresas) == 1
    assert empresas[0].numero == "7"


def test_arquivo_sem_empresa_reclama():
    with pytest.raises(RelatorioInvalido):
        ler_relatorio_socios("Um PDF qualquer, sem nada do relatório de sócios.")


# ------------------------------------------------------------- várias empresas
def test_varias_empresas_no_mesmo_arquivo():
    texto = (
        "Empresa: 1 - PRIMEIRA LTDA Data do quadro societário: 01/01/2025\n"
        "10 ANA SOUZA 111.111.111-11 01/01/2020 100\n"
        "Empresa: 2 - SEGUNDA LTDA Data do quadro societário: 01/01/2025\n"
        "20 BRUNO LIMA 222.222.222-22 02/02/2021 50\n"
        "21 CARLA DIAS 333.333.333-33 03/03/2021 50\n"
    )
    empresas = ler_relatorio_socios(texto).empresas

    assert [e.numero for e in empresas] == ["1", "2"]
    assert [len(e.socios) for e in empresas] == [1, 2]
    assert empresas[1].socios[1].nome == "CARLA DIAS"


# ------------------------------------------------------------ para importar --
def test_linhas_para_importacao_no_formato_da_planilha():
    linhas = linhas_para_importacao(ler_relatorio_socios(RELATORIO).empresas)

    assert len(linhas) == 4
    linha = next(l for l in linhas if l["socio_nome"] == "ANDRE FRANZOTTI CARDOSO")
    assert linha["numero_chamada"] == "91"
    assert linha["empresa_nome"] == "ENDOGASTRO CLINICA MEDICA LTDA"
    assert linha["socio_cpf"] == "076.925.727-55"
    assert linha["tipo_pessoa"] == "fisica"
    assert linha["percentual_capital"] == 46.94
    assert linha["data_entrada"] == "2007-03-23"
    assert linha["data_saida"] is None
    # O relatório não traz nada disso; a empresa nasce para completar depois.
    assert linha["cnpj"] == ""
    assert linha["capital_social"] == 0.0
    assert linha["quantidade_cotas"] == 0.0
    assert linha["ano_base"] is None
    assert linha["valor_distribuido"] == 0.0


def test_linhas_saem_ordenadas_por_entrada():
    # Quem saiu e voltou precisa ter o vínculo antigo encerrado antes do novo.
    texto = (
        "Empresa: 3 - TERCEIRA LTDA Data do quadro societário: 01/06/2025\n"
        "99 ANA SOUZA 111.111.111-11 01/01/2024 01/06/2024 0\n"
        "12 ANA SOUZA 111.111.111-11 01/01/2020 01/01/2023 0\n"
        "40 ANA SOUZA 111.111.111-11 01/03/2025 100\n"
    )
    linhas = linhas_para_importacao(ler_relatorio_socios(texto).empresas)

    assert [l["data_entrada"] for l in linhas] == ["2020-01-01", "2024-01-01", "2025-03-01"]


def test_resumo_conta_empresas_socios_e_saidas():
    leitura = ler_relatorio_socios(RELATORIO)
    assert resumo(leitura.empresas) == "1 empresa(s) · 4 sócio(s) · 1 com saída registrada"
    assert leitura.total_socios == 4


def test_cabecalho_repetido_por_pagina_nao_duplica_a_empresa():
    """Relatório de várias páginas repete o cabeçalho da empresa em cada uma.
    São páginas do mesmo quadro societário, não duas empresas."""
    texto = "\n".join([
        "Empresa: 91 - ENDOGASTRO CLINICA MEDICA LTDA Data do quadro societário: 20/05/2026",
        "75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 23/03/2007 46,94",
        "Página 1 de 2",
        "Empresa: 91 - ENDOGASTRO CLINICA MEDICA LTDA",
        "707 LUIZA DIAS TORRES 103.285.827-35 02/03/2023 20/05/2026 0",
    ])
    leitura = ler_relatorio_socios(texto)

    (empresa,) = leitura.empresas
    assert empresa.data_quadro == "2026-05-20"
    assert [s.nome for s in empresa.socios] == ["ANDRE FRANZOTTI CARDOSO", "LUIZA DIAS TORRES"]
    assert resumo(leitura.empresas) == "1 empresa(s) · 2 sócio(s) · 1 com saída registrada"


# ------------------------------------------- cabeçalhos de outros sistemas --
@pytest.mark.parametrize(
    "cabecalho,numero",
    [
        ("Empresa: 91 - ENDOGASTRO CLINICA MEDICA LTDA", "91"),
        # Na planilha o número e o nome ficam em colunas separadas, e o hífen
        # que os liga no papel simplesmente não existe.
        ("Empresa: 91 ENDOGASTRO CLINICA MEDICA LTDA", "91"),
        ("Cliente: 91 - ENDOGASTRO CLINICA MEDICA LTDA", "91"),
        ("Estabelecimento: 91 - ENDOGASTRO CLINICA MEDICA LTDA", "91"),
    ],
)
def test_outros_rotulos_e_formas_de_cabecalho(cabecalho, numero):
    (empresa,) = ler_relatorio_socios(f"{cabecalho}\n{LINHA_PADRAO}").empresas

    assert empresa.numero == numero
    assert empresa.nome == "ENDOGASTRO CLINICA MEDICA LTDA"
    assert len(empresa.socios) == 1


def test_empresa_identificada_por_cnpj_aproveita_o_cnpj():
    """O CNPJ da empresa é justamente o que o relatório costuma não trazer.
    Quando vem no cabeçalho, a empresa nasce identificada."""
    texto = f"Empresa: 12.345.678/0001-90 ENDOGASTRO CLINICA MEDICA LTDA\n{LINHA_PADRAO}"
    (empresa,) = ler_relatorio_socios(texto).empresas

    assert empresa.nome == "ENDOGASTRO CLINICA MEDICA LTDA"
    assert empresa.cnpj == "12.345.678/0001-90"
    assert linhas_para_importacao([empresa])[0]["cnpj"] == "12.345.678/0001-90"


def test_numero_seguido_de_coisa_que_nao_e_nome_nao_vira_empresa():
    """Sem o hífen separando, o que vem depois do número precisa provar que é
    razão social."""
    with pytest.raises(RelatorioInvalido):
        ler_relatorio_socios(f"Empresa: 3 de 5\n{LINHA_PADRAO}")


def test_cabecalho_sem_numero_e_aceito_quando_nao_ha_outro():
    """Nem todo sistema numera as empresas. Sem nenhum cabeçalho numerado no
    arquivo, o sem número passa a valer."""
    texto = f"Empresa: ENDOGASTRO CLINICA MEDICA LTDA\n{LINHA_PADRAO}"
    (empresa,) = ler_relatorio_socios(texto).empresas

    assert empresa.nome == "ENDOGASTRO CLINICA MEDICA LTDA"
    assert empresa.numero == ""
    assert len(empresa.socios) == 1


def test_sem_numero_o_escritorio_emissor_ainda_fica_de_fora():
    """O cabeçalho do escritório tem exatamente a mesma forma. O que separa um
    do outro é que só a empresa de verdade é seguida de sócios."""
    texto = "\n".join([
        "Empresa: METODOS SERVICOS CONTABEIS LTDA",
        "C.N.P.J.: 02294442000113",
        "Empresa: ENDOGASTRO CLINICA MEDICA LTDA",
        LINHA_PADRAO,
    ])
    empresas = ler_relatorio_socios(texto).empresas

    assert [e.nome for e in empresas] == ["ENDOGASTRO CLINICA MEDICA LTDA"]


def test_socio_sem_data_nenhuma_e_avisado_em_vez_de_sumir():
    """Linha de sócio sem data de ingresso não pode ser importada (a data
    seria inventada), mas também não pode desaparecer calada."""
    leitura = ler_relatorio_socios(f"{CABECALHO}\n75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 46,94")

    assert leitura.total_socios == 0
    assert leitura.ignoradas == ["75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 46,94"]
