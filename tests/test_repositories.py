import sqlite3

import pytest

from controle_lucros import db, repositories as repo
from controle_lucros.models import AlteracaoContratual, Empresa, Movimentacao, Socio, VinculoSocietario


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    db.init_schema(connection)
    yield connection
    connection.close()


def _nova_empresa(conn, **overrides) -> int:
    dados = dict(
        id=None,
        numero_chamada="001",
        nome="ACME LTDA",
        cnpj="00000000000100",
        capital_social=10000,
        quantidade_cotas=1000,
    )
    dados.update(overrides)
    return repo.salvar_empresa(conn, Empresa(**dados))


def test_crud_empresa(conn):
    empresa_id = _nova_empresa(conn)
    (empresa,) = repo.listar_empresas(conn)
    assert empresa.id == empresa_id
    assert empresa.numero_chamada == "001"

    empresa.nome = "ACME COMERCIO LTDA"
    repo.salvar_empresa(conn, empresa)
    (empresa,) = repo.listar_empresas(conn)
    assert empresa.nome == "ACME COMERCIO LTDA"

    repo.excluir_empresa(conn, empresa_id)
    assert repo.listar_empresas(conn) == []


def test_cnpj_alfanumerico_e_aceito(conn):
    empresa_id = _nova_empresa(conn, cnpj="12ABC34501DE35")
    empresa = repo.buscar_empresa(conn, empresa_id)
    assert empresa.cnpj == "12ABC34501DE35"


def test_numeracao_sequencial_de_alteracoes(conn):
    empresa_id = _nova_empresa(conn)
    assert repo.proximo_numero_alteracao(conn, empresa_id) == 1

    id1 = repo.salvar_alteracao(
        conn,
        AlteracaoContratual(None, empresa_id, 1, "2024-01-10", "ACME LTDA", 10000, 1000, "Fundação"),
    )
    assert repo.proximo_numero_alteracao(conn, empresa_id) == 2

    repo.salvar_alteracao(
        conn,
        AlteracaoContratual(None, empresa_id, 2, "2024-06-01", "ACME LTDA", 20000, 2000, "Aumento de capital"),
    )
    alteracoes = repo.listar_alteracoes(conn, empresa_id)
    assert [a.numero for a in alteracoes] == [1, 2]
    assert alteracoes[0].id == id1


def test_estado_atual_empresa_usa_ultima_alteracao(conn):
    empresa_id = _nova_empresa(conn, nome="ACME LTDA", capital_social=10000, quantidade_cotas=1000)

    assert repo.estado_atual_empresa(conn, empresa_id) == {
        "nome": "ACME LTDA",
        "capital_social": 10000,
        "quantidade_cotas": 1000,
    }

    repo.salvar_alteracao(
        conn,
        AlteracaoContratual(None, empresa_id, 1, "2024-06-01", "ACME COMERCIO LTDA", 50000, 5000, "Aumento"),
    )
    estado = repo.estado_atual_empresa(conn, empresa_id)
    assert estado["nome"] == "ACME COMERCIO LTDA"
    assert estado["capital_social"] == 50000


def test_alteracao_fechada_nao_pode_ser_editada(conn):
    empresa_id = _nova_empresa(conn)
    alteracao_id = repo.salvar_alteracao(
        conn, AlteracaoContratual(None, empresa_id, 1, "2024-01-10", "ACME LTDA", 10000, 1000, "Fundação")
    )
    repo.fechar_alteracao(conn, alteracao_id)

    alteracao = repo.buscar_alteracao(conn, alteracao_id)
    assert alteracao.fechada is True

    with pytest.raises(ValueError):
        repo.salvar_alteracao(
            conn,
            AlteracaoContratual(alteracao_id, empresa_id, 1, "2024-02-01", "OUTRO NOME", 10000, 1000, "Tentativa"),
        )

    with pytest.raises(ValueError):
        repo.excluir_alteracao(conn, alteracao_id)

    repo.reabrir_alteracao(conn, alteracao_id)
    assert repo.buscar_alteracao(conn, alteracao_id).fechada is False
    repo.salvar_alteracao(
        conn,
        AlteracaoContratual(alteracao_id, empresa_id, 1, "2024-02-01", "OUTRO NOME", 10000, 1000, "Agora sim"),
    )
    assert repo.buscar_alteracao(conn, alteracao_id).nome_empresa == "OUTRO NOME"


def test_vinculo_nao_pode_ser_criado_em_alteracao_fechada(conn):
    empresa_id = _nova_empresa(conn)
    socio_id = repo.salvar_socio(conn, Socio(None, "Fulano", "111.111.111-11"))
    alteracao_id = repo.salvar_alteracao(
        conn, AlteracaoContratual(None, empresa_id, 1, "2024-01-10", "ACME LTDA", 10000, 1000, "Fundação")
    )
    repo.fechar_alteracao(conn, alteracao_id)

    with pytest.raises(ValueError):
        repo.salvar_vinculo(
            conn,
            VinculoSocietario(
                None, empresa_id, socio_id, 100, 1000, "2024-01-10", None, alteracao_entrada_id=alteracao_id
            ),
        )


