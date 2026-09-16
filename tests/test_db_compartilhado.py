"""O banco compartilhado entre os usuários do Windows da mesma máquina.

Até a 1.1.0 o banco ficava em %LOCALAPPDATA%, que é por conta do Windows:
cada pessoa que abrisse o programa encontrava um cadastro vazio só dela. O
escritório usa um PC com várias contas e precisa do mesmo cadastro para
todos, então o banco passou a morar em %PROGRAMDATA% — a pasta da máquina.

O que se testa aqui é o que quebra silencioso: o caminho escolhido, a espera
por gravação concorrente (sem ela, dois usuários ao mesmo tempo viram erro na
tela) e a migração do banco antigo (sem ela, atualizar parece ter apagado
tudo).
"""
import pathlib
import sqlite3

import pytest

from controle_lucros import db, repositories as repo
from controle_lucros.models import Empresa

PROJETO = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture()
def como_instalado(monkeypatch, tmp_path):
    """Finge o programa empacotado (sys.frozen), com as duas pastas do
    Windows apontando pra lugares temporários."""
    monkeypatch.setattr(db.sys, "frozen", True, raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path / "ProgramData"))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Users" / "fulano" / "AppData" / "Local"))
    return tmp_path


def test_empacotado_o_banco_fica_na_pasta_da_maquina(como_instalado):
    """%PROGRAMDATA% é da máquina; %LOCALAPPDATA% é de uma conta só. É essa
    troca que faz o colega do lado ver o mesmo cadastro."""
    pasta = db._pasta_dados_padrao()
    assert pasta == como_instalado / "ProgramData" / "ControleDeLucros" / "data"
    assert "AppData" not in str(pasta)


def test_sem_programdata_ainda_assim_abre(como_instalado, monkeypatch):
    """Windows sem a variável é caso estranho, mas cair pra conta do usuário
    é melhor do que não abrir."""
    monkeypatch.delenv("PROGRAMDATA")
    assert "AppData" in str(db._pasta_dados_padrao())


def test_rodando_do_codigo_o_banco_continua_ao_lado_do_projeto(monkeypatch):
    monkeypatch.setattr(db.sys, "frozen", False, raising=False)
    assert db._pasta_dados_padrao().name == "data"
    assert "ProgramData" not in str(db._pasta_dados_padrao())


def test_conexao_espera_a_vez_em_vez_de_recusar(tmp_path):
    """Sem busy_timeout o SQLite devolve "database is locked" na hora, e dois
    usuários gravando ao mesmo tempo viram erro de tela."""
    conn = db.connect(tmp_path / "x.db")
    espera = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
    conn.close()
    assert espera == db.ESPERA_DE_BLOQUEIO_MS


def test_duas_instancias_gravam_no_mesmo_banco_e_uma_ve_a_outra(tmp_path):
    """O caso que o escritório vai viver: duas janelas abertas ao mesmo
    tempo, cada uma na sua conta do Windows, no mesmo arquivo."""
    caminho = tmp_path / "compartilhado.db"
    primeira = db.connect(caminho)
    db.init_schema(primeira)
    segunda = db.connect(caminho)

    repo.salvar_empresa(primeira, Empresa(None, "91", "ENDOGASTRO LTDA", "", 1000, 1000))
    repo.salvar_empresa(segunda, Empresa(None, "148", "RENAL NEFRON LTDA", "", 2000, 2000))

    # Cada conexão enxerga o que a outra gravou, que é o ponto de compartilhar.
    assert [e.nome for e in repo.listar_empresas(primeira)] == ["ENDOGASTRO LTDA", "RENAL NEFRON LTDA"]
    assert [e.nome for e in repo.listar_empresas(segunda)] == ["ENDOGASTRO LTDA", "RENAL NEFRON LTDA"]
    primeira.close()
    segunda.close()


# ------------------------------------------------------------- migração --


def _banco_antigo_com_uma_empresa(pasta):
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / "controle_lucros.db"
    conn = db.connect(caminho)
    db.init_schema(conn)
    repo.salvar_empresa(conn, Empresa(None, "91", "ENDOGASTRO LTDA", "", 1000, 1000))
    conn.close()
    return caminho


def test_migra_o_cadastro_que_estava_na_conta_do_windows(como_instalado):
    """Atualizar o programa não pode fazer o cadastro sumir da vista."""
    antiga = db.pasta_dados_por_usuario()
    _banco_antigo_com_uma_empresa(antiga)
    destino = db._pasta_dados_padrao() / "controle_lucros.db"

    origem = db.migrar_banco_por_usuario(destino)

    assert origem == antiga / "controle_lucros.db"
    conn = db.connect(destino)
    assert [e.nome for e in repo.listar_empresas(conn)] == ["ENDOGASTRO LTDA"]
    conn.close()
    # O original fica onde está: se a migração der errado, ele é a garantia.
    assert (antiga / "controle_lucros.db").exists()


