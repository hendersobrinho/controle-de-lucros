"""Backup e restauração do banco: cópia manual ou automática (uma por dia,
ao entrar no sistema) pra uma pasta configurável, e restauração a partir de
um arquivo de backup escolhido.

O backup é um arquivo JSON com todas as tabelas, feito pelo próprio
programa — não depende do pg_dump estar instalado no PC. Não substitui o
backup do servidor (ver manual, "Servidor PostgreSQL"): é a cópia que o
escritório consegue fazer e restaurar sozinho, sem chamar a TI."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import db, preferencias
from .db import Conexao

PREFIXO = "controle_lucros_"
EXTENSAO = ".json"
# Marca que identifica o arquivo como backup deste sistema — restaurar um
# JSON qualquer por engano apagaria o banco inteiro.
SISTEMA = "controle_lucros"
VERSAO_DO_FORMATO = 1


def pasta_backup_padrao() -> Path:
    return db.pasta_local() / "backups"


def pasta_backup_configurada() -> Path:
    salva = preferencias.obter("pasta_backup")
    return Path(salva) if salva else pasta_backup_padrao()


def definir_pasta_backup(caminho: Path) -> None:
    preferencias.salvar_chave("pasta_backup", str(Path(caminho)))


def automatico_habilitado() -> bool:
    return bool(preferencias.obter("backup_automatico", False))


def definir_automatico(habilitado: bool) -> None:
    preferencias.salvar_chave("backup_automatico", bool(habilitado))


def _ler_tabelas(conn: Conexao) -> dict:
    """Todas as tabelas lidas da MESMA foto do banco: com outro PC gravando
    no meio, sem isto o backup podia levar uma distribuição sem a empresa
    dela, e a restauração falharia na chave estrangeira."""
    conn.execute("BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY")
    try:
        tabelas = {}
        for tabela in db.TABELAS:
            cur = conn.execute(f"SELECT * FROM {tabela} ORDER BY id")
            tabelas[tabela] = {
                "colunas": [coluna.name for coluna in cur.description],
                "linhas": [list(linha) for linha in cur.fetchall()],
            }
        return tabelas
    finally:
        conn.commit()


def criar_backup(conn: Conexao, pasta: Path | None = None) -> Path:
    pasta = Path(pasta) if pasta else pasta_backup_configurada()
    pasta.mkdir(parents=True, exist_ok=True)
    agora = dt.datetime.now()
    conteudo = {
        "sistema": SISTEMA,
        "versao_formato": VERSAO_DO_FORMATO,
        "criado_em": agora.isoformat(timespec="seconds"),
        "tabelas": _ler_tabelas(conn),
    }
    caminho = pasta / f"{PREFIXO}{agora:%Y%m%d_%H%M%S}{EXTENSAO}"
    # Grava ao lado e renomeia: backup cortado no meio (disco cheio, PC
    # desligado) nunca fica com cara de backup bom na lista.
    temporario = caminho.with_suffix(".tmp")
    temporario.write_text(json.dumps(conteudo, ensure_ascii=False), encoding="utf-8")
    temporario.replace(caminho)
    return caminho


def listar_backups(pasta: Path | None = None) -> list[dict]:
    pasta = Path(pasta) if pasta else pasta_backup_configurada()
    if not pasta.exists():
        return []
    arquivos = sorted(
        pasta.glob(f"{PREFIXO}*{EXTENSAO}"), key=lambda p: p.stat().st_mtime, reverse=True
    )
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


def backup_automatico_se_necessario(conn: Conexao) -> Path | None:
    """Chamado ao logar — só cria um backup se a opção estiver ligada e
    ainda não tiver um de hoje na pasta configurada, pra não acumular um
    arquivo a cada login."""
    if not automatico_habilitado():
        return None
    pasta = pasta_backup_configurada()
    if _ja_tem_backup_hoje(pasta):
        return None
    return criar_backup(conn, pasta)


def ler_backup(caminho: Path) -> dict:
    """O conteúdo do arquivo, conferido. ValueError se não for um backup
    deste sistema."""
    caminho = Path(caminho)
    try:
        conteudo = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as erro:
        raise ValueError(f"{caminho.name} não é um backup deste sistema.") from erro
    if not isinstance(conteudo, dict) or conteudo.get("sistema") != SISTEMA:
        raise ValueError(f"{caminho.name} não é um backup deste sistema.")
    if conteudo.get("versao_formato", 0) > VERSAO_DO_FORMATO:
        raise ValueError(
            f"{caminho.name} foi feito por uma versão mais nova do sistema. Atualize o programa "
            "neste computador antes de restaurá-lo."
        )
    return conteudo


def restaurar_backup(conn: Conexao, caminho_backup: Path) -> None:
    """Substitui o conteúdo do banco pelo do backup escolhido.

    Numa transação só: ou o banco inteiro vira o do backup, ou (em qualquer
    erro no meio) fica exatamente como estava. Os outros PCs esperam a troca
    terminar e não veem o banco pela metade.

    Colunas que o backup não tem ficam com o valor padrão, e colunas que o
    banco não tem mais são ignoradas — um backup de versão anterior do
    programa continua restaurável.

    As telas já abertas continuam mostrando o que tinham carregado — quem
    chamar isso precisa fechar e reabrir o app depois."""
    tabelas = ler_backup(caminho_backup)["tabelas"]
    conn.execute("BEGIN")
    try:
        conn.execute(f"TRUNCATE {', '.join(db.TABELAS)} RESTART IDENTITY CASCADE")
        for tabela in db.TABELAS:
            dados = tabelas.get(tabela)
            if dados:
                _inserir(conn, tabela, dados["colunas"], dados["linhas"])
            # O próximo id continua depois do maior restaurado: sem isto, o
            # primeiro cadastro novo depois de restaurar bateria num id já
            # existente.
            conn.execute(
                f"SELECT setval(pg_get_serial_sequence('{tabela}', 'id'), "
                f"COALESCE((SELECT MAX(id) FROM {tabela}), 0) + 1, false)"
            )
        conn.commit()
    except BaseException:
        conn.rollback()
        raise


def _inserir(conn: Conexao, tabela: str, colunas: list[str], linhas: list[list]) -> None:
    existentes = {
        linha[0]
        for linha in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = current_schema() AND table_name = %s",
            (tabela,),
        ).fetchall()
    }
    posicoes = [i for i, coluna in enumerate(colunas) if coluna in existentes]
    if not posicoes or not linhas:
        return
    nomes = ", ".join(colunas[i] for i in posicoes)
    marcadores = ", ".join(["%s"] * len(posicoes))
    conn.executemany(
        f"INSERT INTO {tabela} ({nomes}) OVERRIDING SYSTEM VALUE VALUES ({marcadores})",
        [[linha[i] for i in posicoes] for linha in linhas],
    )


def formatar_tamanho(bytes_: int) -> str:
    valor = float(bytes_)
    for unidade in ("B", "KB", "MB", "GB"):
        if valor < 1024:
            return f"{valor:.0f} {unidade}" if unidade == "B" else f"{valor:.1f} {unidade}"
        valor /= 1024
    return f"{valor:.1f} TB"
