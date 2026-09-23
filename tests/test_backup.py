import json
import os

import psycopg
import pytest

from controle_lucros import backup, db, preferencias, repositories as repo
from controle_lucros.models import Empresa, Socio, VinculoSocietario


@pytest.fixture()
def conn(conn):
    """O banco de teste com uma empresa cadastrada."""
    conn.execute(
        "INSERT INTO empresa (numero_chamada, nome, cnpj, capital_social, quantidade_cotas) "
        "VALUES ('001', 'ACME LTDA', '', 1000, 100)"
    )
    conn.commit()
    return conn


@pytest.fixture(autouse=True)
def preferencias_isoladas(tmp_path, monkeypatch):
    """Nunca deixa um teste de backup escrever no preferencias.json de
    verdade do projeto — cada teste ganha seu próprio arquivo isolado."""
    arquivo = tmp_path / "preferencias.json"
    monkeypatch.setattr(preferencias, "_arquivo", lambda: arquivo)
    yield arquivo


def _nomes_das_empresas(conn) -> list[str]:
    return [r["nome"] for r in conn.execute("SELECT nome FROM empresa ORDER BY id")]


def test_criar_backup_gera_arquivo_com_os_dados_atuais(conn, tmp_path):
    caminho = backup.criar_backup(conn, tmp_path)
    assert caminho.exists()
    assert caminho.parent == tmp_path
    assert caminho.suffix == ".json"

    conteudo = json.loads(caminho.read_text(encoding="utf-8"))
    empresas = conteudo["tabelas"]["empresa"]
    (linha,) = empresas["linhas"]
    assert dict(zip(empresas["colunas"], linha))["nome"] == "ACME LTDA"


def test_backup_leva_todas_as_tabelas(conn, tmp_path):
    conteudo = json.loads(backup.criar_backup(conn, tmp_path).read_text(encoding="utf-8"))
    assert set(conteudo["tabelas"]) == set(db.TABELAS)


def test_backup_nao_deixa_transacao_aberta(conn, tmp_path):
    """Leitura em transação aberta seguraria travas no servidor — e a
    próxima restauração, em outro PC, ficaria esperando por ela."""
    backup.criar_backup(conn, tmp_path)
    assert not conn.em_transacao


def test_listar_backups_ordena_do_mais_recente_pro_mais_antigo(conn, tmp_path):
    antigo = tmp_path / f"{backup.PREFIXO}20200101_000000.json"
    novo = tmp_path / f"{backup.PREFIXO}20240101_000000.json"
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


def test_pasta_padrao_fica_neste_computador():
    assert backup.pasta_backup_padrao() == db.pasta_local() / "backups"


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


def test_restaurar_backup_substitui_os_dados(conn, tmp_path):
    caminho_backup = backup.criar_backup(conn, tmp_path)
    conn.execute("UPDATE empresa SET nome = 'MUDOU DEPOIS LTDA'")
    conn.execute(
        "INSERT INTO empresa (numero_chamada, nome, cnpj, capital_social, quantidade_cotas) "
        "VALUES ('002', 'NOVA LTDA', '', 1, 1)"
    )
    conn.commit()

    backup.restaurar_backup(conn, caminho_backup)

    assert _nomes_das_empresas(conn) == ["ACME LTDA"]


def test_restaurar_leva_os_relacionamentos_juntos(conn, tmp_path):
    empresa_id = conn.execute("SELECT id FROM empresa").fetchone()[0]
    socio_id = repo.salvar_socio(conn, Socio(id=None, nome="Fulano", cpf="111.111.111-11"))
    repo.salvar_vinculo(conn, VinculoSocietario(
        id=None, empresa_id=empresa_id, socio_id=socio_id, percentual_capital=100.0,
        quantidade_cotas=100, data_entrada="2024-01-01", data_saida=None))
    caminho_backup = backup.criar_backup(conn, tmp_path)
    conn.execute("TRUNCATE vinculo_societario, socio, log_atividade CASCADE")
    conn.commit()

    backup.restaurar_backup(conn, caminho_backup)

    (vinculo,) = repo.listar_vinculos_empresa(conn, empresa_id)
    assert vinculo.socio_id == socio_id


