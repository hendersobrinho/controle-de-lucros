"""Importar relatório de sócios de dentro de um card da aba Alterações
contratuais: o pedido era amarrar a movimentação trazida pelo relatório à
alteração já aberta, em vez de deixá-la sem alteração nenhuma (como acontece
importando pela tela geral de Cadastro sem passar por lá).

O relatório pode trazer várias empresas no mesmo arquivo, mas o card é de uma
empresa só — só a seção dela entra, o resto é ignorado."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from controle_lucros import db, repositories as repo
from controle_lucros.models import AlteracaoContratual, Empresa, Socio
from controle_lucros.ui import alteracao_card as mod
from controle_lucros.ui import importacao_cadastro_view as vista_importacao
from controle_lucros.ui.alteracao_card import AlteracaoCard


@pytest.fixture(scope="module", autouse=True)
def app():
    aplicativo = QApplication.instance() or QApplication([])
    yield aplicativo


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    db.init_schema(connection)
    yield connection
    connection.close()


TEXTO_DUAS_EMPRESAS = (
    "Empresa: 91 - ENDOGASTRO CLINICA MEDICA LTDA\n"
    "75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 23/03/2007 46,94\n"
    "Empresa: 92 - OUTRA EMPRESA LTDA\n"
    "1041 CAIO GUIMARAES ARAUJO 142.575.367-13 16/02/2024 100\n"
)


def _cenario(conn):
    empresa_a = repo.salvar_empresa(conn, Empresa(None, "91", "ENDOGASTRO CLINICA MEDICA LTDA", "", 10000, 1000))
    empresa_b = repo.salvar_empresa(conn, Empresa(None, "92", "OUTRA EMPRESA LTDA", "", 5000, 500))
    # Pré-cadastrados para o casamento de sócio ser direto — sem pendência,
    # o diálogo de revisão nem chega a abrir (blocking modal em teste).
    repo.salvar_socio(conn, Socio(None, "ANDRE FRANZOTTI CARDOSO", "076.925.727-55"))
    repo.salvar_socio(conn, Socio(None, "CAIO GUIMARAES ARAUJO", "142.575.367-13"))
    alteracao_id = repo.salvar_alteracao(
        conn,
        AlteracaoContratual(
            id=None, empresa_id=empresa_a, numero=1, data="2025-01-01",
            nome_empresa="ENDOGASTRO CLINICA MEDICA LTDA", capital_social=10000,
            quantidade_cotas=1000, descricao="",
        ),
    )
    alteracao = repo.buscar_alteracao(conn, alteracao_id)
    return {"empresa_a": empresa_a, "empresa_b": empresa_b, "alteracao": alteracao}


def _preparar_mocks(monkeypatch, tmp_path, texto=TEXTO_DUAS_EMPRESAS, resposta=QMessageBox.Yes):
    arquivo = tmp_path / "relatorio.pdf"
    arquivo.write_bytes(b"%PDF-falso")
    monkeypatch.setattr(vista_importacao, "extrair_texto", lambda caminho: texto)
    monkeypatch.setattr(mod.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(arquivo), "")))
    perguntas = []
    monkeypatch.setattr(
        mod.QMessageBox, "question",
        staticmethod(lambda parent, titulo, texto, *a, **k: perguntas.append(texto) or resposta),
    )
    monkeypatch.setattr(mod.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(mod.QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    return perguntas


def test_importa_so_a_empresa_do_card_e_amarra_a_alteracao(conn, monkeypatch, tmp_path):
    cenario = _cenario(conn)
    _preparar_mocks(monkeypatch, tmp_path)

    card = AlteracaoCard(conn, cenario["empresa_a"], cenario["alteracao"], lambda _c: None)
    card._importar_relatorio_socios()

    vinculos_a = repo.listar_vinculos_empresa(conn, cenario["empresa_a"])
    assert len(vinculos_a) == 1
    assert vinculos_a[0].alteracao_entrada_id == cenario["alteracao"].id

    # A empresa 92 também aparece no arquivo, mas não é a deste card: nada
    # deve ter sido lançado nela.
    assert repo.listar_vinculos_empresa(conn, cenario["empresa_b"]) == []
    # E nenhuma alteração automática foi criada por conta dela.
    assert repo.listar_alteracoes(conn, cenario["empresa_b"]) == []
    # Nenhuma empresa nova foi criada — o casamento é forçado para a empresa
    # já conhecida do card, não pelo nome como veio escrito no relatório.
    assert len(repo.listar_empresas(conn)) == 2


def test_avisa_quantas_linhas_de_outra_empresa_foram_ignoradas(conn, monkeypatch, tmp_path):
    cenario = _cenario(conn)
    perguntas = _preparar_mocks(monkeypatch, tmp_path)

    card = AlteracaoCard(conn, cenario["empresa_a"], cenario["alteracao"], lambda _c: None)
    card._importar_relatorio_socios()

    assert perguntas
    assert "1 outra(s) empresa(s)" in perguntas[0]
    assert f"Nº {cenario['alteracao'].numero}" in perguntas[0]


def test_recusar_a_confirmacao_nao_grava_nada(conn, monkeypatch, tmp_path):
    cenario = _cenario(conn)
    _preparar_mocks(monkeypatch, tmp_path, resposta=QMessageBox.No)

    card = AlteracaoCard(conn, cenario["empresa_a"], cenario["alteracao"], lambda _c: None)
    card._importar_relatorio_socios()

    assert repo.listar_vinculos_empresa(conn, cenario["empresa_a"]) == []


def test_relatorio_sem_a_empresa_do_card_avisa_e_nao_grava(conn, monkeypatch, tmp_path):
    cenario = _cenario(conn)
    _preparar_mocks(monkeypatch, tmp_path, texto=(
        "Empresa: 92 - OUTRA EMPRESA LTDA\n"
        "1041 CAIO GUIMARAES ARAUJO 142.575.367-13 16/02/2024 100\n"
    ))

    card = AlteracaoCard(conn, cenario["empresa_a"], cenario["alteracao"], lambda _c: None)
    card._importar_relatorio_socios()

    assert repo.listar_vinculos_empresa(conn, cenario["empresa_a"]) == []
    assert repo.listar_vinculos_empresa(conn, cenario["empresa_b"]) == []


def test_botao_so_habilita_com_alteracao_salva_e_aberta(conn):
    cenario = _cenario(conn)

    rascunho = AlteracaoCard(conn, cenario["empresa_a"], None, lambda _c: None)
    assert not rascunho.btn_importar_relatorio.isEnabled()

    aberta = AlteracaoCard(conn, cenario["empresa_a"], cenario["alteracao"], lambda _c: None)
    assert aberta.btn_importar_relatorio.isEnabled()

    repo.fechar_alteracao(conn, cenario["alteracao"].id)
    fechada = AlteracaoCard(conn, cenario["empresa_a"], repo.buscar_alteracao(conn, cenario["alteracao"].id), lambda _c: None)
    assert not fechada.btn_importar_relatorio.isEnabled()
