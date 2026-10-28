"""O programa não herda cores do sistema.

No Windows 11 com o modo escuro ligado, o Qt usava o estilo "windows11" e a
paleta escura do Windows: com o programa no modo claro, campos de número
ficavam com texto branco em fundo branco. Estes testes simulam a paleta do
Windows escuro e conferem que o tema do programa se sobrepõe a ela.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDoubleSpinBox, QLineEdit

from controle_lucros.ui import theme


@pytest.fixture()
def app_com_windows_escuro():
    app = QApplication.instance() or QApplication([])
    # Trocar paleta e estilo do aplicativo refaz toda janela que existir; as
    # que os testes anteriores deixaram para trás tornavam cada teste daqui
    # lento (15 s na suíte inteira). Fechadas antes, não pesam.
    from PySide6.QtCore import QCoreApplication, QEvent
    for janela in app.topLevelWidgets():
        janela.close()
        janela.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    original = (app.palette(), app.styleSheet(), theme.estado().modo)
    escura = QPalette()
    for papel in (QPalette.Text, QPalette.WindowText, QPalette.ButtonText, QPalette.PlaceholderText):
        escura.setColor(papel, QColor("#FFFFFF"))
    for papel in (QPalette.Base, QPalette.Window, QPalette.Button):
        escura.setColor(papel, QColor("#202020"))
    app.setPalette(escura)
    theme.estado().modo = "claro"
    yield app
    theme.estado().modo = original[2]
    app.setPalette(original[0])
    app.setStyleSheet(original[1])


def _escuros(imagem) -> int:
    return sum(
        QColor(imagem.pixel(x, y)).lightness() < 110
        for x in range(4, imagem.width() - 24) for y in range(3, imagem.height() - 3)
    )


def test_tema_claro_vence_o_windows_escuro(app_com_windows_escuro):
    app = app_com_windows_escuro
    theme.aplicar(app)
    paleta = theme.estado().paleta()
    # Com folha de estilo ativa o Qt embrulha o estilo e esconde o nome; sem
    # ela, aparece o de baixo.
    folha = app.styleSheet()
    app.setStyleSheet("")
    assert app.style().name().lower() == "fusion"
    app.setStyleSheet(folha)
    assert app.palette().color(QPalette.Text) == QColor(paleta["INK"])
    assert app.palette().color(QPalette.Base) == QColor(paleta["PAPER_RAISED"])
    assert app.palette().color(QPalette.PlaceholderText) == QColor(paleta["INK_MUTED"])
    # Na plataforma sem tela dos testes o Qt não guarda o esquema pedido
    # (fica "Unknown"); no Windows, fica o que o programa pediu.
    assert app.styleHints().colorScheme() in (Qt.ColorScheme.Light, Qt.ColorScheme.Unknown)


def test_numero_aparece_no_campo(app_com_windows_escuro):
    """O caso relatado: o número sumia do campo."""
    theme.aplicar(app_com_windows_escuro)
    campo = QDoubleSpinBox()
    campo.setRange(0, 1_000_000)
    campo.setValue(888888)
    campo.resize(220, 40)
    campo.show()
    app_com_windows_escuro.processEvents()
    assert _escuros(campo.grab().toImage()) > 40  # há texto escuro (o número) no fundo claro


def test_dica_do_campo_vazio_nao_fica_branca(app_com_windows_escuro):
    theme.aplicar(app_com_windows_escuro)
    campo = QLineEdit()
    campo.setPlaceholderText("MMMMMMMM")
    assert campo.palette().color(QPalette.PlaceholderText).lightness() < 200


def test_modo_escuro_do_programa_tambem_se_impoe(app_com_windows_escuro):
    app = app_com_windows_escuro
    theme.estado().modo = "escuro"
    theme.aplicar(app)
    assert app.palette().color(QPalette.Text) == QColor(theme.PALETA_ESCURA["INK"])
    assert app.palette().color(QPalette.Base) == QColor(theme.PALETA_ESCURA["PAPER_RAISED"])
    assert app.styleHints().colorScheme() in (Qt.ColorScheme.Dark, Qt.ColorScheme.Unknown)
