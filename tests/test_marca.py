"""A marca: símbolo desenhado em código, telas de entrada e carregamento."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from controle_lucros.ui import marca
from controle_lucros.ui.icones import pasta_assets


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


def _imagem(desenhar) -> QImage:
    imagem = QImage(256, 256, QImage.Format_ARGB32)
    imagem.fill(Qt.white)
    pintor = QPainter(imagem)
    desenhar(pintor)
    pintor.end()
    return imagem


def test_simbolo_desenhado_bate_com_o_logo_svg():
    """O símbolo é redesenhado em código para poder ser animado; tem que
    continuar sendo o mesmo do arquivo."""
    svg = _imagem(lambda p: QSvgRenderer(str(pasta_assets() / "logo.svg")).render(p, QRectF(0, 0, 256, 256)))
    codigo = _imagem(lambda p: marca.desenhar_simbolo(p, QRectF(0, 0, 256, 256), fundo=marca.MARINHO))
    diferentes = 0
    for x in range(0, 256, 4):
        for y in range(0, 256, 4):
            a, b = QColor(svg.pixel(x, y)), QColor(codigo.pixel(x, y))
            if max(abs(a.red() - b.red()), abs(a.green() - b.green()), abs(a.blue() - b.blue())) > 40:
                diferentes += 1
    assert diferentes < 40  # só a borda antisserrilhada pode divergir


def test_barra_com_altura_zero_nao_aparece():
    imagem = _imagem(lambda p: marca.desenhar_simbolo(p, QRectF(0, 0, 256, 256), alturas=(0, 0, 1)))
    assert QColor(imagem.pixel(85, 140)) == QColor(Qt.white)  # onde fica a 1ª fatia
    assert QColor(imagem.pixel(188, 110)).red() > 200  # a 3ª, laranja, está lá


def test_carregando_devolve_o_resultado_e_o_erro_do_trabalho():
    tela = marca.TelaCarregando()
    tela.mostrar()
    assert tela.executar("Somando…", lambda: 2 + 2) == 4
    with pytest.raises(ZeroDivisionError):
        tela.executar("Dividindo…", lambda: 1 / 0)
    tela.esconder()


def test_carregando_desenha_em_qualquer_momento_da_animacao():
    import time
    tela = marca.TelaCarregando()
    for ms in (0, 200, 600, 1500, 5000):
        tela._inicio = time.monotonic() - ms / 1000
        assert not tela.grab().isNull()


def test_tela_de_entrada_tem_painel_e_formulario():
    tela = marca.TelaDeEntrada("Teste", "Frase", "Texto")
    tela.cabecalho("Título", "Subtítulo")
    assert tela.painel.titulo == "Frase"
    assert "Teste — Controle de Lucros" == tela.windowTitle()


# ------------------------------------------------ Enter nas telas de entrada --


def test_enter_na_senha_da_conexao_salva_uma_vez_so(monkeypatch):
    from controle_lucros.ui import local_banco

    chamadas = []
    monkeypatch.setattr(local_banco.DialogoConexao, "_salvar", lambda self: chamadas.append(1))
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    tela = local_banco.DialogoConexao(primeira_vez=True)
    tela.show()
    for campo in (tela.senha, tela.servidor, tela.banco, tela.usuario):
        chamadas.clear()
        campo.setFocus()
        QTest.keyClick(campo, Qt.Key_Return)
        assert chamadas == [1], campo.objectName()
    tela.hide()


def test_enter_no_login_e_no_primeiro_acesso_roda_uma_vez_so(conn, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from controle_lucros.ui import login

    for classe, metodo, campo in ((login.DialogoLogin, "_entrar", "senha"),
                                  (login.DialogoPrimeiroUsuario, "_criar", "confirmar")):
        chamadas = []
        monkeypatch.setattr(classe, metodo, lambda self: chamadas.append(1))
        tela = classe(conn)
        tela.show()
        getattr(tela, campo).setFocus()
        QTest.keyClick(getattr(tela, campo), Qt.Key_Return)
        assert chamadas == [1], classe.__name__
        # Enter no campo de login só passa para a senha, não tenta entrar.
        if classe is login.DialogoLogin:
            chamadas.clear()
            tela.login.setFocus()
            QTest.keyClick(tela.login, Qt.Key_Return)
            assert chamadas == [] and tela.focusWidget() is tela.senha
        tela.hide()


def test_banco_indisponivel_enter_tenta_de_novo(monkeypatch):
    import psycopg
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from controle_lucros.ui import local_banco

    tela = local_banco.DialogoBancoInacessivel(psycopg.OperationalError("connection timeout expired"))
    tela.show()
    QTest.keyClick(tela, Qt.Key_Return)
    assert tela.result() == tela.TENTAR_DE_NOVO
