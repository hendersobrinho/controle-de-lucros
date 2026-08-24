import sqlite3

import pytest

from controle_lucros import db, repositories as repo, sessao
from controle_lucros.models import Empresa


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    db.init_schema(connection)
    yield connection
    connection.close()
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

    conn.execute("DELETE FROM usuario WHERE id=?", (usuario_id,))
    conn.commit()

    logs = [l for l in repo.listar_log_atividade(conn) if l.entidade == "empresa"]
    assert logs[0].usuario_nome == "Fulano"
