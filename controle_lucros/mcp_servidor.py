"""Servidor MCP: deixa o Claude consultar o Controle de Lucros.

    python servidor_mcp.py      (ou python -m controle_lucros.mcp_servidor)

Fala MCP pelo stdio — é assim que o Claude Desktop e o Claude Code abrem
servidores locais (ver o README pra configurar). Usa a mesma conexão
configurada neste PC pelo programa.

Só lê. A conexão nasce com default_transaction_read_only, então nem uma
consulta SQL livre consegue gravar; cadastro e lançamento continuam sendo
feitos no programa, com login, log e período trancado.

O que sai daqui vai para o Claude, fora do escritório. Por isso o CPF dos
sócios sai mascarado (***.456.789-**) e a consulta SQL livre não lê a coluna,
a menos que CONTROLE_LUCROS_MCP_DOCUMENTOS=completos esteja definido.
"""
from __future__ import annotations

import datetime as dt
import functools
import os
import threading
from dataclasses import asdict
from decimal import Decimal

import pglast
import psycopg
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pglast import ast
from pglast.visitors import Visitor

from controle_lucros import analise, db, repositories as repo
from controle_lucros.models import TIPOS_MOVIMENTACAO_LABEL, Socio

LIMITE_SQL = 500
TEMPO_MAXIMO_MS = 30_000


class ConexaoSoLeitura(db.Conexao):
    """Conexão que o servidor recusa a gravar — vale também depois de a
    conexão cair e ser refeita, porque é aqui, na abertura, que se trava."""

    def _abrir(self):
        conn = super()._abrir()
        conn.execute("SET default_transaction_read_only = on")
        conn.execute(f"SET statement_timeout = {TEMPO_MAXIMO_MS}")
        return conn

    def consultar(self, sql: str, limite: int) -> tuple[list[str], list[tuple], bool]:
        """Roda um SELECT numa transação só de leitura e desfaz no fim —
        inclusive um set_config() que tentasse destravar a sessão."""
        if self._conn.broken:
            self._conn = self._abrir()
        self._conn.execute("BEGIN TRANSACTION READ ONLY")
        try:
            # Cursor no servidor: só as linhas pedidas atravessam a rede. Um
            # cursor comum traria o resultado inteiro para depois cortar.
            with self._conn.cursor(name="consulta_mcp") as cur:
                cur.execute(sql)
                colunas = [c.name for c in cur.description or []]
                linhas = cur.fetchmany(limite + 1)
        finally:
            # Com a conexão caída o ROLLBACK falharia e esconderia o erro de
            # verdade (tempo esgotado, rede); o servidor já desfez sozinho.
            if not self._conn.broken:
                self._conn.execute("ROLLBACK")
        return colunas, [tuple(l) for l in linhas[:limite]], len(linhas) > limite


_conn: ConexaoSoLeitura | None = None


def conexao() -> ConexaoSoLeitura:
    global _conn
    if _conn is None or _conn.closed:
        parametros = db.conexao_configurada()
        if parametros is None:
            raise ToolError("Este PC ainda não tem conexão configurada: abra o programa e configure o servidor.")
        _conn = ConexaoSoLeitura(parametros)
    return _conn


# ------------------------------------------------------------- formatação --


def documentos_completos() -> bool:
    return os.environ.get("CONTROLE_LUCROS_MCP_DOCUMENTOS", "").lower() == "completos"


def mascarar(documento: str | None) -> str:
    """CPF vira ***.456.789-**; CNPJ (de empresa, público) fica como está."""
    digitos = repo.normalizar_documento(documento)
    if documentos_completos() or len(digitos) != 11:
        return documento or ""
    return f"***.{digitos[3:6]}.{digitos[6:9]}-**"


