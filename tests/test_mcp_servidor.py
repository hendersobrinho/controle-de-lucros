"""Servidor MCP: o que o Claude consegue ler — e o que não consegue."""
import asyncio

import pytest

from controle_lucros import mcp_servidor as mcp
from controle_lucros import repositories as repo
from controle_lucros.models import Empresa, Movimentacao, Socio
from mcp.server.mcpserver.exceptions import ToolError


@pytest.fixture()
def cenario(conn, monkeypatch):
    monkeypatch.delenv("CONTROLE_LUCROS_MCP_DOCUMENTOS", raising=False)
    acme = repo.salvar_empresa(conn, Empresa(None, "001", "ACME", "", 1000, 1000))
    beta = repo.salvar_empresa(conn, Empresa(None, "002", "BETA ACME", "", 1000, 1000))
    ana = repo.salvar_socio(conn, Socio(None, "ANA", "123.456.789-09"))
    bia = repo.salvar_socio(conn, Socio(None, "BIA", ""))
    repo.associar_socio_a_empresa(conn, acme, ana, 50, 500, "2020-01-01")
    repo.associar_socio_a_empresa(conn, acme, bia, 50, 500, "2020-01-01")
    repo.associar_socio_a_empresa(conn, beta, ana, 100, 1000, "2020-01-01")
    repo.salvar_distribuicao(conn, acme, 2023, ana, 1000)
    repo.salvar_distribuicao(conn, acme, 2024, ana, 3000, pro_labore=500)
    repo.salvar_distribuicao(conn, acme, 2024, bia, 1000)
    repo.salvar_distribuicao(conn, beta, 2024, ana, 2000)
    repo.salvar_movimentacao(conn, Movimentacao(None, acme, ana, "emprestimo_empresa_para_socio", 700, "2024-05-01"))
    conn.commit()
    return {"acme": acme, "ana": ana}


def chamar(nome, **argumentos):
    return asyncio.run(mcp.servidor.call_tool(nome, argumentos))


def test_todas_as_ferramentas_sao_marcadas_como_so_leitura():
    ferramentas = asyncio.run(mcp.servidor.list_tools())
    assert {f.name for f in ferramentas} >= {"resumo_geral", "ficha_empresa", "ficha_socio", "consultar_sql"}
    assert all(f.annotations.read_only_hint for f in ferramentas)


def test_resumo_geral_abre_no_ultimo_ano(cenario):
    resumo = mcp.resumo_geral()
    assert resumo["periodo"] == [2024, 2024]
    assert resumo["total"] == 6000
    assert resumo["movimentos"] == {"Empréstimo da empresa ao sócio": 700}
    assert resumo["top_socios"][0]["documento"] == "***.456.789-**"


def test_empresa_pelo_codigo_ou_nome_e_ambiguidade_pede_o_codigo(cenario):
    assert mcp.ficha_empresa("001")["nome"] == "ACME"
    assert mcp.ficha_empresa("beta")["codigo"] == "002"
    # Nome igual ganha de nome que só contém o texto.
    assert mcp.ficha_empresa("acme")["codigo"] == "001"
    with pytest.raises(ToolError, match="001 — ACME"):
        mcp.ficha_empresa("ACM")
    with pytest.raises(ToolError, match="Nenhuma empresa"):
        mcp.ficha_empresa("zzz")


def test_so_ano_de_vai_ate_o_ultimo_ano(cenario):
    assert mcp.resumo_geral(ano_de=2023)["periodo"] == [2023, 2024]
    assert mcp.resumo_geral(ano_ate=2023)["periodo"] == [2023, 2023]


def test_distribuicao_classifica_cada_socio(cenario):
    dist = mcp.distribuicao_da_empresa("001", 2024)
    assert dist["total_distribuido"] == 4000
    por_nome = {s["nome"]: s for s in dist["socios"]}
    assert por_nome["ANA"]["classificacao"] == "desproporcional"
    assert por_nome["ANA"]["percentual_distribuido"] == 75
    assert por_nome["ANA"]["emprestimo_recebido"] == 700


def test_ficha_socio_soma_o_que_recebeu_e_mascara_o_cpf(cenario, monkeypatch):
    ficha = mcp.ficha_socio("ana")
    assert ficha["total_recebido"] == 6000
    assert ficha["documento"] == "***.456.789-**"
    assert {e["empresa_nome"] for e in ficha["historico_societario"]} == {"ACME", "BETA ACME"}
    monkeypatch.setenv("CONTROLE_LUCROS_MCP_DOCUMENTOS", "completos")
    assert mcp.ficha_socio(str(cenario["ana"]))["documento"] == "123.456.789-09"


def test_busca_de_socio_pelos_digitos_visiveis_do_cpf_mascarado(cenario):
    assert [s["nome"] for s in mcp.buscar_socios("456.789")] == ["ANA"]
    # Os dígitos escondidos não servem de busca: senão dava para descobri-los
    # tentando.
    assert mcp.buscar_socios("123.456") == []


