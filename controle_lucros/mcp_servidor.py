"""Servidor MCP: deixa o Claude consultar e alimentar o Controle de Lucros.

    python servidor_mcp.py      (ou python -m controle_lucros.mcp_servidor)

Fala MCP pelo stdio — é assim que o Claude Desktop e o Claude Code abrem
servidores locais (ver o README pra configurar). Usa a mesma conexão
configurada neste PC pelo programa.

Lê, grava, corrige e exclui. As consultas usam uma conexão que nasce com
default_transaction_read_only — a consulta SQL livre continua só de leitura.
As gravações são ferramentas próprias (cadastrar, editar, lançar, importar
planilha, trancar, corrigir, mover, excluir) que chamam as mesmas funções das telas, numa segunda
conexão: valem as mesmas validações, período trancado continua trancado, e
cada gravação entra no Log de atividades com o autor "Claude". Antes da
primeira gravação de cada sessão sai um backup completo na pasta de backups
do PC. Usuários, senhas e restauração de backup ficam só no programa.

O que sai daqui vai para o Claude, fora do escritório. Por isso o CPF dos
sócios sai mascarado (***.456.789-**) e a consulta SQL livre não lê a coluna,
a menos que CONTROLE_LUCROS_MCP_DOCUMENTOS=completos esteja definido.
"""
from __future__ import annotations

import datetime as dt
import functools
import os
import threading
from pathlib import Path
from dataclasses import asdict
from decimal import Decimal

import pglast
import psycopg
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pglast import ast
from pglast.visitors import Visitor

from controle_lucros import analise, backup, db, repositories as repo, sessao
from controle_lucros.layout_importacao import importar_com_layout
from controle_lucros.models import (
    TIPOS_MOVIMENTACAO_LABEL,
    AlteracaoContratual,
    Empresa,
    Movimentacao,
    Socio,
    Usuario,
)
from controle_lucros.planilha import importar_cadastro

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
        "Sistema de controle de distribuição de lucros do escritório — consulta e gravação: "
        "empresas clientes, quadro societário, alterações contratuais, lucro distribuído por ano a "
        "cada sócio, pró-labore, IRRF e movimentações (empréstimos, adiantamentos, devolução de "
        "capital). Valores em reais. Empresas são chamadas pelo código (nº de chamada). "
        "Distribuição 'desproporcional' é quando a fatia recebida pelo sócio difere da fatia dele "
        "no capital além da tolerância, em pontos percentuais. Para perguntas que as outras "
        "ferramentas não cobrem, veja esquema_do_banco e use consultar_sql (só leitura). "
        "Para gravar há ferramentas próprias (cadastrar_*, editar_*, lancar_*, importar_planilha, "
        "registrar_alteracao_contratual, incluir_socio_na_empresa, registrar_saida_de_socio, "
        "alterar_participacao, trancar_*), e para corrigir, mover e excluir (corrigir_*, mover_*, "
        "tirar_socio_da_alteracao, excluir_*); todas seguem as regras do programa. Antes de excluir, diga "
        "à pessoa exatamente o que vai sumir e só exclua depois de ela confirmar; excluir_empresa e "
        "excluir_alteracao_contratual primeiro mostram o que vai junto e só apagam com confirmar=true. Uma alteração contratual é UM documento (número, data, capital, cotas) com todas as "
        "entradas, saídas e participações novas daquele contrato: para lançar um contrato, use "
        "registrar_alteracao_contratual com tudo de uma vez, e não sócio por sócio. Quem usa são pessoas "
        "leigas em tecnologia: antes de gravar, diga em português simples o que vai gravar e espere a "
        "pessoa confirmar. Datas AAAA-MM-DD."
    ),
)
_LEITURA = ToolAnnotations(read_only_hint=True, destructive_hint=False, open_world_hint=False)
# As ferramentas rodam em threads, mas a conexão é uma só: uma de cada vez,
# senão o BEGIN/ROLLBACK de uma consulta_sql pega a leitura de outra no meio.
_uma_por_vez = threading.Lock()


_GRAVA = ToolAnnotations(read_only_hint=False, destructive_hint=False, idempotent_hint=False, open_world_hint=False)
_EXCLUI = ToolAnnotations(read_only_hint=False, destructive_hint=True, idempotent_hint=False, open_world_hint=False)


