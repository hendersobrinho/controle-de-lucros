"""Edição do vínculo na aba de Sócios.

As quatro ações que existiam (editar datas, atualizar cotas, encerrar,
excluir) viraram uma tela só, com todos os campos do vínculo e o botão de
excluir. O que estes testes prendem é que a tela grava o que mostra, que o
capital do sócio aparece, e que os rótulos continuam cabendo na janela.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from controle_lucros import repositories as repo
from controle_lucros.models import AlteracaoContratual, Empresa, Socio
from controle_lucros.ui import socios_tab as mod
from controle_lucros.ui.socios_tab import SociosTab


@pytest.fixture(scope="module", autouse=True)
def app():
    aplicativo = QApplication.instance() or QApplication([])
    yield aplicativo


@pytest.fixture()
def cenario(conn):
    empresa_id = repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 100000, 1000))
    socio_id = repo.salvar_socio(conn, Socio(None, "Fulano de Tal", "005.169.717-35"))
    repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 100.0, 1000, "2020-01-01")
    (vinculo,) = repo.listar_vinculos_socio(conn, socio_id)
    return {"empresa": empresa_id, "socio": socio_id, "vinculo": vinculo}


def _aba(conn) -> SociosTab:
    aba = SociosTab(conn)
    aba.tabela.selectRow(0)
    return aba


def _dialogo(conn, cenario) -> mod._DialogoEditarVinculo:
    vinculo = repo.buscar_vinculo(conn, cenario["vinculo"].id)
    return mod._DialogoEditarVinculo(conn, vinculo, "ACME LTDA")


# ------------------------------------------------------------ a barra --


def test_sem_vinculo_selecionado_editar_fica_travado(conn, cenario):
    aba = _aba(conn)  # seleciona o sócio, não o vínculo
    assert aba.tabela_vinculos.rowCount() == 1
    assert not aba.btn_editar_vinculo.isEnabled()
    # "Associar" não depende de vínculo selecionado: é a ação com que se começa.
    assert aba.btn_associar.isEnabled()


def test_vinculo_ativo_ou_encerrado_pode_ser_editado(conn, cenario):
    aba = _aba(conn)
    aba.tabela_vinculos.selectRow(0)
    assert aba.btn_editar_vinculo.isEnabled()

    repo.encerrar_vinculo(conn, cenario["vinculo"].id, "2024-06-30", None)
    aba = _aba(conn)
    aba.tabela_vinculos.selectRow(0)
    assert aba.btn_editar_vinculo.isEnabled()


def test_dois_cliques_no_vinculo_abrem_a_edicao(conn, cenario, monkeypatch):
    abertos = []
    monkeypatch.setattr(mod._DialogoEditarVinculo, "exec", lambda self: abertos.append(self) or QDialog.Rejected)
    aba = _aba(conn)
    aba.tabela_vinculos.selectRow(0)
    aba.tabela_vinculos.itemDoubleClicked.emit(aba.tabela_vinculos.item(0, 0))
    assert len(abertos) == 1


# ------------------------------------------------------- a edição --


def test_edicao_grava_todos_os_campos(conn, cenario):
    alteracao_id = repo.salvar_alteracao(conn, AlteracaoContratual(
        None, cenario["empresa"], 7, "2019-12-15", "ACME LTDA", 100000, 1000, "Contrato antigo"))
    dialogo = _dialogo(conn, cenario)

    dialogo.percentual.setValue(60.0)
    dialogo.cotas.setValue(600)
    dialogo.capital.setValue(60000)
    dialogo.observacao.setText("corrigido pelo contrato")
    dialogo.alteracao_entrada.setCurrentIndex(dialogo.alteracao_entrada.findData(alteracao_id))
    dialogo._salvar()

    assert dialogo.result() == QDialog.Accepted
    vinculo = repo.buscar_vinculo(conn, cenario["vinculo"].id)
    assert (vinculo.percentual_capital, vinculo.quantidade_cotas, vinculo.valor_capital) == (60.0, 600, 60000)
    assert vinculo.observacao == "corrigido pelo contrato"
    assert vinculo.alteracao_entrada_id == alteracao_id
    # Corrigir não é movimentar: nada de vínculo novo nem alteração nova.
    assert len(repo.listar_vinculos_socio(conn, cenario["socio"])) == 1
    assert [a.id for a in repo.listar_alteracoes(conn, cenario["empresa"])] == [alteracao_id]


def test_marcar_saida_encerra_o_vinculo(conn, cenario):
    dialogo = _dialogo(conn, cenario)
    assert not dialogo.data_saida.isEnabled()

    dialogo.saiu.setChecked(True)
    assert dialogo.data_saida.isEnabled()
    dialogo.data_saida.setDate(dialogo.data_saida.date().fromString("2024-06-30", "yyyy-MM-dd"))
    dialogo._salvar()

    assert repo.buscar_vinculo(conn, cenario["vinculo"].id).data_saida == "2024-06-30"


def test_desmarcar_saida_reabre_o_vinculo(conn, cenario):
    repo.encerrar_vinculo(conn, cenario["vinculo"].id, "2024-06-30", None)
    dialogo = _dialogo(conn, cenario)
    assert dialogo.saiu.isChecked()

    dialogo.saiu.setChecked(False)
    dialogo._salvar()

    assert repo.buscar_vinculo(conn, cenario["vinculo"].id).data_saida is None


def test_capital_em_branco_fica_sem_valor_informado(conn, cenario):
    """Zero no campo é "não informado": a tabela volta a mostrar a estimativa."""
    dialogo = _dialogo(conn, cenario)
    dialogo.capital.setValue(0)
    dialogo._salvar()
    assert repo.buscar_vinculo(conn, cenario["vinculo"].id).valor_capital is None


def test_erro_ao_salvar_mantem_a_tela_aberta(conn, cenario, monkeypatch):
    """Com erro a pessoa corrige na tela, em vez de perder o que digitou."""
    avisos = []
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *a, **k: avisos.append(a[2]))
    dialogo = _dialogo(conn, cenario)
    dialogo.saiu.setChecked(True)
    dialogo.data_saida.setDate(dialogo.data_saida.date().fromString("2010-01-01", "yyyy-MM-dd"))

    dialogo._salvar()

    assert dialogo.result() != QDialog.Accepted
    assert "anterior à data de entrada" in avisos[0]


def test_excluir_pela_tela_de_edicao_pede_confirmacao(conn, cenario, monkeypatch):
    monkeypatch.setattr(mod.QMessageBox, "question", lambda *a, **k: QMessageBox.No)
    dialogo = _dialogo(conn, cenario)
    dialogo._excluir()
    assert repo.buscar_vinculo(conn, cenario["vinculo"].id) is not None

    monkeypatch.setattr(mod.QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dialogo._excluir()
    assert dialogo.result() == mod._DialogoEditarVinculo.EXCLUIDO
    assert repo.buscar_vinculo(conn, cenario["vinculo"].id) is None


def test_alteracoes_da_empresa_aparecem_para_associar(conn, cenario):
    repo.salvar_alteracao(conn, AlteracaoContratual(
        None, cenario["empresa"], 3, "2018-05-10", "ACME LTDA", 100000, 1000, "Entrada do Fulano"))
    dialogo = _dialogo(conn, cenario)
    rotulos = [dialogo.alteracao_entrada.itemText(i) for i in range(dialogo.alteracao_entrada.count())]
    assert rotulos[0] == "Nenhuma (associar depois)"
    assert "Nº 3 — 10/05/2018 — Entrada do Fulano" in rotulos


# ---------------------------------------------- capital na tabela --


def test_tabela_mostra_capital_informado_ou_a_estimativa(conn, cenario):
    aba = _aba(conn)
    item = aba.tabela_vinculos.item(0, SociosTab.COLUNA_CAPITAL)
    # 1000 cotas de uma empresa de R$ 100.000 em 1000 cotas.
    assert item.text() == "≈ 100.000,00"
    assert "Estimativa" in item.toolTip()

    vinculo = repo.buscar_vinculo(conn, cenario["vinculo"].id)
    vinculo.valor_capital = 75000
    repo.salvar_vinculo(conn, vinculo)
    aba = _aba(conn)
    assert aba.tabela_vinculos.item(0, SociosTab.COLUNA_CAPITAL).text() == "75.000,00"


def test_associar_com_entrada_antiga_avisa_que_nao_cria_alteracao(conn, cenario, monkeypatch):
    monkeypatch.setattr(repo, "_ano_corrente", lambda: 2026)
    outra = repo.salvar_empresa(conn, Empresa(None, "002", "BETA LTDA", "", 1000, 100))
    dialogo = mod._DialogoAssociarEmpresa(conn, cenario["socio"])
    dialogo.empresa.setCurrentIndex(dialogo.empresa.findData(outra))

    dialogo.data_entrada.setDate(dialogo.data_entrada.date().fromString("2015-03-01", "yyyy-MM-dd"))
    assert not dialogo.aviso_alteracao.isHidden()
    assert "associe depois" in dialogo.aviso_alteracao.text()
    assert not dialogo.descricao.isEnabled()

    dialogo.data_entrada.setDate(dialogo.data_entrada.date().fromString("2026-03-01", "yyyy-MM-dd"))
    assert dialogo.aviso_alteracao.isHidden()
    assert dialogo.descricao.isEnabled()


# --------------------------------------------------- larguras --


def test_nenhum_botao_trunca_na_largura_minima_da_janela(conn, cenario):
    """A régua é a janela no seu tamanho mínimo: se couber ali, cabe em
    qualquer uso real. Foi assim que "Cancelar" virou "ancel" antes.

    O estilo do programa é aplicado de propósito: é ele que dá padding aos
    botões, então sem ele a medida sai menor do que a real."""
    from controle_lucros.ui.main_window import MainWindow
    from controle_lucros.ui.theme import build_stylesheet

    QApplication.instance().setStyleSheet(build_stylesheet())
    repo.criar_usuario(conn, "Admin", "admin", "senha123", True)
    janela = MainWindow(conn, repo.listar_usuarios(conn)[0])
    janela.resize(janela.minimumSizeHint().width(), 720)
    janela._ir_para("socios")
    janela.show()

    aba = janela.socios_tab
    aba.tabela.selectRow(0)
    aba.tabela_vinculos.selectRow(0)
    janela.layout().activate()

    botoes = {
        "Novo": aba.btn_novo, "Salvar": aba.btn_salvar, "Cancelar": aba.btn_cancelar,
        "Excluir": aba.btn_excluir, "Associar": aba.btn_associar,
        "Editar vínculo": aba.btn_editar_vinculo, "Informe": aba.btn_informe,
        "Mapa de vínculos": aba.btn_mapa,
    }
    truncados = [nome for nome, b in botoes.items() if b.width() < b.sizeHint().width()]
    assert truncados == [], f"rótulos cortados: {truncados}"
