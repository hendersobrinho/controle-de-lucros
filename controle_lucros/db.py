"""Conexão SQLite (modo WAL) e criação do schema."""
from __future__ import annotations

import os
import shutil
import sqlite3
import sys
from pathlib import Path

# Rodando do código-fonte, o banco fica ao lado do projeto (bom pra
# desenvolvimento — dá pra achar fácil). Empacotado com o PyInstaller,
# __file__ aponta pra dentro da pasta temporária de extração (sys._MEIPASS
# no modo --onefile, ou a pasta do próprio .exe no --onedir) — gravar o
# banco ali seria gravar num lugar que ou não é permitido (instalado em
# Arquivos de Programas) ou é apagado a cada execução, perdendo os dados.
#
# Empacotado, o banco vai pra %PROGRAMDATA% (C:\ProgramData), que é a pasta
# de dados da MÁQUINA, não a de cada conta do Windows. É o que faz o
# escritório inteiro ver o mesmo cadastro: com %LOCALAPPDATA%, cada usuário
# do Windows abria o programa e encontrava um banco vazio só dele, sem
# enxergar nada do que o colega tinha lançado.
#
# O instalador é que abre a permissão de escrita dessa pasta pros usuários
# comuns (ver [Dirs] em controle_lucros.iss) — o padrão do Windows deixaria
# só quem criou o arquivo poder alterá-lo.
NOME_DA_PASTA = "ControleDeLucros"


def _pasta_dados_padrao() -> Path:
    if getattr(sys, "frozen", False):
        base = os.getenv("PROGRAMDATA") or os.getenv("LOCALAPPDATA") or str(Path.home())
        return Path(base) / NOME_DA_PASTA / "data"
    return Path(__file__).resolve().parent.parent / "data"


def pasta_dados_por_usuario() -> Path | None:
    """Onde o banco ficava até a versão 1.1.0: dentro da conta do Windows.

    Serve pra migração — uma instalação que já rodou guarda o cadastro lá, e
    atualizar o programa não pode fazer esse cadastro sumir da vista."""
    base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA")
    return Path(base) / NOME_DA_PASTA / "data" if base else None


DEFAULT_DB_PATH = _pasta_dados_padrao() / "controle_lucros.db"

# Quanto tempo uma gravação espera a vez quando outro usuário está gravando
# naquele instante. Sem isso o SQLite devolve "database is locked" na hora, e
# com duas pessoas usando ao mesmo tempo isso apareceria como erro na tela em
# vez de uma espera de milissegundos. As gravações aqui são curtas (um
# INSERT, um UPDATE), então dez segundos é folga de sobra.
ESPERA_DE_BLOQUEIO_MS = 10_000