def _limpo(valor, casas: int | None = 4):
    """Tira o ruído de ponto flutuante e transforma o que o JSON não aceita.
    Quatro casas, e não duas: percentual de participação usa quatro (0,0040%
    é uma participação, não zero). casas=None não arredonda — o SQL livre
    devolve o que o banco calculou."""
    if isinstance(valor, Decimal):
        valor = float(valor)
    if isinstance(valor, float):
        return valor if casas is None else round(valor, casas)
    if isinstance(valor, (dt.date, dt.datetime)):
        return valor.isoformat()
    if isinstance(valor, dict):
        return {str(k): _limpo(v, casas) for k, v in valor.items()}
    if isinstance(valor, (list, tuple)):
        return [_limpo(v, casas) for v in valor]
    if hasattr(valor, "__dataclass_fields__"):
        return _limpo(asdict(valor), casas)
    return valor


def _periodo(ano_de: int | None, ano_ate: int | None) -> tuple[int, int]:
    """Sem nada, o último ano com lançamento; só ano_de ("desde 2020"), de
    ano_de até o último; só ano_ate, aquele ano."""
    ultimo = repo.ultimo_ano_com_distribuicao(conexao())
    if ultimo is None:
        raise ToolError("Ainda não há distribuição lançada no sistema.")
    ano_ate = ano_ate or max(ano_de or ultimo, ultimo)
    ano_de = ano_de or ano_ate
    if ano_de > ano_ate:
        ano_de, ano_ate = ano_ate, ano_de
    return ano_de, ano_ate


def _pelo_nome(registros: list, texto: str) -> list:
    """Nome igual ganha de nome que só contém o texto: "ANA" acha a ANA
    mesmo havendo uma ANA MARIA."""
    chave = repo.chave_nome(texto)
    if not chave:
        return []
    iguais = [r for r in registros if repo.chave_nome(r.nome) == chave]
    return iguais or [r for r in registros if chave in repo.chave_nome(r.nome)]


def _achar_empresa(empresa: str):
    """Pelo código (nº de chamada), pelo CNPJ ou por um pedaço do nome."""
    texto = str(empresa).strip()
    linha = conexao().execute("SELECT id FROM empresa WHERE numero_chamada = %s", (texto,)).fetchone()
    if linha is not None:
        return repo.buscar_empresa(conexao(), linha["id"])
    # Nome e CNPJ são comparados sem acento e sem máscara, o que o SQL não
    # faz sozinho; são poucas centenas de empresas.
    empresas = repo.listar_empresas(conexao())
    exatas = []
    if repo.normalizar_documento(texto):
        exatas = [e for e in empresas if repo.normalizar_documento(e.cnpj) == repo.normalizar_documento(texto)]
    if not exatas:
        exatas = _pelo_nome(empresas, texto)
    if len(exatas) == 1:
        return exatas[0]
    if not exatas:
        raise ToolError(f'Nenhuma empresa encontrada para "{texto}". Use buscar_empresas.')
    opcoes = "; ".join(f"{e.numero_chamada} — {e.nome}" for e in exatas[:15])
    raise ToolError(f'"{texto}" serve para {len(exatas)} empresas, diga o código: {opcoes}')


def _achar_socio(socio: str):
    """Pelo id, pelo CPF/CNPJ ou por um pedaço do nome."""
    texto = str(socio).strip()
    if texto.isdigit() and len(texto) < 11:
        linha = conexao().execute("SELECT id, nome, cpf, tipo_pessoa FROM socio WHERE id = %s", (int(texto),)).fetchone()
        if linha is not None:
            return Socio(**dict(linha))
    socios = repo.listar_socios(conexao())
    exatos = []
    documento = repo.normalizar_documento(texto)
    if len(documento) >= 11:
        exatos = [s for s in socios if repo.normalizar_documento(s.cpf) == documento]
    if not exatos:
        exatos = _pelo_nome(socios, texto)
    if len(exatos) == 1:
        return exatos[0]
    if not exatos:
        raise ToolError(f'Nenhum sócio encontrado para "{texto}". Use buscar_socios.')
    opcoes = "; ".join(f"id {s.id} — {s.nome}" for s in exatos[:15])
    raise ToolError(f'"{texto}" serve para {len(exatos)} sócios, diga o id: {opcoes}')


# ---------------------------------------------------------------- servidor --

