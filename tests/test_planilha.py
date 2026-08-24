import csv

import openpyxl
import pytest

from controle_lucros.planilha import (
    exportar_modelo_cadastro,
    exportar_modelo_distribuicao,
    exportar_relatorio_excel,
    importar_cadastro,
    importar_distribuicao,
)


def test_exportar_e_reimportar_modelo(tmp_path):
    caminho = tmp_path / "modelo.xlsx"
    linhas = [
        {"cpf": "111.111.111-11", "nome": "Fulano de Tal", "valor_distribuido": 0},
        {"cpf": "222.222.222-22", "nome": "Beltrano da Silva", "valor_distribuido": 0},
    ]
    exportar_modelo_distribuicao(caminho, linhas)
    assert caminho.exists()

    importadas = importar_distribuicao(caminho)
    assert len(importadas) == 2
    assert importadas[0]["cpf"] == "111.111.111-11"
    assert importadas[0]["nome"] == "Fulano de Tal"
    assert importadas[0]["valor_distribuido"] == 0


def test_importar_xlsx_com_valores_preenchidos(tmp_path):
    caminho = tmp_path / "distribuicao.xlsx"
    exportar_modelo_distribuicao(
        caminho,
        [
            {"cpf": "111.111.111-11", "nome": "Fulano", "valor_distribuido": 15000.5},
            {"cpf": "222.222.222-22", "nome": "Beltrano", "valor_distribuido": 9999.99},
        ],
    )
    linhas = importar_distribuicao(caminho)
    assert linhas[0]["valor_distribuido"] == 15000.5
    assert linhas[1]["valor_distribuido"] == 9999.99


def test_importar_csv_formato_brasileiro(tmp_path):
    caminho = tmp_path / "distribuicao.csv"
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(["CPF", "Sócio", "Valor Distribuído"])
        escritor.writerow(["111.111.111-11", "Fulano", "1.234.567,89"])
        escritor.writerow(["222.222.222-22", "Beltrano", "500,00"])

    linhas = importar_distribuicao(caminho)
    assert len(linhas) == 2
    assert linhas[0]["valor_distribuido"] == pytest.approx(1234567.89)
    assert linhas[1]["valor_distribuido"] == pytest.approx(500.0)


def test_importar_csv_delimitado_por_virgula(tmp_path):
    caminho = tmp_path / "distribuicao.csv"
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f, delimiter=",")
        escritor.writerow(["CPF", "Sócio", "Valor Distribuído"])
        escritor.writerow(["111.111.111-11", "Fulano", "2000.50"])

    linhas = importar_distribuicao(caminho)
    assert linhas[0]["valor_distribuido"] == 2000.50


def test_importar_ignora_linhas_em_branco(tmp_path):
    caminho = tmp_path / "distribuicao.csv"
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(["CPF", "Sócio", "Valor Distribuído"])
        escritor.writerow(["111.111.111-11", "Fulano", "1000"])
        escritor.writerow(["", "", ""])
        escritor.writerow(["222.222.222-22", "Beltrano", "2000"])

    linhas = importar_distribuicao(caminho)
    assert len(linhas) == 2


def test_importar_sem_coluna_valor_da_erro_claro(tmp_path):
    caminho = tmp_path / "invalida.csv"
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(["CPF", "Sócio"])
        escritor.writerow(["111.111.111-11", "Fulano"])

    with pytest.raises(ValueError, match="Valor Distribuído"):
        importar_distribuicao(caminho)


def test_importar_valor_invalido_aponta_a_linha(tmp_path):
    caminho = tmp_path / "invalida.csv"
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(["CPF", "Sócio", "Valor Distribuído"])
        escritor.writerow(["111.111.111-11", "Fulano", "não é número"])

    with pytest.raises(ValueError, match="Linha 2"):
        importar_distribuicao(caminho)


def test_importar_arquivo_so_com_cabecalho_retorna_vazio(tmp_path):
    caminho = tmp_path / "vazio.csv"
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(["CPF", "Sócio", "Valor Distribuído"])

    assert importar_distribuicao(caminho) == []