def test_vinculo_entrada_e_saida_rastreiam_alteracao(conn):
    empresa_id = _nova_empresa(conn)
    socio_id = repo.salvar_socio(conn, Socio(None, "Fulano", "111.111.111-11"))
    alt1 = repo.salvar_alteracao(
        conn, AlteracaoContratual(None, empresa_id, 1, "2024-01-10", "ACME LTDA", 10000, 1000, "Fundação")
    )
    vinculo_id = repo.salvar_vinculo(
        conn,
        VinculoSocietario(
            None, empresa_id, socio_id, 100, 1000, "2024-01-10", None, alteracao_entrada_id=alt1
        ),
    )

    alt2 = repo.salvar_alteracao(
        conn, AlteracaoContratual(None, empresa_id, 2, "2024-06-01", "ACME LTDA", 10000, 1000, "Saída de sócio")
    )
    repo.encerrar_vinculo(conn, vinculo_id, "2024-06-01", alt2)

    vinculo = repo.listar_vinculos_empresa(conn, empresa_id)[0]
    assert vinculo.alteracao_entrada_id == alt1
    assert vinculo.alteracao_saida_id == alt2

    movimentados_alt1 = repo.vinculos_movimentados_na_alteracao(conn, alt1)
    movimentados_alt2 = repo.vinculos_movimentados_na_alteracao(conn, alt2)
    assert [v.id for v in movimentados_alt1] == [vinculo_id]
    assert [v.id for v in movimentados_alt2] == [vinculo_id]


def test_associar_socio_a_empresa_gera_alteracao_contratual(conn):
    empresa_id = _nova_empresa(conn, capital_social=10000, quantidade_cotas=1000)
    socio_id = repo.salvar_socio(conn, Socio(None, "Fulano", "111.111.111-11"))

    assert repo.listar_alteracoes(conn, empresa_id) == []

    vinculo_id = repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 50, 500, "2024-03-01")

    alteracoes = repo.listar_alteracoes(conn, empresa_id)
    assert len(alteracoes) == 1
    assert alteracoes[0].numero == 1
    assert alteracoes[0].fechada is False

    vinculo = repo.listar_vinculos_socio(conn, socio_id)[0]
    assert vinculo.id == vinculo_id
    assert vinculo.alteracao_entrada_id == alteracoes[0].id
    assert vinculo.data_saida is None


def test_encerrar_vinculo_pela_aba_de_socios_gera_alteracao(conn):
    empresa_id = _nova_empresa(conn, capital_social=10000, quantidade_cotas=1000)
    socio_id = repo.salvar_socio(conn, Socio(None, "Fulano", "111.111.111-11"))
    repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 50, 500, "2024-03-01")

    vinculo = repo.listar_vinculos_socio(conn, socio_id)[0]
    repo.encerrar_vinculo_registrando_alteracao(conn, vinculo, "2024-09-01")

    alteracoes = repo.listar_alteracoes(conn, empresa_id)
    assert len(alteracoes) == 2

    vinculo_atualizado = repo.listar_vinculos_socio(conn, socio_id)[0]
    assert vinculo_atualizado.data_saida == "2024-09-01"
    assert vinculo_atualizado.alteracao_saida_id == alteracoes[1].id


def test_atualizar_cotas_fecha_vinculo_antigo_e_abre_novo(conn):
    empresa_id = _nova_empresa(conn, capital_social=10000, quantidade_cotas=1000)
    socio_id = repo.salvar_socio(conn, Socio(None, "Fulano", "111.111.111-11"))
    repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 50, 500, "2024-03-01")

    vinculo_antigo = repo.listar_vinculos_socio(conn, socio_id)[0]
    repo.atualizar_cotas_vinculo(conn, vinculo_antigo, 70, 700, "2024-07-01")

    vinculos = repo.listar_vinculos_socio(conn, socio_id)
    assert len(vinculos) == 2

    antigo = next(v for v in vinculos if v.id == vinculo_antigo.id)
    assert antigo.data_saida == "2024-07-01"

    novo = next(v for v in vinculos if v.id != vinculo_antigo.id)
    assert novo.quantidade_cotas == 700
    assert novo.percentual_capital == 70
    assert novo.data_saida is None

    assert len(repo.listar_alteracoes(conn, empresa_id)) == 2


def test_valor_participacao_usa_estado_atual_da_empresa(conn):
    empresa_id = _nova_empresa(conn, capital_social=10000, quantidade_cotas=1000)
    socio_id = repo.salvar_socio(conn, Socio(None, "Fulano", "111.111.111-11"))
    repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 50, 500, "2024-03-01")

    vinculo = repo.listar_vinculos_socio(conn, socio_id)[0]
    assert repo.valor_participacao(conn, vinculo) == pytest.approx(5000.0)

    repo.salvar_alteracao(
        conn, AlteracaoContratual(None, empresa_id, 2, "2024-08-01", "ACME LTDA", 20000, 1000, "Aumento de capital")
    )
    assert repo.valor_participacao(conn, vinculo) == pytest.approx(10000.0)


def _empresa_com_dois_socios(conn, percentuais=(60, 40)):
    empresa_id = _nova_empresa(conn, capital_social=10000, quantidade_cotas=1000)
    s1 = repo.salvar_socio(conn, Socio(None, "Fulano", "111.111.111-11"))
    s2 = repo.salvar_socio(conn, Socio(None, "Beltrano", "222.222.222-22"))
    repo.associar_socio_a_empresa(conn, empresa_id, s1, percentuais[0], percentuais[0] * 10, "2020-01-01")
    repo.associar_socio_a_empresa(conn, empresa_id, s2, percentuais[1], percentuais[1] * 10, "2020-01-01")
    return empresa_id, s1, s2


