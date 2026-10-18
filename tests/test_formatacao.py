"""Como números e datas aparecem na tela — o mesmo formato em todo o programa."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from controle_lucros.ui.common import campo_cotas, campo_percentual, formatar_data_br, formatar_percentual


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("valor, esperado", [
    (46.94, "46,9400%"),
    (100, "100,0000%"),
    (0, "0,0000%"),
    (None, "0,0000%"),
    (46.9, "46,9000%"),
    # Sociedade dividida em três: cortar em duas casas faria a soma dos
    # sócios não fechar 100% na tela.
    (33.3333, "33,3333%"),
    (12.3456789, "12,3457%"),
])
def test_percentual_sempre_com_simbolo_e_quatro_casas(valor, esperado):
    assert formatar_percentual(valor) == esperado


@pytest.mark.parametrize("iso, esperado", [
    ("2007-03-23", "23/03/2007"),
    ("2024-01-01T10:00:00", "01/01/2024"),
    (None, "—"),
    ("", "—"),
])
def test_data_no_formato_de_quem_le(iso, esperado):
    assert formatar_data_br(iso) == esperado


def test_campo_de_percentual_escreve_igual_a_tela():
    campo = campo_percentual()
    for valor, texto in ((46.94, "46,9400 %"), (100, "100,0000 %"), (33.3333, "33,3333 %")):
        campo.setValue(valor)
        assert campo.text() == texto


def test_campo_de_percentual_aceita_digitar_com_virgula():
    campo = campo_percentual()
    campo.lineEdit().setText("12,5 %")
    campo.interpretText()
    assert campo.value() == 12.5


def test_campo_de_cotas_sem_virgula_quando_e_inteiro():
    campo = campo_cotas()
    campo.setValue(1500)
    assert campo.text() == "1.500"
    campo.setValue(10.5)
    assert campo.text() == "10,5"


@pytest.mark.parametrize("digitado, esperado", [
    ("1500000", "1.500.000"),
    ("1.500.000,5", "1.500.000,5"),
    ("1500000,567", "1.500.000,56"),
    ("0001234", "1.234"),
    (",5", "0,5"),
    ("12.34", "1.234"),   # ponto digitado é ignorado: o milhar é a tela que põe
    ("", ""),
])
def test_formatar_digitacao(digitado, esperado):
    from controle_lucros.ui.common import formatar_digitacao
    assert formatar_digitacao(digitado, 2)[0] == esperado


def test_campo_de_dinheiro_formata_enquanto_digita():
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDoubleSpinBox
    from controle_lucros.ui.common import configurar_campo_moeda

    campo = configurar_campo_moeda(QDoubleSpinBox())
    campo.lineEdit().selectAll()
    QTest.keyClicks(campo.lineEdit(), "1500000")
    assert campo.text() == "R$ 1.500.000"
    QTest.keyClicks(campo.lineEdit(), ",5")
    assert campo.text() == "R$ 1.500.000,5"
    assert campo.value() == 1500000.5
    QTest.keyClick(campo.lineEdit(), Qt.Key_Return)
    assert campo.text() == "R$ 1.500.000,50"
