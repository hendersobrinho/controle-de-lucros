"""Distribuição trimestral e a propagação dela para a distribuição anual."""
import sqlite3

import pytest

from controle_lucros import db, repositories as repo
from controle_lucros.models import Empresa, Socio, periodo_trimestre


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    db.init_schema(connection)
    yield connection
    connection.close()


@pytest.fixture()
def cenario(conn):
    empresa_id = repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 100000, 1000))
    fulano = repo.salvar_socio(conn, Socio(None, "Fulano de Tal", "111.111.111-11"))
    beltrano = repo.salvar_socio(conn, Socio(None, "Beltrano da Silva", "222.222.222-22"))
    repo.associar_socio_a_empresa(conn, empresa_id, fulano, 60.0, 600, "2020-01-01")
    repo.associar_socio_a_empresa(conn, empresa_id, beltrano, 40.0, 400, "2020-01-01")
    return {"empresa": empresa_id, "fulano": fulano, "beltrano": beltrano}


def _anual(conn, empresa_id, socio_id, ano=2025):
    return next(
        (d for d in repo.listar_distribuicoes(conn, empresa_id, ano) if d.socio_id == socio_id), None
    )


# ------------------------------------------------------ limites do período --


@pytest.mark.parametrize(
    "trimestre,esperado",
    [
        (1, ("2025-01-01", "2025-03-31")),
        (2, ("2025-04-01", "2025-06-30")),
        (3, ("2025-07-01", "2025-09-30")),
        (4, ("2025-10-01", "2025-12-31")),
    ],
)
def test_periodo_trimestre(trimestre, esperado):
    assert periodo_trimestre(2025, trimestre) == esperado


# ------------------------------------------------------- gravação e soma --


def test_lancar_trimestre_grava_e_reflete_no_anual(conn, cenario):
    repo.salvar_distribuicao_trimestral(
        conn, cenario["empresa"], 2025, 1, cenario["fulano"], 10000.0, pro_labore=6000.0, irrf=138.0
    )
    anual = _anual(conn, cenario["empresa"], cenario["fulano"])
    assert anual.valor_distribuido == 10000.0
    assert anual.pro_labore == 6000.0
    assert anual.irrf == 138.0


def test_o_anual_vai_acumulando_a_cada_trimestre(conn, cenario):
    """É o comportamento central: o anual sobe conforme os trimestres entram,
    sem ninguém somar à mão."""
    esperado = 0.0
    for trimestre, valor in ((1, 10000.0), (2, 20000.0), (3, 5000.0), (4, 15000.0)):
        repo.salvar_distribuicao_trimestral(
            conn, cenario["empresa"], 2025, trimestre, cenario["fulano"], valor
        )
        esperado += valor
        assert _anual(conn, cenario["empresa"], cenario["fulano"]).valor_distribuido == esperado
    assert esperado == 50000.0


def test_corrigir_um_trimestre_recalcula_o_anual_em_vez_de_somar_de_novo(conn, cenario):
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 1, cenario["fulano"], 10000.0)
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 2, cenario["fulano"], 20000.0)
    # Correção do 1º trimestre: o anual tem que virar 5.000 + 20.000, não 35.000.
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 1, cenario["fulano"], 5000.0)
    assert _anual(conn, cenario["empresa"], cenario["fulano"]).valor_distribuido == 25000.0
    assert len(repo.listar_distribuicoes_trimestrais(conn, cenario["empresa"], 2025)) == 2


def test_trimestres_sao_isolados_por_socio_e_por_ano(conn, cenario):
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 1, cenario["fulano"], 10000.0)
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 1, cenario["beltrano"], 8000.0)
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2024, 1, cenario["fulano"], 999.0)

    assert _anual(conn, cenario["empresa"], cenario["fulano"]).valor_distribuido == 10000.0
    assert _anual(conn, cenario["empresa"], cenario["beltrano"]).valor_distribuido == 8000.0
    assert _anual(conn, cenario["empresa"], cenario["fulano"], ano=2024).valor_distribuido == 999.0


def test_trimestre_invalido_e_recusado(conn, cenario):
    for trimestre in (0, 5, -1):
        with pytest.raises(ValueError, match="Trimestre inválido"):
            repo.salvar_distribuicao_trimestral(
                conn, cenario["empresa"], 2025, trimestre, cenario["fulano"], 1000.0
            )