servidor = MCPServer(
    name="controle-de-lucros",
    title="Controle de Lucros",
    instructions=(
        "Consulta (só leitura) ao sistema de controle de distribuição de lucros do escritório: "
        "empresas clientes, quadro societário, alterações contratuais, lucro distribuído por ano a "
        "cada sócio, pró-labore, IRRF e movimentações (empréstimos, adiantamentos, devolução de "
        "capital). Valores em reais. Empresas são chamadas pelo código (nº de chamada). "
        "Distribuição 'desproporcional' é quando a fatia recebida pelo sócio difere da fatia dele "
        "no capital além da tolerância, em pontos percentuais. Para perguntas que as outras "
        "ferramentas não cobrem, veja esquema_do_banco e use consultar_sql."
    ),
)
_LEITURA = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
# As ferramentas rodam em threads, mas a conexão é uma só: uma de cada vez,
# senão o BEGIN/ROLLBACK de uma consulta_sql pega a leitura de outra no meio.
_uma_por_vez = threading.Lock()


def ferramenta(funcao):
    @functools.wraps(funcao)
    def serializada(*args, **kwargs):
        with _uma_por_vez:
            return funcao(*args, **kwargs)

    return servidor.tool(annotations=_LEITURA)(serializada)


@ferramenta
def resumo_geral(ano_de: int | None = None, ano_ate: int | None = None) -> dict:
    """Panorama de todas as empresas num período (padrão: o último ano com
    lançamento; só ano_de = desde aquele ano até o último): total distribuído, comparação com o período anterior,
    pró-labore, IRRF, as empresas que mais distribuíram, os sócios que mais
    receberam, movimentações por tipo e a evolução ano a ano."""
    ano_de, ano_ate = _periodo(ano_de, ano_ate)
    painel = repo.painel_geral(conexao(), ano_de, ano_ate, limite=15)
    for s in painel["top_socios"]:
        s["documento"] = mascarar(s["documento"])
    painel["movimentos"] = {TIPOS_MOVIMENTACAO_LABEL.get(t, t): v for t, v in painel["movimentos"].items()}
    return _limpo({"periodo": [ano_de, ano_ate], **painel})


@ferramenta
def pontos_de_atencao(ano_de: int | None = None, ano_ate: int | None = None, tolerancia: float = 0.0) -> dict:
    """O que merece olhar no período: sócios que receberam fora da proporção
    do capital (tolerância em pontos percentuais), lucro distribuído a sócio
    pessoa física em anos sem pró-labore (somado por sócio e empresa),
    empresas que não distribuíram e empréstimos a sócios. As listas param em
    100/50 itens; os campos quantidade_* dizem quantos há. Só ano_de = desde
    aquele ano até o último. Com muitas empresas pode levar alguns segundos."""
    ano_de, ano_ate = _periodo(ano_de, ano_ate)
    conn = conexao()
    geral = repo.visao_geral(conn, ano_de, ano_ate, tolerancia)
    fora = sorted(
        (l for l in geral["linhas"] if l["classificacao"] == "desproporcional"),
        key=lambda l: abs(l["percentual_distribuido"] - l["percentual_capital"]), reverse=True,
    )
    # O mesmo cálculo do cartão do dashboard: somado por sócio e empresa.
    sem_pro = analise.sem_pro_labore(geral["linhas"])
    emprestimos = [
        {"empresa": r["empresa_nome"], "total": r["total_emprestimos"]}
        for r in sorted(geral["resumo_empresas"], key=lambda r: -r["total_emprestimos"])
        if r["total_emprestimos"] > 0
    ]
    return _limpo({
        "periodo": [ano_de, ano_ate],
        "tolerancia_pp": tolerancia,
        "total_distribuido": geral["total_distribuido"],
        "total_proporcional": geral["total_proporcional"],
        "total_desproporcional": geral["total_desproporcional"],
        "fora_da_proporcao": [
            {"empresa": l["empresa_nome"], "ano": l["ano_base"], "socio": l["socio_nome"],
             "percentual_capital": l["percentual_capital"], "percentual_recebido": l["percentual_distribuido"],
             "valor_recebido": l["valor_distribuido"]}
            for l in fora[:100]
        ],
        "quantidade_fora_da_proporcao": len(fora),
        "lucro_sem_pro_labore": [
            {"socio": i.socio_nome, "empresa": i.empresa_nome, "anos_sem_pro_labore": list(i.anos),
             "lucro_nesses_anos": i.valor_sem_pro_labore, "lucro_no_periodo": i.valor_distribuido,
             "pro_labore_no_periodo": i.pro_labore}
            for i in sem_pro[:50]
        ],
        "quantidade_sem_pro_labore": len(sem_pro),
        "total_sem_pro_labore": sum(i.valor_sem_pro_labore for i in sem_pro),
        "empresas_sem_distribuicao": geral["empresas_sem_distribuicao"],
        "emprestimos_a_socios": emprestimos[:50],
        "quantidade_empresas_com_emprestimo": len(emprestimos),
        "total_emprestimos": geral["total_emprestimos"],
    })