def ferramenta(funcao=None, *, anotacoes: ToolAnnotations = _LEITURA):
    def registrar(f):
        @functools.wraps(f)
        def serializada(*args, **kwargs):
            with _uma_por_vez:
                return f(*args, **kwargs)

        return servidor.tool(annotations=anotacoes)(serializada)

    return registrar(funcao) if funcao is not None else registrar


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
def ficha_alteracao_contratual(empresa: str, numero: int) -> dict:
    """Uma alteração contratual: número, data, capital e cotas, o que ela
    registrou (entradas, saídas, participações novas, com os valores dela) e
    como ficou o quadro de sócios depois dela."""
    e = _achar_empresa(empresa)
    alvo = next((a for a in repo.listar_alteracoes(conexao(), e.id) if a.numero == numero), None)
    if alvo is None:
        raise ToolError(f"A {e.nome} não tem a alteração contratual Nº {numero}.")
    ficha = repo.ficha_alteracao(conexao(), alvo.id)
    return _limpo({
        "empresa": f"{e.numero_chamada} — {e.nome}",
        "numero": alvo.numero, "data": alvo.data, "razao_social": alvo.nome_empresa,
        "capital_social": alvo.capital_social, "quantidade_cotas": alvo.quantidade_cotas,
        "descricao": alvo.descricao, "trancada": alvo.fechada,
        "movimentos": [
            {"socio": m["socio_nome"], "tipo": repo.TIPOS_MOVIMENTO[m["tipo"]], "data": m["data_efetiva"],
             "percentual": m["percentual_capital"], "cotas": m["quantidade_cotas"], "capital": m["valor_capital"],
             "saiu_em": m["fim"]}
            for m in ficha["movimentos"]
        ],
        "quadro_depois": [{"socio": q["nome"], "documento": mascarar(q["documento"]), "percentual": q["percentual"],
                           "cotas": q["cotas"], "capital": q["capital"]} for q in ficha["quadro"]],
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
        {"id": r["id"], "empresa": r["nome"], "tipo": TIPOS_MOVIMENTACAO_LABEL.get(r["tipo"], r["tipo"]),
         "data": r["data"], "valor": r["valor"]}
        for r in conn.execute(
            """SELECT m.id, e.nome, m.tipo, m.data, m.valor FROM movimentacao m JOIN empresa e ON e.id = m.empresa_id
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


# ---------------------------------------------------------------- gravação --
#
# Cada ferramenta chama a mesma função do repositório que a tela chama: é o
# que garante as mesmas regras (CPF repetido, período trancado, número de
# alteração, alteração contratual automática) sem reescrevê-las aqui.

CLAUDE = Usuario(id=None, nome="Claude (assistente)", login="claude", senha_hash="", senha_salt="")

_conn_escrita: db.Conexao | None = None
_backup_da_sessao: str | None = None


def conexao_escrita() -> db.Conexao:
    global _conn_escrita
    if _conn_escrita is None or _conn_escrita.closed:
        parametros = db.conexao_configurada()
        if parametros is None:
            raise ToolError("Este PC ainda não tem conexão configurada: abra o programa e configure o servidor.")
        _conn_escrita = db.Conexao(parametros)
    return _conn_escrita


class _Gravando:
    """Em volta de toda gravação: o autor no log é o Claude, sai um backup
    antes da primeira gravação da sessão, e erro de regra do programa volta
    para o Claude como explicação (desfazendo o que estava pela metade)."""

    def __enter__(self) -> db.Conexao:
        global _backup_da_sessao
        conn = conexao_escrita()
        sessao.definir_usuario_atual(CLAUDE)
        if _backup_da_sessao is None:
            try:
                _backup_da_sessao = str(backup.criar_backup(conn))
            except (OSError, psycopg.Error) as erro:
                raise ToolError(f"Não gravei nada: o backup de segurança antes de gravar falhou ({erro}).") from erro
        return conn

    def __exit__(self, tipo, erro, _rastro) -> bool:
        if erro is None:
            return False
        conexao_escrita().rollback()
        if isinstance(erro, ToolError):
            return False
        if isinstance(erro, ValueError):
            raise ToolError(str(erro)) from erro
        if isinstance(erro, psycopg.Error):
            raise ToolError(db.explicar_erro(erro)) from erro
        return False


def _feito(mensagem: str, **dados) -> dict:
    resposta = {"ok": True, "mensagem": mensagem, **dados}
    if _backup_da_sessao:
        resposta["backup_antes_das_gravacoes"] = _backup_da_sessao
    return _limpo(resposta)


def _data(texto: str) -> str:
    """Aceita AAAA-MM-DD ou DD/MM/AAAA; grava AAAA-MM-DD."""
    texto = str(texto).strip()
    for formato in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return dt.datetime.strptime(texto, formato).date().isoformat()
        except ValueError:
            continue
    raise ToolError(f'Data inválida: "{texto}". Use AAAA-MM-DD (ex.: 2025-03-31).')


def _vinculo_ativo(empresa_id: int, socio_id: int):
    ativos = [v for v in repo.listar_vinculos_empresa(conexao_escrita(), empresa_id)
              if v.socio_id == socio_id and v.data_saida is None]
    if not ativos:
        raise ToolError("Este sócio não está no quadro atual desta empresa.")
    return ativos[-1]


def _alteracao(empresa_id: int, numero: int):
    achadas = [a for a in repo.listar_alteracoes(conexao_escrita(), empresa_id) if a.numero == numero]
    if not achadas:
        raise ToolError(f"Esta empresa não tem a alteração contratual nº {numero}.")
    return achadas[0]


def _tipo_movimentacao(tipo: str) -> str:
    texto = repo.chave_nome(tipo)
    for chave, rotulo in TIPOS_MOVIMENTACAO_LABEL.items():
        if texto in (repo.chave_nome(chave), repo.chave_nome(rotulo)):
            return chave
    raise ToolError("Tipo de movimentação inválido. Use um destes: " + "; ".join(TIPOS_MOVIMENTACAO_LABEL.values()))


# -- empresas --


@ferramenta(anotacoes=_GRAVA)
def cadastrar_empresa(codigo: str, nome: str, cnpj: str = "", capital_social: float = 0.0,
                      quantidade_cotas: float = 0.0, valor_cota: float | None = None) -> dict:
    """Cadastra uma empresa nova. codigo é o nº de chamada do escritório."""
    with _Gravando() as conn:
        if conn.execute("SELECT 1 FROM empresa WHERE numero_chamada = %s", (codigo.strip(),)).fetchone():
            raise ToolError(f"Já existe uma empresa com o código {codigo}.")
        novo = repo.salvar_empresa(conn, Empresa(None, codigo, nome, cnpj, capital_social, quantidade_cotas,
                                                 valor_cota))
    return _feito(f"Empresa {codigo} cadastrada.", empresa_id=novo)


@ferramenta(anotacoes=_GRAVA)
def editar_empresa(empresa: str, codigo: str | None = None, nome: str | None = None, cnpj: str | None = None,
                   capital_social: float | None = None, quantidade_cotas: float | None = None,
                   valor_cota: float | None = None) -> dict:
    """Muda os dados de cadastro de uma empresa (só os campos informados).
    Capital e cotas aqui são os de fundação; mudança de capital ao longo do
    tempo é por alteração contratual."""
    e = _achar_empresa(empresa)
    with _Gravando() as conn:
        for campo, valor in (("numero_chamada", codigo), ("nome", nome), ("cnpj", cnpj),
                             ("capital_social", capital_social), ("quantidade_cotas", quantidade_cotas),
                             ("valor_cota", valor_cota)):
            if valor is not None:
                setattr(e, campo, valor)
        repo.salvar_empresa(conn, e)
    return _feito(f"Empresa {e.numero_chamada} atualizada.")


# -- sócios --


@ferramenta(anotacoes=_GRAVA)
def cadastrar_socio(nome: str, documento: str = "", tipo_pessoa: str = "fisica") -> dict:
    """Cadastra um sócio (pessoa física com CPF, ou jurídica com CNPJ —
    tipo_pessoa "fisica" ou "juridica"). Depois use incluir_socio_na_empresa."""
    if tipo_pessoa not in ("fisica", "juridica"):
        raise ToolError('tipo_pessoa é "fisica" ou "juridica".')
    with _Gravando() as conn:
        novo = repo.salvar_socio(conn, Socio(None, nome, documento, tipo_pessoa))
    return _feito(f"Sócio cadastrado (id {novo}).", socio_id=novo)


@ferramenta(anotacoes=_GRAVA)
def editar_socio(socio: str, nome: str | None = None, documento: str | None = None,
                 tipo_pessoa: str | None = None) -> dict:
    """Corrige nome, CPF/CNPJ ou tipo de pessoa de um sócio."""
    s = _achar_socio(socio)
    with _Gravando() as conn:
        repo.salvar_socio(conn, Socio(s.id, nome if nome is not None else s.nome,
                                      documento if documento is not None else s.cpf,
                                      tipo_pessoa or s.tipo_pessoa))
    return _feito(f"Sócio id {s.id} atualizado.")


# -- quadro societário --


def _alteracao_alvo(conn, empresa_id: int, numero: int | None, data: str, descricao: str) -> int:
    """A alteração em que o movimento entra: a de número informado, ou a do
    mesmo dia (que é criada, se ainda não existe)."""
    if numero is not None:
        return _alteracao(empresa_id, numero).id
    return repo.alteracao_do_dia(conn, empresa_id, data, descricao)


@ferramenta(anotacoes=_GRAVA)
def incluir_socio_na_empresa(empresa: str, socio: str, percentual: float, cotas: float, data_entrada: str,
                             capital: float | None = None, alteracao: int | None = None) -> dict:
    """Põe um sócio (já cadastrado) no quadro da empresa a partir de
    data_entrada, com a % do capital e as cotas. alteracao é o nº da
    alteração contratual que registra a entrada; sem ela, vai para a
    alteração da empresa naquele dia (a mesma para todos os sócios do dia).
    Para lançar um contrato inteiro, prefira registrar_alteracao_contratual."""
    e, s = _achar_empresa(empresa), _achar_socio(socio)
    data = _data(data_entrada)
    with _Gravando() as conn:
        if alteracao is None and not repo.alteracao_automatica_cabe(data):
            vinculo = repo.associar_socio_a_empresa(conn, e.id, s.id, percentual, cotas, data, valor_capital=capital)
        else:
            alvo = _alteracao_alvo(conn, e.id, alteracao, data, "Inclusão de sócio (registrada pelo Claude)")
            repo.salvar_movimento(conn, alvo, s.id, "entrada", data=data, percentual=percentual, cotas=cotas,
                                  capital=capital)
            vinculo = repo._vinculo_do_movimento(conn, alvo, s.id)
    return _feito(f"{s.nome} incluído no quadro da {e.nome}.", vinculo_id=vinculo)


@ferramenta(anotacoes=_GRAVA)
def registrar_saida_de_socio(empresa: str, socio: str, data_saida: str, alteracao: int | None = None) -> dict:
    """Tira o sócio do quadro da empresa na data informada. alteracao é o nº
    da alteração contratual que registra a saída; sem ela, vai para a
    alteração da empresa naquele dia. O histórico dele continua guardado."""
    e, s = _achar_empresa(empresa), _achar_socio(socio)
    data = _data(data_saida)
    with _Gravando() as conn:
        _vinculo_ativo(e.id, s.id)
        alvo = _alteracao_alvo(conn, e.id, alteracao, data, "Saída de sócio (registrada pelo Claude)")
        repo.salvar_movimento(conn, alvo, s.id, "saida", data=data)
    return _feito(f"Saída de {s.nome} da {e.nome} registrada.")


@ferramenta(anotacoes=_GRAVA)
def alterar_participacao(empresa: str, socio: str, percentual: float, cotas: float, data: str,
                         capital: float | None = None, alteracao: int | None = None) -> dict:
    """Muda a % e as cotas de um sócio que continua na empresa, a partir da
    data (a participação antiga fica no histórico). alteracao é o nº da
    alteração contratual que registra a mudança; sem ela, a do dia."""
    e, s = _achar_empresa(empresa), _achar_socio(socio)
    quando = _data(data)
    with _Gravando() as conn:
        _vinculo_ativo(e.id, s.id)
        alvo = _alteracao_alvo(conn, e.id, alteracao, quando, "Atualização de cotas (registrada pelo Claude)")
        repo.salvar_movimento(conn, alvo, s.id, "participacao", data=quando, percentual=percentual, cotas=cotas,
                              capital=capital)
    return _feito(f"Participação de {s.nome} na {e.nome} atualizada.")


@ferramenta(anotacoes=_GRAVA)
def registrar_alteracao_contratual(
    empresa: str,
    numero: int,
    data: str,
    capital_social: float | None = None,
    quantidade_cotas: float | None = None,
    descricao: str = "",
    razao_social: str | None = None,
    entradas: list[dict] | None = None,
    saidas: list[str] | None = None,
    participacoes: list[dict] | None = None,
) -> dict:
    """Registra UMA alteração contratual com tudo o que ela trouxe — é o jeito
    certo de lançar um contrato. numero é o da alteração no contrato; capital
    e cotas são os da empresa depois dela (vazios = os de antes).

    entradas: [{"socio": nome/CPF/id, "percentual": 10, "cotas": 1000,
    "capital": 1000, "data": opcional}] — sócios já cadastrados (use
    cadastrar_socio antes). saidas: [nome/CPF/id]. participacoes: quem
    continua com outra participação, no mesmo formato das entradas.
    Tudo ou nada: se um item não puder ser gravado, a alteração não fica."""
    e = _achar_empresa(empresa)
    quando = _data(data)
    def com_valores(tipo: str, item) -> tuple:
        if not isinstance(item, dict):
            raise ToolError(f"Cada item de {tipo}s é um objeto: {{\"socio\": ..., \"percentual\": ...}}.")
        extra = {"percentual": item.get("percentual"), "cotas": item.get("cotas"), "capital": item.get("capital")}
        return tipo, _achar_socio(str(item.get("socio", ""))), extra, _data(item["data"]) if item.get("data") else None

    # Tudo conferido antes de gravar qualquer coisa.
    itens = (
        [com_valores("entrada", x) for x in entradas or []]
        + [com_valores("participacao", x) for x in participacoes or []]
        + [("saida", _achar_socio(str(x.get("socio", "") if isinstance(x, dict) else x)), {}, None)
           for x in saidas or []]
    )
    with _Gravando() as conn:
        if repo.numero_alteracao_em_uso(conn, e.id, numero):
            raise ToolError(f"A {e.nome} já tem a alteração contratual Nº {numero}. Use editar_alteracao_contratual.")
        estado = repo.estado_atual_empresa(conn, e.id)
        nova = repo.salvar_alteracao(conn, AlteracaoContratual(
            None, e.id, numero, quando, razao_social or estado["nome"],
            capital_social if capital_social is not None else estado["capital_social"],
            quantidade_cotas if quantidade_cotas is not None else estado["quantidade_cotas"], descricao,
        ))
        try:
            for tipo, socio, extra, quando_item in itens:
                repo.salvar_movimento(conn, nova, socio.id, tipo, data=quando_item, **extra)
        except Exception as erro:
            # Tudo ou nada: a alteração recém-criada sai, qualquer que seja o erro.
            conn.rollback()
            repo.excluir_alteracao(conn, nova)
            if isinstance(erro, (ValueError, ToolError)):
                raise ToolError(f"Nada foi gravado: {erro}") from erro
            raise
    return _feito(f"Alteração contratual Nº {numero} da {e.nome} registrada com {len(itens)} movimento(s).",
                  alteracao_numero=numero)


@ferramenta(anotacoes=_GRAVA)
def editar_alteracao_contratual(
    empresa: str,
    numero: int,
    novo_numero: int | None = None,
    data: str | None = None,
    capital_social: float | None = None,
    quantidade_cotas: float | None = None,
    descricao: str | None = None,
    razao_social: str | None = None,
) -> dict:
    """Corrige os dados de uma alteração contratual (só os informados).
    Mudar a data leva junto as entradas e saídas dela; as outras alterações
    continuam com o que registraram."""
    e = _achar_empresa(empresa)
    with _Gravando() as conn:
        a = _alteracao(e.id, numero)
        for campo, valor in (("numero", novo_numero), ("data", _data(data) if data else None),
                             ("capital_social", capital_social), ("quantidade_cotas", quantidade_cotas),
                             ("descricao", descricao), ("nome_empresa", razao_social)):
            if valor is not None:
                setattr(a, campo, valor)
        repo.salvar_alteracao(conn, a)
    return _feito(f"Alteração Nº {a.numero} da {e.nome} atualizada.")


@ferramenta(anotacoes=_GRAVA)
def definir_valor_da_cota(empresa: str, valor: float) -> dict:
    """Valor nominal de UMA cota da empresa (R$ 1,00 na maioria)."""
    e = _achar_empresa(empresa)
    with _Gravando() as conn:
        repo.definir_valor_da_cota(conn, e.id, valor)
    return _feito(f"Valor da cota da {e.nome}: R$ {valor}.")


@ferramenta(anotacoes=_GRAVA)
def trancar_alteracao_contratual(empresa: str, numero: int, trancar: bool = True) -> dict:
    """Tranca (ou destranca, com trancar=false) uma alteração contratual."""
    e = _achar_empresa(empresa)
    with _Gravando() as conn:
        alteracao = _alteracao(e.id, numero)
        (repo.fechar_alteracao if trancar else repo.reabrir_alteracao)(conn, alteracao.id)
    return _feito(f"Alteração nº {numero} {'trancada' if trancar else 'destrancada'}.")


# -- distribuição e movimentações --


@ferramenta(anotacoes=_GRAVA)
def lancar_distribuicao(empresa: str, ano: int, socio: str, valor: float, pro_labore: float = 0.0,
                        irrf: float = 0.0) -> dict:
    """Lança (ou substitui) o lucro distribuído no ano a um sócio, com
    pró-labore e IRRF."""
    e, s = _achar_empresa(empresa), _achar_socio(socio)
    with _Gravando() as conn:
        repo.salvar_distribuicao(conn, e.id, ano, s.id, valor, pro_labore, irrf)
    return _feito(f"Distribuição de {ano} de {s.nome} na {e.nome} lançada.")


@ferramenta(anotacoes=_GRAVA)
def lancar_distribuicao_trimestral(empresa: str, ano: int, trimestre: int, socio: str, valor: float,
                                   pro_labore: float = 0.0, irrf: float = 0.0) -> dict:
    """Lança o valor de um trimestre (1 a 4); o anual passa a ser a soma dos
    trimestres, como na tela."""
    if trimestre not in (1, 2, 3, 4):
        raise ToolError("trimestre vai de 1 a 4.")
    e, s = _achar_empresa(empresa), _achar_socio(socio)
    with _Gravando() as conn:
        repo.salvar_distribuicao_trimestral(conn, e.id, ano, trimestre, s.id, valor, pro_labore, irrf)
    return _feito(f"{trimestre}º trimestre de {ano} de {s.nome} na {e.nome} lançado.")


@ferramenta(anotacoes=_GRAVA)
def lancar_movimentacao(empresa: str, socio: str, tipo: str, valor: float, data: str) -> dict:
    """Lança uma movimentação: "Empréstimo da empresa ao sócio",
    "Empréstimo do sócio à empresa", "Adiantamento de lucro" ou
    "Devolução de capital"."""
    e, s = _achar_empresa(empresa), _achar_socio(socio)
    chave = _tipo_movimentacao(tipo)
    with _Gravando() as conn:
        novo = repo.salvar_movimentacao(conn, Movimentacao(None, e.id, s.id, chave, valor, _data(data)))
    return _feito(f"{TIPOS_MOVIMENTACAO_LABEL[chave]} de {s.nome} lançado.", movimentacao_id=novo)


@ferramenta(anotacoes=_GRAVA)
def trancar_periodo(empresa: str, ano: int, trancar: bool = True) -> dict:
    """Tranca (ou destranca, com trancar=false) o ano da empresa: trancado,
    ninguém altera distribuição, movimentação nem quadro daquele ano."""
    e = _achar_empresa(empresa)
    with _Gravando() as conn:
        (repo.fechar_periodo if trancar else repo.reabrir_periodo)(conn, e.id, ano)
    return _feito(f"{ano} da {e.nome} {'trancado' if trancar else 'destrancado'}.")


# -- correções finas e exclusão --
#
# Excluir é definitivo (o backup da sessão é a rede de segurança). As que
# levam muita coisa junto (empresa, alteração) primeiro só mostram o que
# vai sair; apagam de fato com confirmar=true, depois de a pessoa concordar.


def _vinculo_do_socio(empresa_id: int, socio_id: int, data_entrada: str | None):
    """A participação do sócio na empresa: a que começou em data_entrada,
    ou — sem ela — a vigente (ou a mais recente, se ele já saiu)."""
    vinculos = [v for v in repo.listar_vinculos_empresa(conexao_escrita(), empresa_id) if v.socio_id == socio_id]
    if not vinculos:
        raise ToolError("Este sócio nunca esteve no quadro desta empresa.")
    if data_entrada:
        quando = _data(data_entrada)
        achados = [v for v in vinculos if v.data_entrada == quando]
        if not achados:
            datas = ", ".join(v.data_entrada for v in vinculos)
            raise ToolError(f"Não há participação começando em {quando}. Começos registrados: {datas}.")
        return achados[-1]
    ativos = [v for v in vinculos if v.data_saida is None]
    return (ativos or sorted(vinculos, key=lambda v: (v.data_entrada, v.id)))[-1]


@ferramenta(anotacoes=_GRAVA)
def corrigir_participacao(empresa: str, socio: str, data_entrada_atual: str | None = None,
                          percentual: float | None = None, cotas: float | None = None, capital: float | None = None,
                          data_entrada: str | None = None, data_saida: str | None = None,
                          desfazer_saida: bool = False, observacao: str | None = None) -> dict:
    """Corrige uma participação já registrada no quadro (como "Editar" na
    aba Sócios): % do capital, cotas, capital, datas, observação.
    data_entrada_atual escolhe qual participação (sem ela, a vigente).
    desfazer_saida=true volta o sócio a ativo. Participação que veio de uma
    alteração contratual é corrigida nela, e só nela."""
    e, s = _achar_empresa(empresa), _achar_socio(socio)
    with _Gravando() as conn:
        v = _vinculo_do_socio(e.id, s.id, data_entrada_atual)
        for campo, valor in (("percentual_capital", percentual), ("quantidade_cotas", cotas),
                             ("valor_capital", capital), ("observacao", observacao)):
            if valor is not None:
                setattr(v, campo, valor)
        if data_entrada:
            v.data_entrada = _data(data_entrada)
        if desfazer_saida:
            v.data_saida, v.alteracao_saida_id = None, None
        elif data_saida:
            v.data_saida = _data(data_saida)
        repo.salvar_vinculo(conn, v)
    return _feito(f"Participação de {s.nome} na {e.nome} corrigida.")


@ferramenta(anotacoes=_EXCLUI)
def excluir_participacao(empresa: str, socio: str, data_entrada: str | None = None) -> dict:
    """Apaga do quadro uma participação lançada por engano (não é a saída
    do sócio — para isso, registrar_saida_de_socio). data_entrada escolhe
    qual; sem ela, a vigente. Se veio de uma alteração contratual, sai dela."""
    e, s = _achar_empresa(empresa), _achar_socio(socio)
    with _Gravando() as conn:
        v = _vinculo_do_socio(e.id, s.id, data_entrada)
        repo.excluir_vinculo(conn, v.id)
    return _feito(f"Participação de {s.nome} na {e.nome} (desde {v.data_entrada}) excluída.")


def _movimento_na_alteracao(conn, alteracao, socio) -> dict:
    movimento = repo._movimento(conn, alteracao.id, socio.id)
    if movimento is None:
        raise ToolError(f"A alteração Nº {alteracao.numero} não registra nada de {socio.nome}.")
    return movimento


@ferramenta(anotacoes=_GRAVA)
def corrigir_movimento_da_alteracao(empresa: str, numero: int, socio: str, data: str | None = None,
                                    percentual: float | None = None, cotas: float | None = None,
                                    capital: float | None = None) -> dict:
    """Corrige o que a alteração Nº numero registrou de um sócio (entrada,
    saída ou participação nova): data e valores. Só mexe nesta alteração."""
    e, s = _achar_empresa(empresa), _achar_socio(socio)
    with _Gravando() as conn:
        a = _alteracao(e.id, numero)
        m = _movimento_na_alteracao(conn, a, s)
        extra = {} if m["tipo"] == "saida" else {
            "percentual": m["percentual_capital"] if percentual is None else percentual,
            "cotas": m["quantidade_cotas"] if cotas is None else cotas,
            "capital": m["valor_capital"] if capital is None else capital,
            "fim": m["fim"], "saida_nesta": bool(m["saida_nesta"]),
        }
        repo.salvar_movimento(conn, a.id, s.id, m["tipo"], data=_data(data) if data else m["data"], **extra)
    return _feito(f"Movimento de {s.nome} na alteração Nº {numero} corrigido.")


@ferramenta(anotacoes=_EXCLUI)
def tirar_socio_da_alteracao(empresa: str, numero: int, socio: str) -> dict:
    """Tira da alteração Nº numero o que ela registrou de um sócio: o quadro
    volta a ser como se ela não tivesse falado dele. As outras não mudam."""
    e, s = _achar_empresa(empresa), _achar_socio(socio)
    with _Gravando() as conn:
        a = _alteracao(e.id, numero)
        _movimento_na_alteracao(conn, a, s)
        repo.remover_movimento(conn, a.id, s.id)
    return _feito(f"{s.nome} tirado da alteração Nº {numero} da {e.nome}.")


@ferramenta(anotacoes=_GRAVA)
def mover_socio_de_alteracao(empresa: str, de_numero: int, para_numero: int, socio: str) -> dict:
    """Passa o que a alteração Nº de_numero registrou de um sócio para a
    alteração Nº para_numero (lançado na alteração errada). A data passa a
    ser a da alteração de destino."""
    e, s = _achar_empresa(empresa), _achar_socio(socio)
    with _Gravando() as conn:
        origem, destino = _alteracao(e.id, de_numero), _alteracao(e.id, para_numero)
        m = _movimento_na_alteracao(conn, origem, s)
        if repo._movimento(conn, destino.id, s.id) is not None:
            raise ToolError(f"A alteração Nº {para_numero} já registra {s.nome}. Corrija lá ou tire de lá antes.")
        valores = {} if m["tipo"] == "saida" else {
            "percentual": m["percentual_capital"], "cotas": m["quantidade_cotas"], "capital": m["valor_capital"]}
        repo.remover_movimento(conn, origem.id, s.id)
        try:
            repo.salvar_movimento(conn, destino.id, s.id, m["tipo"], **valores)
        except Exception:
            # Não coube no destino: volta para onde estava.
            repo.salvar_movimento(conn, origem.id, s.id, m["tipo"], data=m["data"], fim=m["fim"],
                                  saida_nesta=bool(m["saida_nesta"]), **valores)
            raise
    return _feito(f"{s.nome} passado da alteração Nº {de_numero} para a Nº {para_numero}.")


@ferramenta(anotacoes=_EXCLUI)
def excluir_alteracao_contratual(empresa: str, numero: int, confirmar: bool = False) -> dict:
    """Exclui a alteração Nº numero desfazendo o que ela registrou (quem
    entrou por ela deixa de ter entrado, quem saiu volta). Sem confirmar,
    só mostra quem é afetado; com confirmar=true, exclui."""
    e = _achar_empresa(empresa)
    with _Gravando() as conn:
        a = _alteracao(e.id, numero)
        if not confirmar:
            return _limpo({"excluido": False, "alteracao": numero, **repo.resumo_exclusao_alteracao(conn, a.id),
                           "para_excluir": "Confirme com a pessoa e chame de novo com confirmar=true."})
        repo.excluir_alteracao(conn, a.id)
    return _feito(f"Alteração Nº {numero} da {e.nome} excluída.")


@ferramenta(anotacoes=_EXCLUI)
def excluir_empresa(empresa: str, confirmar: bool = False) -> dict:
    """Exclui a empresa com tudo o que é dela (quadro, alterações,
    distribuições, movimentações). Os sócios ficam cadastrados. Sem
    confirmar, só mostra o que vai junto; com confirmar=true, exclui."""
    e = _achar_empresa(empresa)
    with _Gravando() as conn:
        if not confirmar:
            return _limpo({"excluido": False, "empresa": f"{e.numero_chamada} — {e.nome}",
                           "vai_junto": repo.resumo_exclusao_empresa(conn, e.id),
                           "para_excluir": "Confirme com a pessoa e chame de novo com confirmar=true."})
        repo.excluir_empresa(conn, e.id)
    return _feito(f"Empresa {e.numero_chamada} — {e.nome} excluída.")


@ferramenta(anotacoes=_EXCLUI)
def excluir_socio(socio: str) -> dict:
    """Exclui o cadastro de um sócio. Só dá se ele não tiver participação,
    distribuição nem movimentação em nenhuma empresa (apague essas antes)."""
    s = _achar_socio(socio)
    with _Gravando() as conn:
        repo.excluir_socio(conn, s.id)
    return _feito(f"Sócio {s.nome} excluído.")


@ferramenta(anotacoes=_EXCLUI)
def excluir_distribuicao(empresa: str, ano: int, socio: str, trimestre: int | None = None) -> dict:
    """Apaga o lucro distribuído no ano a um sócio — ou só o de um
    trimestre (1 a 4), quando informado."""
    e, s = _achar_empresa(empresa), _achar_socio(socio)
    with _Gravando() as conn:
        if trimestre is None:
            apagou = repo.excluir_distribuicao(conn, e.id, ano, s.id)
        else:
            linha = conn.execute(
                """SELECT id FROM distribuicao_trimestral
                   WHERE empresa_id = %s AND ano_base = %s AND trimestre = %s AND socio_id = %s""",
                (e.id, ano, trimestre, s.id),
            ).fetchone()
            apagou = linha is not None
            if apagou:
                repo.excluir_distribuicao_trimestral(conn, linha["id"])
        if not apagou:
            raise ToolError("Não há distribuição lançada para esse sócio nesse período.")
    quando = f"{trimestre}º trimestre de {ano}" if trimestre else str(ano)
    return _feito(f"Distribuição de {quando} de {s.nome} na {e.nome} excluída.")


def _movimentacao(conn, movimentacao_id: int) -> Movimentacao:
    linha = conn.execute("SELECT * FROM movimentacao WHERE id = %s", (movimentacao_id,)).fetchone()
    if linha is None:
        raise ToolError(f"Não há movimentação com id {movimentacao_id} (os ids aparecem na ficha_socio).")
    return Movimentacao(linha["id"], linha["empresa_id"], linha["socio_id"], linha["tipo"], linha["valor"],
                        linha["data"])


@ferramenta(anotacoes=_GRAVA)
def editar_movimentacao(movimentacao_id: int, tipo: str | None = None, valor: float | None = None,
                        data: str | None = None) -> dict:
    """Corrige uma movimentação lançada (o id aparece na ficha_socio)."""
    with _Gravando() as conn:
        m = _movimentacao(conn, movimentacao_id)
        if tipo:
            m.tipo = _tipo_movimentacao(tipo)
        if valor is not None:
            m.valor = valor
        if data:
            m.data = _data(data)
        repo.salvar_movimentacao(conn, m)
    return _feito(f"Movimentação {movimentacao_id} corrigida.")


@ferramenta(anotacoes=_EXCLUI)
def excluir_movimentacao(movimentacao_id: int) -> dict:
    """Apaga uma movimentação lançada (o id aparece na ficha_socio)."""
    with _Gravando() as conn:
        _movimentacao(conn, movimentacao_id)
        repo.excluir_movimentacao(conn, movimentacao_id)
    return _feito(f"Movimentação {movimentacao_id} excluída.")


# -- importação de planilha --


def _ler_planilha(caminho: str, layout: str | None) -> list[dict]:
    arquivo = Path(caminho).expanduser()
    if not arquivo.is_file():
        raise ToolError(f"Não achei o arquivo {arquivo}. Passe o caminho completo da planilha (.xlsx ou .csv).")
    try:
        if not layout:
            return importar_cadastro(arquivo)
        layouts = repo.listar_layouts_importacao(conexao())
        escolhido = next((l for l in layouts if repo.chave_nome(l.nome) == repo.chave_nome(layout)), None)
        if escolhido is None:
            nomes = ", ".join(l.nome for l in layouts) or "nenhum cadastrado"
            raise ToolError(f'Não há layout "{layout}". Layouts do escritório: {nomes}.')
        return importar_com_layout(arquivo, escolhido)
    except (ValueError, OSError) as erro:
        raise ToolError(f"Não consegui ler a planilha: {erro}") from erro


@ferramenta(anotacoes=_GRAVA)
def importar_planilha(caminho: str, layout: str | None = None, gravar: bool = False) -> dict:
    """Importa uma planilha de cadastro (empresas, sócios, participações e
    distribuição) pelo mesmo caminho da tela de Importação. caminho é o
    arquivo neste computador; layout é o nome de um layout do escritório
    (vazio = o formato padrão do sistema, colunas pelo cabeçalho).

    Primeiro chame com gravar=false: mostra o que vai entrar, sem gravar
    nada. Mostre isso à pessoa e, com o ok dela, chame de novo com
    gravar=true. Sócio que não existe é cadastrado; sócio com nome repetido
    no cadastro (sem CPF que desempate) e linhas em conflito ficam de fora e
    são listados."""
    linhas = _ler_planilha(caminho, layout)
    if not linhas:
        raise ToolError("A planilha não tem linhas para importar (confira o formato ou o layout).")
    for ordem, linha in enumerate(linhas):
        linha["_ordem"] = ordem
    preparado = repo.preparar_importacao_cadastro(conexao(), linhas)
    novos = [p for p in preparado["pendencias"] if p["aviso"].startswith("Nenhum sócio")]
    ambiguos = [p for p in preparado["pendencias"] if p not in novos]
    empresas_novas = sorted({l["empresa_nome"] for l in preparado["prontas"] + preparado["pendencias"]
                             if l.get("empresa_existente") is None})
    resumo = {
        "linhas_na_planilha": len(linhas),
        "linhas_prontas": len(preparado["prontas"]),
        "empresas_novas": empresas_novas,
        "socios_novos": sorted({p["socio_nome"] for p in novos}),
        "ficam_de_fora": [{"linha": p["_ordem"] + 2, "socio": p["socio_nome"], "motivo": p["aviso"]}
                          for p in ambiguos]
                         + [{"linha": c["_ordem"] + 2, "empresa": c["empresa_nome"], "motivo": c["aviso"]}
                            for c in preparado["conflitos"]],
    }
    if not gravar:
        return _limpo({"gravado": False, **resumo,
                       "proximo_passo": "Confirme com a pessoa e chame de novo com gravar=true."})

    with _Gravando() as conn:
        criados: dict[str, int] = {}
        resolvidas = list(preparado["prontas"])
        for pendencia in novos:
            chave = (repo.normalizar_documento(pendencia["socio_cpf"])
                     or repo.normalizar_nome(pendencia["socio_nome"]))
            if chave not in criados:
                criados[chave] = repo.salvar_socio(conn, Socio(
                    None, pendencia["socio_nome"], pendencia["socio_cpf"] or "",
                    pendencia.get("tipo_pessoa") or "fisica",
                ))
            resolvidas.append({**pendencia, "socio_id": criados[chave]})
        resolvidas.sort(key=lambda l: l["_ordem"])
        aplicado = repo.aplicar_importacao_cadastro(conn, resolvidas)
    return _feito("Planilha importada.", **resumo, socios_cadastrados=len(criados),
                  resultado={k: v for k, v in aplicado.items() if isinstance(v, (int, float))})


def main() -> None:
    servidor.run("stdio")


if __name__ == "__main__":
    main()