def test_periodo_trancado_impede_lancamento_trimestral(conn, cenario):
    """Trancar o ano na aba anual tem que trancar o trimestre também — senão
    a trava seria contornável por outra tela."""
    repo.fechar_periodo(conn, cenario["empresa"], 2025)
    with pytest.raises(ValueError, match="trancado"):
        repo.salvar_distribuicao_trimestral(
            conn, cenario["empresa"], 2025, 1, cenario["fulano"], 10000.0
        )


# ------------------------------------------------------------- exclusão --


def test_excluir_trimestre_recalcula_o_anual_com_o_que_sobrou(conn, cenario):
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 1, cenario["fulano"], 10000.0)
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 2, cenario["fulano"], 20000.0)
    primeiro = repo.listar_distribuicoes_trimestrais(conn, cenario["empresa"], 2025, trimestre=1)[0]

    repo.excluir_distribuicao_trimestral(conn, primeiro.id)
    assert _anual(conn, cenario["empresa"], cenario["fulano"]).valor_distribuido == 20000.0


def test_excluir_o_ultimo_trimestre_zera_o_anual(conn, cenario):
    """Deixar o valor antigo pendurado seria pior: ninguém saberia de onde veio."""
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 1, cenario["fulano"], 10000.0)
    unico = repo.listar_distribuicoes_trimestrais(conn, cenario["empresa"], 2025)[0]
    repo.excluir_distribuicao_trimestral(conn, unico.id)
    assert _anual(conn, cenario["empresa"], cenario["fulano"]).valor_distribuido == 0.0
    assert repo.trimestres_lancados(conn, cenario["empresa"], 2025) == []


# ------------------------------------------------------------ acumulado --


def test_acumulado_respeita_o_limite_de_trimestre(conn, cenario):
    for trimestre, valor in ((1, 10000.0), (2, 20000.0), (3, 5000.0)):
        repo.salvar_distribuicao_trimestral(
            conn, cenario["empresa"], 2025, trimestre, cenario["fulano"], valor
        )
    ate_2 = repo.acumulado_trimestral(conn, cenario["empresa"], 2025, ate_trimestre=2)
    assert ate_2[cenario["fulano"]]["valor_distribuido"] == 30000.0
    ano_todo = repo.acumulado_trimestral(conn, cenario["empresa"], 2025)
    assert ano_todo[cenario["fulano"]]["valor_distribuido"] == 35000.0


def test_trimestres_lancados_lista_so_os_que_tem_lancamento(conn, cenario):
    assert repo.trimestres_lancados(conn, cenario["empresa"], 2025) == []
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 3, cenario["fulano"], 1000.0)
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 1, cenario["beltrano"], 500.0)
    assert repo.trimestres_lancados(conn, cenario["empresa"], 2025) == [1, 3]


# ------------------------------------------------- panorama do trimestre --


def test_panorama_traz_lancamento_do_trimestre_e_acumulado_do_ano(conn, cenario):
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 1, cenario["fulano"], 10000.0)
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 2, cenario["fulano"], 20000.0)

    linhas = repo.panorama_distribuicao_trimestral(conn, cenario["empresa"], 2025, 2)
    fulano = next(l for l in linhas if l["socio_id"] == cenario["fulano"])
    assert fulano["valor_distribuido"] == 20000.0  # só o 2º trimestre
    assert fulano["acumulado_valor"] == 30000.0  # 1º + 2º
    assert fulano["registro_id"] is not None

    beltrano = next(l for l in linhas if l["socio_id"] == cenario["beltrano"])
    assert beltrano["valor_distribuido"] == 0.0
    assert beltrano["registro_id"] is None


def test_panorama_so_lista_socios_do_trimestre(conn, cenario):
    """Quem saiu no 1º trimestre não aparece no 4º — lançar valor pra ele lá
    seria distribuir lucro a quem já não era sócio."""
    vinculo = next(
        v for v in repo.listar_vinculos_socio(conn, cenario["beltrano"]) if v.data_saida is None
    )
    repo.encerrar_vinculo_registrando_alteracao(conn, vinculo, "2025-02-15", "Saída")

    primeiro = repo.panorama_distribuicao_trimestral(conn, cenario["empresa"], 2025, 1)
    assert cenario["beltrano"] in {l["socio_id"] for l in primeiro}
    assert next(l for l in primeiro if l["socio_id"] == cenario["beltrano"])["saiu_no_trimestre"]

    quarto = repo.panorama_distribuicao_trimestral(conn, cenario["empresa"], 2025, 4)
    assert cenario["beltrano"] not in {l["socio_id"] for l in quarto}


