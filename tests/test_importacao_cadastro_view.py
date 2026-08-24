import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton

from controle_lucros import db, repositories as repo
from controle_lucros.ui.importacao_cadastro_view import _DialogoRevisaoCadastro


@pytest.fixture(scope="module", autouse=True)
def app():
    aplicativo = QApplication.instance() or QApplication([])
    yield aplicativo


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    db.init_schema(connection)
    yield connection
    connection.close()


def _linha(numero_chamada, empresa_nome, **overrides):
    dados = dict(
        numero_chamada=numero_chamada, empresa_nome=empresa_nome, cnpj="",
        capital_social=1000, quantidade_cotas=100,
        socio_nome="Carlos Mendes", socio_cpf="555.555.555-55", tipo_pessoa="fisica",
        percentual_capital=100.0, cotas_socio=100, data_entrada="2025-01-01",
    )
    dados.update(overrides)
    return dados


def test_mesmo_socio_novo_em_varias_empresas_vira_um_cartao_so(conn, monkeypatch):
    """O ponto central: sócio novo que aparece em N linhas (N empresas) da
    mesma planilha não pode virar N pendências independentes — resolver uma
    vez (criar o cadastro) precisa valer pras outras empresas dele também,
    sem duplicar o sócio."""
    linhas_planilha = [
        _linha("101", "Empresa A LTDA", percentual_capital=100.0),
        _linha("102", "Empresa B LTDA", percentual_capital=50.0),
        _linha("103", "Empresa C LTDA", percentual_capital=30.0),
    ]
    resultado = repo.preparar_importacao_cadastro(conn, linhas_planilha)
    assert resultado["prontas"] == []
    assert len(resultado["pendencias"]) == 3

    dialogo = _DialogoRevisaoCadastro(conn, resultado["pendencias"])
    assert len(dialogo._grupos_ui) == 1

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
    linhas_grupo, combo = dialogo._grupos_ui[0]
    dialogo._cadastrar_novo(linhas_grupo, combo, QPushButton())

    socios = repo.listar_socios(conn)
    assert len(socios) == 1

    resolvidos = dialogo.resolvidos()
    assert len(resolvidos) == 3
    assert {r["socio_id"] for r in resolvidos} == {socios[0].id}

    aplicado = repo.aplicar_importacao_cadastro(conn, resultado["prontas"] + resolvidos)
    assert aplicado == {"empresas_criadas": 3, "vinculos_criados": 3, "vinculos_ja_existentes": 0}

    for empresa in repo.listar_empresas(conn):
        (vinculo,) = repo.listar_vinculos_empresa(conn, empresa.id)
        assert vinculo.socio_id == socios[0].id


def test_socios_diferentes_ficam_em_cartoes_separados(conn):
    linhas_planilha = [
        _linha("101", "Empresa A LTDA", socio_nome="Carlos Mendes", socio_cpf="555.555.555-55"),
        _linha("102", "Empresa B LTDA", socio_nome="Ana Paula", socio_cpf="666.666.666-66"),
    ]
    resultado = repo.preparar_importacao_cadastro(conn, linhas_planilha)
    dialogo = _DialogoRevisaoCadastro(conn, resultado["pendencias"])
    assert len(dialogo._grupos_ui) == 2


def test_agrupa_por_nome_quando_cpf_esta_vazio(conn):
    linhas_planilha = [
        _linha("101", "Empresa A LTDA", socio_nome="Carlos Mendes", socio_cpf=""),
        _linha("102", "Empresa B LTDA", socio_nome="Carlos Mendes", socio_cpf=""),
    ]
    resultado = repo.preparar_importacao_cadastro(conn, linhas_planilha)
    dialogo = _DialogoRevisaoCadastro(conn, resultado["pendencias"])
    assert len(dialogo._grupos_ui) == 1