def test_salvar_distribuicao_e_upsert_por_ano(conn):
    empresa_id, s1, _ = _empresa_com_dois_socios(conn)

    repo.salvar_distribuicao(conn, empresa_id, 2024, s1, 6000)
    assert repo.total_distribuido_empresa_ano(conn, empresa_id, 2024) == 6000

    repo.salvar_distribuicao(conn, empresa_id, 2024, s1, 7000)
    distribuicoes = repo.listar_distribuicoes(conn, empresa_id, 2024)
    assert len(distribuicoes) == 1
    assert distribuicoes[0].valor_distribuido == 7000


def test_panorama_distribuicao_anual_calcula_percentual_com_precisao(conn):
    empresa_id, s1, s2 = _empresa_com_dois_socios(conn)
    repo.salvar_distribuicao(conn, empresa_id, 2024, s1, 6000)
    repo.salvar_distribuicao(conn, empresa_id, 2024, s2, 3000)

    linhas = repo.panorama_distribuicao_anual(conn, empresa_id, 2024)
    assert len(linhas) == 2

    fulano = next(l for l in linhas if l["socio_nome"] == "Fulano")
    assert fulano["valor_distribuido"] == 6000
    assert fulano["percentual_distribuido"] == pytest.approx(66.6666666, rel=1e-4)
    assert fulano["percentual_capital"] == 60
    assert fulano["quantidade_cotas"] == 600


def test_panorama_marca_entrada_e_saida_no_ano(conn):
    empresa_id, s1, s2 = _empresa_com_dois_socios(conn)
    vinculo_s2 = repo.listar_vinculos_socio(conn, s2)[0]
    repo.encerrar_vinculo_registrando_alteracao(conn, vinculo_s2, "2024-06-01")

    s3 = repo.salvar_socio(conn, Socio(None, "Ciclano", "333.333.333-33"))
    repo.associar_socio_a_empresa(conn, empresa_id, s3, 20, 200, "2024-08-01")

    linhas = repo.panorama_distribuicao_anual(conn, empresa_id, 2024)
    por_nome = {l["socio_nome"]: l for l in linhas}

    assert por_nome["Fulano"]["entrou_no_ano"] is False
    assert por_nome["Fulano"]["saiu_no_ano"] is False
    assert por_nome["Beltrano"]["saiu_no_ano"] is True
    assert por_nome["Ciclano"]["entrou_no_ano"] is True


def test_movimentacao_de_emprestimo_soma_por_ano(conn):
    empresa_id, s1, _ = _empresa_com_dois_socios(conn)

    repo.salvar_movimentacao(
        conn, Movimentacao(None, empresa_id, s1, "emprestimo_empresa_para_socio", 1000, "2024-03-01")
    )
    repo.salvar_movimentacao(
        conn, Movimentacao(None, empresa_id, s1, "emprestimo_empresa_para_socio", 500, "2024-11-01")
    )
    repo.salvar_movimentacao(
        conn, Movimentacao(None, empresa_id, s1, "emprestimo_empresa_para_socio", 999, "2023-12-01")
    )

    total_2024 = repo.soma_movimentacoes(conn, empresa_id, s1, 2024, "emprestimo_empresa_para_socio")
    assert total_2024 == 1500

    linhas = repo.panorama_distribuicao_anual(conn, empresa_id, 2024)
    fulano = next(l for l in linhas if l["socio_id"] == s1)
    assert fulano["emprestimo_recebido"] == 1500

    entradas = repo.listar_movimentacoes(conn, empresa_id, s1, 2024, "emprestimo_empresa_para_socio")
    assert len(entradas) == 2
    movimentacao_id = entradas[0].id
    repo.excluir_movimentacao(conn, movimentacao_id)
    assert repo.soma_movimentacoes(conn, empresa_id, s1, 2024, "emprestimo_empresa_para_socio") == 500


def test_estado_empresa_no_periodo_sem_alteracoes_usa_fundacao(conn):
    empresa_id = _nova_empresa(conn, capital_social=10000, quantidade_cotas=1000)
    estado = repo.estado_empresa_no_periodo(conn, empresa_id, 2024)
    assert estado == {
        "capital_inicio": 10000,
        "capital_fim": 10000,
        "variacao_capital": 0,
        "cotas_inicio": 1000,
        "cotas_fim": 1000,
        "variacao_cotas": 0,
    }


def test_estado_empresa_no_periodo_detecta_aumento_no_ano(conn):
    empresa_id = _nova_empresa(conn, capital_social=10000, quantidade_cotas=1000)
    repo.salvar_alteracao(
        conn, AlteracaoContratual(None, empresa_id, 1, "2023-06-01", "ACME LTDA", 10000, 1000, "Fundação")
    )
    repo.salvar_alteracao(
        conn, AlteracaoContratual(None, empresa_id, 2, "2024-08-01", "ACME LTDA", 25000, 2500, "Aumento de capital")
    )

    estado_2023 = repo.estado_empresa_no_periodo(conn, empresa_id, 2023)
    assert estado_2023["capital_fim"] == 10000 and estado_2023["variacao_capital"] == 0

    estado_2024 = repo.estado_empresa_no_periodo(conn, empresa_id, 2024)
    assert estado_2024["capital_inicio"] == 10000
    assert estado_2024["capital_fim"] == 25000
    assert estado_2024["variacao_capital"] == 15000
    assert estado_2024["cotas_inicio"] == 1000
    assert estado_2024["cotas_fim"] == 2500
    assert estado_2024["variacao_cotas"] == 1500

    estado_2025 = repo.estado_empresa_no_periodo(conn, empresa_id, 2025)
    assert estado_2025["capital_inicio"] == 25000 and estado_2025["variacao_capital"] == 0