@ferramenta
def buscar_empresas(texto: str = "", limite: int = 30) -> list[dict]:
    """Procura empresas pelo código, CNPJ ou parte do nome (vazio lista
    todas, até o limite). Traz quantos sócios ativos cada uma tem."""
    conn = conexao()
    chave, digitos = repo.chave_nome(texto), repo.normalizar_documento(texto)
    achadas = [
        e for e in repo.listar_empresas(conn)
        if not texto.strip() or e.numero_chamada == texto.strip()
        or (chave and chave in repo.chave_nome(e.nome))
        or (len(digitos) >= 4 and digitos in repo.normalizar_documento(e.cnpj))
    ]
    if not achadas:
        return []
    ativos = repo.quantidade_socios_ativos_por_empresa(conn)
    return _limpo([
        {"codigo": e.numero_chamada, "nome": e.nome, "cnpj": e.cnpj, "socios_ativos": ativos.get(e.id, 0)}
        for e in achadas[:limite]
    ])


@ferramenta
def ficha_empresa(empresa: str) -> dict:
    """Ficha de uma empresa (código, CNPJ ou nome): capital e cotas
    vigentes, quadro societário de hoje, ex-sócios, alterações contratuais e
    o lucro distribuído em cada ano."""
    conn = conexao()
    e = _achar_empresa(empresa)
    ficha = repo.ficha_empresa(conn, e.id)
    for q in ficha["quadro"]:
        q["documento"] = mascarar(q["documento"])
    alteracoes = [
        {"numero": a.numero, "data": a.data, "descricao": a.descricao, "capital_social": a.capital_social,
         "quantidade_cotas": a.quantidade_cotas}
        for a in sorted(repo.listar_alteracoes(conn, e.id), key=lambda a: (a.data, a.numero))
    ]
    por_ano = [{"ano": a["ano"], "total": a["total"], "pro_labore": a["pro_labore"], "irrf": a["irrf"]}
               for a in repo.painel_empresa(conn, e.id)["por_ano"]]
    return _limpo({
        "codigo": e.numero_chamada, "nome": e.nome, "cnpj": e.cnpj,
        "capital_social": ficha["capital_social"], "quantidade_cotas": ficha["quantidade_cotas"],
        "valor_cota": ficha["valor_cota"],
        "quadro_societario": [{k: q[k] for k in ("socio_id", "nome", "documento", "percentual", "cotas",
                                                  "capital", "data_entrada")} for q in ficha["quadro"]],
        "soma_percentual": ficha["soma_percentual"],
        "ex_socios": ficha["saidas"],
        "alteracoes_contratuais": alteracoes,
        "distribuicao_por_ano": por_ano,
    })