def test_exportar_relatorio_excel_gera_titulo_cabecalho_e_linhas(tmp_path):
    caminho = tmp_path / "relatorio.xlsx"
    exportar_relatorio_excel(
        caminho,
        titulo="Relatório de Distribuição — 2024",
        cabecalho=["Empresa", "Sócio", "CPF", "Classificação"],
        linhas=[
            ["ACME LTDA", "Fulano", "111.111.111-11", "Proporcional"],
            ["ACME LTDA", "Beltrano", "222.222.222-22", "Desproporcional"],
        ],
    )
    assert caminho.exists()

    wb = openpyxl.load_workbook(caminho)
    aba = wb.active
    assert aba["A1"].value == "Relatório de Distribuição — 2024"
    assert [c.value for c in aba[3]] == ["Empresa", "Sócio", "CPF", "Classificação"]
    assert [c.value for c in aba[4]] == ["ACME LTDA", "Fulano", "111.111.111-11", "Proporcional"]
    assert [c.value for c in aba[5]] == ["ACME LTDA", "Beltrano", "222.222.222-22", "Desproporcional"]


def test_exportar_relatorio_excel_sem_linhas_nao_quebra(tmp_path):
    caminho = tmp_path / "relatorio_vazio.xlsx"
    exportar_relatorio_excel(caminho, titulo="Vazio", cabecalho=["A", "B"], linhas=[])
    assert caminho.exists()


def test_exportar_e_reimportar_modelo_cadastro(tmp_path):
    caminho = tmp_path / "cadastro.xlsx"
    linhas = [
        {
            "numero_chamada": "001", "empresa_nome": "ACME LTDA", "cnpj": "00.000.000/0001-00",
            "capital_social": 10000, "quantidade_cotas": 1000,
            "socio_nome": "Fulano de Tal", "socio_cpf": "111.111.111-11", "tipo_pessoa": "fisica",
            "percentual_capital": 100.0, "cotas_socio": 1000, "data_entrada": "2024-01-01",
        }
    ]
    exportar_modelo_cadastro(caminho, linhas)
    assert caminho.exists()

    importadas = importar_cadastro(caminho)
    assert len(importadas) == 1
    linha = importadas[0]
    assert linha["numero_chamada"] == "001"
    assert linha["empresa_nome"] == "ACME LTDA"
    assert linha["socio_nome"] == "Fulano de Tal"
    assert linha["socio_cpf"] == "111.111.111-11"
    assert linha["tipo_pessoa"] == "fisica"
    assert linha["percentual_capital"] == 100.0
    assert linha["cotas_socio"] == 1000
    assert linha["data_entrada"] == "2024-01-01"


def test_exportar_modelo_cadastro_vazio_so_cabecalho(tmp_path):
    caminho = tmp_path / "cadastro_vazio.xlsx"
    exportar_modelo_cadastro(caminho)
    assert importar_cadastro(caminho) == []


def test_importar_cadastro_detecta_tipo_pessoa_juridica(tmp_path):
    caminho = tmp_path / "cadastro.csv"
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f, delimiter=";")
        escritor.writerow(
            ["Nº Chamada", "Empresa", "CNPJ", "Capital Social", "Qtd. Cotas da Empresa",
             "Sócio", "CPF/CNPJ do Sócio", "Tipo (física/jurídica)",
             "% Capital do Sócio", "Cotas do Sócio", "Data de Entrada"]
        )
        escritor.writerow(
            ["002", "Beta LTDA", "", "50000", "5000", "Holding XYZ", "12.345.678/0001-90",
             "Jurídica", "50", "2500", "01/03/2023"]
        )
    importadas = importar_cadastro(caminho)
    assert len(importadas) == 1
    assert importadas[0]["tipo_pessoa"] == "juridica"
    assert importadas[0]["data_entrada"] == "2023-03-01"
    assert importadas[0]["percentual_capital"] == 50.0


def test_importar_cadastro_sem_coluna_empresa_da_erro_claro(tmp_path):
    caminho = tmp_path / "cadastro.csv"
    with open(caminho, "w", newline="", encoding="utf-8") as f:
        escritor = csv.writer(f)
        escritor.writerow(["Sócio", "CPF"])
        escritor.writerow(["Fulano", "111.111.111-11"])

    with pytest.raises(ValueError, match="Empresa"):
        importar_cadastro(caminho)


def test_importar_cadastro_ignora_linhas_sem_empresa_ou_socio(tmp_path):
    caminho = tmp_path / "cadastro.xlsx"
    exportar_modelo_cadastro(caminho)
    wb = openpyxl.load_workbook(caminho)
    aba = wb.active
    aba.append(["001", "", "", 0, 0, "Fulano", "", "fisica", 0, 0, ""])
    aba.append(["001", "ACME LTDA", "", 0, 0, "", "", "fisica", 0, 0, ""])
    wb.save(caminho)

    assert importar_cadastro(caminho) == []