def test_consistencia_cotas_socios_detecta_cotas_nao_redistribuidas(conn):
    empresa_id, s1, s2 = _empresa_com_dois_socios(conn)  # 600 + 400 = 1000 cotas, batendo com a fundação

    consistente = repo.consistencia_cotas_socios(conn, empresa_id, 2024)
    assert consistente == {"cotas_totais_empresa": 1000, "soma_cotas_socios": 1000, "diferenca": 0}

    numero = repo.proximo_numero_alteracao(conn, empresa_id)
    repo.salvar_alteracao(
        conn, AlteracaoContratual(None, empresa_id, numero, "2024-06-01", "ACME LTDA", 25000, 2500, "Aumento de capital")
    )

    divergente = repo.consistencia_cotas_socios(conn, empresa_id, 2024)
    assert divergente == {"cotas_totais_empresa": 2500, "soma_cotas_socios": 1000, "diferenca": 1500}

    vinculo_s1 = repo.listar_vinculos_socio(conn, s1)[0]
    repo.atualizar_cotas_vinculo(conn, vinculo_s1, 60, 1500, "2024-06-01")
    ajustado = repo.consistencia_cotas_socios(conn, empresa_id, 2024)
    assert ajustado == {"cotas_totais_empresa": 2500, "soma_cotas_socios": 1900, "diferenca": 600}


def test_buscar_vinculo(conn):
    empresa_id, s1, _ = _empresa_com_dois_socios(conn)
    vinculo = repo.listar_vinculos_socio(conn, s1)[0]
    encontrado = repo.buscar_vinculo(conn, vinculo.id)
    assert encontrado == vinculo
    assert repo.buscar_vinculo(conn, 999999) is None


def test_atualizar_cotas_no_mesmo_ano_nao_duplica_linha_nem_marca_entrada_saida(conn):
    """Atualizar cotas fecha e reabre o vínculo internamente (para manter
    histórico), mas isso não é um sócio saindo e voltando — o panorama anual
    deve mostrar uma linha só, sem destaque de entrada/saída."""
    empresa_id, s1, s2 = _empresa_com_dois_socios(conn)
    repo.salvar_distribuicao(conn, empresa_id, 2024, s1, 9000)
    repo.salvar_distribuicao(conn, empresa_id, 2024, s2, 6000)

    vinculo_s1 = repo.listar_vinculos_socio(conn, s1)[0]
    repo.atualizar_cotas_vinculo(conn, vinculo_s1, 60, 1500, "2024-06-01")

    linhas = repo.panorama_distribuicao_anual(conn, empresa_id, 2024)
    assert len(linhas) == 2

    fulano = next(l for l in linhas if l["socio_id"] == s1)
    assert fulano["quantidade_cotas"] == 1500
    assert fulano["entrou_no_ano"] is False
    assert fulano["saiu_no_ano"] is False
    assert fulano["data_saida"] is None
    assert fulano["valor_distribuido"] == 9000


def _linha_cadastro(**overrides) -> dict:
    dados = dict(
        numero_chamada="001",
        empresa_nome="ACME LTDA",
        cnpj="00000000000100",
        capital_social=10000,
        quantidade_cotas=1000,
        socio_nome="Fulano de Tal",
        socio_cpf="111.111.111-11",
        tipo_pessoa="fisica",
        percentual_capital=100.0,
        cotas_socio=1000,
        data_entrada="2024-01-01",
    )
    dados.update(overrides)
    return dados


def test_importacao_cadastro_socio_novo_vira_pendencia(conn):
    resultado = repo.preparar_importacao_cadastro(conn, [_linha_cadastro()])
    assert resultado["prontas"] == []
    assert len(resultado["pendencias"]) == 1
    assert resultado["pendencias"][0]["socio_nome"] == "Fulano de Tal"


def test_importacao_cadastro_reconhece_empresa_e_socio_existentes(conn):
    empresa_id = _nova_empresa(conn)
    socio_id = repo.salvar_socio(conn, Socio(id=None, nome="Fulano de Tal", cpf="111.111.111-11"))

    resultado = repo.preparar_importacao_cadastro(conn, [_linha_cadastro()])
    assert resultado["pendencias"] == []
    (pronta,) = resultado["prontas"]
    assert pronta["empresa_existente"].id == empresa_id
    assert pronta["socio_id"] == socio_id

    aplicado = repo.aplicar_importacao_cadastro(conn, resultado["prontas"])
    assert aplicado == {"empresas_criadas": 0, "vinculos_criados": 1, "vinculos_ja_existentes": 0}
    vinculos = repo.listar_vinculos_empresa(conn, empresa_id)
    assert len(vinculos) == 1
    assert vinculos[0].socio_id == socio_id


def test_importacao_cadastro_nao_duplica_vinculo_ja_ativo(conn):
    empresa_id = _nova_empresa(conn)
    socio_id = repo.salvar_socio(conn, Socio(id=None, nome="Fulano de Tal", cpf="111.111.111-11"))
    repo.salvar_vinculo(
        conn,
        VinculoSocietario(
            id=None, empresa_id=empresa_id, socio_id=socio_id,
            percentual_capital=100.0, quantidade_cotas=1000,
            data_entrada="2023-01-01", data_saida=None,
        ),
    )

    resultado = repo.preparar_importacao_cadastro(conn, [_linha_cadastro()])
    aplicado = repo.aplicar_importacao_cadastro(conn, resultado["prontas"])
    assert aplicado == {"empresas_criadas": 0, "vinculos_criados": 0, "vinculos_ja_existentes": 1}
    assert len(repo.listar_vinculos_empresa(conn, empresa_id)) == 1


