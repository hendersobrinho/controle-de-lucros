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


@pytest.fixture(autouse=True)
def preferencias_deste_teste(tmp_path, monkeypatch):
    """O login lembrado fica nas preferências do PC: cada teste com a sua
    pasta, pra um não abrir a tela já preenchida pelo outro."""
    monkeypatch.setenv("CONTROLE_LUCROS_DADOS", str(tmp_path))


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
    assert dialogo.erro.text() == "Senha incorreta."


def test_usuario_desativado_nao_entra(conn, usuario):
    repo.definir_ativo(conn, usuario.id, False)
    dialogo = DialogoLogin(conn)
    dialogo.login.setText("henderson")
    dialogo.senha.setText("senha123")

    dialogo._entrar()

    assert dialogo.usuario_autenticado is None
    assert dialogo.erro.isVisibleTo(dialogo)
    assert "desativado" in dialogo.erro.text()


def test_nome_no_lugar_do_login_mostra_o_login_certo(conn, usuario):
    """O engano de quem esqueceu a senha: digita o nome, não o login, e uma
    senha recém-redefinida parecia não ter funcionado."""
    dialogo = DialogoLogin(conn)
    dialogo.login.setText(usuario.nome)
    dialogo.senha.setText("senha123")

    dialogo._entrar()

    assert dialogo.usuario_autenticado is None
    assert "login: henderson" in dialogo.erro.text()


def test_login_que_nao_existe_diz_isso(conn, usuario):
    dialogo = DialogoLogin(conn)
    dialogo.login.setText("ninguem")
    dialogo.senha.setText("senha123")

    dialogo._entrar()

    assert 'Não existe usuário com o login "ninguem"' in dialogo.erro.text()


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


# ---------------------------------------------------------- lembrar login --
def _entrar(conn, login, senha, lembrar):
    dialogo = DialogoLogin(conn)
    dialogo.login.setText(login)
    dialogo.senha.setText(senha)
    dialogo.lembrar.setChecked(lembrar)
    dialogo._entrar()
    return dialogo


def test_sem_login_lembrado_a_tela_abre_vazia(conn, usuario):
    dialogo = DialogoLogin(conn)
    assert dialogo.login.text() == ""
    assert not dialogo.lembrar.isChecked()


def test_lembrar_preenche_o_login_na_proxima_abertura(conn, usuario):
    _entrar(conn, "henderson", "senha123", lembrar=True)

    proxima = DialogoLogin(conn)
    assert proxima.login.text() == "henderson"
    assert proxima.lembrar.isChecked()
    # Só falta a senha: o cursor já vai pra ela.
    assert proxima.senha.hasFocus() or proxima.focusWidget() is proxima.senha
    assert proxima.senha.text() == ""


def test_a_senha_nunca_fica_guardada(conn, usuario, tmp_path):
    _entrar(conn, "henderson", "senha123", lembrar=True)
    for arquivo in tmp_path.rglob("*"):
        if arquivo.is_file():
            assert "senha123" not in arquivo.read_text(encoding="utf-8", errors="ignore")


def test_desmarcar_esquece_o_login(conn, usuario):
    _entrar(conn, "henderson", "senha123", lembrar=True)
    _entrar(conn, "henderson", "senha123", lembrar=False)
    assert DialogoLogin(conn).login.text() == ""


def test_login_errado_nao_e_lembrado(conn, usuario):
    """Só se lembra o login que entrou: um errado preencheria a próxima
    abertura com algo que não funciona."""
    dialogo = _entrar(conn, "henderzon", "senha123", lembrar=True)
    assert dialogo.usuario_autenticado is None
    assert DialogoLogin(conn).login.text() == ""


def test_lembra_o_login_como_cadastrado(conn, usuario):
    """Login digitado com maiúscula ou espaço é guardado como está no cadastro."""
    _entrar(conn, "  Henderson ", "senha123", lembrar=True)
    assert DialogoLogin(conn).login.text() == "henderson"


# ---------------------------------------------------- entrar sem a senha --
from controle_lucros.ui.login import entrar_sem_senha, esquecer_acesso  # noqa: E402


def _entrar_direto(conn):
    dialogo = DialogoLogin(conn)
    dialogo.login.setText("henderson")
    dialogo.senha.setText("senha123")
    dialogo.entrar_direto.setChecked(True)
    dialogo._entrar()
    return dialogo


def test_sem_marcar_continua_pedindo_a_senha(conn, usuario):
    _entrar(conn, "henderson", "senha123", lembrar=True)
    assert entrar_sem_senha(conn) is None


def test_entrar_direto_abre_a_conta_na_proxima_vez(conn, usuario):
    _entrar_direto(conn)
    assert entrar_sem_senha(conn).login == "henderson"


def test_entrar_direto_tambem_lembra_o_login(conn, usuario):
    dialogo = DialogoLogin(conn)
    dialogo.entrar_direto.setChecked(True)
    assert dialogo.lembrar.isChecked()
    dialogo.lembrar.setChecked(False)
    assert not dialogo.entrar_direto.isChecked()


def test_entrar_direto_nao_guarda_a_senha(conn, usuario, tmp_path):
    _entrar_direto(conn)
    for arquivo in tmp_path.rglob("*"):
        if arquivo.is_file():
            assert "senha123" not in arquivo.read_text(encoding="utf-8", errors="ignore")
    linhas = conn.execute("SELECT chave_hash FROM acesso_lembrado").fetchall()
    assert len(linhas) == 1 and "senha123" not in linhas[0]["chave_hash"]


def test_sair_volta_a_pedir_a_senha(conn, usuario):
    _entrar_direto(conn)
    esquecer_acesso(conn)
    assert entrar_sem_senha(conn) is None
    assert conn.execute("SELECT count(*) AS n FROM acesso_lembrado").fetchone()["n"] == 0


def test_trocar_a_senha_derruba_o_entrar_direto(conn, usuario):
    _entrar_direto(conn)
    repo.alterar_senha(conn, usuario.id, "outra456")
    assert entrar_sem_senha(conn) is None


def test_usuario_desativado_nao_entra_direto(conn, usuario):
    _entrar_direto(conn)
    repo.definir_ativo(conn, usuario.id, False)
    assert entrar_sem_senha(conn) is None