def test_pontos_de_atencao(cenario):
    pontos = mcp.pontos_de_atencao(2024, 2024)
    assert pontos["quantidade_fora_da_proporcao"] == 2
    sem_pro = {(p["socio"], p["empresa"]): p for p in pontos["lucro_sem_pro_labore"]}
    assert set(sem_pro) == {("BIA", "ACME"), ("ANA", "BETA ACME")}
    assert sem_pro[("BIA", "ACME")]["lucro_nesses_anos"] == 1000
    assert pontos["quantidade_sem_pro_labore"] == 2
    assert pontos["emprestimos_a_socios"] == [{"empresa": "ACME", "total": 700}]


def test_sem_pro_labore_soma_os_anos_como_o_dashboard(cenario, conn):
    pontos = mcp.pontos_de_atencao(2023, 2024)
    ana_acme = next(p for p in pontos["lucro_sem_pro_labore"] if p["socio"] == "ANA" and p["empresa"] == "ACME")
    assert ana_acme["anos_sem_pro_labore"] == [2023]
    assert ana_acme["lucro_nesses_anos"] == 1000 and ana_acme["lucro_no_periodo"] == 4000


def test_consultar_sql_le_sem_arredondar_e_corta_no_limite(cenario):
    r = mcp.consultar_sql("SELECT nome, round(1.0 / 300, 6) AS fatia FROM socio ORDER BY nome;")
    assert r["colunas"] == ["nome", "fatia"]
    assert r["linhas"][0] == ["ANA", 0.003333]
    assert mcp.consultar_sql("SELECT id FROM socio", limite=1)["cortado_no_limite"] is True
    # Ponto e vírgula e palavra reservada dentro de um texto não atrapalham.
    assert mcp.consultar_sql("SELECT nome FROM empresa WHERE nome LIKE '%;usuario%'")["linhas"] == []


@pytest.mark.parametrize("sql,erro", [
    ("DELETE FROM socio", "Só um comando"),
    ("SELECT 1; DELETE FROM socio", "Só um comando"),
    ("WITH x AS (DELETE FROM socio RETURNING id) SELECT id FROM x", "INSERT, UPDATE e DELETE"),
    ("SELECT id INTO copia FROM empresa", "INTO"),
    ("SELECT id FROM empresa FOR UPDATE", "FOR UPDATE"),
    # Tabelas fora da lista, por qualquer caminho.
    ("SELECT login FROM usuario", "usuario"),
    ('SELECT login FROM U&"\\0075suario"', "usuario"),
    ("SELECT login FROM public.usuario", "sem esquema"),
    ("SELECT query_to_xml('select * from usu'||'ario', true, false, '')", "query_to_xml"),
    ("SELECT usename FROM pg_user", "pg_user"),
    # Funções com efeito colateral.
    ("SELECT pg_terminate_backend(pid) FROM pg_stat_activity", "pg_terminate_backend|pg_stat_activity"),
    ("SELECT pg_advisory_lock(1)", "pg_advisory_lock"),
    ("SELECT set_config('default_transaction_read_only', 'off', false)", "set_config"),
    ("SELECT pg_catalog.pg_read_file('postgresql.conf')", "pg_read_file"),
    # CPF por qualquer caminho.
    ("SELECT cpf AS doc FROM socio", "CPF"),
    ("SELECT s.cpf || '' FROM socio s", "CPF"),
    ("SELECT nome FROM socio ORDER BY cpf", "CPF"),
    ("SELECT * FROM socio", r"\*"),
    ("SELECT s.* FROM socio s", r"\*"),
    ("SELECT s FROM socio s", "linha inteira"),
    ("SELECT x.id FROM (SELECT * FROM socio) x", r"\*"),
    ("SELECT coluna_que_nao_existe FROM socio", "does not exist|não existe"),
])
def test_consultar_sql_recusa_o_que_nao_deve(cenario, conn, sql, erro):
    with pytest.raises(ToolError, match=erro):
        mcp.consultar_sql(sql)
    assert conn.execute("SELECT COUNT(*) FROM socio").fetchone()[0] == 2


def test_cpf_por_sql_so_com_documentos_completos(cenario, monkeypatch):
    monkeypatch.setenv("CONTROLE_LUCROS_MCP_DOCUMENTOS", "completos")
    assert mcp.consultar_sql("SELECT cpf FROM socio WHERE nome = 'ANA'")["linhas"] == [["123.456.789-09"]]


def test_esquema_lista_so_o_que_o_sql_pode_ler(cenario):
    esquema = mcp.esquema_do_banco()
    assert "usuario" not in esquema["tabelas"] and "log_atividade" not in esquema["tabelas"]
    assert not any(c.startswith("cpf ") for c in esquema["tabelas"]["socio"])
    assert "sum" in esquema["funcoes_aceitas"]


def test_a_conexao_continua_so_de_leitura(cenario):
    with pytest.raises(Exception, match="read-only"):
        mcp.conexao().execute("UPDATE socio SET nome = nome")


def test_erro_esperado_chega_ao_claude_com_a_explicacao(cenario):
    with pytest.raises(ToolError, match="diga o código"):
        chamar("ficha_empresa", empresa="ACM")
