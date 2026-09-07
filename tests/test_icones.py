"""Ícone do programa.

Estes testes existem porque o problema anterior era silencioso: o Qt não
aplica o clipPath do SVG, então a "sombra longa" do desenho vazava pra fora
do círculo e virava um retângulo cinza — sem erro nenhum, só feio.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import struct

import pytest
from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication

from controle_lucros.ui.icones import caminho_ico, icone_app, pasta_assets

TAMANHOS_ESPERADOS = [16, 20, 24, 32, 40, 48, 64, 96, 128, 256]


@pytest.fixture(scope="module", autouse=True)
def app():
    aplicativo = QApplication.instance() or QApplication([])
    yield aplicativo


def _render_svg(tamanho: int) -> QImage:
    imagem = QImage(QSize(tamanho, tamanho), QImage.Format_ARGB32)
    imagem.fill(Qt.transparent)
    pintor = QPainter(imagem)
    pintor.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(str(pasta_assets() / "logo.svg")).render(pintor, QRectF(0, 0, tamanho, tamanho))
    pintor.end()
    return imagem


# ------------------------------------------------------------------ SVG --


def test_nada_e_desenhado_fora_do_circulo():
    """O desenho todo cabe no círculo. A sombra antiga vazava num quadrante,
    parando antes dos cantos da imagem — por isso o teste varre o entorno
    inteiro em vez de conferir só os quatro cantos."""
    imagem = _render_svg(256)
    centro = 256 * 340 / 680  # centro do círculo no viewBox, em pixels
    raio = 256 * 300 / 680  # raio externo; +3px de folga pro antialiasing
    fora = [
        (x, y)
        for y in range(imagem.height())
        for x in range(imagem.width())
        if ((x - centro) ** 2 + (y - centro) ** 2) ** 0.5 > raio + 3
        and imagem.pixelColor(x, y).alpha() > 0
    ]
    assert fora == [], f"{len(fora)} pixels pintados fora do círculo, a partir de {fora[0]}"


def test_o_desenho_e_simetrico_entre_a_metade_de_cima_e_a_de_baixo():
    """A sombra longa descia na diagonal e engordava só a metade de baixo: no
    desenho antigo a diferença era de 322 pixels amostrados, contra 44 do
    atual (que vêm do relevo do cifrão e do antialiasing)."""
    imagem = _render_svg(256)
    metade = imagem.height() // 2
    opacos = lambda inicio, fim: sum(  # noqa: E731
        imagem.pixelColor(x, y).alpha() > 0
        for y in range(inicio, fim, 4)
        for x in range(0, imagem.width(), 4)
    )
    assert abs(opacos(0, metade) - opacos(metade, imagem.height())) < 120


def test_o_svg_nao_usa_recurso_que_o_qt_ignora():
    """clipPath não é suportado pelo renderizador SVG do Qt: o que estiver
    dentro dele aparece inteiro, sem recorte. Melhor não depender disso."""
    svg = (pasta_assets() / "logo.svg").read_text(encoding="utf-8")
    assert "clipPath" not in svg
    assert "clip-path" not in svg


# ------------------------------------------------------------------ ICO --


def test_o_ico_tem_todas_as_resolucoes():
    """Faltando um tamanho, o Windows redimensiona o mais próximo na hora —
    que é o ícone embaçado na área de trabalho."""
    icone = QIcon(str(caminho_ico()))
    assert sorted(s.width() for s in icone.availableSizes()) == TAMANHOS_ESPERADOS


def test_as_entradas_do_ico_batem_com_o_cabecalho():
    """O .ico é montado à mão; um deslocamento errado gera arquivo que abre
    em algumas ferramentas e falha em outras."""
    dados = caminho_ico().read_bytes()
    reservado, tipo, quantidade = struct.unpack("<HHH", dados[:6])
    assert (reservado, tipo) == (0, 1)
    assert quantidade == len(TAMANHOS_ESPERADOS)

    for i in range(quantidade):
        entrada = dados[6 + i * 16 : 6 + (i + 1) * 16]
        largura, altura, cores, _res, planos, bits, tamanho, deslocamento = struct.unpack(
            "<BBBBHHII", entrada
        )
        esperado = TAMANHOS_ESPERADOS[i]
        assert largura == (0 if esperado >= 256 else esperado)
        assert altura == largura
        assert (cores, planos, bits) == (0, 1, 32)
        assert deslocamento + tamanho <= len(dados)
        # Entradas em PNG, como o Windows aceita desde o Vista.
        assert dados[deslocamento : deslocamento + 8] == b"\x89PNG\r\n\x1a\n"


def test_cada_tamanho_do_ico_foi_desenhado_no_proprio_tamanho():
    """Reduzir um PNG grande borra os traços finos nos tamanhos pequenos. Se
    o 16x16 veio do vetor, ele bate com o vetor renderizado em 16x16."""
    icone = QIcon(str(caminho_ico()))
    for tamanho in (16, 32, 48):
        do_ico = icone.pixmap(QSize(tamanho, tamanho)).toImage().convertToFormat(QImage.Format_ARGB32)
        do_vetor = _render_svg(tamanho)
        diferencas = sum(
            abs(do_ico.pixelColor(x, y).alpha() - do_vetor.pixelColor(x, y).alpha()) > 40
            for y in range(tamanho)
            for x in range(tamanho)
        )
        assert diferencas <= tamanho, f"{tamanho}x{tamanho} destoa do vetor em {diferencas} pixels"


# ------------------------------------------------------------ no programa --


def test_icone_do_app_traz_todos_os_tamanhos():
    icone = icone_app()
    assert not icone.isNull()
    assert sorted(s.width() for s in icone.availableSizes()) == TAMANHOS_ESPERADOS


def test_logo_png_continua_disponivel_como_reserva():
    imagem = QImage(str(pasta_assets() / "logo.png"))
    assert not imagem.isNull()
    assert imagem.width() >= 256
    assert imagem.hasAlphaChannel()
