"""Conexão SQLite e criação do schema.

O banco pode ficar neste computador (modo WAL) ou numa pasta compartilhada
de um servidor, usada por vários PCs ao mesmo tempo (journal tradicional —
ver _ajustar_journal)."""
from __future__ import annotations

import json
import ntpath
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
    saida_sociedade_data TEXT NOT NULL DEFAULT '',
    cotas_inicio REAL NOT NULL DEFAULT 0,
    cotas_fim REAL NOT NULL DEFAULT 0,
    cota_valor_nominal INTEGER NOT NULL DEFAULT 0,
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


# ------------------------------------------------ configuração local --
#
# O que é DESTE computador e não pode morar junto do banco: principalmente
# ONDE o banco está. Com o banco numa pasta do servidor, cada PC precisa
# saber sozinho o caminho até lá antes de conseguir abrir qualquer coisa.
ARQUIVO_CONFIG_LOCAL = "configuracao_local.json"
CHAVE_BANCO = "banco"
# Marca que o banco configurado ainda não existe e DEVE ser criado na próxima
# abertura — posta pelo instalador quando a pessoa escolheu criar um banco
# novo. Sem ela, banco configurado que não existe é erro (ver
# verificar_banco_configurado), nunca um banco novo criado em silêncio.
CHAVE_CRIAR = "criar_banco"


def pasta_local() -> Path:
    """A pasta de dados desta máquina, onde quer que o banco esteja. Guarda a
    configuração local e o registro de falhas — coisas de um PC só, que no
    servidor os PCs ficariam sobrescrevendo uns dos outros.

    CONTROLE_LUCROS_DB (usado pelos testes) leva esta pasta junto, pra rodar
    a suíte não gravar na configuração de quem usa o sistema."""
    override = os.environ.get("CONTROLE_LUCROS_DB")
    return Path(override).parent if override else _pasta_dados_padrao()


