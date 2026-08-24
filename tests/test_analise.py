import sqlite3

import pytest

from controle_lucros import db, repositories as repo
from controle_lucros.models import Empresa, Socio


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    db.init_schema(connection)
    yield connection
    connection.close()


def _empresa(conn, nome="ACME LTDA", capital_social=10000, quantidade_cotas=1000) -> int:
    return repo.salvar_empresa(
        conn, Empresa(None, "001", nome, "", capital_social, quantidade_cotas)
    )


def _socio(conn, nome, cpf) -> int:
    return repo.salvar_socio(conn, Socio(None, nome, cpf))


def test_classificacao_proporcional_e_desproporcional(conn):
    empresa_id = _empresa(conn)
    s1 = _socio(conn, "Fulano", "111.111.111-11")
    s2 = _socio(conn, "Beltrano", "222.222.222-22")
    repo.associar_socio_a_empresa(conn, empresa_id, s1, 60, 600, "2020-01-01")
    repo.associar_socio_a_empresa(conn, empresa_id, s2, 40, 400, "2020-01-01")

    # distribuição fiel ao percentual de capital (60/40)
    repo.salvar_distribuicao(conn, empresa_id, 2024, s1, 6000)
    repo.salvar_distribuicao(conn, empresa_id, 2024, s2, 4000)

    linhas = repo.linhas_classificadas_empresa_ano(conn, empresa_id, 2024, tolerancia=1)
    assert all(l["classificacao"] == "proporcional" for l in linhas)

    # agora desproporcional: 90/10 quando deveria ser 60/40
    repo.salvar_distribuicao(conn, empresa_id, 2024, s1, 9000)
    repo.salvar_distribuicao(conn, empresa_id, 2024, s2, 1000)
    linhas = repo.linhas_classificadas_empresa_ano(conn, empresa_id, 2024, tolerancia=1)
    fulano = next(l for l in linhas if l["socio_id"] == s1)
    beltrano = next(l for l in linhas if l["socio_id"] == s2)
    assert fulano["classificacao"] == "desproporcional"
    assert beltrano["classificacao"] == "desproporcional"


def test_classificacao_respeita_tolerancia(conn):
    empresa_id = _empresa(conn)
    s1 = _socio(conn, "Fulano", "111.111.111-11")
    s2 = _socio(conn, "Beltrano", "222.222.222-22")
    repo.associar_socio_a_empresa(conn, empresa_id, s1, 60, 600, "2020-01-01")
    repo.associar_socio_a_empresa(conn, empresa_id, s2, 40, 400, "2020-01-01")

    # 63/37 em vez de 60/40 -- divergencia de 3 pontos percentuais
    repo.salvar_distribuicao(conn, empresa_id, 2024, s1, 6300)
    repo.salvar_distribuicao(conn, empresa_id, 2024, s2, 3700)

    linhas_tolerantes = repo.linhas_classificadas_empresa_ano(conn, empresa_id, 2024, tolerancia=5)
    assert all(l["classificacao"] == "proporcional" for l in linhas_tolerantes)

    linhas_estritas = repo.linhas_classificadas_empresa_ano(conn, empresa_id, 2024, tolerancia=1)
    assert all(l["classificacao"] == "desproporcional" for l in linhas_estritas)


def test_classificacao_socio_sem_distribuicao(conn):
    empresa_id = _empresa(conn)
    s1 = _socio(conn, "Fulano", "111.111.111-11")
    s2 = _socio(conn, "Beltrano", "222.222.222-22")
    repo.associar_socio_a_empresa(conn, empresa_id, s1, 60, 600, "2020-01-01")
    repo.associar_socio_a_empresa(conn, empresa_id, s2, 40, 400, "2020-01-01")

    repo.salvar_distribuicao(conn, empresa_id, 2024, s1, 10000)
    # beltrano nao recebeu nada, mas a empresa distribuiu para fulano

    linhas = repo.linhas_classificadas_empresa_ano(conn, empresa_id, 2024, tolerancia=1)
    beltrano = next(l for l in linhas if l["socio_id"] == s2)
    fulano = next(l for l in linhas if l["socio_id"] == s1)
    assert beltrano["classificacao"] == "socio_sem_distribuicao"
    # fulano recebeu 100% do total distribuído, mas seu capital é só 60% -> desproporcional
    assert fulano["classificacao"] == "desproporcional"