@ferramenta
def distribuicao_da_empresa(empresa: str, ano: int, tolerancia: float = 0.0) -> dict:
    """A distribuição de um ano numa empresa, sócio a sócio: % do capital,
    valor e % recebido, pró-labore, IRRF, empréstimos, adiantamento,
    devolução de capital, entrada/saída no ano e se ficou proporcional."""
    conn = conexao()
    e = _achar_empresa(empresa)
    linhas = repo.linhas_classificadas_empresa_ano(conn, e.id, ano, tolerancia)
    campos = ("socio_id", "percentual_capital", "quantidade_cotas", "valor_distribuido", "percentual_distribuido",
              "pro_labore", "irrf", "emprestimo_recebido", "emprestimo_feito", "adiantamento", "devolucao_capital",
              "data_entrada", "data_saida", "entrou_no_ano", "saiu_no_ano", "origem_valor", "classificacao")
    return _limpo({
        "empresa": f"{e.numero_chamada} — {e.nome}",
        "ano": ano,
        "periodo_trancado": repo.periodo_esta_fechado(conn, e.id, ano),
        "total_distribuido": repo.total_distribuido_empresa_ano(conn, e.id, ano),
        "socios": [{"nome": l["socio_nome"], "documento": mascarar(l["socio_cpf"]), **{k: l[k] for k in campos}}
                   for l in linhas],
    })


@ferramenta
def buscar_socios(texto: str, limite: int = 30) -> list[dict]:
    """Procura sócios por parte do nome ou do CPF/CNPJ — inclusive os
    dígitos que aparecem no CPF mascarado (***.456.789-** → "456.789").
    Traz em quantas empresas cada um está hoje."""
    conn = conexao()
    chave, digitos = repo.chave_nome(texto), repo.normalizar_documento(texto)
    achados = [
        s for s in repo.listar_socios(conn)
        if (chave and chave in repo.chave_nome(s.nome))
        or (len(digitos) >= 4 and digitos in _parte_buscavel(s.cpf))
    ]
    if not achados:
        return []
    ativos = repo.quantidade_empresas_ativas_por_socio(conn)
    return _limpo([
        {"id": s.id, "nome": s.nome, "documento": mascarar(s.cpf), "tipo_pessoa": s.tipo_pessoa,
         "empresas_ativas": ativos.get(s.id, 0)}
        for s in achados[:limite]
    ])


def _parte_buscavel(documento: str | None) -> str:
    """Os dígitos do documento que a busca pode casar. Com o CPF mascarado,
    só os do meio — os mesmos que a resposta mostra: casar o CPF inteiro
    deixaria descobrir os dígitos escondidos tentando um a um."""
    digitos = repo.normalizar_documento(documento)
    if len(digitos) == 11 and not documentos_completos():
        return digitos[3:9]
    return digitos


@ferramenta
def ficha_socio(socio: str) -> dict:
    """Ficha de um sócio (id, CPF ou nome): empresas em que está ou esteve,
    a história de entradas, saídas e participações refeitas, e o lucro
    recebido em cada empresa ano a ano."""
    conn = conexao()
    s = _achar_socio(socio)
    eventos = [
        {k: ev[k] for k in ("empresa_nome", "tipo", "data", "percentual", "cotas", "capital", "percentual_antes",
                            "alteracao_numero", "refeita")}
        for ev in repo.movimentacoes_do_socio(conn, s.id)
    ]
    recebido = [
        {"empresa": r["nome"], "ano": r["ano_base"], "lucro": r["valor_distribuido"], "pro_labore": r["pro_labore"],
         "irrf": r["irrf"]}
        for r in conn.execute(
            """SELECT e.nome, d.ano_base, d.valor_distribuido, d.pro_labore, d.irrf
               FROM distribuicao_lucro d JOIN empresa e ON e.id = d.empresa_id
               WHERE d.socio_id = %s ORDER BY d.ano_base, e.nome""",
            (s.id,),
        ).fetchall()
    ]
    movimentacoes = [
        {"empresa": r["nome"], "tipo": TIPOS_MOVIMENTACAO_LABEL.get(r["tipo"], r["tipo"]), "data": r["data"],
         "valor": r["valor"]}
        for r in conn.execute(
            """SELECT e.nome, m.tipo, m.data, m.valor FROM movimentacao m JOIN empresa e ON e.id = m.empresa_id
               WHERE m.socio_id = %s ORDER BY m.data""",
            (s.id,),
        ).fetchall()
    ]
    return _limpo({
        "id": s.id, "nome": s.nome, "documento": mascarar(s.cpf), "tipo_pessoa": s.tipo_pessoa,
        "historico_societario": eventos,
        "lucro_recebido": recebido,
        "total_recebido": sum(r["lucro"] or 0 for r in recebido),
        "movimentacoes": movimentacoes,
    })


