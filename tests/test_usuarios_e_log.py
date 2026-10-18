
import pytest

from controle_lucros import repositories as repo, sessao
from controle_lucros.models import Empresa


@pytest.fixture(autouse=True)
def sem_usuario_na_sessao():
    yield
    sessao.definir_usuario_atual(None)


def test_criar_e_autenticar_usuario(conn):
    repo.criar_usuario(conn, "Fulano", "fulano", "senha123", admin=True)
    usuario = repo.autenticar(conn, "fulano", "senha123")
    assert usuario is not None
    assert usuario.nome == "Fulano"
    assert usuario.admin is True


def test_autenticar_com_senha_errada_retorna_none(conn):
    repo.criar_usuario(conn, "Fulano", "fulano", "senha123")
    assert repo.autenticar(conn, "fulano", "senha_errada") is None


def test_autenticar_usuario_inexistente_retorna_none(conn):
    assert repo.autenticar(conn, "ninguem", "qualquer") is None


def test_nao_deixa_criar_login_duplicado(conn):
    repo.criar_usuario(conn, "Fulano", "fulano", "senha123")
    with pytest.raises(ValueError):
        repo.criar_usuario(conn, "Outro Fulano", "FULANO", "outrasenha")


def test_login_e_case_insensitive(conn):
    repo.criar_usuario(conn, "Fulano", "Fulano.Silva", "senha123")
    assert repo.autenticar(conn, "fulano.silva", "senha123") is not None
    assert repo.autenticar(conn, "FULANO.SILVA", "senha123") is not None


def test_usuario_desativado_nao_autentica(conn):
    usuario_id = repo.criar_usuario(conn, "Fulano", "fulano", "senha123")
    repo.definir_ativo(conn, usuario_id, False)
    assert repo.autenticar(conn, "fulano", "senha123") is None
    repo.definir_ativo(conn, usuario_id, True)
    assert repo.autenticar(conn, "fulano", "senha123") is not None


def test_alterar_senha(conn):
    usuario_id = repo.criar_usuario(conn, "Fulano", "fulano", "senha_antiga")
    repo.alterar_senha(conn, usuario_id, "senha_nova")
    assert repo.autenticar(conn, "fulano", "senha_antiga") is None
    assert repo.autenticar(conn, "fulano", "senha_nova") is not None


def test_existe_algum_usuario(conn):
    assert repo.existe_algum_usuario(conn) is False
    repo.criar_usuario(conn, "Fulano", "fulano", "senha123")
    assert repo.existe_algum_usuario(conn) is True


def test_atualizar_usuario_rejeita_login_ja_usado(conn):
    repo.criar_usuario(conn, "Fulano", "fulano", "senha123")
    id2 = repo.criar_usuario(conn, "Beltrano", "beltrano", "senha123")
    with pytest.raises(ValueError):
        repo.atualizar_usuario(conn, id2, "Beltrano", "fulano", admin=False)


# ------------------------------------------------------------- log de atividade --


def test_acao_sem_login_registra_como_sistema(conn):
    repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 10000, 1000))
    (log,) = repo.listar_log_atividade(conn)
    assert log.usuario_nome == "Sistema"
    assert log.usuario_id is None
    assert log.acao == "criar"
    assert log.entidade == "empresa"


def test_acao_com_usuario_logado_registra_o_nome_certo(conn):
    usuario_id = repo.criar_usuario(conn, "Fulano", "fulano", "senha123")
    usuario = repo.autenticar(conn, "fulano", "senha123")
    sessao.definir_usuario_atual(usuario)

    repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 10000, 1000))

    logs = repo.listar_log_atividade(conn)
    log_empresa = next(l for l in logs if l.entidade == "empresa")
    assert log_empresa.usuario_nome == "Fulano"
    assert log_empresa.usuario_id == usuario_id


def test_log_registra_criacao_atualizacao_e_exclusao(conn):
    empresa_id = repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 10000, 1000))
    empresa = repo.buscar_empresa(conn, empresa_id)
    empresa.nome = "ACME COMERCIO LTDA"
    repo.salvar_empresa(conn, empresa)
    repo.excluir_empresa(conn, empresa_id)

    logs = [l for l in repo.listar_log_atividade(conn) if l.entidade == "empresa"]
    acoes = [l.acao for l in logs]
    assert acoes.count("criar") == 1
    assert acoes.count("atualizar") == 1
    assert acoes.count("excluir") == 1


def test_listar_log_filtra_por_usuario(conn):
    id1 = repo.criar_usuario(conn, "Fulano", "fulano", "senha123")
    id2 = repo.criar_usuario(conn, "Beltrano", "beltrano", "senha123")

    sessao.definir_usuario_atual(repo.autenticar(conn, "fulano", "senha123"))
    repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 10000, 1000))

    sessao.definir_usuario_atual(repo.autenticar(conn, "beltrano", "senha123"))
    repo.salvar_empresa(conn, Empresa(None, "002", "BETA COMERCIO", "", 20000, 2000))

    logs_fulano = [l for l in repo.listar_log_atividade(conn, usuario_id=id1) if l.entidade == "empresa"]
    assert len(logs_fulano) == 1
    assert logs_fulano[0].detalhes.startswith("ACME")

    logs_beltrano = [l for l in repo.listar_log_atividade(conn, usuario_id=id2) if l.entidade == "empresa"]
    assert len(logs_beltrano) == 1
    assert logs_beltrano[0].detalhes.startswith("BETA")


