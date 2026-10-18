"""A lista à esquerda das telas de Empresas e Sócios.

Uma tabela pra escolher um cadastro pedia que se lesse coluna por coluna —
"Nº empresa", "CNPJ", "Capital social" lado a lado — só pra achar um nome.
Aqui cada cadastro é uma linha de duas camadas: o nome em destaque, que é o
que se procura, e embaixo o que ajuda a confirmar que é ele (documento,
quantos sócios ou empresas). O detalhe completo fica na ficha, à direita.

Desenhada por um delegate, e não com um widget por linha: um escritório
com centenas de sócios rola a lista sem engasgar.
"""
from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRect, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QAbstractItemView, QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate

from .common import pintura_segura
from .theme import ALT_ROW, BRASS, ENTROU_BG, HAIRLINE, INK, INK_MUTED, PAPER_RAISED
from .theme import estado as tema_estado

PAPEL_DETALHE = Qt.UserRole + 1
PAPEL_MARCADOR = Qt.UserRole + 2
PAPEL_APAGADO = Qt.UserRole + 3

ALTURA_LINHA = 56
MARGEM = 14


class _DesenhoFicha(QStyledItemDelegate):
    def sizeHint(self, option, index) -> QSize:  # noqa: N802 (Qt override)
        return QSize(option.rect.width(), ALTURA_LINHA)

    def paint(self, painter: QPainter, option, index: QModelIndex) -> None:
        painter.save()
        try:
            retangulo = option.rect
            selecionado = bool(option.state & QStyle.State_Selected)
            sobre = bool(option.state & QStyle.State_MouseOver)
            apagado = bool(index.data(PAPEL_APAGADO))

            fundo = ENTROU_BG() if selecionado else (ALT_ROW() if sobre else PAPER_RAISED())
            painter.fillRect(retangulo, QColor(fundo))
            if selecionado:
                # A barra dourada à esquerda marca o escolhido mesmo pra quem
                # não distingue bem o tom do fundo.
                painter.fillRect(QRect(retangulo.left(), retangulo.top(), 3, retangulo.height()), QColor(BRASS()))
            painter.setPen(QPen(QColor(HAIRLINE())))
            painter.drawLine(retangulo.left() + MARGEM, retangulo.bottom(), retangulo.right() - MARGEM, retangulo.bottom())

            fonte_base = option.font
            marcador = index.data(PAPEL_MARCADOR) or ""
            fonte_marcador = QFont(fonte_base)
            fonte_marcador.setPixelSize(11)
            largura_marcador = QFontMetrics(fonte_marcador).horizontalAdvance(marcador) + (10 if marcador else 0)

            area = retangulo.adjusted(MARGEM + 4, 8, -MARGEM - largura_marcador, -8)

            titulo = QFont(fonte_base)
            titulo.setPixelSize(14)
            titulo.setWeight(QFont.DemiBold)
            painter.setFont(titulo)
            painter.setPen(QColor(INK_MUTED() if apagado else INK()))
            metricas = QFontMetrics(titulo)
            texto = metricas.elidedText(index.data(Qt.DisplayRole) or "", Qt.ElideRight, area.width())
            painter.drawText(QRect(area.left(), area.top(), area.width(), 20), Qt.AlignLeft | Qt.AlignVCenter, texto)

            detalhe = QFont(fonte_base)
            detalhe.setPixelSize(12)
            painter.setFont(detalhe)
            painter.setPen(QColor(INK_MUTED()))
            metricas = QFontMetrics(detalhe)
            texto = metricas.elidedText(index.data(PAPEL_DETALHE) or "", Qt.ElideRight, area.width())
            painter.drawText(QRect(area.left(), area.top() + 21, area.width(), 18), Qt.AlignLeft | Qt.AlignVCenter, texto)

            if marcador:
                painter.setFont(fonte_marcador)
                painter.drawText(
                    QRect(retangulo.right() - MARGEM - largura_marcador, retangulo.top(), largura_marcador, 30),
                    Qt.AlignRight | Qt.AlignVCenter,
                    marcador,
                )
        finally:
            painter.restore()


class ListaFichas(QListWidget):
    """Lista de cadastros: nome em destaque, detalhe embaixo, marcador à
    direita. O id do registro vai no Qt.UserRole de cada item."""

    def __init__(self, mensagem_vazia: str, parent=None):
        super().__init__(parent)
        self._mensagem_vazia = mensagem_vazia
        self.setProperty("role", "listaFichas")
        self.setItemDelegate(_DesenhoFicha(self))
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setMouseTracking(True)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setUniformItemSizes(True)
        # O texto longo é cortado com "…" no desenho: rolagem lateral só
        # escondia o marcador da direita.
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tema_estado().mudou.connect(self.viewport().update)

    def adicionar(self, registro_id: int, titulo: str, detalhe: str = "", marcador: str = "",
                  apagado: bool = False) -> QListWidgetItem:
        item = QListWidgetItem(titulo)
        item.setData(Qt.UserRole, registro_id)
        item.setData(PAPEL_DETALHE, detalhe)
        item.setData(PAPEL_MARCADOR, marcador)
        item.setData(PAPEL_APAGADO, apagado)
        item.setToolTip(f"{titulo}\n{detalhe}" if detalhe else titulo)
        self.addItem(item)
        return item

    def id_selecionado(self) -> int | None:
        selecionados = self.selectedItems()
        return selecionados[0].data(Qt.UserRole) if selecionados else None

    def selecionar_id(self, registro_id: int | None) -> bool:
        for linha in range(self.count()):
            if self.item(linha).data(Qt.UserRole) == registro_id:
                self.setCurrentRow(linha)
                return True
        return False

    def selectRow(self, linha: int) -> None:  # noqa: N802 — mesmo nome da tabela que esta lista substituiu
        self.setCurrentRow(linha)

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().paintEvent(event)
        if self.count():
            return
        with pintura_segura(self.viewport()) as painter:
            painter.setPen(QColor(INK_MUTED()))
            painter.drawText(self.viewport().rect().adjusted(16, 0, -16, 0), Qt.AlignCenter | Qt.TextWordWrap,
                             self._mensagem_vazia)
