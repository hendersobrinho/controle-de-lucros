"""Organização da barra lateral e o acesso a trocar a própria senha.

O ponto delicado: "Trocar minha senha" mora dentro de Usuários, que é uma
tela só de administrador. Quem não é admin precisa continuar tendo como
trocar a própria senha por outro caminho.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3

import pytest
from PySide6.QtWidgets import QApplication

from controle_lucros import db, repositories as repo
from controle_lucros.ui.main_window import MainWindow


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


def _janela(conn, admin: bool) -> MainWindow:
    repo.criar_usuario(conn, "Fulano", "fulano", "senha123", admin)
    usuario = repo.listar_usuarios(conn)[0]
    return MainWindow(conn, usuario)


# ---------------------------------------------------------- organização --


def test_importacao_em_massa_esta_em_sistema(conn):
    janela = _janela(conn, admin=True)
    assert "sistema.importar" in janela._paginas
    assert "empresas.importar" not in janela._paginas
    assert "sistema.importar" in janela.sidebar._botoes
    janela._ir_para("sistema.importar")
    assert janela.pilha.currentWidget() is janela.importacao_cadastro
    assert janela.titulo_pagina.text().startswith("Sistema")


def test_sobre_continua_navegavel_no_rodape(conn):
    """Mudou de lugar, mas segue sendo item de navegação de verdade: tem que
    trocar a página e ficar marcado como os outros."""
    janela = _janela(conn, admin=True)
    janela._ir_para("sistema.sobre")
    assert janela.pilha.currentWidget() is janela.sobre_view
    assert janela.sidebar._botoes["sistema.sobre"].isChecked()


def test_toda_chave_da_sidebar_tem_pagina(conn):
    """Item de menu apontando pra página inexistente quebraria com KeyError
    no clique."""
    janela = _janela(conn, admin=True)
    assert set(janela.sidebar._botoes) == set(janela._paginas)


# ------------------------------------------------------- trocar a senha --


def test_admin_troca_a_senha_dentro_de_usuarios(conn):
    janela = _janela(conn, admin=True)
    assert hasattr(janela.usuarios_tab, "btn_minha_senha")
    assert janela.usuarios_tab.btn_minha_senha.isEnabled()
    # Sendo admin, o atalho do rodapé some: o caminho é um só.
    assert not janela.sidebar.btn_trocar_senha.isVisibleTo(janela.sidebar)


def test_usuario_comum_mantem_o_atalho_no_rodape(conn):
    """Usuários é tela de admin — sem este atalho, quem não é administrador
    não teria como trocar a própria senha."""
    janela = _janela(conn, admin=False)
    assert janela.sidebar.btn_trocar_senha.isVisibleTo(janela.sidebar)
    assert not janela.sidebar._botoes["sistema.usuarios"].isVisibleTo(janela.sidebar)
    # E a trava de navegação continua valendo.
    janela._ir_para("sistema.usuarios")
    assert janela.pilha.currentWidget() is not janela.usuarios_tab


def test_trocar_minha_senha_pede_a_senha_atual(conn, monkeypatch):
    """Diferente de "Redefinir senha", que é ação de admin sobre outra conta."""
    from controle_lucros.ui import usuarios_tab as mod

    janela = _janela(conn, admin=True)
    from controle_lucros import sessao

    sessao.definir_usuario_atual(repo.listar_usuarios(conn)[0])
    try:
        abertos = []
        monkeypatch.setattr(
            mod, "QMessageBox", type("M", (), {"information": staticmethod(lambda *a, **k: None)})
        )
        import controle_lucros.ui.login as login_mod

        monkeypatch.setattr(
            login_mod,
            "DialogoTrocarMinhaSenha",
            lambda conn_, usuario, parent=None: type(
                "D", (), {"exec": lambda self: abertos.append(usuario.login) or 0}
            )(),
        )
        janela.usuarios_tab._trocar_minha_senha()
        assert abertos == ["fulano"]
    finally:
        sessao.definir_usuario_atual(None)


def test_redefinir_senha_continua_exigindo_selecao(conn):
    janela = _janela(conn, admin=True)
    tab = janela.usuarios_tab
    assert not tab.btn_redefinir_senha.isEnabled()
    # Trocar a própria senha não depende de linha selecionada.
    assert tab.btn_minha_senha.isEnabled()
