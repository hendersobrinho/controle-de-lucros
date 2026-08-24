"""O selo: elemento-assinatura do app. Um badge circular estilo carimbo
cartorial que mostra se uma alteração contratual está aberta (editável) ou
fechada (travada) — cadeado aberto em latão vs. selo fechado em vinho."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from .theme import BRASS, PAPER_RAISED, SEAL_RED
from .theme import estado as tema_estado


class Selo(QWidget):
    def __init__(self, numero: int = 0, fechada: bool = False, parent=None):
        super().__init__(parent)
        self._numero = numero
        self._fechada = fechada
        self.setFixedSize(64, 64)
        tema_estado().mudou.connect(self.update)

    def definir_estado(self, numero: int, fechada: bool) -> None:
        self._numero = numero
        self._fechada = fechada
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        cor = QColor(SEAL_RED() if self._fechada else BRASS())
        centro = self.rect().center()
        raio = min(self.width(), self.height()) / 2 - 3

        painter.setPen(QPen(cor, 2))
        painter.setBrush(QColor(PAPER_RAISED()))
        painter.drawEllipse(centro, raio, raio)

        anel = raio - 6
        painter.setPen(QPen(cor, 1))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(centro, anel, anel)

        self._desenhar_cadeado(painter, centro, cor)

        painter.setPen(QPen(cor, 1))
        fonte = QFont()
        fonte.setPointSize(8)
        fonte.setBold(True)
        painter.setFont(fonte)
        rotulo = QRectF(0, self.height() - 16, self.width(), 14)
        painter.drawText(rotulo, Qt.AlignCenter, f"Nº {self._numero}")

    def _desenhar_cadeado(self, painter: QPainter, centro, cor: QColor) -> None:
        largura_corpo, altura_corpo = 16, 12
        corpo = QRectF(
            centro.x() - largura_corpo / 2,
            centro.y() - 4,
            largura_corpo,
            altura_corpo,
        )
        painter.setPen(QPen(cor, 1.5))
        painter.setBrush(cor if self._fechada else Qt.NoBrush)
        painter.drawRoundedRect(corpo, 2, 2)

        arco = QRectF(centro.x() - 6, centro.y() - 14, 12, 14)
        painter.setBrush(Qt.NoBrush)
        if self._fechada:
            painter.drawArc(arco, 0, 180 * 16)
        else:
            arco.translate(5, -2)
            painter.drawArc(arco, 0, 180 * 16)
