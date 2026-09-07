"""Continuar conectado.

O que precisa estar amarrado: a senha nunca é guardada, o token só vale na
máquina onde foi criado, e tudo que deveria derrubar o acesso (sair, trocar
senha, desativar conta, vencer o prazo) derruba mesmo.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import datetime as dt
import json
import sqlite3

import pytest

from controle_lucros import auth, db, preferencias, repositories as repo


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    db.init_schema(connection)
    yield connection
    connection.close()


@pytest.fixture()
def usuario_id(conn):
    return repo.criar_usuario(conn, "Fulano", "fulano", "senha123", admin=True)


@pytest.fixture()
def prefs(tmp_path, monkeypatch):
    """Aponta as preferências pra um lugar temporário — sem isso o teste
    escreveria no preferencias.json de quem está rodando a suíte."""
    monkeypatch.setenv("CONTROLE_LUCROS_DB", str(tmp_path / "teste.db"))
    return tmp_path / "preferencias.json"


# ------------------------------------------------------------- o token --


def test_o_banco_guarda_o_hash_e_nunca_o_token(conn, usuario_id):
    token = repo.salvar_sessao(conn, usuario_id)
    linha = conn.execute("SELECT * FROM sessao_salva").fetchone()
    assert linha["token_hash"] != token
    assert token not in json.dumps(dict(linha))
    assert linha["token_hash"] == auth.hash_token(token)


def test_a_senha_nao_aparece_em_lugar_nenhum_da_sessao(conn, usuario_id):
    repo.salvar_sessao(conn, usuario_id)
    linha = conn.execute("SELECT * FROM sessao_salva").fetchone()
    assert "senha123" not in json.dumps(dict(linha))


def test_token_valido_devolve_o_usuario(conn, usuario_id):
    token = repo.salvar_sessao(conn, usuario_id)
    usuario = repo.usuario_de_sessao_salva(conn, usuario_id, token)
    assert usuario is not None and usuario.login == "fulano"


def test_token_errado_e_recusado_e_a_sessao_e_apagada(conn, usuario_id):
    repo.salvar_sessao(conn, usuario_id)
    assert repo.usuario_de_sessao_salva(conn, usuario_id, "token-inventado") is None
    assert conn.execute("SELECT COUNT(*) AS n FROM sessao_salva").fetchone()["n"] == 0


def test_entrar_de_novo_invalida_o_token_anterior(conn, usuario_id):
    """Uma sessão por usuário: token antigo que continuasse valendo seria um
    acesso a mais que ninguém sabe que existe."""
    primeiro = repo.salvar_sessao(conn, usuario_id)
    segundo = repo.salvar_sessao(conn, usuario_id)
    assert repo.usuario_de_sessao_salva(conn, usuario_id, segundo) is not None
    assert repo.usuario_de_sessao_salva(conn, usuario_id, primeiro) is None


# ---------------------------------------------------------- revogação --


def test_sessao_vencida_nao_entra(conn, usuario_id):
    token = repo.salvar_sessao(conn, usuario_id, dias=30)
    vencida = (dt.datetime.now() - dt.timedelta(days=1)).isoformat(timespec="seconds")
    conn.execute("UPDATE sessao_salva SET expira_em=? WHERE usuario_id=?", (vencida, usuario_id))
    conn.commit()
    assert repo.usuario_de_sessao_salva(conn, usuario_id, token) is None


def test_trocar_a_senha_derruba_a_sessao(conn, usuario_id):
    """Quem troca a senha costuma estar tirando o acesso de alguém; sessão
    sobrevivente anularia isso."""
    token = repo.salvar_sessao(conn, usuario_id)
    repo.alterar_senha(conn, usuario_id, "outra-senha")
    assert repo.usuario_de_sessao_salva(conn, usuario_id, token) is None


def test_desativar_a_conta_derruba_a_sessao(conn, usuario_id):
    token = repo.salvar_sessao(conn, usuario_id)
    repo.definir_ativo(conn, usuario_id, False)
    assert repo.usuario_de_sessao_salva(conn, usuario_id, token) is None


def test_esquecer_sessao_apaga(conn, usuario_id):
    token = repo.salvar_sessao(conn, usuario_id)
    repo.esquecer_sessao(conn, usuario_id)
    assert repo.usuario_de_sessao_salva(conn, usuario_id, token) is None


def test_excluir_o_usuario_leva_a_sessao_junto(conn, usuario_id):
    repo.salvar_sessao(conn, usuario_id)
    conn.execute("DELETE FROM usuario WHERE id=?", (usuario_id,))
    conn.commit()
    assert conn.execute("SELECT COUNT(*) AS n FROM sessao_salva").fetchone()["n"] == 0


# -------------------------------------------------------- preferências --


def test_guardar_e_ler_a_sessao_da_maquina(prefs):
    assert preferencias.sessao_salva() is None
    preferencias.guardar_sessao(7, "abc123")
    assert preferencias.sessao_salva() == (7, "abc123")
    preferencias.esquecer_sessao()
    assert preferencias.sessao_salva() is None


def test_preferencias_com_conteudo_estranho_nao_quebram(prefs):
    """Arquivo editado à mão ou de uma versão antiga não pode impedir o
    programa de abrir."""
    for lixo in ('{"sessao_salva": "texto"}', '{"sessao_salva": {"usuario_id": "x", "token": 1}}',
                 '{"sessao_salva": {}}', "{}"):
        prefs.write_text(lixo, encoding="utf-8")
        assert preferencias.sessao_salva() is None


def test_ultimo_login_e_guardado_sem_a_senha(prefs):
    preferencias.guardar_ultimo_login("fulano")
    assert preferencias.ultimo_login() == "fulano"
    assert "senha" not in prefs.read_text(encoding="utf-8")


# ------------------------------------------------------ tela e fluxo --


@pytest.fixture(scope="module", autouse=True)
def app():
    from PySide6.QtWidgets import QApplication

    aplicativo = QApplication.instance() or QApplication([])
    yield aplicativo


def _dialogo(conn):
    from controle_lucros.ui.login import DialogoLogin

    return DialogoLogin(conn)


def test_a_opcao_vem_desmarcada(conn, usuario_id, prefs):
    """Padrão seguro: entrar direto só acontece se a pessoa pedir."""
    assert not _dialogo(conn).continuar_conectado.isChecked()


def test_entrar_sem_marcar_nao_deixa_sessao(conn, usuario_id, prefs):
    dialogo = _dialogo(conn)
    dialogo.login.setText("fulano")
    dialogo.senha.setText("senha123")
    dialogo._entrar()

    assert dialogo.usuario_autenticado is not None
    assert preferencias.sessao_salva() is None
    # Mas o login fica guardado, pra não redigitar.
    assert preferencias.ultimo_login() == "fulano"


def test_entrar_marcando_guarda_a_sessao(conn, usuario_id, prefs):
    dialogo = _dialogo(conn)
    dialogo.login.setText("fulano")
    dialogo.senha.setText("senha123")
    dialogo.continuar_conectado.setChecked(True)
    dialogo._entrar()

    salva = preferencias.sessao_salva()
    assert salva is not None and salva[0] == usuario_id
    assert repo.usuario_de_sessao_salva(conn, *salva) is not None


def test_desmarcar_e_entrar_apaga_a_sessao_anterior(conn, usuario_id, prefs):
    """Sem isto a opção só ligaria e nunca desligaria."""
    dialogo = _dialogo(conn)
    dialogo.login.setText("fulano")
    dialogo.senha.setText("senha123")
    dialogo.continuar_conectado.setChecked(True)
    dialogo._entrar()
    assert preferencias.sessao_salva() is not None

    outro = _dialogo(conn)
    outro.login.setText("fulano")
    outro.senha.setText("senha123")
    outro.continuar_conectado.setChecked(False)
    outro._entrar()
    assert preferencias.sessao_salva() is None
    assert conn.execute("SELECT COUNT(*) AS n FROM sessao_salva").fetchone()["n"] == 0


def test_senha_errada_nao_guarda_nada(conn, usuario_id, prefs):
    dialogo = _dialogo(conn)
    dialogo.login.setText("fulano")
    dialogo.senha.setText("errada")
    dialogo.continuar_conectado.setChecked(True)
    dialogo._entrar()

    assert dialogo.usuario_autenticado is None
    assert preferencias.sessao_salva() is None
    assert preferencias.ultimo_login() == ""


def test_login_anterior_vem_preenchido(conn, usuario_id, prefs):
    preferencias.guardar_ultimo_login("fulano")
    dialogo = _dialogo(conn)
    assert dialogo.login.text() == "fulano"
    # Com o login pronto, o cursor já vai pra senha.
    assert dialogo.focusWidget() is dialogo.senha


def test_auto_login_usa_a_sessao_salva(conn, usuario_id, prefs):
    import main as programa

    preferencias.guardar_sessao(usuario_id, repo.salvar_sessao(conn, usuario_id))
    usuario = programa._entrar_com_sessao_salva(conn)
    assert usuario is not None and usuario.login == "fulano"


def test_auto_login_limpa_a_preferencia_quando_o_token_nao_vale(conn, usuario_id, prefs):
    """Banco trocado, conta desativada, prazo vencido: cai na tela de login e
    não fica tentando o mesmo token pra sempre."""
    import main as programa

    preferencias.guardar_sessao(usuario_id, "token-que-nao-existe")
    assert programa._entrar_com_sessao_salva(conn) is None
    assert preferencias.sessao_salva() is None


def test_sair_encerra_o_continuar_conectado(conn, usuario_id, prefs, monkeypatch):
    """Sair é como se passa o computador pra outra pessoa; sem encerrar, a
    tela de login nem apareceria de novo."""
    from PySide6.QtWidgets import QMessageBox

    from controle_lucros.ui import main_window as mod
    from controle_lucros.ui.main_window import MainWindow

    preferencias.guardar_sessao(usuario_id, repo.salvar_sessao(conn, usuario_id))
    janela = MainWindow(conn, repo.listar_usuarios(conn)[0])
    monkeypatch.setattr(mod.QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    janela._sair()

    assert janela.logout_solicitado
    assert preferencias.sessao_salva() is None
    assert conn.execute("SELECT COUNT(*) AS n FROM sessao_salva").fetchone()["n"] == 0
