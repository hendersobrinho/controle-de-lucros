"""Backup e restauração do banco: cópia manual ou automática (uma por dia,
ao entrar no sistema) pra uma pasta configurável, e restauração a partir de
um arquivo de backup escolhido."""
from __future__ import annotations

import datetime as dt
import sqlite3
import tempfile
from pathlib import Path

from . import db, preferencias

PREFIXO = "controle_lucros_"


def pasta_backup_padrao() -> Path:
    return db.get_db_path().parent / "backups"


def pasta_backup_configurada() -> Path:
    salva = preferencias.obter("pasta_backup")
    return Path(salva) if salva else pasta_backup_padrao()


def definir_pasta_backup(caminho: Path) -> None:
    preferencias.salvar_chave("pasta_backup", str(Path(caminho)))


def automatico_habilitado() -> bool:
    return bool(preferencias.obter("backup_automatico", False))


def definir_automatico(habilitado: bool) -> None:
    preferencias.salvar_chave("backup_automatico", bool(habilitado))


def criar_backup(conn: sqlite3.Connection, pasta: Path | None = None) -> Path:
    """Cópia consistente do banco, mesmo com o app rodando em modo WAL —
    usa a API de backup nativa do sqlite3 (lê através do WAL sem precisar
    checkpoint manual), não uma cópia crua do arquivo."""
    pasta = Path(pasta) if pasta else pasta_backup_configurada()
    pasta.mkdir(parents=True, exist_ok=True)
    nome = f"{PREFIXO}{dt.datetime.now():%Y%m%d_%H%M%S}.db"
    caminho = pasta / nome
    destino = sqlite3.connect(caminho)
    try:
        conn.backup(destino)
        _tirar_do_wal(destino)
    finally:
        destino.close()
    return caminho


def _tirar_do_wal(conn: sqlite3.Connection) -> None:
    """A cópia pelo backup do SQLite herda o modo WAL do banco de origem, e
    esse modo vai junto quando ela for restaurada. Num banco do servidor,
    WAL é o que corrompe (ver db._ajustar_journal) — então cópia nunca fica
    em WAL. Num banco local, a próxima abertura liga o WAL de novo."""
    conn.execute("PRAGMA journal_mode = DELETE;")


def listar_backups(pasta: Path | None = None) -> list[dict]:
    pasta = Path(pasta) if pasta else pasta_backup_configurada()
    if not pasta.exists():
        return []
    arquivos = sorted(pasta.glob(f"{PREFIXO}*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [
        {
            "caminho": arquivo,
            "nome": arquivo.name,
            "tamanho": arquivo.stat().st_size,
            "modificado_em": dt.datetime.fromtimestamp(arquivo.stat().st_mtime),
        }
        for arquivo in arquivos
    ]


def _ja_tem_backup_hoje(pasta: Path) -> bool:
    hoje = dt.date.today()
    return any(b["modificado_em"].date() == hoje for b in listar_backups(pasta))


def backup_automatico_se_necessario(conn: sqlite3.Connection) -> Path | None:
    """Chamado ao logar — só cria um backup se a opção estiver ligada e
    ainda não tiver um de hoje na pasta configurada, pra não acumular um
    arquivo a cada login."""
    if not automatico_habilitado():
        return None
    pasta = pasta_backup_configurada()
    if _ja_tem_backup_hoje(pasta):
        return None
    return criar_backup(conn, pasta)


def restaurar_backup(caminho_backup: Path, caminho_db: Path | None = None) -> None:
    """Substitui o conteúdo do banco pelo do backup escolhido.

    Pelo backup do próprio SQLite, e não copiando o arquivo por cima: com o
    banco no servidor, outros PCs podem estar com ele aberto, e trocar o
    arquivo debaixo deles corrompe o banco (ou nem é permitido pelo Windows).
    Assim a troca respeita o travamento — espera quem estiver gravando, e
    ninguém vê o banco pela metade. Também dispensa mexer no -wal e no -shm.

    As telas já abertas continuam mostrando o que tinham carregado — quem
    chamar isso precisa fechar e reabrir o app depois."""
    caminho_backup = Path(caminho_backup)
    if not db.e_banco_do_sistema(caminho_backup):
        raise ValueError(f"{caminho_backup.name} não é um backup deste sistema.")
    caminho_db = Path(caminho_db) if caminho_db else db.get_db_path()
    with tempfile.TemporaryDirectory() as pasta:
        # Backup feito por versão anterior pode estar em WAL: passa por uma
        # cópia particular, sem disputa, pra sair de lá antes de ir pro banco.
        copia = sqlite3.connect(Path(pasta) / "restaurar.db")
        try:
            origem = sqlite3.connect(caminho_backup)
            try:
                origem.backup(copia)
            finally:
                origem.close()
            _tirar_do_wal(copia)
            destino = db.connect(caminho_db)
            try:
                copia.backup(destino)
            finally:
                destino.close()
        finally:
            copia.close()


def formatar_tamanho(bytes_: int) -> str:
    valor = float(bytes_)
    for unidade in ("B", "KB", "MB", "GB"):
        if valor < 1024:
            return f"{valor:.0f} {unidade}" if unidade == "B" else f"{valor:.1f} {unidade}"
        valor /= 1024
    return f"{valor:.1f} TB"