def test_importacao_cadastro_cria_empresa_nova_quando_nao_encontra(conn):
    socio_id = repo.salvar_socio(conn, Socio(id=None, nome="Fulano de Tal", cpf="111.111.111-11"))

    resultado = repo.preparar_importacao_cadastro(conn, [_linha_cadastro(numero_chamada="999", empresa_nome="Nova Empresa LTDA")])
    (pronta,) = resultado["prontas"]
    assert pronta["empresa_existente"] is None

    aplicado = repo.aplicar_importacao_cadastro(conn, resultado["prontas"])
    assert aplicado["empresas_criadas"] == 1
    assert aplicado["vinculos_criados"] == 1
    (empresa,) = [e for e in repo.listar_empresas(conn) if e.numero_chamada == "999"]
    assert empresa.nome == "Nova Empresa LTDA"
    vinculos = repo.listar_vinculos_empresa(conn, empresa.id)
    assert vinculos[0].socio_id == socio_id


def test_importacao_cadastro_reaproveita_empresa_nova_entre_linhas(conn):
    s1 = repo.salvar_socio(conn, Socio(id=None, nome="Fulano", cpf="111.111.111-11"))
    s2 = repo.salvar_socio(conn, Socio(id=None, nome="Beltrano", cpf="222.222.222-22"))

    linhas = [
        _linha_cadastro(numero_chamada="999", empresa_nome="Nova Empresa LTDA", socio_nome="Fulano", socio_cpf="111.111.111-11", percentual_capital=60),
        _linha_cadastro(numero_chamada="999", empresa_nome="Nova Empresa LTDA", socio_nome="Beltrano", socio_cpf="222.222.222-22", percentual_capital=40),
    ]
    resultado = repo.preparar_importacao_cadastro(conn, linhas)
    assert len(resultado["prontas"]) == 2

    aplicado = repo.aplicar_importacao_cadastro(conn, resultado["prontas"])
    assert aplicado["empresas_criadas"] == 1
    assert aplicado["vinculos_criados"] == 2
    empresas = [e for e in repo.listar_empresas(conn) if e.numero_chamada == "999"]
    assert len(empresas) == 1


def test_importacao_cadastro_nome_de_socio_ambiguo_vira_pendencia(conn):
    _nova_empresa(conn)
    repo.salvar_socio(conn, Socio(id=None, nome="João Silva", cpf="111.111.111-11"))
    repo.salvar_socio(conn, Socio(id=None, nome="João Silva", cpf="222.222.222-22"))

    resultado = repo.preparar_importacao_cadastro(conn, [_linha_cadastro(socio_nome="João Silva", socio_cpf="")])
    assert resultado["prontas"] == []
    assert "Encontrei 2 sócios" in resultado["pendencias"][0]["aviso"]


def test_panorama_detecta_reentrada_real_apos_saida_definitiva(conn):
    """Bug encontrado em revisão: usar o primeiro segmento histórico do
    vínculo pra decidir "entrou_no_ano" confundia reentrada de verdade (saiu
    e voltou anos depois) com atualização de cotas (fecha/reabre no mesmo
    dia, sem lacuna) — as duas usavam o mesmo sinal errado."""
    empresa_id = _nova_empresa(conn)
    socio_id = repo.salvar_socio(conn, Socio(id=None, nome="Fulano", cpf="111.111.111-11"))

    repo.salvar_vinculo(
        conn,
        VinculoSocietario(
            id=None, empresa_id=empresa_id, socio_id=socio_id,
            percentual_capital=50.0, quantidade_cotas=50,
            data_entrada="2018-01-01", data_saida="2020-06-01",
        ),
    )
    repo.salvar_vinculo(
        conn,
        VinculoSocietario(
            id=None, empresa_id=empresa_id, socio_id=socio_id,
            percentual_capital=30.0, quantidade_cotas=30,
            data_entrada="2023-03-01", data_saida=None,
        ),
    )
    repo.salvar_distribuicao(conn, empresa_id, 2023, socio_id, 10000)

    (linha,) = repo.panorama_distribuicao_anual(conn, empresa_id, 2023)
    assert linha["entrou_no_ano"] is True
    assert linha["saiu_no_ano"] is False

    # no ano do primeiro stint (que nao teve reentrada), nao deveria marcar
    # como se tivesse acabado de entrar
    linha_2018 = repo.panorama_distribuicao_anual(conn, empresa_id, 2018)
    assert linha_2018[0]["entrou_no_ano"] is True
    linha_2019 = repo.panorama_distribuicao_anual(conn, empresa_id, 2019)
    assert linha_2019[0]["entrou_no_ano"] is False


def test_salvar_socio_nao_permite_cpf_duplicado(conn):
    """Regra desconexa encontrada em revisão: a importação em massa nunca
    cria sócio duplicado por CPF, mas o cadastro manual (aba Sócios) não
    tinha nenhuma trava equivalente — dava pra criar dois sócios com o
    mesmo CPF direto pelo formulário."""
    repo.salvar_socio(conn, Socio(id=None, nome="Fulano de Tal", cpf="111.111.111-11"))
    with pytest.raises(ValueError, match="[Jj]á existe um sócio"):
        repo.salvar_socio(conn, Socio(id=None, nome="Fulano da Silva", cpf="111.111.111-11"))