def test_log_sobrevive_a_exclusao_do_usuario(conn):
    usuario_id = repo.criar_usuario(conn, "Fulano", "fulano", "senha123")
    sessao.definir_usuario_atual(repo.autenticar(conn, "fulano", "senha123"))
    repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 10000, 1000))

    conn.execute("DELETE FROM usuario WHERE id=%s", (usuario_id,))
    conn.commit()

    logs = [l for l in repo.listar_log_atividade(conn) if l.entidade == "empresa"]
    assert logs[0].usuario_nome == "Fulano"


def _nova_senha_confirmada(dialogo):
    """Dublê do exec() da tela de redefinir: digita "nova1234" duas vezes e
    confirma, passando pela mesma validação da tela de verdade."""
    dialogo.senha.setText("nova1234")
    dialogo.confirmar.setText("nova1234")
    dialogo._validar()
    return dialogo.result()


def test_admin_redefine_a_senha_de_outro_e_ele_entra_com_a_nova(conn, monkeypatch):
    """O caso relatado: o primeiro administrador esqueceu a senha, outro
    administrador a redefine pela aba Usuários, e o primeiro tem que entrar
    com a senha nova — e não mais com a antiga. A confirmação diz com que
    LOGIN entrar, que é o outro esquecimento comum."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from controle_lucros.ui import usuarios_tab as mod

    QApplication.instance() or QApplication([])
    repo.criar_usuario(conn, "Henderson Pereira", "henderson", "esquecida", admin=True)
    repo.criar_usuario(conn, "Outro Admin", "outro", "senha123", admin=True)
    sessao.definir_usuario_atual(repo.autenticar(conn, "outro", "senha123"))

    aba = mod.UsuariosTab(conn)
    linha = next(r for r in range(aba.tabela.count()) if aba.tabela.item(r).text() == "Henderson Pereira")
    aba.tabela.selectRow(linha)

    avisos = []
    monkeypatch.setattr(mod._DialogoNovaSenha, "exec", _nova_senha_confirmada)
    monkeypatch.setattr(mod.QMessageBox, "information", lambda *a, **k: avisos.append(a[2]))
    aba._redefinir_senha()

    assert repo.autenticar(conn, "henderson", "nova1234") is not None
    assert repo.autenticar(conn, "henderson", "esquecida") is None
    assert repo.autenticar(conn, "outro", "senha123") is not None  # a do outro não muda
    assert "login: henderson" in avisos[0]


def test_redefinir_senha_de_usuario_desativado_avisa(conn, monkeypatch):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from controle_lucros.ui import usuarios_tab as mod

    QApplication.instance() or QApplication([])
    usuario_id = repo.criar_usuario(conn, "Fulano", "fulano", "senha123")
    repo.definir_ativo(conn, usuario_id, False)
    aba = mod.UsuariosTab(conn)
    aba.tabela.selectRow(0)

    avisos = []
    monkeypatch.setattr(mod._DialogoNovaSenha, "exec", _nova_senha_confirmada)
    monkeypatch.setattr(mod.QMessageBox, "information", lambda *a, **k: avisos.append(a[2]))
    aba._redefinir_senha()

    assert "DESATIVADO" in avisos[0]


def test_ficha_do_usuario_mostra_acesso_e_atividade(conn):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel

    from controle_lucros.ui import usuarios_tab as mod

    QApplication.instance() or QApplication([])
    usuario_id = repo.criar_usuario(conn, "Fulano", "fulano", "senha123")
    repo.criar_acesso_lembrado(conn, usuario_id)
    aba = mod.UsuariosTab(conn)
    aba.tabela.selecionar_id(usuario_id)
    textos = " | ".join(l.text() for l in aba.findChildren(QLabel))
    assert "1 computador(es)" in textos
    aba._encerrar_acessos()
    assert repo.quantidade_acessos_lembrados(conn, usuario_id) == 0


def test_dialogo_de_usuario_escolhe_o_nivel_em_cartoes_e_valida(conn):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from controle_lucros.ui import usuarios_tab as mod

    QApplication.instance() or QApplication([])
    dialogo = mod.DialogoUsuario(conn)
    dialogo.nome.setText("Joana")
    dialogo.login.setText("joana")
    dialogo.senha.setText("1234")
    dialogo.confirmar.setText("4321")
    dialogo._salvar()
    assert "não são iguais" in dialogo.erro.text()
    dialogo.confirmar.setText("1234")
    dialogo.cartao_admin.escolhido.emit(True)
    dialogo._salvar()
    criado = repo.buscar_usuario_por_login(conn, "joana")
    assert criado is not None and criado.admin
