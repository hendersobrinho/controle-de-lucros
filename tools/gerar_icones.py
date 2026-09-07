"""Gera logo.png e logo.ico a partir de logo.svg.

Rodar depois de mexer no SVG:

    python tools/gerar_icones.py

Cada tamanho do .ico é renderizado direto do vetor, não reduzido a partir de
um PNG grande: reduzir borra os traços finos nos tamanhos pequenos, que são
justamente os que aparecem na barra de tarefas e na lista de arquivos.

O .ico é montado à mão porque o Qt só grava um tamanho por arquivo, e um
ícone com um tamanho só faz o Windows redimensionar na hora — que é o
resultado embaçado que se quer evitar.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS = Path(__file__).resolve().parent.parent / "controle_lucros" / "ui" / "assets"
SVG = ASSETS / "logo.svg"

# 16/32/48/256 são os que o Windows usa nas visualizações padrão; 20/40/64/96
# entram para as escalas de tela (125%, 150%, 200%) não caírem num
# redimensionamento em tempo de execução.
TAMANHOS_ICO = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
TAMANHO_PNG = 512


def renderizar(tamanho: int) -> QImage:
    imagem = QImage(QSize(tamanho, tamanho), QImage.Format_ARGB32)
    imagem.fill(Qt.transparent)
    pintor = QPainter(imagem)
    pintor.setRenderHint(QPainter.Antialiasing)
    pintor.setRenderHint(QPainter.SmoothPixmapTransform)
    QSvgRenderer(str(SVG)).render(pintor, QRectF(0, 0, tamanho, tamanho))
    pintor.end()
    return imagem


def _png_em_bytes(imagem: QImage) -> bytes:
    # O QByteArray precisa de nome próprio: passado direto como temporário,
    # ele é destruído e o QBuffer fica apontando pra memória liberada.
    dados = QByteArray()
    buffer = QBuffer(dados)
    buffer.open(QBuffer.WriteOnly)
    imagem.save(buffer, "PNG")
    buffer.close()
    return bytes(dados)


def gravar_ico(caminho: Path, tamanhos: tuple[int, ...]) -> None:
    imagens = [_png_em_bytes(renderizar(t)) for t in tamanhos]

    cabecalho = struct.pack("<HHH", 0, 1, len(tamanhos))  # reservado, tipo=ícone, quantidade
    deslocamento = len(cabecalho) + 16 * len(tamanhos)
    entradas, corpo = b"", b""
    for tamanho, dados in zip(tamanhos, imagens):
        entradas += struct.pack(
            "<BBBBHHII",
            0 if tamanho >= 256 else tamanho,  # 256 é gravado como 0 no formato
            0 if tamanho >= 256 else tamanho,
            0,  # paleta: 0 = sem paleta indexada
            0,  # reservado
            1,  # planos de cor
            32,  # bits por pixel
            len(dados),
            deslocamento,
        )
        corpo += dados
        deslocamento += len(dados)
    caminho.write_bytes(cabecalho + entradas + corpo)


def main() -> None:
    app = QGuiApplication(sys.argv)  # noqa: F841 - QSvgRenderer exige aplicação viva
    renderizar(TAMANHO_PNG).save(str(ASSETS / "logo.png"), "PNG")
    gravar_ico(ASSETS / "logo.ico", TAMANHOS_ICO)
    print(f"logo.png {TAMANHO_PNG}x{TAMANHO_PNG}")
    print("logo.ico " + ", ".join(f"{t}x{t}" for t in TAMANHOS_ICO))


if __name__ == "__main__":
    main()