def test_salvar_socio_permite_varios_sem_cpf(conn):
    """CPF em branco não deveria colidir consigo mesmo — muitos sócios ainda
    sem documento cadastrado é normal."""
    repo.salvar_socio(conn, Socio(id=None, nome="Fulano", cpf=""))
    repo.salvar_socio(conn, Socio(id=None, nome="Beltrano", cpf=""))
    assert len(repo.listar_socios(conn)) == 2


def test_salvar_socio_permite_atualizar_mantendo_o_proprio_cpf(conn):
    socio_id = repo.salvar_socio(conn, Socio(id=None, nome="Fulano", cpf="111.111.111-11"))
    repo.salvar_socio(conn, Socio(id=socio_id, nome="Fulano de Tal", cpf="111.111.111-11"))
    (socio,) = repo.listar_socios(conn)
    assert socio.nome == "Fulano de Tal"


def test_salvar_socio_detecta_cpf_duplicado_mesmo_sem_pontuacao(conn):
    """A mesma regra de unicidade precisa reconhecer o CPF independente de
    como foi digitado — sócio cadastrado via importação (sem máscara) tem
    que colidir com o mesmo CPF digitado com máscara no formulário manual."""
    repo.salvar_socio(conn, Socio(id=None, nome="Fulano de Tal", cpf="11111111111"))
    with pytest.raises(ValueError, match="[Jj]á existe um sócio"):
        repo.salvar_socio(conn, Socio(id=None, nome="Fulano da Silva", cpf="111.111.111-11"))


def test_importacao_cadastro_reconhece_cpf_sem_pontuacao_na_planilha(conn):
    """Planilhas exportadas de outros sistemas costumam vir sem máscara —
    isso não pode virar pendência de revisão pra alguém já cadastrado."""
    empresa_id = _nova_empresa(conn)
    socio_id = repo.salvar_socio(conn, Socio(id=None, nome="Fulano de Tal", cpf="111.111.111-11"))

    resultado = repo.preparar_importacao_cadastro(
        conn, [_linha_cadastro(socio_cpf="11111111111")]
    )
    assert resultado["pendencias"] == []
    (pronta,) = resultado["prontas"]
    assert pronta["socio_id"] == socio_id


def test_excluir_empresa_com_vinculo_da_mensagem_clara(conn):
    """Antes: excluir uma empresa com sócios vinculados estourava um
    sqlite3.IntegrityError cru ("FOREIGN KEY constraint failed") direto na
    tela. Agora vira um ValueError com mensagem que explica o que fazer."""
    empresa_id, s1, s2 = _empresa_com_dois_socios(conn)
    with pytest.raises(ValueError, match="[Nn]ão é possível excluir"):
        repo.excluir_empresa(conn, empresa_id)


def test_excluir_socio_com_vinculo_da_mensagem_clara(conn):
    empresa_id, s1, s2 = _empresa_com_dois_socios(conn)
    with pytest.raises(ValueError, match="[Nn]ão é possível excluir"):
        repo.excluir_socio(conn, s1)


def test_excluir_alteracao_com_vinculo_da_mensagem_clara(conn):
    empresa_id = _nova_empresa(conn)
    socio_id = repo.salvar_socio(conn, Socio(id=None, nome="Fulano", cpf="111.111.111-11"))
    alteracao_id = repo.salvar_alteracao(
        conn, AlteracaoContratual(id=None, empresa_id=empresa_id, numero=1, data="2024-01-01",
                                   nome_empresa="ACME LTDA", capital_social=1000, quantidade_cotas=100,
                                   descricao="teste")
    )
    repo.salvar_vinculo(
        conn,
        VinculoSocietario(
            id=None, empresa_id=empresa_id, socio_id=socio_id,
            percentual_capital=100.0, quantidade_cotas=100,
            data_entrada="2024-01-01", data_saida=None, alteracao_entrada_id=alteracao_id,
        ),
    )
    with pytest.raises(ValueError, match="[Nn]ão é possível excluir"):
        repo.excluir_alteracao(conn, alteracao_id)


def test_estado_atual_empresa_usa_data_nao_numero(conn):
    """Bug encontrado em revisão: estado_atual_empresa ordenava só por
    número, enquanto estado_empresa_no_periodo (que resolve o mesmo
    conceito — "estado vigente") já ordenava por data. Um registro
    retroativo (número mais alto, data efetiva anterior) fazia as duas
    funções discordarem sobre o capital/cotas atuais da empresa."""
    empresa_id = _nova_empresa(conn)
    repo.salvar_alteracao(
        conn, AlteracaoContratual(id=None, empresa_id=empresa_id, numero=1, data="2022-01-01",
                                   nome_empresa="ACME LTDA", capital_social=5000, quantidade_cotas=500,
                                   descricao="aumento")
    )
    repo.salvar_alteracao(
        conn, AlteracaoContratual(id=None, empresa_id=empresa_id, numero=2, data="2019-01-01",
                                   nome_empresa="ACME LTDA", capital_social=1000, quantidade_cotas=100,
                                   descricao="registro retroativo, nº maior mas data anterior")
    )

    estado_atual = repo.estado_atual_empresa(conn, empresa_id)
    estado_periodo = repo.estado_empresa_no_periodo(conn, empresa_id, 2024)
    assert estado_atual["capital_social"] == 5000
    assert estado_atual["capital_social"] == estado_periodo["capital_fim"]