def test_migracao_traz_junto_as_preferencias(como_instalado):
    antiga = db.pasta_dados_por_usuario()
    _banco_antigo_com_uma_empresa(antiga)
    (antiga / "preferencias.json").write_text('{"tema": "escuro"}', encoding="utf-8")
    destino = db._pasta_dados_padrao() / "controle_lucros.db"

    db.migrar_banco_por_usuario(destino)

    assert (destino.parent / "preferencias.json").read_text(encoding="utf-8") == '{"tema": "escuro"}'


def test_nao_migra_por_cima_de_um_banco_compartilhado_existente(como_instalado):
    """Depois da primeira vez, o banco compartilhado é a verdade — sobrescrevê-lo
    com o antigo apagaria tudo que o escritório lançou desde a atualização."""
    antiga = db.pasta_dados_por_usuario()
    _banco_antigo_com_uma_empresa(antiga)

    destino = db._pasta_dados_padrao() / "controle_lucros.db"
    destino.parent.mkdir(parents=True, exist_ok=True)
    conn = db.connect(destino)
    db.init_schema(conn)
    repo.salvar_empresa(conn, Empresa(None, "999", "JA ESTAVA AQUI LTDA", "", 1, 1))
    conn.close()

    assert db.migrar_banco_por_usuario(destino) is None

    conn = db.connect(destino)
    assert [e.nome for e in repo.listar_empresas(conn)] == ["JA ESTAVA AQUI LTDA"]
    conn.close()


def test_sem_banco_antigo_nao_ha_o_que_migrar(como_instalado):
    destino = db._pasta_dados_padrao() / "controle_lucros.db"
    assert db.migrar_banco_por_usuario(destino) is None
    assert not destino.exists()


def test_migracao_leva_gravacao_que_ainda_estava_no_wal(como_instalado):
    """O banco roda em WAL: gravação confirmada pode estar no arquivo -wal ao
    lado, não no .db. Copiar só o .db traria um cadastro desatualizado — por
    isso a migração passa pelo backup do próprio SQLite."""
    antiga = db.pasta_dados_por_usuario()
    caminho_antigo = _banco_antigo_com_uma_empresa(antiga)

    # Grava e deixa a conexão aberta, pra o dado ficar no -wal sem checkpoint.
    aberta = db.connect(caminho_antigo)
    repo.salvar_empresa(aberta, Empresa(None, "148", "SO NO WAL LTDA", "", 1, 1))
    assert (antiga / "controle_lucros.db-wal").exists()

    destino = db._pasta_dados_padrao() / "controle_lucros.db"
    db.migrar_banco_por_usuario(destino)
    aberta.close()

    conn = db.connect(destino)
    assert "SO NO WAL LTDA" in [e.nome for e in repo.listar_empresas(conn)]
    conn.close()


def test_abrir_o_banco_novo_com_outra_conta_dentro_nao_derruba(tmp_path):
    """Duas contas do Windows abrindo o programa no mesmo instante, na
    primeiríssima vez que o banco compartilhado é usado.

    Converter o banco para WAL reescreve o cabeçalho e exige que mais ninguém
    o tenha aberto — é a única operação que o busy_timeout não salva: ela
    espera o timeout inteiro e falha assim mesmo. Sem tolerar essa falha, a
    segunda conta a abrir recebia "database is locked" antes da tela de
    login.

    O banco precisa nascer FORA do WAL: já convertido, o pragma vira no-op e
    não disputa nada — que é por que isso só alcança a primeira abertura."""
    caminho = tmp_path / "compartilhado.db"
    fora_do_wal = sqlite3.connect(caminho)
    fora_do_wal.execute("CREATE TABLE marca (id INTEGER PRIMARY KEY)")
    fora_do_wal.commit()
    assert fora_do_wal.execute("PRAGMA journal_mode;").fetchone()[0].lower() != "wal"

    # A outra conta, com o programa aberto e uma leitura em curso.
    outra_conta = sqlite3.connect(caminho)
    outra_conta.execute("BEGIN")
    outra_conta.execute("SELECT * FROM marca").fetchall()

    conn = db.connect(caminho)  # não pode levantar: é aqui que quebrava

    # A outra conta termina o que estava fazendo — no programa real as
    # leituras são curtas, não uma transação segurada a tarde inteira.
    outra_conta.rollback()
    outra_conta.close()

    db.init_schema(conn)
    repo.salvar_empresa(conn, Empresa(None, "91", "ABRIU ASSIM MESMO LTDA", "", 1, 1))
    assert [e.nome for e in repo.listar_empresas(conn)] == ["ABRIU ASSIM MESMO LTDA"]
    conn.close()
    fora_do_wal.close()


def test_banco_ja_em_wal_abre_na_hora_mesmo_com_outra_conta_dentro(tmp_path):
    """O caso de todo dia, depois da primeira vez: o pragma é no-op e não
    disputa bloqueio nenhum."""
    caminho = tmp_path / "compartilhado.db"
    primeira = db.connect(caminho)
    db.init_schema(primeira)

    lendo = sqlite3.connect(caminho)
    lendo.execute("BEGIN")
    lendo.execute("SELECT * FROM empresa").fetchall()

    segunda = db.connect(caminho)
    assert segunda.execute("PRAGMA journal_mode;").fetchone()[0].lower() == "wal"

    lendo.close()
    primeira.close()
    segunda.close()
