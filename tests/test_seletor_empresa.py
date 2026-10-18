"""Escolher empresa por código ou por nome, com F2 abrindo a busca."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from controle_lucros import repositories as repo
from controle_lucros.models import Empresa
from controle_lucros.ui import seletor_empresa as mod
from controle_lucros.ui.seletor_empresa import DialogoBuscaEmpresa, SeletorEmpresa


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def seletor(conn):
    repo.salvar_empresa(conn, Empresa(None, "042", "ACME LTDA", "11.222.333/0001-81", 0, 0))
    repo.salvar_empresa(conn, Empresa(None, "7", "BETA COMERCIO LTDA", "", 0, 0))
    repo.salvar_empresa(conn, Empresa(None, "105", "CLINICA BOA SAUDE", "", 0, 0))
    seletor = SeletorEmpresa()
    seletor.definir_empresas(repo.listar_empresas(conn))
    return seletor


def test_comeca_na_primeira_como_a_lista_suspensa(seletor):
    assert seletor.currentText() == "ACME LTDA"
    assert seletor.codigo.text() == "042"


def test_digitar_o_codigo_escolhe_a_empresa(seletor):
    mudancas = []
    seletor.currentIndexChanged.connect(mudancas.append)
    seletor.codigo.setText("105")
    seletor.codigo.returnPressed.emit()
    assert seletor.currentText() == "CLINICA BOA SAUDE"
    assert seletor.nome.text() == "CLINICA BOA SAUDE"
    assert mudancas == [2]


def test_codigo_sem_zeros_a_esquerda_tambem_acha(seletor):
    seletor.codigo.setText("42")
    seletor.codigo.returnPressed.emit()
    assert seletor.currentText() == "ACME LTDA"
    seletor.codigo.setText("0007")
    seletor.codigo.returnPressed.emit()
    assert seletor.currentText() == "BETA COMERCIO LTDA"


def test_codigo_que_nao_existe_avisa_e_nao_muda(seletor):
    seletor.codigo.setText("999")
    seletor.codigo.returnPressed.emit()
    assert seletor.currentText() == "ACME LTDA"
    assert "999" in seletor.codigo.toolTip()


def test_f2_abre_a_busca_e_escolhe(seletor, monkeypatch):
    abertas = []

    def escolher_clinica(self):
        abertas.append(self.busca.text())
        self.busca.setText("clinica")
        self._escolher()
        return QDialog.Accepted
    monkeypatch.setattr(mod.DialogoBuscaEmpresa, "exec", escolher_clinica)
    QTest.keyClick(seletor.codigo, Qt.Key_F2)
    assert abertas == [""]
    assert seletor.currentText() == "CLINICA BOA SAUDE"


def test_enter_no_nome_busca_pelo_que_foi_digitado(seletor, monkeypatch):
    termos = []
    monkeypatch.setattr(mod.DialogoBuscaEmpresa, "exec", lambda self: termos.append(self.busca.text()) or QDialog.Rejected)
    seletor.nome.setText("beta")
    seletor.nome.returnPressed.emit()
    assert termos == ["beta"]
    # Cancelou: continua a empresa de antes, com o nome dela no campo.
    assert seletor.nome.text() == "ACME LTDA"


def test_busca_filtra_por_nome_codigo_e_cnpj(conn, seletor):
    dialogo = DialogoBuscaEmpresa(repo.listar_empresas(conn))
    nomes = lambda: [dialogo.lista.item(i).text() for i in range(dialogo.lista.count())]  # noqa: E731
    dialogo.busca.setText("saude")
    assert nomes() == ["CLINICA BOA SAUDE"]
    dialogo.busca.setText("7")
    assert nomes() == ["BETA COMERCIO LTDA"]
    dialogo.busca.setText("11222333")
    assert nomes() == ["ACME LTDA"]


def test_definir_de_novo_mantem_a_escolhida(conn, seletor):
    seletor.selecionar_id(repo.listar_empresas(conn)[2].id)
    seletor.definir_empresas(repo.listar_empresas(conn))
    assert seletor.currentText() == "CLINICA BOA SAUDE"