def test_depois_de_restaurar_o_proximo_cadastro_nao_repete_id(conn, tmp_path):
    caminho_backup = backup.criar_backup(conn, tmp_path)
    backup.restaurar_backup(conn, caminho_backup)

    novo_id = repo.salvar_empresa(conn, Empresa(None, "002", "OUTRA LTDA", "", 1, 1))

    assert _nomes_das_empresas(conn) == ["ACME LTDA", "OUTRA LTDA"]
    assert novo_id > conn.execute("SELECT MIN(id) FROM empresa").fetchone()[0]


def test_restaurar_com_outro_computador_usando_o_banco(conn, tmp_path):
    """Outro PC conectado vê os dados restaurados, sem precisar reconectar."""
    caminho_backup = backup.criar_backup(conn, tmp_path)
    outro_pc = db.connect()
    try:
        assert _nomes_das_empresas(outro_pc) == ["ACME LTDA"]
        conn.execute("UPDATE empresa SET nome = 'MUDOU LTDA'")
        conn.commit()

        backup.restaurar_backup(conn, caminho_backup)

        assert _nomes_das_empresas(outro_pc) == ["ACME LTDA"]
    finally:
        outro_pc.close()


def test_restaurar_recusa_arquivo_que_nao_e_backup(conn, tmp_path):
    """Escolher o arquivo errado não pode apagar o banco do escritório."""
    errado = tmp_path / "qualquer.json"
    errado.write_text('{"outra": "coisa"}', encoding="utf-8")
    lixo = tmp_path / "lixo.json"
    lixo.write_bytes(b"nao sou json")

    for arquivo in (errado, lixo):
        with pytest.raises(ValueError):
            backup.restaurar_backup(conn, arquivo)

    assert _nomes_das_empresas(conn) == ["ACME LTDA"]


def test_restaurar_que_falha_no_meio_nao_apaga_nada(conn, tmp_path):
    """A restauração começa apagando tudo. Se um registro do backup não
    entra (arquivo editado à mão, por exemplo), o banco tem que voltar como
    estava — não pode ficar vazio."""
    caminho_backup = backup.criar_backup(conn, tmp_path)
    conteudo = json.loads(caminho_backup.read_text(encoding="utf-8"))
    conteudo["tabelas"]["vinculo_societario"] = {
        "colunas": ["id", "empresa_id", "socio_id", "percentual_capital", "data_entrada"],
        "linhas": [[1, 999, 999, 10.0, "2024-01-01"]],  # empresa e sócio que não existem
    }
    caminho_backup.write_text(json.dumps(conteudo), encoding="utf-8")

    with pytest.raises(psycopg.IntegrityError):
        backup.restaurar_backup(conn, caminho_backup)

    assert _nomes_das_empresas(conn) == ["ACME LTDA"]
    assert not conn.em_transacao


def test_backup_de_versao_anterior_sem_coluna_nova_restaura(conn, tmp_path):
    caminho_backup = backup.criar_backup(conn, tmp_path)
    conteudo = json.loads(caminho_backup.read_text(encoding="utf-8"))
    socios = conteudo["tabelas"]["socio"]
    socios["colunas"] = ["id", "nome", "cpf"]  # antes do tipo_pessoa existir
    socios["linhas"] = [[7, "Fulano", "111"]]
    caminho_backup.write_text(json.dumps(conteudo), encoding="utf-8")

    backup.restaurar_backup(conn, caminho_backup)

    (socio,) = repo.listar_socios(conn)
    assert (socio.id, socio.nome, socio.tipo_pessoa) == (7, "Fulano", "fisica")


def test_backup_de_versao_mais_nova_e_recusado(conn, tmp_path):
    caminho_backup = backup.criar_backup(conn, tmp_path)
    conteudo = json.loads(caminho_backup.read_text(encoding="utf-8"))
    conteudo["versao_formato"] = backup.VERSAO_DO_FORMATO + 1
    caminho_backup.write_text(json.dumps(conteudo), encoding="utf-8")

    with pytest.raises(ValueError, match="versão mais nova"):
        backup.restaurar_backup(conn, caminho_backup)


def test_formatar_tamanho():
    assert backup.formatar_tamanho(500) == "500 B"
    assert backup.formatar_tamanho(2048) == "2.0 KB"
    assert backup.formatar_tamanho(5 * 1024 * 1024) == "5.0 MB"
