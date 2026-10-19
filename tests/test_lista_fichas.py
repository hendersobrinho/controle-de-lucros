"""A lista à esquerda das telas de Empresas e Sócios, usada com o mouse.

Os outros testes escolhem a linha por código (selectRow), e por esse caminho
o Qt marca o item como atual e como selecionado de uma vez. O clique do
mouse não: ele avisa que o item atual mudou ANTES de selecioná-lo — e a ficha
da direita ficava vazia ao clicar numa empresa ou num sócio. Por isso aqui o
clique é de verdade.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from controle_lucros import repositories as repo
from controle_lucros.models import Empresa, Socio, VinculoSocietario
from controle_lucros.ui.empresas_tab import EmpresasTab
from controle_lucros.ui.socios_tab import SociosTab


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def cenario(conn):
    acme = repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 100000, 1000))
    repo.salvar_empresa(conn, Empresa(None, "002", "BETA LTDA", "", 50000, 500))
    fulano = repo.salvar_socio(conn, Socio(None, "FULANO DE TAL", "005.169.717-35"))
    repo.salvar_socio(conn, Socio(None, "ZECA SEM EMPRESA", ""))
    repo.salvar_vinculo(conn, VinculoSocietario(None, acme, fulano, 100, 1000, "2020-01-01", None))
    return {"acme": acme, "fulano": fulano}


def _clicar(tela, linha: int) -> None:
    tela.resize(1200, 700)
    tela.show()
    QApplication.processEvents()
    lista = tela.lista
    centro = lista.visualItemRect(lista.item(linha)).center()
    QTest.mouseClick(lista.viewport(), Qt.LeftButton, Qt.NoModifier, centro)
    QApplication.processEvents()


def test_clicar_numa_empresa_mostra_a_ficha(conn, cenario):
    tela = EmpresasTab(conn)
    _clicar(tela, 0)  # ACME
    assert tela._empresa_atual_id == cenario["acme"]
    assert not tela.rolagem.isHidden()
    assert tela.painel_vazio.isHidden()
    assert tela.titulo_empresa.text() == "ACME LTDA"


def test_clicar_num_socio_mostra_a_ficha(conn, cenario):
    tela = SociosTab(conn)
    _clicar(tela, 0)  # Fulano de Tal
    assert tela._socio_atual_id == cenario["fulano"]
    assert tela.titulo_socio.text() == "FULANO DE TAL"
    assert len(tela.cartoes) == 1


def test_clicar_em_outro_troca_a_ficha(conn, cenario):
    tela = EmpresasTab(conn)
    _clicar(tela, 0)
    _clicar(tela, 1)
    assert tela.titulo_empresa.text() == "BETA LTDA"


def test_setas_do_teclado_tambem_trocam_a_ficha(conn, cenario):
    tela = SociosTab(conn)
    _clicar(tela, 0)
    QTest.keyClick(tela.lista, Qt.Key_Down)
    QApplication.processEvents()
    assert tela.titulo_socio.text() == "ZECA SEM EMPRESA"