@ferramenta
def esquema_do_banco() -> dict:
    """Tabelas e colunas que a consultar_sql pode ler, e as funções que ela
    aceita."""
    tabelas: dict[str, list[str]] = {}
    for r in conexao().execute(
        """SELECT table_name, column_name, data_type FROM information_schema.columns
           WHERE table_schema = current_schema() ORDER BY table_name, ordinal_position"""
    ).fetchall():
        if r["table_name"] in TABELAS_LIVRES and (r["column_name"] != "cpf" or documentos_completos()):
            tabelas.setdefault(r["table_name"], []).append(f'{r["column_name"]} ({r["data_type"]})')
    return {
        "tabelas": tabelas,
        "funcoes_aceitas": sorted(FUNCOES_LIVRES),
        "observacoes": [
            "datas são texto AAAA-MM-DD; distribuicao_lucro.ano_base é o ano",
            "vinculo_societario: participação do sócio na empresa; data_saida NULL = ainda é sócio",
            "movimentacao.tipo: " + ", ".join(TIPOS_MOVIMENTACAO_LABEL),
            "socio.cpf não é consultável por SQL; o CPF (mascarado) vem em buscar_socios e ficha_socio",
        ],
    }


# ---------------------------------------------------------------- SQL livre --
#
# A consulta é lida pelo analisador do próprio PostgreSQL (pglast) e só passa
# o que está na lista: tabelas do negócio e funções de cálculo. Procurar
# palavras no texto não serve — 'usu'||'ario' dentro de query_to_xml(), ou
# U&"\0075suario", leem a tabela de usuários sem escrever "usuario". E uma
# transação só de leitura não segura função com efeito colateral
# (pg_terminate_backend derruba quem está usando o programa,
# pg_advisory_lock sobrevive ao ROLLBACK).

# Fora: usuario (hash e sal das senhas), log_atividade e layout_importacao.
# acesso_lembrado nem está em db.TABELAS.
TABELAS_LIVRES = frozenset({
    "empresa", "socio", "alteracao_contratual", "vinculo_societario", "distribuicao_lucro",
    "distribuicao_trimestral", "periodo_distribuicao", "movimentacao", "informe_rendimento",
})
FUNCOES_LIVRES = frozenset({
    # agregação
    "count", "sum", "avg", "min", "max", "string_agg", "array_agg", "bool_and", "bool_or", "every",
    "stddev", "stddev_pop", "stddev_samp", "variance", "var_pop", "var_samp", "percentile_cont",
    "percentile_disc", "mode", "corr",
    # janela
    "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile", "lag", "lead",
    "first_value", "last_value", "nth_value",
    # números
    "abs", "round", "trunc", "ceil", "ceiling", "floor", "power", "sqrt", "mod", "sign", "div", "exp", "ln",
    "log",
    # texto
    "lower", "upper", "initcap", "length", "char_length", "left", "right", "substr", "substring", "trim",
    "btrim", "ltrim", "rtrim", "replace", "concat", "concat_ws", "split_part", "strpos", "position", "lpad",
    "rpad", "reverse", "translate", "regexp_replace", "regexp_match", "starts_with", "format",
    # datas
    "extract", "date_part", "date_trunc", "to_char", "to_date", "to_number", "make_date", "age", "now",
    # séries e listas
    "generate_series", "unnest", "array_length", "cardinality",
})


class _Nos(Visitor):
    def __init__(self):
        self.nos = []

    def visit(self, ancestors, node):
        self.nos.append(node)


