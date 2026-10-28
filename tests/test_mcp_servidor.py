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


def test_consultas_sao_so_leitura_e_exclusoes_sao_marcadas():
    ferramentas = {f.name: f for f in asyncio.run(mcp.servidor.list_tools())}
    for nome in ("resumo_geral", "ficha_empresa", "ficha_socio", "consultar_sql", "pontos_de_atencao"):
        assert ferramentas[nome].annotations.read_only_hint
    for nome in ("cadastrar_empresa", "lancar_distribuicao", "importar_planilha"):
        assert not ferramentas[nome].annotations.read_only_hint
    # O Claude avisa antes de usar o que é destrutivo.
    destrutivas = {n for n, f in ferramentas.items() if f.annotations.destructive_hint}
    assert {n for n in ferramentas if "exclu" in n or n.startswith("tirar_")} == destrutivas
    # Usuários e senhas ficam só no programa.
    assert not [n for n in ferramentas if "usuario" in n or "senha" in n]


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


# ---------------------------------------------------------------- gravação --


@pytest.fixture()
def gravacao(monkeypatch):
    """Cada teste começa sem o backup da sessão, para conferir que ele sai."""
    monkeypatch.setattr(mcp, "_backup_da_sessao", None)
    yield
    from controle_lucros import sessao
    sessao.definir_usuario_atual(None)


def test_cadastrar_e_editar_empresa_com_backup_e_log_do_claude(cenario, conn, gravacao):
    r = mcp.cadastrar_empresa("003", "gama ltda", capital_social=5000, quantidade_cotas=5000)
    assert r["ok"] and r["backup_antes_das_gravacoes"].endswith(".json")
    assert mcp.ficha_empresa("003")["nome"] == "GAMA LTDA"
    mcp.editar_empresa("003", cnpj="12.345.678/0001-90")
    assert mcp.ficha_empresa("003")["cnpj"] == "12.345.678/0001-90"
    autores = {r[0] for r in conn.execute(
        "SELECT usuario_nome FROM log_atividade WHERE entidade = 'empresa' AND detalhes LIKE 'GAMA%'").fetchall()}
    assert autores == {"Claude (assistente)"}
    with pytest.raises(ToolError, match="Já existe"):
        mcp.cadastrar_empresa("003", "outra")


def test_socio_quadro_e_distribuicao(cenario, gravacao):
    novo = mcp.cadastrar_socio("caio", "529.982.247-25")["socio_id"]
    mcp.incluir_socio_na_empresa("001", str(novo), 10, 100, "01/01/2024")
    nomes = {q["nome"] for q in mcp.ficha_empresa("001")["quadro_societario"]}
    assert "CAIO" in nomes
    mcp.alterar_participacao("001", "caio", 20, 200, "2024-06-01")
    mcp.lancar_distribuicao("001", 2024, "caio", 500, pro_labore=100)
    assert mcp.ficha_socio("caio")["total_recebido"] == 500
    mcp.registrar_saida_de_socio("001", "caio", "2024-12-31")
    assert "CAIO" not in {q["nome"] for q in mcp.ficha_empresa("001")["quadro_societario"]}
    with pytest.raises(ToolError, match="não está no quadro"):
        mcp.registrar_saida_de_socio("001", "caio", "2025-01-10")


def test_regras_do_programa_valem_para_o_claude(cenario, gravacao):
    with pytest.raises(ToolError, match="CPF"):
        mcp.cadastrar_socio("outra ana", "123.456.789-09")  # CPF da ANA
    mcp.trancar_periodo("001", 2024)
    with pytest.raises(ToolError):
        mcp.lancar_distribuicao("001", 2024, "ana", 1)
    mcp.trancar_periodo("001", 2024, trancar=False)
    mcp.lancar_distribuicao("001", 2024, "ana", 1)
    with pytest.raises(ToolError, match="Data inválida"):
        mcp.lancar_movimentacao("001", "ana", "Adiantamento de lucro", 10, "31-02-2024")
    r = mcp.lancar_movimentacao("001", "ana", "adiantamento de lucro", 10, "2024-02-10")
    assert any(m["id"] == r["movimentacao_id"] for m in mcp.ficha_socio("ana")["movimentacoes"])


