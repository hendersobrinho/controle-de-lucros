import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3

import pytest
from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from controle_lucros import db, repositories as repo
from controle_lucros.models import Empresa, Socio
from controle_lucros.ui import distribuicao_anual_view as mod
from controle_lucros.ui.distribuicao_anual_view import DistribuicaoAnualView


@pytest.fixture(scope="module", autouse=True)
def app():
    aplicativo = QApplication.instance() or QApplication([])
    yield aplicativo


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    db.init_schema(connection)
    yield connection
    connection.close()


@pytest.fixture()
def cenario(conn):
    empresa_id = repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 100000, 1000))
    s1 = repo.salvar_socio(conn, Socio(None, "Fulano de Tal", "111.111.111-11"))
    s2 = repo.salvar_socio(conn, Socio(None, "Beltrano da Silva", "222.222.222-22"))
    repo.associar_socio_a_empresa(conn, empresa_id, s1, 60.0, 600, "2023-01-01")
    repo.associar_socio_a_empresa(conn, empresa_id, s2, 40.0, 400, "2023-01-01")
    repo.salvar_distribuicao(conn, empresa_id, 2025, s1, 10000)
    repo.salvar_distribuicao(conn, empresa_id, 2025, s2, 8000)
    return {"empresa_id": empresa_id, "s1": s1, "s2": s2}


def _view(conn):
    view = DistribuicaoAnualView(conn)
    view.ano.setValue(2025)
    return view


def _linha(view, socio_id):
    idx = next(i for i, l in enumerate(view._linhas) if l["socio_id"] == socio_id)
    return idx, view._linhas[idx]


def test_editar_alterna_botoes_e_bloqueia_combo(conn, cenario):
    view = _view(conn)
    view.show()
    assert view.btn_editar.isVisible() and not view.btn_salvar_edicao.isVisible()

    view._iniciar_edicao()
    assert not view.btn_editar.isVisible() and view.btn_salvar_edicao.isVisible()
    assert not view.empresa.isEnabled()
    assert not view.ano.isEnabled()

    view._cancelar_edicao()
    assert view.btn_editar.isVisible() and not view.btn_salvar_edicao.isVisible()
    assert view.empresa.isEnabled()


def test_editar_valor_distribuido_nao_pede_data(conn, cenario, monkeypatch):
    view = _view(conn)
    view._iniciar_edicao()
    idx, _ = _linha(view, cenario["s1"])
    view._widgets_edicao[idx]["valor"].setValue(15000)

    chamou_dialogo = {"sim": False}
    monkeypatch.setattr(mod, "_DialogoDataVigencia", lambda parent=None: chamou_dialogo.__setitem__("sim", True))
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

    view._salvar_edicao()

    assert chamou_dialogo["sim"] is False
    (dist,) = [d for d in repo.listar_distribuicoes(conn, cenario["empresa_id"], 2025) if d.socio_id == cenario["s1"]]
    assert dist.valor_distribuido == 15000


def test_editar_percentual_pede_data_e_gera_alteracao(conn, cenario, monkeypatch):
    view = _view(conn)
    alteracoes_antes = len(repo.listar_alteracoes(conn, cenario["empresa_id"]))

    view._iniciar_edicao()
    idx, _ = _linha(view, cenario["s1"])
    view._widgets_edicao[idx]["percentual"].setValue(70.0)
    view._widgets_edicao[idx]["cotas"].setValue(700)

    class DialogoFake:
        def __init__(self, parent=None):
            self.data = type("D", (), {"date": lambda self: QDate(2025, 6, 1)})()

        def exec(self):
            return QDialog.Accepted

    monkeypatch.setattr(mod, "_DialogoDataVigencia", DialogoFake)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

    view._salvar_edicao()

    linhas = repo.panorama_distribuicao_anual(conn, cenario["empresa_id"], 2025)
    (linha_s1,) = [l for l in linhas if l["socio_id"] == cenario["s1"]]
    assert linha_s1["percentual_capital"] == 70.0
    assert linha_s1["quantidade_cotas"] == 700
    assert len(repo.listar_alteracoes(conn, cenario["empresa_id"])) == alteracoes_antes + 1


def test_cancelar_data_vigencia_nao_aplica_nada(conn, cenario, monkeypatch):
    view = _view(conn)
    view._iniciar_edicao()
    idx, _ = _linha(view, cenario["s1"])
    view._widgets_edicao[idx]["percentual"].setValue(70.0)

    class DialogoRejeitado:
        def __init__(self, parent=None):
            pass

        def exec(self):
            return QDialog.Rejected

    monkeypatch.setattr(mod, "_DialogoDataVigencia", DialogoRejeitado)

    view._salvar_edicao()

    linhas = repo.panorama_distribuicao_anual(conn, cenario["empresa_id"], 2025)
    (linha_s1,) = [l for l in linhas if l["socio_id"] == cenario["s1"]]
    assert linha_s1["percentual_capital"] == 60.0  # nao mudou


def test_editar_data_saida_encerra_vinculo(conn, cenario, monkeypatch):
    view = _view(conn)
    view._iniciar_edicao()
    idx, _ = _linha(view, cenario["s2"])
    view._widgets_edicao[idx]["data_saida"].setDate(QDate(2025, 9, 15))

    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    view._salvar_edicao()

    linhas = repo.panorama_distribuicao_anual(conn, cenario["empresa_id"], 2025)
    (linha_s2,) = [l for l in linhas if l["socio_id"] == cenario["s2"]]
    assert linha_s2["data_saida"] == "2025-09-15"


def test_salvar_sem_mudancas_nao_altera_nada(conn, cenario, monkeypatch):
    avisos = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda self, titulo, msg: avisos.append(msg)))

    view = _view(conn)
    view._iniciar_edicao()
    view._salvar_edicao()

    assert avisos == ["Nenhuma alteração pra salvar."]


def test_periodo_trancado_desabilita_editar(conn, cenario):
    repo.fechar_periodo(conn, cenario["empresa_id"], 2025)
    view = _view(conn)
    assert view.btn_editar.isEnabled() is False
