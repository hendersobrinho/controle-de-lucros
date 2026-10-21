"""Dashboards: os números agregados e as telas montando com eles."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from controle_lucros import repositories as repo
from controle_lucros.models import Empresa, Movimentacao, Socio
from controle_lucros.ui.dashboard_empresa import DashboardEmpresaView
from controle_lucros.ui.dashboard_visao_geral import DashboardVisaoGeralView


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def analise_na_hora(monkeypatch):
    """Os testes de números leem o resultado logo depois de abrir a tela; o
    segundo plano tem testes próprios (no fim do arquivo)."""
    monkeypatch.setattr(DashboardVisaoGeralView, "assincrono", False)


@pytest.fixture()
def cenario(conn):
    acme = repo.salvar_empresa(conn, Empresa(None, "001", "ACME", "", 1000, 1000))
    beta = repo.salvar_empresa(conn, Empresa(None, "002", "BETA", "", 1000, 1000))
    ana = repo.salvar_socio(conn, Socio(None, "ANA", "111.111.111-11"))
    bia = repo.salvar_socio(conn, Socio(None, "BIA", ""))
    repo.associar_socio_a_empresa(conn, acme, ana, 50, 500, "2020-01-01")
    repo.associar_socio_a_empresa(conn, acme, bia, 50, 500, "2020-01-01")
    repo.associar_socio_a_empresa(conn, beta, ana, 100, 1000, "2020-01-01")
    repo.salvar_distribuicao(conn, acme, 2023, ana, 1000)
    repo.salvar_distribuicao(conn, acme, 2023, bia, 1000)
    repo.salvar_distribuicao(conn, acme, 2024, ana, 3000, pro_labore=500)
    repo.salvar_distribuicao(conn, acme, 2024, bia, 1000)
    repo.salvar_distribuicao(conn, beta, 2024, ana, 2000)
    repo.salvar_movimentacao(conn, Movimentacao(None, acme, ana, "emprestimo_empresa_para_socio", 700, "2024-05-01"))
    return {"acme": acme, "beta": beta, "ana": ana, "bia": bia}


def test_painel_geral_soma_o_periodo_e_compara_com_o_anterior(conn, cenario):
    painel = repo.painel_geral(conn, 2024, 2024)
    assert painel["total"] == 6000
    assert painel["total_anterior"] == 2000
    assert painel["pro_labore"] == 500
    assert painel["empresas_que_distribuiram"] == 2
    assert painel["socios_que_receberam"] == 2
    assert [e["nome"] for e in painel["top_empresas"]] == ["ACME", "BETA"]
    assert painel["top_socios"][0]["nome"] == "ANA" and painel["top_socios"][0]["total"] == 5000
    assert painel["movimentos"]["emprestimo_empresa_para_socio"] == 700
    assert [a["ano"] for a in painel["por_ano"]] == [2023, 2024]


def test_painel_geral_sem_periodo_anterior(conn, cenario):
    assert repo.painel_geral(conn, 2023, 2023)["total_anterior"] is None


def test_painel_empresa_separa_cada_socio_por_ano(conn, cenario):
    painel = repo.painel_empresa(conn, cenario["acme"])
    ano_2024 = next(a for a in painel["por_ano"] if a["ano"] == 2024)
    assert ano_2024["total"] == 4000
    assert ano_2024["socios"][cenario["ana"]] == ("ANA", 3000)
    assert painel["movimentos"][2024]["emprestimo_empresa_para_socio"] == 700


def test_visao_geral_abre_no_ultimo_ano_e_mostra_os_numeros(conn, cenario):
    tela = DashboardVisaoGeralView(conn)
    assert (tela.ano_de.value(), tela.ano_ate.value()) == (2024, 2024)
    assert tela.valor_total.text() == "R$ 6.000,00"
    assert "200,0%" in tela.variacao.text()
    assert tela.atencao_desproporcional.property("tom") == "alerta"


def test_fichas_de_ano_mudam_o_periodo(conn, cenario):
    tela = DashboardVisaoGeralView(conn)
    tela.periodo.escolher(2023, 2024)
    assert (tela.ano_de.value(), tela.ano_ate.value()) == (2023, 2024)
    assert tela.valor_total.text() == "R$ 8.000,00"
    assert tela.periodo.btn_tudo.isChecked()


def test_clicar_no_ranking_abre_a_empresa_no_mesmo_periodo(conn, cenario):
    tela = DashboardVisaoGeralView(conn)
    abertas = []
    tela.ao_abrir_empresa = lambda *args: abertas.append(args)
    tela.ranking_empresas.clicado.emit(cenario["acme"])
    assert abertas == [(cenario["acme"], 2024, 2024, 0.0)]


def test_analise_da_empresa_compara_capital_e_recebido(conn, cenario):
    tela = DashboardEmpresaView(conn)
    tela.selecionar(cenario["acme"], 2024, 2024, 0)
    assert tela.valor_total.text() == "R$ 4.000,00"
    itens = tela.grafico_desvio._itens
    ana = next(i for i in itens if i[0] == "ANA")
    # 50% do capital, 75% do recebido: R$ 1.000 acima da proporção.
    assert ana[1] == 50 and ana[2] == 75 and round(ana[4], 2) == 1000
    assert tela.atencao_fora.property("tom") == "alerta"


def test_lucro_sem_pro_labore_conta_so_os_anos_sem_pro_labore(conn, cenario):
    tela = DashboardEmpresaView(conn)
    tela.selecionar(cenario["acme"], 2023, 2024, 0)
    # ANA: 1.000 em 2023 sem pró-labore, 3.000 em 2024 com; BIA: 1.000 + 1.000 sem.
    assert "R$ 3.000,00" in tela.atencao_pro_labore.explicacao.text()


def test_nome_aparece_uma_vez_no_cartao_de_pro_labore(conn, cenario):
    tela = DashboardVisaoGeralView(conn)
    tela.periodo.escolher(2024, 2024)
    nomes = tela.atencao_pro_labore.nomes.text().split(" · ")
    assert len(nomes) == len(set(nomes))


def test_periodo_anterior_incompleto_nao_e_comparado(conn, cenario):
    # Lançamentos começam em 2023: 2024–2025 comparado com 2022–2023 seria meia janela.
    assert repo.painel_geral(conn, 2024, 2025)["total_anterior"] is None


def test_shift_clique_vai_da_ancora_ate_o_ano(conn, cenario, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication as App

    tela = DashboardVisaoGeralView(conn)
    tela.periodo.btn_tudo.click()
    monkeypatch.setattr(App, "keyboardModifiers", staticmethod(lambda: Qt.ShiftModifier))
    tela.periodo._clicar(2023)
    assert (tela.ano_de.value(), tela.ano_ate.value()) == (2023, 2023)


def test_sem_empresa_limpa_os_numeros(conn):
    tela = DashboardEmpresaView(conn)
    assert tela.valor_total.text() == "—"
    assert all(valor.text() == "—" for valor, _nota in tela.kpis.values())


def test_atualizar_esquece_a_classificacao_guardada(conn, cenario):
    tela = DashboardVisaoGeralView(conn)
    repo.salvar_distribuicao(conn, cenario["beta"], 2024, cenario["ana"], 9000)
    tela.atualizar()
    assert tela.valor_total.text() == "R$ 13.000,00"


# ------------------------------------------------- análise em segundo plano --


def _esperar(condicao, limite_ms=8000):
    from PySide6.QtTest import QTest

    passou = 0
    while not condicao() and passou < limite_ms:
        QTest.qWait(20)
        passou += 20
    assert condicao(), "a análise em segundo plano não terminou"


def test_analise_em_segundo_plano_nao_trava_e_mostra_o_resultado(conn, cenario, monkeypatch):
    monkeypatch.setattr(DashboardVisaoGeralView, "assincrono", True)
    tela = DashboardVisaoGeralView(conn)
    tela.resize(1100, 800)
    tela.show()
    tela.atualizar()
    # O painel azul sai na hora; a classificação ainda não.
    assert tela.valor_total.text() == "R$ 6.000,00"
    assert tela._resultado is None and not tela.btn_exportar_excel.isEnabled()
    _esperar(lambda: tela._resultado is not None)
    assert tela.atencao_desproporcional.property("tom") == "alerta"
    assert tela.btn_exportar_excel.isEnabled()
    assert not tela.carregando.isVisible()


def test_trocar_o_periodo_no_meio_fica_com_a_analise_nova(conn, cenario, monkeypatch):
    monkeypatch.setattr(DashboardVisaoGeralView, "assincrono", True)
    tela = DashboardVisaoGeralView(conn)
    tela.periodo.escolher(2023, 2023)
    tela.periodo.escolher(2024, 2024)
    _esperar(lambda: tela._resultado is not None and tela._trabalho is None)
    assert tela._resultado["total_distribuido"] == 6000  # 2024, não 2023


def test_cancelar_limpa_os_cartoes_em_vez_de_mostrar_outro_periodo(conn, cenario, monkeypatch):
    monkeypatch.setattr(DashboardVisaoGeralView, "assincrono", True)
    tela = DashboardVisaoGeralView(conn)
    tela.periodo.escolher(2024, 2024)
    tela.carregando.cancelar.emit()
    assert tela._resultado is None
    assert "cancelada" in tela.atencao_desproporcional.explicacao.text()
    assert not tela.btn_exportar_pdf.isEnabled()


def test_voltar_ao_dashboard_sem_gravacao_nao_refaz_a_conta(conn, cenario, monkeypatch):
    chamadas = []
    original = repo.visao_geral
    monkeypatch.setattr(repo, "visao_geral", lambda *a, **k: chamadas.append(1) or original(*a, **k))
    tela = DashboardVisaoGeralView(conn)
    tela.atualizar()
    tela.atualizar()
    assert len(chamadas) == 1
    repo.salvar_distribuicao(conn, cenario["beta"], 2024, cenario["ana"], 9000)
    tela.atualizar()
    assert len(chamadas) == 2


def test_progresso_pode_cancelar_a_analise(conn, cenario):
    vistas = []

    def progresso(feitas, total, nome):
        vistas.append(nome)
        raise repo.AnaliseCancelada()

    with pytest.raises(repo.AnaliseCancelada):
        repo.visao_geral(conn, 2024, 2024, 0, progresso)
    assert vistas == ["ACME"]


def test_aviso_de_carregamento_desenha(conn, cenario):
    tela = DashboardVisaoGeralView(conn)
    tela.resize(900, 700)
    tela.carregando.comecar("Analisando 2021 a 2025…")
    tela.carregando._aparecer()
    tela.carregando.andamento(40, 214, "MEDTÓRAX")
    assert not tela.carregando.grab().isNull()
    tela.carregando.terminar()
    assert not tela.carregando.isVisible()