def test_total_do_trimestre_soma_todos_os_socios(conn, cenario):
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 1, cenario["fulano"], 10000.0)
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 1, cenario["beltrano"], 8000.0)
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 2, cenario["fulano"], 999.0)
    assert repo.total_distribuido_trimestre(conn, cenario["empresa"], 2025, 1) == 18000.0


# ----------------------------------------- origem do valor no panorama anual --


def test_panorama_anual_marca_valor_vindo_dos_trimestres(conn, cenario):
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 1, cenario["fulano"], 10000.0)
    linha = next(
        l for l in repo.panorama_distribuicao_anual(conn, cenario["empresa"], 2025)
        if l["socio_id"] == cenario["fulano"]
    )
    assert linha["tem_trimestres"] is True
    assert linha["origem_valor"] == "trimestres"
    assert linha["acumulado_trimestral"] == 10000.0


def test_panorama_anual_marca_valor_sobrescrito_a_mao(conn, cenario):
    """Editar o anual à mão continua valendo — a tela só passa a dizer que
    aquele número não é mais o somatório dos trimestres."""
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 1, cenario["fulano"], 10000.0)
    repo.salvar_distribuicao(conn, cenario["empresa"], 2025, cenario["fulano"], 12345.0)

    linha = next(
        l for l in repo.panorama_distribuicao_anual(conn, cenario["empresa"], 2025)
        if l["socio_id"] == cenario["fulano"]
    )
    assert linha["valor_distribuido"] == 12345.0
    assert linha["origem_valor"] == "manual"
    assert linha["acumulado_trimestral"] == 10000.0


def test_lancar_trimestre_de_novo_sobrescreve_a_edicao_manual(conn, cenario):
    """Foi a regra escolhida: o lançamento trimestral volta a mandar."""
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 1, cenario["fulano"], 10000.0)
    repo.salvar_distribuicao(conn, cenario["empresa"], 2025, cenario["fulano"], 12345.0)
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 2, cenario["fulano"], 20000.0)
    assert _anual(conn, cenario["empresa"], cenario["fulano"]).valor_distribuido == 30000.0


def test_empresa_sem_trimestre_nao_ganha_origem(conn, cenario):
    """Quem não usa a aba trimestral continua funcionando exatamente como antes."""
    repo.salvar_distribuicao(conn, cenario["empresa"], 2025, cenario["fulano"], 50000.0)
    linha = next(
        l for l in repo.panorama_distribuicao_anual(conn, cenario["empresa"], 2025)
        if l["socio_id"] == cenario["fulano"]
    )
    assert linha["tem_trimestres"] is False
    assert linha["origem_valor"] == "manual"
    assert linha["acumulado_trimestral"] == 0.0


def test_lancamento_trimestral_fica_no_log_de_atividades(conn, cenario):
    repo.salvar_distribuicao_trimestral(conn, cenario["empresa"], 2025, 1, cenario["fulano"], 10000.0)
    acoes = [
        (l.acao, l.entidade) for l in repo.listar_log_atividade(conn)
        if l.entidade == "distribuicao_trimestral"
    ]
    assert ("criar", "distribuicao_trimestral") in acoes


def test_editar_so_o_pro_labore_no_anual_ja_desmarca_a_origem_trimestres(conn, cenario):
    """Os três campos são propagados juntos; se qualquer um divergir, o valor
    anual deixou de ser o somatório e a tela precisa dizer isso."""
    repo.salvar_distribuicao_trimestral(
        conn, cenario["empresa"], 2025, 1, cenario["fulano"], 10000.0, pro_labore=6000.0, irrf=138.0
    )
    linha = next(
        l for l in repo.panorama_distribuicao_anual(conn, cenario["empresa"], 2025)
        if l["socio_id"] == cenario["fulano"]
    )
    assert linha["origem_valor"] == "trimestres"

    # Só o pró-labore muda; o valor distribuído continua batendo.
    repo.salvar_distribuicao(conn, cenario["empresa"], 2025, cenario["fulano"], 10000.0, 9999.0, 138.0)
    linha = next(
        l for l in repo.panorama_distribuicao_anual(conn, cenario["empresa"], 2025)
        if l["socio_id"] == cenario["fulano"]
    )
    assert linha["origem_valor"] == "manual"