SCHEMA = """
CREATE TABLE IF NOT EXISTS empresa (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    numero_chamada TEXT NOT NULL,
    nome TEXT NOT NULL,
    cnpj TEXT,
    capital_social REAL NOT NULL DEFAULT 0,
    quantidade_cotas REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS socio (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    cpf TEXT,
    tipo_pessoa TEXT NOT NULL DEFAULT 'fisica' CHECK (tipo_pessoa IN ('fisica', 'juridica'))
);

CREATE TABLE IF NOT EXISTS alteracao_contratual (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id INTEGER NOT NULL REFERENCES empresa(id),
    numero INTEGER NOT NULL,
    data TEXT NOT NULL,
    nome_empresa TEXT NOT NULL,
    capital_social REAL NOT NULL,
    quantidade_cotas REAL NOT NULL,
    descricao TEXT,
    fechada INTEGER NOT NULL DEFAULT 0,
    UNIQUE(empresa_id, numero)
);

CREATE TABLE IF NOT EXISTS vinculo_societario (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id INTEGER NOT NULL REFERENCES empresa(id),
    socio_id INTEGER NOT NULL REFERENCES socio(id),
    percentual_capital REAL NOT NULL,
    quantidade_cotas REAL,
    data_entrada TEXT NOT NULL,
    data_saida TEXT,
    alteracao_entrada_id INTEGER REFERENCES alteracao_contratual(id),
    alteracao_saida_id INTEGER REFERENCES alteracao_contratual(id),
    observacao TEXT
);

CREATE TABLE IF NOT EXISTS distribuicao_lucro (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id INTEGER NOT NULL REFERENCES empresa(id),
    ano_base INTEGER NOT NULL,
    socio_id INTEGER NOT NULL REFERENCES socio(id),
    valor_distribuido REAL NOT NULL DEFAULT 0,
    pro_labore REAL NOT NULL DEFAULT 0,
    irrf REAL NOT NULL DEFAULT 0,
    UNIQUE(empresa_id, ano_base, socio_id)
);

-- Lançamento trimestral da distribuição. Existe separado de distribuicao_lucro
-- (e não como quatro colunas dela) porque nem toda empresa distribui por
-- trimestre: quem não usa continua com um lançamento anual só, sem quatro
-- campos vazios no meio do caminho. Ao salvar um trimestre, a soma dos
-- trimestres do ano é gravada de volta na distribuição anual.
CREATE TABLE IF NOT EXISTS distribuicao_trimestral (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id INTEGER NOT NULL REFERENCES empresa(id),
    ano_base INTEGER NOT NULL,
    trimestre INTEGER NOT NULL CHECK (trimestre BETWEEN 1 AND 4),
    socio_id INTEGER NOT NULL REFERENCES socio(id),
    valor_distribuido REAL NOT NULL DEFAULT 0,
    pro_labore REAL NOT NULL DEFAULT 0,
    irrf REAL NOT NULL DEFAULT 0,
    UNIQUE(empresa_id, ano_base, trimestre, socio_id)
);

CREATE INDEX IF NOT EXISTS idx_distribuicao_trimestral_periodo
    ON distribuicao_trimestral (empresa_id, ano_base);

CREATE TABLE IF NOT EXISTS periodo_distribuicao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id INTEGER NOT NULL REFERENCES empresa(id),
    ano_base INTEGER NOT NULL,
    fechado INTEGER NOT NULL DEFAULT 0,
    fechado_em TEXT,
    UNIQUE(empresa_id, ano_base)
);

CREATE TABLE IF NOT EXISTS movimentacao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id INTEGER NOT NULL REFERENCES empresa(id),
    socio_id INTEGER NOT NULL REFERENCES socio(id),
    tipo TEXT NOT NULL CHECK (tipo IN (
        'emprestimo_empresa_para_socio',
        'emprestimo_socio_para_empresa',
        'adiantamento_lucro',
        'devolucao_capital'
    )),
    valor REAL NOT NULL,
    data TEXT NOT NULL
);

-- Diferente do resto do banco (que guarda dinheiro como REAL), os valores do
-- informe são INTEIRO de centavos: é documento fiscal entregue à Receita, e um
-- centavo de erro de arredondamento já é documento errado.
CREATE TABLE IF NOT EXISTS informe_rendimento (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    empresa_id INTEGER NOT NULL REFERENCES empresa(id),
    socio_id INTEGER NOT NULL REFERENCES socio(id),
    ano_base INTEGER NOT NULL,
    codigo_beneficiario TEXT NOT NULL DEFAULT '',
    natureza_rendimento TEXT NOT NULL DEFAULT 'RENDIMENTO DO TRABALHO ASSALARIADO NO PAÍS',
    q3_total_rendimentos INTEGER NOT NULL DEFAULT 0,
    q3_previdencia_oficial INTEGER NOT NULL DEFAULT 0,
    q3_previdencia_complementar INTEGER NOT NULL DEFAULT 0,
    q3_pensao_alimenticia INTEGER NOT NULL DEFAULT 0,
    q3_irrf INTEGER NOT NULL DEFAULT 0,
    q4_parcela_isenta_65 INTEGER NOT NULL DEFAULT 0,
    q4_parcela_isenta_13_65 INTEGER NOT NULL DEFAULT 0,
    q4_diarias_ajudas_custo INTEGER NOT NULL DEFAULT 0,
    q4_pensao_molestia_grave INTEGER NOT NULL DEFAULT 0,
    q4_lucros_dividendos INTEGER NOT NULL DEFAULT 0,
    q4_valores_socio_microempresa INTEGER NOT NULL DEFAULT 0,
    q4_indenizacoes_rescisao INTEGER NOT NULL DEFAULT 0,
    q4_juros_mora INTEGER NOT NULL DEFAULT 0,
    q4_outros INTEGER NOT NULL DEFAULT 0,
    q5_decimo_terceiro INTEGER NOT NULL DEFAULT 0,
    q5_irrf_decimo_terceiro INTEGER NOT NULL DEFAULT 0,
    q5_outros INTEGER NOT NULL DEFAULT 0,
    emprestimo_saldo INTEGER NOT NULL DEFAULT 0,
    informacoes_complementares TEXT NOT NULL DEFAULT '',
    responsavel_nome TEXT NOT NULL DEFAULT '',
    atualizado_em TEXT NOT NULL,
    UNIQUE(empresa_id, ano_base, socio_id)
);

CREATE INDEX IF NOT EXISTS idx_informe_socio_ano ON informe_rendimento (socio_id, ano_base);

CREATE TABLE IF NOT EXISTS usuario (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    login TEXT NOT NULL UNIQUE,
    senha_hash TEXT NOT NULL,
    senha_salt TEXT NOT NULL,
    admin INTEGER NOT NULL DEFAULT 0,
    ativo INTEGER NOT NULL DEFAULT 1,
    criado_em TEXT NOT NULL
);

-- Como ler uma planilha de origem: cada campo do cadastro e a letra da coluna
-- em que ele está naquele arquivo. Guardado como JSON porque é um conjunto de
-- pares campo->letra que muda com os campos do sistema; uma coluna por campo
-- viraria ALTER TABLE a cada campo novo, e nada aqui é consultado por campo.
CREATE TABLE IF NOT EXISTS layout_importacao (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL UNIQUE,
    linha_inicial INTEGER NOT NULL DEFAULT 2,
    colunas_json TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    atualizado_em TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS log_atividade (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario_id INTEGER REFERENCES usuario(id) ON DELETE SET NULL,
    usuario_nome TEXT NOT NULL,
    data_hora TEXT NOT NULL,
    acao TEXT NOT NULL,
    entidade TEXT NOT NULL,
    entidade_id INTEGER,
    detalhes TEXT
);
"""


