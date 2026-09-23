"""Isolamento dos testes do ambiente real, e o PostgreSQL que eles usam.

Pasta local: sem isto, qualquer teste que construa uma tela acaba gravando
na configuração de verdade — o mesmo arquivo que guarda a conexão, o tema e
a pasta de backup de quem usa o sistema. CONTROLE_LUCROS_DADOS aponta
db.pasta_local() pra uma pasta temporária.

Banco: um PostgreSQL descartável, criado com initdb numa pasta temporária e
desligado no fim — rodar a suíte não encosta em nenhum servidor de verdade.
Precisa dos binários do PostgreSQL na máquina (no Ubuntu, o pacote
postgresql; no Windows, o instalador da EDB). Quem já tem um servidor de
teste pode apontar CONTROLE_LUCROS_TESTE_PG pra ele ("host=... dbname=...
user=..."): TODAS as tabelas do sistema nesse banco são apagadas a cada teste.

Cada teste recebe o banco vazio (fixture conn), com o schema já criado.
"""
import glob
import os
import shutil
import socket
import subprocess
import time
from pathlib import Path

import psycopg
import pytest

from controle_lucros import db


def _binarios_postgres() -> Path | None:
    initdb = shutil.which("initdb")
    if initdb:
        return Path(initdb).parent
    candidatos = sorted(glob.glob("/usr/lib/postgresql/*/bin/initdb"))
    candidatos += sorted(glob.glob(r"C:\Program Files\PostgreSQL\*\bin\initdb.exe"))
    return Path(candidatos[-1]).parent if candidatos else None


def _porta_livre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def servidor_pg(tmp_path_factory):
    """String de conexão de um banco de teste, vazio, só da suíte."""
    externo = os.environ.get("CONTROLE_LUCROS_TESTE_PG")
    if externo:
        yield externo
        return

    binarios = _binarios_postgres()
    if binarios is None:
        pytest.exit(
            "Os testes precisam do PostgreSQL instalado (não encontrei o initdb). Instale o "
            "PostgreSQL ou aponte CONTROLE_LUCROS_TESTE_PG para um banco de teste.",
            returncode=2,
        )
    pasta = tmp_path_factory.mktemp("postgres")
    dados = pasta / "dados"
    porta = _porta_livre()
    subprocess.run(
        [binarios / "initdb", "-D", dados, "-U", "postgres", "-A", "trust", "-E", "UTF8",
         "--no-sync"],
        check=True, capture_output=True,
    )
    # No postgresql.conf, e não na linha de comando do pg_ctl: as aspas do
    # valor vazio não sobrevivem ao cmd do Windows. Sem socket Unix porque o
    # caminho da pasta temporária passa do limite de 107 caracteres dele.
    with open(dados / "postgresql.conf", "a", encoding="utf-8") as conf:
        conf.write(
            f"\nport = {porta}\nlisten_addresses = '127.0.0.1'\n"
            "unix_socket_directories = ''\nfsync = off\n"
        )
    subprocess.run(
        [binarios / "pg_ctl", "-D", dados, "-l", pasta / "log.txt", "-w", "start"],
        check=True, capture_output=True,
    )
    try:
        base = f"host=127.0.0.1 port={porta} user=postgres"
        for _ in range(50):
            try:
                with psycopg.connect(f"{base} dbname=postgres", autocommit=True) as c:
                    c.execute("CREATE DATABASE controle_lucros_teste")
                break
            except psycopg.OperationalError:
                time.sleep(0.1)
        yield f"{base} dbname=controle_lucros_teste"
    finally:
        subprocess.run([binarios / "pg_ctl", "-D", dados, "-m", "immediate", "stop"],
                       capture_output=True)


@pytest.fixture(scope="session", autouse=True)
def dados_isolados(tmp_path_factory, servidor_pg):
    pasta = tmp_path_factory.mktemp("dados")
    anteriores = {k: os.environ.get(k) for k in ("CONTROLE_LUCROS_DADOS", "CONTROLE_LUCROS_PG")}
    os.environ["CONTROLE_LUCROS_DADOS"] = str(pasta)
    os.environ["CONTROLE_LUCROS_PG"] = servidor_pg
    conn = db.connect()
    db.init_schema(conn)
    conn.close()
    yield pasta
    for chave, valor in anteriores.items():
        if valor is None:
            os.environ.pop(chave, None)
        else:
            os.environ[chave] = valor


def esvaziar_banco(conn) -> None:
    conn.execute(f"TRUNCATE {', '.join(db.TABELAS)} RESTART IDENTITY CASCADE")
    conn.commit()


@pytest.fixture()
def conn():
    """Conexão com o banco de teste, vazio e com o schema criado."""
    connection = db.connect()
    esvaziar_banco(connection)
    yield connection
    connection.rollback()
    connection.close()