def test_salvar_vinculo_rejeita_data_saida_anterior_a_entrada(conn):
    empresa_id = _nova_empresa(conn)
    socio_id = repo.salvar_socio(conn, Socio(id=None, nome="Fulano", cpf="111.111.111-11"))
    with pytest.raises(ValueError, match="data de saída"):
        repo.salvar_vinculo(
            conn,
            VinculoSocietario(
                id=None, empresa_id=empresa_id, socio_id=socio_id,
                percentual_capital=100.0, quantidade_cotas=100,
                data_entrada="2024-06-01", data_saida="2024-01-01",
            ),
        )


def test_encerrar_vinculo_rejeita_data_saida_anterior_a_entrada(conn):
    empresa_id = _nova_empresa(conn)
    socio_id = repo.salvar_socio(conn, Socio(id=None, nome="Fulano", cpf="111.111.111-11"))
    vinculo_id = repo.salvar_vinculo(
        conn,
        VinculoSocietario(
            id=None, empresa_id=empresa_id, socio_id=socio_id,
            percentual_capital=100.0, quantidade_cotas=100,
            data_entrada="2024-06-01", data_saida=None,
        ),
    )
    with pytest.raises(ValueError, match="data de saída"):
        repo.encerrar_vinculo(conn, vinculo_id, "2024-01-01", None)


def test_encerrar_vinculo_registrando_alteracao_nao_deixa_alteracao_orfa_em_data_invalida(conn):
    """A validação precisa acontecer ANTES de abrir a alteração contratual
    automática — senão uma data inválida deixava uma alteração vazia (sem
    nenhuma saída de sócio de fato) já salva no banco."""
    empresa_id = _nova_empresa(conn)
    socio_id = repo.salvar_socio(conn, Socio(id=None, nome="Fulano", cpf="111.111.111-11"))
    vinculo_id = repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 100.0, 100, "2024-06-01")
    vinculo = repo.buscar_vinculo(conn, vinculo_id)

    alteracoes_antes = len(repo.listar_alteracoes(conn, empresa_id))
    with pytest.raises(ValueError, match="data de saída"):
        repo.encerrar_vinculo_registrando_alteracao(conn, vinculo, "2024-01-01")
    assert len(repo.listar_alteracoes(conn, empresa_id)) == alteracoes_antes


def test_atualizar_cotas_vinculo_rejeita_data_anterior_a_entrada(conn):
    empresa_id = _nova_empresa(conn)
    socio_id = repo.salvar_socio(conn, Socio(id=None, nome="Fulano", cpf="111.111.111-11"))
    vinculo_id = repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 100.0, 100, "2024-06-01")
    vinculo = repo.buscar_vinculo(conn, vinculo_id)

    alteracoes_antes = len(repo.listar_alteracoes(conn, empresa_id))
    with pytest.raises(ValueError, match="data da atualização"):
        repo.atualizar_cotas_vinculo(conn, vinculo, 50.0, 50, "2024-01-01")
    assert len(repo.listar_alteracoes(conn, empresa_id)) == alteracoes_antes


def test_init_schema_migra_banco_antigo_sem_colunas_novas():
    """Bug encontrado importando dados reais: um banco criado antes do
    tipo_pessoa/pro_labore/irrf existirem no schema nunca ganhava essas
    colunas, porque CREATE TABLE IF NOT EXISTS não altera tabela já criada
    — a primeira tela que usasse esses campos quebrava com
    "table has no column named ..."."""
    antigo = sqlite3.connect(":memory:")
    antigo.row_factory = sqlite3.Row
    antigo.executescript(
        """
        CREATE TABLE empresa (
            id INTEGER PRIMARY KEY AUTOINCREMENT, numero_chamada TEXT NOT NULL,
            nome TEXT NOT NULL, cnpj TEXT, capital_social REAL NOT NULL DEFAULT 0,
            quantidade_cotas REAL NOT NULL DEFAULT 0
        );
        CREATE TABLE socio (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT NOT NULL, cpf TEXT);
        CREATE TABLE distribuicao_lucro (
            id INTEGER PRIMARY KEY AUTOINCREMENT, empresa_id INTEGER NOT NULL,
            ano_base INTEGER NOT NULL, socio_id INTEGER NOT NULL,
            valor_distribuido REAL NOT NULL DEFAULT 0
        );
        """
    )
    antigo.commit()

    db.init_schema(antigo)  # deve migrar sem apagar nada e sem dar erro

    colunas_socio = {r["name"] for r in antigo.execute("PRAGMA table_info(socio)").fetchall()}
    colunas_dist = {r["name"] for r in antigo.execute("PRAGMA table_info(distribuicao_lucro)").fetchall()}
    assert "tipo_pessoa" in colunas_socio
    assert {"pro_labore", "irrf"} <= colunas_dist

    socio_id = repo.salvar_socio(antigo, Socio(id=None, nome="Fulano", cpf="111.111.111-11", tipo_pessoa="juridica"))
    (socio,) = repo.listar_socios(antigo)
    assert socio.tipo_pessoa == "juridica"


# ------------------------------------------------- Trancamento de período --

def test_periodo_comeca_destrancado(conn):
    empresa_id = _nova_empresa(conn)
    assert repo.periodo_esta_fechado(conn, empresa_id, 2025) is False


def test_fechar_e_reabrir_periodo(conn):
    empresa_id = _nova_empresa(conn)
    repo.fechar_periodo(conn, empresa_id, 2025)
    assert repo.periodo_esta_fechado(conn, empresa_id, 2025) is True
    assert repo.periodo_esta_fechado(conn, empresa_id, 2024) is False  # outro ano nao é afetado

    repo.reabrir_periodo(conn, empresa_id, 2025)
    assert repo.periodo_esta_fechado(conn, empresa_id, 2025) is False