def ler_config_local() -> dict:
    try:
        # utf-8-sig: o instalador (Inno Setup) grava este arquivo com BOM.
        return json.loads((pasta_local() / ARQUIVO_CONFIG_LOCAL).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {}


def gravar_config_local(chave: str, valor) -> None:
    """None apaga a chave. Relê o arquivo antes de gravar pra não perder o
    que outra parte do programa guardou nele."""
    dados = ler_config_local()
    if valor is None:
        dados.pop(chave, None)
    else:
        dados[chave] = valor
    arquivo = pasta_local() / ARQUIVO_CONFIG_LOCAL
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    arquivo.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


def banco_configurado() -> Path | None:
    """O banco escolhido pra este PC (normalmente o do servidor), ou None
    quando ele usa o banco local padrão."""
    valor = ler_config_local().get(CHAVE_BANCO)
    return Path(valor) if valor else None


def definir_banco(caminho: Path | None) -> None:
    """Aponta este PC pra outro arquivo de banco; None escolhe o banco local
    deste computador. Fica gravado mesmo vazio: é a resposta à pergunta de
    onde fica o banco, que não deve ser feita de novo. Só vale na próxima
    conexão — a já aberta continua no arquivo antigo."""
    gravar_config_local(CHAVE_BANCO, str(caminho) if caminho else "")
    gravar_config_local(CHAVE_CRIAR, None)


class BancoNaoEncontrado(sqlite3.OperationalError):
    """O banco configurado pra este PC não está onde deveria."""


def verificar_banco_configurado() -> None:
    """Antes de conectar: o banco escolhido tem que existir.

    O SQLite cria um arquivo vazio quando o caminho não existe. Com o banco
    no servidor, isso transformaria um caminho errado, um arquivo movido ou
    uma pasta que ainda não sincronizou num cadastro novo e vazio — e o PC
    pediria um primeiro usuário como se o escritório nunca tivesse usado o
    sistema. Só se cria quando alguém pediu (CHAVE_CRIAR)."""
    caminho = banco_configurado()
    if caminho is None or caminho.exists() or ler_config_local().get(CHAVE_CRIAR):
        return
    raise BancoNaoEncontrado(
        f"Não encontrei o banco de dados em:\n{caminho}\n\n"
        "Se ele fica no servidor, confira se este computador está na rede e se a pasta abre no "
        "Explorador de Arquivos. Se o banco mudou de pasta, use \"Escolher outro banco\"."
    )


def banco_aberto_com_sucesso() -> None:
    """O banco que era pra criar já existe — a marca não serve mais. Fica
    fora de connect de propósito: só vale depois de o schema estar lá."""
    if CHAVE_CRIAR in ler_config_local():
        gravar_config_local(CHAVE_CRIAR, None)


def get_db_path() -> Path:
    override = os.environ.get("CONTROLE_LUCROS_DB")
    if override:
        return Path(override)
    return banco_configurado() or DEFAULT_DB_PATH


# DRIVE_REMOTE do GetDriveTypeW: unidade mapeada pra uma pasta de rede (Z:).
_UNIDADE_DE_REDE = 4


def banco_em_rede(caminho: Path) -> bool:
    r"""Se o arquivo está numa pasta de outra máquina — \\SERVIDOR\pasta ou
    uma unidade mapeada. Decide o modo de journal (ver _ajustar_journal),
    então na dúvida é melhor dizer que sim: o modo de rede só é mais lento,
    o outro corrompe o banco se estiver errado."""
    texto = str(caminho).replace("/", "\\")
    if texto.startswith("\\\\?\\"):  # \\?\ é caminho longo: só é rede se for \\?\UNC\
        return texto.upper().startswith("\\\\?\\UNC\\")
    if texto.startswith("\\\\"):
        return True
    if sys.platform == "win32":
        unidade = os.path.splitdrive(os.path.abspath(str(caminho)))[0]
        if unidade:
            import ctypes

            return ctypes.windll.kernel32.GetDriveTypeW(unidade + "\\") == _UNIDADE_DE_REDE
    return False


def _destino_da_unidade(unidade: str) -> str | None:
    """O \\\\SERVIDOR\\pasta por trás de uma letra mapeada (Z:), ou None."""
    import ctypes
    from ctypes import wintypes

    tamanho = wintypes.DWORD(1024)
    destino = ctypes.create_unicode_buffer(tamanho.value)
    if ctypes.windll.mpr.WNetGetConnectionW(unidade, destino, ctypes.byref(tamanho)) == 0:
        return destino.value
    return None


def caminho_de_rede(caminho: Path) -> Path:
    """Troca a letra de unidade mapeada pelo caminho de rede verdadeiro.

    A letra é configuração de cada conta do Windows: em outra conta ela pode
    não existir ou apontar pra outro lugar, e o programa guardaria um caminho
    que só funciona pra quem o escolheu. Letra de disco local, ou fora do
    Windows, volta como veio."""
    if sys.platform != "win32":
        return Path(caminho)
    unidade, resto = ntpath.splitdrive(str(caminho))
    if len(unidade) != 2 or unidade[1] != ":":
        return Path(caminho)
    destino = _destino_da_unidade(unidade)
    return Path(destino + resto) if destino else Path(caminho)


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    _ajustar_journal(conn, em_rede=banco_em_rede(path))
    # Duas gravações ao mesmo tempo: a segunda espera a vez em vez de dar
    # erro. Em rede vale também pra leitura x gravação (ver _ajustar_journal).
    conn.execute(f"PRAGMA busy_timeout = {ESPERA_DE_BLOQUEIO_MS};")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn



NOME_DO_ARQUIVO = "controle_lucros.db"


def banco_na_pasta(pasta: Path) -> Path:
    return Path(pasta) / NOME_DO_ARQUIVO


def precisa_configurar() -> bool:
    """Instalação nova, que ainda não sabe onde fica o banco: nada escolhido
    e nenhum banco local. É quando se pergunta se este PC cria o banco ou
    usa um que já está no servidor — perguntar depois seria tarde, porque
    abrir cria um banco local vazio e o PC pediria um primeiro usuário.

    Chamar depois da migração do banco antigo: um PC que já tinha cadastro
    não é instalação nova."""
    if os.environ.get("CONTROLE_LUCROS_DB") or CHAVE_BANCO in ler_config_local():
        return False
    return not DEFAULT_DB_PATH.exists()


def criar_banco_em(pasta: Path) -> Path:
    """Cria um banco vazio na pasta e devolve o arquivo. Recusa se já houver
    um lá: pode ser o do escritório, criado por outro PC."""
    destino = banco_na_pasta(pasta)
    if destino.exists():
        raise FileExistsError(f"Já existe um banco em {destino}.")
    destino.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(destino)
    try:
        init_schema(conn)
    finally:
        conn.close()
    return destino


def e_banco_do_sistema(caminho: Path) -> bool:
    """Se o arquivo é um banco deste programa — e não um .db qualquer que
    alguém escolheu por engano. Só lê: não cria o arquivo (confere antes que
    ele existe) nem mexe no journal de um banco que outros PCs estão usando.

    Sem URI "file:...?mode=ro" de propósito: pra \\\\SERVIDOR\\pasta ela vira
    file://SERVIDOR/..., e o SQLite recusa URI com nome de máquina — todo
    banco do servidor seria dado como "não reconhecido"."""
    caminho = Path(caminho)
    try:
        if not caminho.is_file():
            return False
        conn = sqlite3.connect(caminho)
    except (sqlite3.Error, OSError):
        return False
    try:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'usuario'"
        ).fetchone() is not None
    except sqlite3.Error:
        return False
    finally:
        conn.close()


