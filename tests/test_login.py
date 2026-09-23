"""As telas de entrada: primeiro acesso, login e troca de senha.

Não havia teste nenhum aqui, e o preço apareceu: uma mexida no layout deixou a
troca de senha quebrando ao abrir, porque nada instanciava o diálogo. Os testes
de construção existem por isso — a tela que só é aberta de vez em quando é
exatamente a que ninguém percebe que parou de funcionar.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


import pytest
from PySide6.QtWidgets import QApplication, QDialog

from controle_lucros import repositories as repo
from controle_lucros.ui.login import (
    DialogoLogin,
    DialogoPrimeiroUsuario,
    DialogoTrocarMinhaSenha,
)


@pytest.fixture(scope="module", autouse=True)
def app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture()
def usuario(conn):
    repo.criar_usuario(conn, "Henderson Pereira", "henderson", "senha123", True)
    return repo.buscar_usuario_por_login(conn, "henderson")


def _textos(dialogo):
    """O texto de todos os rótulos do diálogo. `isVisible` não serve aqui: um
    filho só conta como visível depois que a janela é exibida, e estes testes
    não abrem janela nenhuma — por isso o aviso de erro é conferido com
    `isVisibleTo`."""
    from PySide6.QtWidgets import QLabel

    return " ".join(r.text() for r in dialogo.findChildren(QLabel))


# ------------------------------------------------------------- construção --
def test_as_tres_telas_abrem(conn, usuario):
    assert DialogoLogin(conn) is not None
    assert DialogoPrimeiroUsuario(conn) is not None
    assert DialogoTrocarMinhaSenha(conn, usuario) is not None


def test_a_entrada_da_boas_vindas(conn, usuario):
    """É a primeira coisa que se vê do programa todo dia."""
    assert "Seja bem-vindo" in _textos(DialogoLogin(conn))
    assert "Seja bem-vindo" in _textos(DialogoPrimeiroUsuario(conn))


def test_o_foco_comeca_onde_se_digita(conn, usuario):
    dialogo = DialogoLogin(conn)
    assert dialogo.login.hasFocus() or dialogo.focusWidget() is dialogo.login


# ------------------------------------------------------------------ login --
def test_login_correto_autentica(conn, usuario):
    dialogo = DialogoLogin(conn)
    dialogo.login.setText("henderson")
    dialogo.senha.setText("senha123")

    dialogo._entrar()

    assert dialogo.result() == QDialog.Accepted
    assert dialogo.usuario_autenticado.login == "henderson"


def test_senha_errada_avisa_e_limpa_o_campo(conn, usuario):
    dialogo = DialogoLogin(conn)
    dialogo.login.setText("henderson")
    dialogo.senha.setText("errada")

    dialogo._entrar()

    assert dialogo.usuario_autenticado is None
    assert dialogo.erro.isVisibleTo(dialogo)
    assert dialogo.senha.text() == ""


def test_usuario_desativado_nao_entra(conn, usuario):
    repo.definir_ativo(conn, usuario.id, False)
    dialogo = DialogoLogin(conn)
    dialogo.login.setText("henderson")
    dialogo.senha.setText("senha123")

    dialogo._entrar()

    assert dialogo.usuario_autenticado is None
    assert dialogo.erro.isVisibleTo(dialogo)


# --------------------------------------------------------- primeiro acesso --
def test_primeiro_acesso_cria_a_conta_administradora(conn):
    dialogo = DialogoPrimeiroUsuario(conn)
    dialogo.nome.setText("Henderson Pereira")
    dialogo.login.setText("henderson")
    dialogo.senha.setText("senha123")
    dialogo.confirmar.setText("senha123")

    dialogo._criar()

    assert dialogo.result() == QDialog.Accepted
    (criado,) = repo.listar_usuarios(conn)
    assert criado.login == "henderson"
    assert criado.admin
    assert dialogo.usuario_autenticado.id == criado.id


@pytest.mark.parametrize(
    "nome,login,senha,confirmar",
    [
        ("", "henderson", "senha123", "senha123"),      # sem nome
        ("Henderson", "", "senha123", "senha123"),      # sem login
        ("Henderson", "henderson", "123", "123"),       # senha curta demais
        ("Henderson", "henderson", "senha123", "outra"),  # não confere
    ],
    ids=["sem nome", "sem login", "senha curta", "senhas diferentes"],
)
def test_primeiro_acesso_recusa_dados_incompletos(conn, nome, login, senha, confirmar):
    dialogo = DialogoPrimeiroUsuario(conn)
    dialogo.nome.setText(nome)
    dialogo.login.setText(login)
    dialogo.senha.setText(senha)
    dialogo.confirmar.setText(confirmar)

    dialogo._criar()

    assert repo.listar_usuarios(conn) == []
    assert dialogo.erro.isVisibleTo(dialogo)


# ----------------------------------------------------------- trocar senha --
def test_trocar_senha_exige_a_atual(conn, usuario):
    dialogo = DialogoTrocarMinhaSenha(conn, usuario)
    dialogo.senha_atual.setText("errada")
    dialogo.senha_nova.setText("novasenha")
    dialogo.confirmar.setText("novasenha")

    dialogo._validar()

    assert dialogo.erro.isVisibleTo(dialogo)
    assert repo.autenticar(conn, "henderson", "senha123") is not None


def test_trocar_senha_troca_mesmo(conn, usuario):
    dialogo = DialogoTrocarMinhaSenha(conn, usuario)
    dialogo.senha_atual.setText("senha123")
    dialogo.senha_nova.setText("novasenha")
    dialogo.confirmar.setText("novasenha")

    dialogo._validar()

    assert dialogo.result() == QDialog.Accepted
    assert repo.autenticar(conn, "henderson", "novasenha") is not None
    assert repo.autenticar(conn, "henderson", "senha123") is None