def get_db_path() -> Path:
    override = os.environ.get("CONTROLE_LUCROS_DB")
    return Path(override) if override else DEFAULT_DB_PATH


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _garantir_wal(conn)
    # WAL deixa quem está lendo a tela seguir lendo enquanto outro grava; o
    # busy_timeout cobre o que o WAL não cobre, que é gravação x gravação.
    conn.execute(f"PRAGMA busy_timeout = {ESPERA_DE_BLOQUEIO_MS};")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# Espera curta só para a conversão do journal_mode: ela não desiste antes do
# timeout, então um valor alto aqui viraria o programa parado olhando pra
# nada antes da tela de login.
ESPERA_DA_CONVERSAO_MS = 2_000


def _garantir_wal(conn: sqlite3.Connection) -> None:
    """Liga o WAL tolerando o banco estar ocupado por outra conta.

    Trocar o journal_mode reescreve o cabeçalho do arquivo e exige que mais
    ninguém o tenha aberto. É a única operação daqui que o busy_timeout não
    salva: com outra conexão aberta ela espera o timeout inteiro e falha
    assim mesmo. Sem este cuidado, duas pessoas abrindo o programa no mesmo
    instante faziam a segunda receber "database is locked" antes da tela de
    login.

    Na prática isso só alcança a primeiríssima abertura do banco: WAL é
    propriedade gravada no arquivo, então da segunda vez em diante o pragma
    vira no-op instantâneo — é por isso que o teste precisa de um banco
    nascido fora do WAL para reproduzir o caso.

    Falhar aqui não impede nada: sem WAL o banco continua correto, só com
    bloqueio mais grosseiro, e a primeira abertura sem disputa converte."""
    if str(conn.execute("PRAGMA journal_mode;").fetchone()[0]).lower() == "wal":
        return
    conn.execute(f"PRAGMA busy_timeout = {ESPERA_DA_CONVERSAO_MS};")
    try:
        conn.execute("PRAGMA journal_mode = WAL;")
    except sqlite3.OperationalError:
        pass


def migrar_banco_por_usuario(destino: Path | None = None) -> Path | None:
    """Traz pro banco compartilhado o cadastro que ficou na conta do Windows.

    Só roda quando não há banco compartilhado ainda e existe um antigo: numa
    atualização, o usuário abriria o programa e daria de cara com o sistema
    vazio, achando que perdeu tudo.

    Copia pelo backup do próprio SQLite, e não com copy do arquivo, porque o
    banco em WAL tem gravação confirmada que ainda mora no arquivo -wal ao
    lado — copiar só o .db traria um cadastro desatualizado. O original é
    deixado onde está: se algo der errado aqui, ele continua lá inteiro.

    Devolve a origem quando migrou, None quando não havia o que migrar."""
    destino = destino or get_db_path()
    if destino.exists():
        return None

    antiga = pasta_dados_por_usuario()
    if antiga is None:
        return None
    origem = antiga / "controle_lucros.db"
    if not origem.exists() or origem.resolve() == destino.resolve():
        return None

    destino.parent.mkdir(parents=True, exist_ok=True)
    de_origem = sqlite3.connect(origem)
    para_destino = sqlite3.connect(destino)
    try:
        de_origem.backup(para_destino)
    finally:
        para_destino.close()
        de_origem.close()

    preferencias_antigas = antiga / "preferencias.json"
    if preferencias_antigas.exists():
        shutil.copy2(preferencias_antigas, destino.parent / "preferencias.json")
    return origem


# Colunas adicionadas ao schema depois que as tabelas já existiam em bancos
# reais — CREATE TABLE IF NOT EXISTS não altera uma tabela já criada, então
# sem isso um banco antigo nunca ganha essas colunas e quebra na primeira
# tela que usa o campo novo. Cada entrada aqui é (tabela, coluna, definição).
COLUNAS_ADICIONADAS = [
    ("socio", "tipo_pessoa", "TEXT NOT NULL DEFAULT 'fisica' CHECK (tipo_pessoa IN ('fisica', 'juridica'))"),
    ("distribuicao_lucro", "pro_labore", "REAL NOT NULL DEFAULT 0"),
    ("distribuicao_lucro", "irrf", "REAL NOT NULL DEFAULT 0"),
]


def _migrar_colunas_faltantes(conn: sqlite3.Connection) -> None:
    colunas_por_tabela: dict[str, set[str]] = {}
    for tabela, coluna, definicao in COLUNAS_ADICIONADAS:
        if tabela not in colunas_por_tabela:
            colunas_por_tabela[tabela] = {
                row["name"] for row in conn.execute(f"PRAGMA table_info({tabela})").fetchall()
            }
        if coluna not in colunas_por_tabela[tabela]:
            conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {definicao}")
            colunas_por_tabela[tabela].add(coluna)


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    _migrar_colunas_faltantes(conn)
    conn.commit()