def test_periodo_trancado_bloqueia_salvar_distribuicao(conn):
    empresa_id, s1, s2 = _empresa_com_dois_socios(conn)
    repo.fechar_periodo(conn, empresa_id, 2024)
    with pytest.raises(ValueError, match="trancado"):
        repo.salvar_distribuicao(conn, empresa_id, 2024, s1, 1000)
    # outro ano continua liberado
    repo.salvar_distribuicao(conn, empresa_id, 2025, s1, 1000)


def test_periodo_trancado_bloqueia_movimentacao(conn):
    empresa_id, s1, s2 = _empresa_com_dois_socios(conn)
    repo.fechar_periodo(conn, empresa_id, 2024)
    with pytest.raises(ValueError, match="trancado"):
        repo.salvar_movimentacao(
            conn, Movimentacao(id=None, empresa_id=empresa_id, socio_id=s1,
                                tipo="emprestimo_empresa_para_socio", valor=500, data="2024-06-01")
        )

    mov_id = repo.salvar_movimentacao(
        conn, Movimentacao(id=None, empresa_id=empresa_id, socio_id=s1,
                            tipo="emprestimo_empresa_para_socio", valor=500, data="2025-06-01")
    )
    repo.fechar_periodo(conn, empresa_id, 2025)
    with pytest.raises(ValueError, match="trancado"):
        repo.excluir_movimentacao(conn, mov_id)


def test_periodo_trancado_bloqueia_vinculo(conn):
    empresa_id = _nova_empresa(conn)
    socio_id = repo.salvar_socio(conn, Socio(id=None, nome="Fulano", cpf="111.111.111-11"))
    repo.fechar_periodo(conn, empresa_id, 2024)

    with pytest.raises(ValueError, match="trancado"):
        repo.salvar_vinculo(
            conn, VinculoSocietario(id=None, empresa_id=empresa_id, socio_id=socio_id,
                                     percentual_capital=100.0, quantidade_cotas=100,
                                     data_entrada="2024-01-01", data_saida=None)
        )

    vinculo_id = repo.salvar_vinculo(
        conn, VinculoSocietario(id=None, empresa_id=empresa_id, socio_id=socio_id,
                                 percentual_capital=100.0, quantidade_cotas=100,
                                 data_entrada="2025-01-01", data_saida=None)
    )
    repo.fechar_periodo(conn, empresa_id, 2025)
    with pytest.raises(ValueError, match="trancado"):
        repo.encerrar_vinculo(conn, vinculo_id, "2025-12-01", None)
    with pytest.raises(ValueError, match="trancado"):
        repo.excluir_vinculo(conn, vinculo_id)


def test_periodo_trancado_bloqueia_wrappers_sem_deixar_alteracao_orfa(conn):
    """associar_socio_a_empresa, atualizar_cotas_vinculo e
    encerrar_vinculo_registrando_alteracao abrem uma alteração contratual
    automática antes da operação principal — o trancamento precisa barrar
    ANTES disso, senão sobra uma alteração vazia no histórico."""
    empresa_id = _nova_empresa(conn)
    socio_id = repo.salvar_socio(conn, Socio(id=None, nome="Fulano", cpf="111.111.111-11"))
    repo.fechar_periodo(conn, empresa_id, 2025)

    with pytest.raises(ValueError, match="trancado"):
        repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 100.0, 100, "2025-01-01")
    assert repo.listar_alteracoes(conn, empresa_id) == []

    # cria o vinculo num ano destrancado pra poder testar os outros dois wrappers
    vinculo_id = repo.salvar_vinculo(
        conn, VinculoSocietario(id=None, empresa_id=empresa_id, socio_id=socio_id,
                                 percentual_capital=100.0, quantidade_cotas=100,
                                 data_entrada="2023-01-01", data_saida=None)
    )
    vinculo = repo.buscar_vinculo(conn, vinculo_id)

    with pytest.raises(ValueError, match="trancado"):
        repo.atualizar_cotas_vinculo(conn, vinculo, 50.0, 50, "2025-06-01")
    assert repo.listar_alteracoes(conn, empresa_id) == []

    with pytest.raises(ValueError, match="trancado"):
        repo.encerrar_vinculo_registrando_alteracao(conn, vinculo, "2025-06-01")
    assert repo.listar_alteracoes(conn, empresa_id) == []


def test_periodo_trancado_bloqueia_alteracao_contratual(conn):
    empresa_id = _nova_empresa(conn)
    repo.fechar_periodo(conn, empresa_id, 2025)

    with pytest.raises(ValueError, match="trancado"):
        repo.salvar_alteracao(
            conn, AlteracaoContratual(id=None, empresa_id=empresa_id, numero=1, data="2025-03-01",
                                       nome_empresa="ACME LTDA", capital_social=1000, quantidade_cotas=100,
                                       descricao="teste")
        )

    alteracao_id = repo.salvar_alteracao(
        conn, AlteracaoContratual(id=None, empresa_id=empresa_id, numero=1, data="2023-03-01",
                                   nome_empresa="ACME LTDA", capital_social=1000, quantidade_cotas=100,
                                   descricao="teste")
    )
    repo.fechar_periodo(conn, empresa_id, 2023)
    with pytest.raises(ValueError, match="trancado"):
        repo.excluir_alteracao(conn, alteracao_id)