def test_classificacao_empresa_sem_distribuicao(conn):
    empresa_id = _empresa(conn)
    s1 = _socio(conn, "Fulano", "111.111.111-11")
    repo.associar_socio_a_empresa(conn, empresa_id, s1, 100, 1000, "2020-01-01")
    # nenhuma distribuicao registrada em 2024

    linhas = repo.linhas_classificadas_empresa_ano(conn, empresa_id, 2024, tolerancia=1)
    assert len(linhas) == 1
    assert linhas[0]["classificacao"] == "empresa_sem_distribuicao"


def test_analise_empresa_periodo_cobre_varios_anos(conn):
    empresa_id = _empresa(conn)
    s1 = _socio(conn, "Fulano", "111.111.111-11")
    repo.associar_socio_a_empresa(conn, empresa_id, s1, 100, 1000, "2020-01-01")
    repo.salvar_distribuicao(conn, empresa_id, 2022, s1, 5000)
    repo.salvar_distribuicao(conn, empresa_id, 2023, s1, 7000)
    # 2024 sem distribuicao

    linhas = repo.analise_empresa_periodo(conn, empresa_id, 2022, 2024, tolerancia=1)
    anos = sorted(l["ano_base"] for l in linhas)
    assert anos == [2022, 2023, 2024]
    classificacoes = {l["ano_base"]: l["classificacao"] for l in linhas}
    assert classificacoes[2022] == "proporcional"
    assert classificacoes[2023] == "proporcional"
    assert classificacoes[2024] == "empresa_sem_distribuicao"


def test_visao_geral_agrega_todas_as_empresas(conn):
    e1 = _empresa(conn, nome="ACME LTDA")
    e2 = _empresa(conn, nome="BETA COMERCIO")

    s1 = _socio(conn, "Fulano", "111.111.111-11")
    s2 = _socio(conn, "Beltrano", "222.222.222-22")

    repo.associar_socio_a_empresa(conn, e1, s1, 50, 500, "2020-01-01")
    repo.associar_socio_a_empresa(conn, e1, s2, 50, 500, "2020-01-01")
    repo.salvar_distribuicao(conn, e1, 2024, s1, 5000)
    repo.salvar_distribuicao(conn, e1, 2024, s2, 5000)  # proporcional

    repo.associar_socio_a_empresa(conn, e2, s1, 100, 1000, "2020-01-01")
    # BETA nao distribuiu nada em 2024

    resultado = repo.visao_geral(conn, 2024, 2024, tolerancia=1)
    assert resultado["total_empresas"] == 2
    assert resultado["empresas_sem_distribuicao"] == ["BETA COMERCIO"]
    assert resultado["total_distribuido"] == 10000
    assert resultado["total_proporcional"] == 10000
    assert resultado["total_desproporcional"] == 0

    resumo_acme = next(r for r in resultado["resumo_empresas"] if r["empresa_nome"] == "ACME LTDA")
    assert resumo_acme["distribuiu_no_periodo"] is True
    assert resumo_acme["socios_desproporcionais"] == 0


def test_visao_geral_soma_emprestimos(conn):
    from controle_lucros.models import Movimentacao

    e1 = _empresa(conn)
    s1 = _socio(conn, "Fulano", "111.111.111-11")
    repo.associar_socio_a_empresa(conn, e1, s1, 100, 1000, "2020-01-01")
    repo.salvar_movimentacao(
        conn, Movimentacao(None, e1, s1, "emprestimo_empresa_para_socio", 3000, "2024-05-01")
    )

    resultado = repo.visao_geral(conn, 2024, 2024, tolerancia=1)
    assert resultado["total_emprestimos"] == 3000


def test_anos_disponiveis(conn):
    empresa_id = _empresa(conn)
    s1 = _socio(conn, "Fulano", "111.111.111-11")
    repo.associar_socio_a_empresa(conn, empresa_id, s1, 100, 1000, "2020-01-01")
    repo.salvar_distribuicao(conn, empresa_id, 2021, s1, 1000)
    repo.salvar_distribuicao(conn, empresa_id, 2023, s1, 2000)

    assert repo.anos_disponiveis(conn) == [2021, 2023]