def levar_banco_para(conn: sqlite3.Connection, pasta: Path) -> Path:
    """Copia o banco aberto pra outra pasta (a do servidor) e devolve o
    arquivo novo. Não aponta o PC pra lá — isso é definir_banco, depois.

    Pelo backup do SQLite, que leva junto o que ainda está no -wal. Recusa
    sobrescrever um banco que já esteja lá: pode ser o do escritório, com o
    trabalho de todo mundo. O original fica onde está."""
    destino = Path(pasta) / NOME_DO_ARQUIVO
    if destino.exists():
        raise FileExistsError(
            f"Já existe um banco em {destino}. Para usá-lo, escolha \"Usar um banco que já está "
            "no servidor\" e aponte para essa pasta, em vez de levar este."
        )
    destino.parent.mkdir(parents=True, exist_ok=True)
    copia = sqlite3.connect(destino)
    try:
        conn.backup(copia)
        # A cópia herda o WAL do original; no servidor ele não pode ficar.
        copia.execute("PRAGMA journal_mode = DELETE;")
    finally:
        copia.close()
    return destino


def explicar_erro(erro: BaseException) -> str:
    """O texto do erro do banco trocado por algo que a pessoa entenda e saiba
    o que fazer. Com o banco no servidor, "disk I/O error" é quase sempre a
    rede que caiu — e quem lê isso não tem como adivinhar."""
    if isinstance(erro, (BancoEmWalNaRede, BancoNaoEncontrado)):
        return str(erro)
    if isinstance(erro, sqlite3.OperationalError):
        texto = str(erro).lower()
        if "locked" in texto or "busy" in texto:
            return (
                "O banco está ocupado por outro computador neste momento. "
                "Espere alguns segundos e tente de novo."
            )
        if "disk i/o" in texto or "unable to open" in texto or "readonly" in texto:
            return (
                f"Não consegui acessar o banco de dados em {get_db_path()}.\n\n"
                "Se ele fica no servidor, confira se este computador está na rede e se a pasta "
                "abre no Explorador de Arquivos. O que você estava gravando pode não ter sido "
                "salvo — feche o programa e abra de novo depois de a rede voltar."
            )
    return str(erro)

# Espera curta só para a conversão do journal_mode: ela não desiste antes do
# timeout, então um valor alto aqui viraria o programa parado olhando pra
# nada antes da tela de login.
ESPERA_DA_CONVERSAO_MS = 2_000


class BancoEmWalNaRede(sqlite3.OperationalError):
    """O banco da rede está em WAL e não deu pra tirar agora."""


def _ajustar_journal(conn: sqlite3.Connection, em_rede: bool) -> None:
    """WAL no disco local, journal tradicional (DELETE) na pasta do servidor.

    O WAL coordena quem lê e quem grava por um arquivo -shm de memória
    compartilhada, que só funciona com todos os programas na MESMA máquina —
    a documentação do SQLite diz com todas as letras que WAL não funciona em
    pasta de rede. Dois PCs gravando assim pelo servidor corrompem o banco.
    O journal tradicional se coordena pelo travamento de arquivo do próprio
    Windows, que funciona entre máquinas. Custo: enquanto um grava, os
    outros esperam até pra ler — por isso o busy_timeout vale ainda mais aqui.

    Um banco que chegou em WAL no servidor (copiado à mão de um PC) é
    convertido na abertura. Se não der — outro PC com ele aberto em WAL —
    não abre: seguir assim é o caso que corrompe."""
    if not em_rede:
        _garantir_wal(conn)
        return
    if str(conn.execute("PRAGMA journal_mode;").fetchone()[0]).lower() != "wal":
        return
    conn.execute(f"PRAGMA busy_timeout = {ESPERA_DA_CONVERSAO_MS};")
    try:
        modo = conn.execute("PRAGMA journal_mode = DELETE;").fetchone()[0]
    except sqlite3.OperationalError:
        modo = "wal"
    if str(modo).lower() == "wal":
        conn.close()
        raise BancoEmWalNaRede(
            "O banco no servidor está em uso por outro computador num modo que não funciona "
            "em rede. Feche o programa nos outros computadores e abra de novo."
        )


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
    # Banco no servidor fica de fora: ou ele já existe lá, ou o servidor está
    # fora do ar — e aí não é hora de criar um banco lá com o cadastro velho
    # de uma conta só.
    if banco_em_rede(destino) or destino.exists():
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
    ("informe_rendimento", "saida_sociedade_data", "TEXT NOT NULL DEFAULT ''"),
    ("informe_rendimento", "cotas_inicio", "REAL NOT NULL DEFAULT 0"),
    ("informe_rendimento", "cotas_fim", "REAL NOT NULL DEFAULT 0"),
    ("informe_rendimento", "cota_valor_nominal", "INTEGER NOT NULL DEFAULT 0"),
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