def validar_sql(sql: str) -> None:
    """Recusa, com uma explicação que o Claude consiga seguir, tudo que não
    seja um SELECT sobre TABELAS_LIVRES usando FUNCOES_LIVRES. Sem os
    documentos completos, socio.cpf também fica de fora — inclusive por
    *, por linha inteira (SELECT s FROM socio s) ou dentro de um cálculo."""
    try:
        comandos = pglast.parse_sql(sql)
    except pglast.parser.ParseError as erro:
        raise ToolError(f"SQL inválido: {erro}") from erro
    if len(comandos) != 1 or not isinstance(comandos[0].stmt, ast.SelectStmt):
        raise ToolError("Só um comando, e ele tem que ser SELECT (ou WITH ... SELECT).")
    coletor = _Nos()
    coletor(comandos[0])
    nos = coletor.nos

    ctes = {n.ctename for n in nos if isinstance(n, ast.CommonTableExpr)}
    nomes_do_socio = set()
    for n in nos:
        if isinstance(n, (ast.InsertStmt, ast.UpdateStmt, ast.DeleteStmt, ast.MergeStmt)):
            raise ToolError("Só leitura: INSERT, UPDATE e DELETE não são aceitos, nem dentro de um WITH.")
        if isinstance(n, ast.SelectStmt) and (n.intoClause or n.lockingClause):
            raise ToolError("SELECT ... INTO e FOR UPDATE/SHARE não são aceitos.")
        if isinstance(n, ast.RangeVar):
            if n.schemaname:
                raise ToolError(f"Use o nome da tabela sem esquema ({n.schemaname}.{n.relname}).")
            if n.relname not in TABELAS_LIVRES | ctes:
                raise ToolError(f'A tabela "{n.relname}" não está disponível. Disponíveis: '
                                + ", ".join(sorted(TABELAS_LIVRES)) + ".")
            if n.relname == "socio" and n.relname not in ctes:
                nomes_do_socio |= {"socio", n.alias.aliasname if n.alias else "socio"}
        if isinstance(n, ast.FuncCall):
            partes = [p.sval for p in n.funcname]
            if len(partes) == 2 and partes[0] == "pg_catalog":
                partes = partes[1:]
            if len(partes) != 1 or partes[0] not in FUNCOES_LIVRES:
                raise ToolError(f'A função "{".".join(partes)}" não é aceita aqui; '
                                "as aceitas estão em esquema_do_banco (funcoes_aceitas).")

    if documentos_completos() or not nomes_do_socio:
        return
    for n in nos:
        if not isinstance(n, ast.ColumnRef):
            continue
        campos = n.fields
        if any(isinstance(c, ast.A_Star) for c in campos):
            raise ToolError("Com a tabela socio na consulta, liste as colunas em vez de * (o CPF não sai por SQL).")
        ultimo = campos[-1].sval if isinstance(campos[-1], ast.String) else ""
        if ultimo == "cpf":
            raise ToolError("O CPF não sai por SQL. Use buscar_socios ou ficha_socio, que o trazem mascarado.")
        if len(campos) == 1 and ultimo in nomes_do_socio:
            raise ToolError(f'"{ultimo}" sozinho traz a linha inteira do sócio, com o CPF. Liste as colunas.')


@ferramenta
def consultar_sql(sql: str, limite: int = 200) -> dict:
    """Roda UM SELECT (ou WITH ... SELECT) no banco, só leitura, e devolve
    até `limite` linhas (máx. 500). Para perguntas que as outras ferramentas
    não respondem. Só as tabelas e funções listadas em esquema_do_banco;
    socio.cpf não é consultável."""
    comando = sql.strip().rstrip(";").strip()
    validar_sql(comando)
    try:
        colunas, linhas, cortou = conexao().consultar(comando, max(1, min(limite, LIMITE_SQL)))
    except psycopg.Error as erro:
        # O erro do PostgreSQL (coluna que não existe, sintaxe) é o que o
        # Claude precisa para corrigir a consulta.
        raise ToolError(str(erro).strip()) from erro
    return _limpo({"colunas": colunas, "linhas": linhas, "cortado_no_limite": cortou}, casas=None)


def main() -> None:
    servidor.run("stdio")


if __name__ == "__main__":
    main()