def test_importar_planilha_mostra_antes_e_grava_depois(cenario, conn, gravacao, tmp_path):
    planilha = tmp_path / "importar.csv"
    planilha.write_text(
        "Nº empresa;Empresa;Sócio;CPF/CNPJ do sócio;% capital;Cotas do sócio;Data de entrada;Ano;Valor distribuído\n"
        "010;Delta;Duda;;100;1000;2023-01-01;2024;3000\n",
        encoding="utf-8",
    )
    previa = mcp.importar_planilha(str(planilha))
    assert previa["gravado"] is False
    assert previa["empresas_novas"] == ["DELTA"] and previa["socios_novos"] == ["DUDA"]
    assert conn.execute("SELECT COUNT(*) FROM empresa").fetchone()[0] == 2  # nada gravado

    feito = mcp.importar_planilha(str(planilha), gravar=True)
    assert feito["ok"] and feito["socios_cadastrados"] == 1
    assert mcp.ficha_empresa("010")["distribuicao_por_ano"][0]["total"] == 3000
    with pytest.raises(ToolError, match="Não achei o arquivo"):
        mcp.importar_planilha(str(tmp_path / "nao_existe.xlsx"))


# ------------------------------------------------- alteração contratual inteira --


def test_registrar_alteracao_inteira_e_uma_so(cenario, gravacao):
    mcp.cadastrar_socio("caio", "529.982.247-25")
    mcp.cadastrar_socio("dora", "111.444.777-35")
    r = mcp.registrar_alteracao_contratual(
        "001", 5, "2025-04-01", capital_social=2000, quantidade_cotas=2000, descricao="Entrada de dois",
        entradas=[{"socio": "caio", "percentual": 25, "cotas": 500}, {"socio": "dora", "percentual": 25, "cotas": 500}],
        saidas=["bia"],
        participacoes=[{"socio": "ana", "percentual": 50, "cotas": 1000}],
    )
    assert r["ok"]
    ficha = mcp.ficha_alteracao_contratual("001", 5)
    assert ficha["capital_social"] == 2000
    assert {(m["socio"], m["tipo"]) for m in ficha["movimentos"]} == {
        ("CAIO", "Entrou"), ("DORA", "Entrou"), ("BIA", "Saiu"), ("ANA", "Participação nova")}
    assert {q["socio"] for q in ficha["quadro_depois"]} == {"ANA", "CAIO", "DORA"}
    assert [a["numero"] for a in mcp.ficha_empresa("001")["alteracoes_contratuais"]] == [5]


def test_alteracao_inteira_e_tudo_ou_nada(cenario, gravacao):
    mcp.cadastrar_socio("caio", "529.982.247-25")
    mcp.cadastrar_socio("dora", "111.444.777-35")
    # A entrada do CAIO é válida; a participação nova da DORA, que não é
    # sócia, não é — e leva a alteração inteira junto.
    with pytest.raises(ToolError, match="Nada foi gravado.*não é sócio"):
        mcp.registrar_alteracao_contratual("001", 6, "2025-04-01",
                                           entradas=[{"socio": "caio", "percentual": 10, "cotas": 100}],
                                           participacoes=[{"socio": "dora", "percentual": 1}])
    assert mcp.ficha_empresa("001")["alteracoes_contratuais"] == []
    assert "CAIO" not in {q["nome"] for q in mcp.ficha_empresa("001")["quadro_societario"]}


def test_socio_por_socio_no_mesmo_dia_cai_na_mesma_alteracao(cenario, gravacao):
    for nome, cpf in (("caio", "529.982.247-25"), ("dora", "111.444.777-35")):
        mcp.cadastrar_socio(nome, cpf)
        mcp.incluir_socio_na_empresa("001", nome, 10, 100, "2026-02-01")
    mcp.registrar_saida_de_socio("001", "bia", "2026-02-01")
    (alteracao,) = mcp.ficha_empresa("001")["alteracoes_contratuais"]
    assert len(mcp.ficha_alteracao_contratual("001", alteracao["numero"])["movimentos"]) == 3


def test_editar_alteracao_leva_a_data_junto(cenario, gravacao):
    mcp.registrar_alteracao_contratual("001", 5, "2025-04-01", saidas=["bia"])
    mcp.editar_alteracao_contratual("001", 5, data="2025-09-01", capital_social=3000)
    ficha = mcp.ficha_alteracao_contratual("001", 5)
    assert ficha["data"] == "2025-09-01" and ficha["capital_social"] == 3000
    assert ficha["movimentos"][0]["data"] == "2025-09-01"


def test_alteracao_inteira_desfaz_com_qualquer_erro(cenario, gravacao, monkeypatch):
    mcp.cadastrar_socio("caio", "529.982.247-25")
    with pytest.raises(ToolError, match="objeto"):
        mcp.registrar_alteracao_contratual("001", 7, "2025-04-01", entradas=["caio"])
    original = mcp.repo.salvar_movimento

    def falha_no_segundo(conn, alteracao_id, socio_id, tipo, **kwargs):
        if tipo == "saida":
            raise RuntimeError("conexão caiu")
        return original(conn, alteracao_id, socio_id, tipo, **kwargs)

    monkeypatch.setattr(mcp.repo, "salvar_movimento", falha_no_segundo)
    with pytest.raises(RuntimeError):
        mcp.registrar_alteracao_contratual("001", 7, "2025-04-01",
                                           entradas=[{"socio": "caio", "percentual": 10}], saidas=["bia"])
    assert mcp.ficha_empresa("001")["alteracoes_contratuais"] == []


