import datetime as dt
import os
import sqlite3

import pytest

from controle_lucros import backup, db, preferencias


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    db.init_schema(connection)
    connection.execute(
        "INSERT INTO empresa (numero_chamada, nome, cnpj, capital_social, quantidade_cotas) "
        "VALUES ('001', 'ACME LTDA', '', 1000, 100)"
    )
    connection.commit()
    yield connection
    connection.close()


@pytest.fixture(autouse=True)
def preferencias_isoladas(tmp_path, monkeypatch):
    """Nunca deixa um teste de backup escrever no preferencias.json de
    verdade do projeto — cada teste ganha seu próprio arquivo isolado."""
    arquivo = tmp_path / "preferencias.json"
    monkeypatch.setattr(preferencias, "_arquivo", lambda: arquivo)
    yield arquivo


def test_criar_backup_gera_arquivo_com_os_dados_atuais(conn, tmp_path):
    caminho = backup.criar_backup(conn, tmp_path)
    assert caminho.exists()
    assert caminho.parent == tmp_path

    copia = sqlite3.connect(caminho)
    copia.row_factory = sqlite3.Row
    (empresa,) = copia.execute("SELECT * FROM empresa").fetchall()
    assert empresa["nome"] == "ACME LTDA"
    copia.close()


def test_listar_backups_ordena_do_mais_recente_pro_mais_antigo(conn, tmp_path):
    antigo = tmp_path / f"{backup.PREFIXO}20200101_000000.db"
    novo = tmp_path / f"{backup.PREFIXO}20240101_000000.db"
    antigo.write_bytes(b"x")
    novo.write_bytes(b"x")
    os.utime(antigo, (1000, 1000))
    os.utime(novo, (2000, 2000))

    listados = backup.listar_backups(tmp_path)
    assert [b["nome"] for b in listados] == [novo.name, antigo.name]


def test_listar_backups_pasta_inexistente_retorna_vazio(tmp_path):
    assert backup.listar_backups(tmp_path / "nao_existe") == []


def test_pasta_backup_e_configuravel(tmp_path):
    assert backup.pasta_backup_configurada() == backup.pasta_backup_padrao()
    nova_pasta = tmp_path / "meus_backups"
    backup.definir_pasta_backup(nova_pasta)
    assert backup.pasta_backup_configurada() == nova_pasta


def test_automatico_desabilitado_por_padrao_nao_cria_backup(conn, tmp_path):
    backup.definir_pasta_backup(tmp_path)
    assert backup.automatico_habilitado() is False
    assert backup.backup_automatico_se_necessario(conn) is None
    assert backup.listar_backups(tmp_path) == []


def test_automatico_habilitado_cria_uma_vez_por_dia(conn, tmp_path):
    backup.definir_pasta_backup(tmp_path)
    backup.definir_automatico(True)

    primeiro = backup.backup_automatico_se_necessario(conn)
    assert primeiro is not None
    assert len(backup.listar_backups(tmp_path)) == 1

    segundo = backup.backup_automatico_se_necessario(conn)
    assert segundo is None
    assert len(backup.listar_backups(tmp_path)) == 1


def _banco_com_empresa(caminho, nome):
    conn = db.connect(caminho)
    db.init_schema(conn)
    conn.execute(
        "INSERT INTO empresa (numero_chamada, nome, cnpj, capital_social, quantidade_cotas) "
        "VALUES ('001', ?, '', 1000, 100)", (nome,)
    )
    conn.commit()
    return conn


def test_restaurar_backup_substitui_os_dados(tmp_path):
    caminho_db = tmp_path / "controle_lucros.db"
    _banco_com_empresa(caminho_db, "ATUAL LTDA").close()
    caminho_backup = tmp_path / "backup_para_restaurar.db"
    _banco_com_empresa(caminho_backup, "DO BACKUP LTDA").close()

    backup.restaurar_backup(caminho_backup, caminho_db)

    conn = db.connect(caminho_db)
    assert [r["nome"] for r in conn.execute("SELECT nome FROM empresa")] == ["DO BACKUP LTDA"]
    conn.close()


def test_restaurar_com_outro_computador_usando_o_banco(tmp_path):
    """Com o banco no servidor, outro PC pode estar com ele aberto. Trocar o
    arquivo por baixo dele corromperia o banco; pelo backup do SQLite, o
    outro PC passa a enxergar os dados restaurados."""
    caminho_db = tmp_path / "controle_lucros.db"
    outro_pc = _banco_com_empresa(caminho_db, "ATUAL LTDA")
    caminho_backup = tmp_path / "backup_para_restaurar.db"
    _banco_com_empresa(caminho_backup, "DO BACKUP LTDA").close()

    backup.restaurar_backup(caminho_backup, caminho_db)

    assert [r["nome"] for r in outro_pc.execute("SELECT nome FROM empresa")] == ["DO BACKUP LTDA"]
    outro_pc.close()


def test_restaurar_recusa_arquivo_que_nao_e_backup(tmp_path):
    """Escolher o arquivo errado não pode apagar o banco do escritório."""
    caminho_db = tmp_path / "controle_lucros.db"
    _banco_com_empresa(caminho_db, "ATUAL LTDA").close()
    errado = tmp_path / "qualquer.db"
    errado.write_bytes(b"nao sou um banco")

    with pytest.raises(ValueError):
        backup.restaurar_backup(errado, caminho_db)

    conn = db.connect(caminho_db)
    assert [r["nome"] for r in conn.execute("SELECT nome FROM empresa")] == ["ATUAL LTDA"]
    conn.close()


def test_formatar_tamanho():
    assert backup.formatar_tamanho(500) == "500 B"
    assert backup.formatar_tamanho(2048) == "2.0 KB"
    assert backup.formatar_tamanho(5 * 1024 * 1024) == "5.0 MB"