def test_anos_disponiveis_sem_dados_retorna_ano_atual(conn):
    import datetime as dt

    assert repo.anos_disponiveis(conn) == [dt.date.today().year]


def test_salvar_distribuicao_guarda_pro_labore_e_irrf(conn):
    empresa_id = _empresa(conn)
    s1 = _socio(conn, "Fulano", "111.111.111-11")
    repo.associar_socio_a_empresa(conn, empresa_id, s1, 100, 1000, "2020-01-01")

    repo.salvar_distribuicao(conn, empresa_id, 2024, s1, 10000, pro_labore=3000, irrf=450)
    (dist,) = repo.listar_distribuicoes(conn, empresa_id, 2024)
    assert dist.pro_labore == 3000
    assert dist.irrf == 450

    linhas = repo.panorama_distribuicao_anual(conn, empresa_id, 2024)
    assert linhas[0]["pro_labore"] == 3000
    assert linhas[0]["irrf"] == 450


def test_consistencia_percentual_socios(conn):
    empresa_id = _empresa(conn)
    s1 = _socio(conn, "Fulano", "111.111.111-11")
    s2 = _socio(conn, "Beltrano", "222.222.222-22")
    repo.associar_socio_a_empresa(conn, empresa_id, s1, 60, 600, "2020-01-01")
    repo.associar_socio_a_empresa(conn, empresa_id, s2, 30, 300, "2020-01-01")

    resultado = repo.consistencia_percentual_socios(conn, empresa_id, 2024)
    assert resultado["soma_percentual"] == 90
    assert resultado["diferenca"] == 10


def test_consistencia_percentual_fecha_em_100(conn):
    empresa_id = _empresa(conn)
    s1 = _socio(conn, "Fulano", "111.111.111-11")
    s2 = _socio(conn, "Beltrano", "222.222.222-22")
    repo.associar_socio_a_empresa(conn, empresa_id, s1, 60, 600, "2020-01-01")
    repo.associar_socio_a_empresa(conn, empresa_id, s2, 40, 400, "2020-01-01")

    resultado = repo.consistencia_percentual_socios(conn, empresa_id, 2024)
    assert resultado["diferenca"] == 0


def test_socio_pessoa_juridica(conn):
    from controle_lucros.models import Socio

    socio_id = repo.salvar_socio(conn, Socio(None, "HOLDING XYZ LTDA", "12.345.678/0001-90", tipo_pessoa="juridica"))
    (socio,) = repo.listar_socios(conn)
    assert socio.tipo_pessoa == "juridica"
    assert socio.cpf == "12.345.678/0001-90"


def test_socio_default_e_pessoa_fisica(conn):
    from controle_lucros.models import Socio

    repo.salvar_socio(conn, Socio(None, "Fulano", "111.111.111-11"))
    (socio,) = repo.listar_socios(conn)
    assert socio.tipo_pessoa == "fisica"


def test_listar_movimentacoes_todos_os_tipos(conn):
    from controle_lucros.models import Movimentacao

    empresa_id = _empresa(conn)
    s1 = _socio(conn, "Fulano", "111.111.111-11")
    repo.associar_socio_a_empresa(conn, empresa_id, s1, 100, 1000, "2020-01-01")

    repo.salvar_movimentacao(conn, Movimentacao(None, empresa_id, s1, "emprestimo_empresa_para_socio", 1000, "2024-01-01"))
    repo.salvar_movimentacao(conn, Movimentacao(None, empresa_id, s1, "emprestimo_socio_para_empresa", 2000, "2024-02-01"))
    repo.salvar_movimentacao(conn, Movimentacao(None, empresa_id, s1, "adiantamento_lucro", 500, "2024-03-01"))
    repo.salvar_movimentacao(conn, Movimentacao(None, empresa_id, s1, "devolucao_capital", 300, "2024-04-01"))

    todos = repo.listar_movimentacoes(conn, empresa_id, s1, 2024)
    assert len(todos) == 4

    so_emprestimos = repo.listar_movimentacoes(conn, empresa_id, s1, 2024, tipo="emprestimo_empresa_para_socio")
    assert len(so_emprestimos) == 1