# ------------------------------------------------------ corrigir e excluir --


def test_excluir_empresa_mostra_antes_e_so_apaga_confirmado(cenario, gravacao):
    previa = mcp.excluir_empresa("002")
    assert previa["excluido"] is False and previa["vai_junto"]
    assert mcp.ficha_empresa("002")
    mcp.excluir_empresa("002", confirmar=True)
    with pytest.raises(ToolError):
        mcp.ficha_empresa("002")
    assert mcp.ficha_socio("ana")  # o sócio fica


def test_excluir_alteracao_mostra_antes_e_desfaz(cenario, gravacao):
    mcp.cadastrar_socio("caio", "529.982.247-25")
    mcp.registrar_alteracao_contratual("001", 5, "2025-04-01",
                                       entradas=[{"socio": "caio", "percentual": 10, "cotas": 100}])
    assert mcp.excluir_alteracao_contratual("001", 5)["entradas"] == ["CAIO"]
    assert [a["numero"] for a in mcp.ficha_empresa("001")["alteracoes_contratuais"]] == [5]
    mcp.excluir_alteracao_contratual("001", 5, confirmar=True)
    assert mcp.ficha_empresa("001")["alteracoes_contratuais"] == []
    assert "CAIO" not in {q["nome"] for q in mcp.ficha_empresa("001")["quadro_societario"]}


def test_corrigir_tirar_e_mover_movimento_entre_alteracoes(cenario, gravacao):
    mcp.cadastrar_socio("caio", "529.982.247-25")
    mcp.registrar_alteracao_contratual("001", 5, "2025-04-01",
                                       entradas=[{"socio": "caio", "percentual": 10, "cotas": 100}])
    mcp.registrar_alteracao_contratual("001", 6, "2025-08-01", saidas=["bia"])
    mcp.corrigir_movimento_da_alteracao("001", 5, "caio", percentual=12)
    (mov,) = mcp.ficha_alteracao_contratual("001", 5)["movimentos"]
    assert mov["percentual"] == 12

    mcp.mover_socio_de_alteracao("001", 5, 6, "caio")
    assert mcp.ficha_alteracao_contratual("001", 5)["movimentos"] == []
    assert {m["socio"] for m in mcp.ficha_alteracao_contratual("001", 6)["movimentos"]} == {"BIA", "CAIO"}

    mcp.tirar_socio_da_alteracao("001", 6, "bia")
    assert "BIA" in {q["nome"] for q in mcp.ficha_empresa("001")["quadro_societario"]}


def test_corrigir_e_excluir_participacao(cenario, conn, gravacao):
    mcp.corrigir_participacao("001", "bia", percentual=40, observacao="conferido")
    vinculo = next(v for v in repo.listar_vinculos_empresa(conn, cenario["acme"]) if v.percentual_capital == 40)
    assert vinculo.observacao == "conferido"
    mcp.registrar_saida_de_socio("001", "bia", "2025-02-01")
    mcp.corrigir_participacao("001", "bia", desfazer_saida=True)
    assert "BIA" in {q["nome"] for q in mcp.ficha_empresa("001")["quadro_societario"]}
    mcp.excluir_participacao("001", "bia")
    assert "BIA" not in {q["nome"] for q in mcp.ficha_empresa("001")["quadro_societario"]}


def test_excluir_distribuicao_movimentacao_e_socio(cenario, gravacao):
    mcp.excluir_distribuicao("001", 2024, "bia")
    with pytest.raises(ToolError, match="Não há distribuição"):
        mcp.excluir_distribuicao("001", 2024, "bia")
    (mov,) = mcp.ficha_socio("ana")["movimentacoes"]
    mcp.editar_movimentacao(mov["id"], valor=800)
    assert mcp.ficha_socio("ana")["movimentacoes"][0]["valor"] == 800
    mcp.excluir_movimentacao(mov["id"])
    assert mcp.ficha_socio("ana")["movimentacoes"] == []
    with pytest.raises(ToolError, match="Não é possível excluir"):
        mcp.excluir_socio("ana")
    mcp.cadastrar_socio("caio", "529.982.247-25")
    mcp.excluir_socio("caio")
    with pytest.raises(ToolError):
        mcp.ficha_socio("caio")
