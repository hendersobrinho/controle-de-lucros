"""Conexão SQLite (modo WAL) e criação do schema."""
from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path

# Rodando do código-fonte, o banco fica ao lado do projeto (bom pra
# desenvolvimento — dá pra achar fácil). Empacotado com o PyInstaller,
# __file__ aponta pra dentro da pasta temporária de extração (sys._MEIPASS
# no modo --onefile, ou a pasta do próprio .exe no --onedir) — gravar o
# banco ali seria gravar num lugar que ou não é permitido (instalado em
# Arquivos de Programas) ou é apagado a cada execução, perdendo os dados.
# Empacotado, o banco vai pra pasta de dados do usuário (%LOCALAPPDATA% no
# Windows), que é sempre gravável e persiste entre execuções.
def _pasta_dados_padrao() -> Path:
    if getattr(sys, "frozen", False):
        base = os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or str(Path.home())
        return Path(base) / "ControleDeLucros" / "data"
    return Path(__file__).resolve().parent.parent / "data"


DEFAULT_DB_PATH = _pasta_dados_padrao() / "controle_lucros.db"

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
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


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
