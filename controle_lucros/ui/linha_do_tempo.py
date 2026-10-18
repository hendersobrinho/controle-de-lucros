"""A linha do tempo das alterações contratuais de uma empresa.

Cada alteração é um selo sobre uma linha, da mais antiga (à esquerda) à mais
recente, com o número dentro e a data embaixo — lê-se a história do contrato
de uma olhada, e um clique leva a qualquer uma delas, sem passar página por
página. As que não foram cadastradas aparecem como trecho tracejado ("Nº 1 a
6 não registradas"): o escritório começa do contrato de hoje, e a linha diz
isso em vez de fingir que a história começa na Nº 7. No fim, o selo "+"
cadastra a próxima.

Selo dourado é alteração aberta; vinho, fechada (com o cadeado) — as mesmas
cores do selo grande da ficha.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from .common import formatar_data_br, pintura_segura
from .theme import BRASS, BRASS_DARK, INK, INK_MUTED, PAPER_RAISED, SEAL_RED
from .theme import estado as tema_estado

RAIO = 17
RAIO_ESCOLHIDO = 23
ESPACO_MINIMO = 118
MARGEM = 56
ALTURA = 98
Y_LINHA = 42


@dataclass
class _Marco:
    alteracao_id: int | None  # None = o selo "+" de nova alteração
    numero: int
    data: str
    fechada: bool
    descricao: str
    x: float = 0.0


class LinhaDoTempo(QWidget):
    escolhida = Signal(int)
    nova = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._marcos: list[_Marco] = []
        self._escolhida_id: int | None = None
        self._sobre: int | None = None  # índice do marco sob o mouse
        self._pode_criar = False
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(ALTURA)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tema_estado().mudou.connect(self.update)

    # ------------------------------------------------------------ dados --
    def definir(self, alteracoes: list, escolhida_id: int | None, pode_criar: bool = True) -> None:
        ordenadas = sorted(alteracoes, key=lambda a: (a.data, a.numero))
        self._marcos = [_Marco(a.id, a.numero, a.data, a.fechada, a.descricao or "") for a in ordenadas]
        self._pode_criar = pode_criar
        if pode_criar:
            proximo = max((a.numero for a in ordenadas), default=0) + 1
            self._marcos.append(_Marco(None, proximo, "", False, ""))
        self._escolhida_id = escolhida_id
        self._sobre = None
        self.setMinimumWidth(MARGEM * 2 + max(0, len(self._marcos) - 1) * ESPACO_MINIMO + 40)
        self._posicionar()
        self.update()

    def escolher(self, alteracao_id: int | None) -> None:
        self._escolhida_id = alteracao_id
        self.update()

    def ids(self) -> list[int]:
        return [m.alteracao_id for m in self._marcos if m.alteracao_id is not None]

    def posicao_do_marco(self, alteracao_id: int | None) -> QPointF | None:
        """Centro do selo — pros testes clicarem como o mouse clicaria."""
        for m in self._marcos:
            if m.alteracao_id == alteracao_id:
                return QPointF(m.x, Y_LINHA)
        return None

    def _tem_lacuna_inicial(self) -> bool:
        reais = [m for m in self._marcos if m.alteracao_id is not None]
        return bool(reais) and min(m.numero for m in reais) > 1

    def _posicionar(self) -> None:
        if not self._marcos:
            return
        inicio = MARGEM + (96 if self._tem_lacuna_inicial() else 0)
        fim = self.width() - MARGEM
        if len(self._marcos) == 1:
            self._marcos[0].x = inicio if self._tem_lacuna_inicial() else self.width() / 2
            return
        passo = max(ESPACO_MINIMO, (fim - inicio) / (len(self._marcos) - 1))
        # Poucas alterações não se espalham pela tela inteira: com passo
        # gigante a linha parece vazia e os selos ficam longe do olho.
        passo = min(passo, 220)
        largura_total = passo * (len(self._marcos) - 1)
        if not self._tem_lacuna_inicial():
            inicio = max(MARGEM, (self.width() - largura_total) / 2)
        for i, m in enumerate(self._marcos):
            m.x = inicio + i * passo

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self._posicionar()

    # ----------------------------------------------------------- mouse --
    def _marco_em(self, ponto) -> int | None:
        for i, m in enumerate(self._marcos):
            dx, dy = ponto.x() - m.x, ponto.y() - Y_LINHA
            if dx * dx + dy * dy <= (RAIO_ESCOLHIDO + 6) ** 2 or (abs(dx) < 46 and Y_LINHA < ponto.y() < ALTURA - 4):
                return i
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        indice = self._marco_em(event.position())
        if indice != self._sobre:
            self._sobre = indice
            self.setCursor(Qt.PointingHandCursor if indice is not None else Qt.ArrowCursor)
            self.update()
        if indice is not None:
            m = self._marcos[indice]
            if m.alteracao_id is None:
                dica = f"Cadastrar a alteração Nº {m.numero}"
            else:
                dica = f"Alteração Nº {m.numero} — {formatar_data_br(m.data)}"
                if m.descricao:
                    dica += f"\n{m.descricao}"
                if m.fechada:
                    dica += "\n(período fechado)"
            QToolTip.showText(event.globalPosition().toPoint(), dica, self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._sobre = None
        self.update()

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() != Qt.LeftButton:
            return
        indice = self._marco_em(event.position())
        if indice is None:
            return
        self._ativar(self._marcos[indice])

    def _ativar(self, marco: _Marco) -> None:
        if marco.alteracao_id is None:
            self.nova.emit()
        elif marco.alteracao_id != self._escolhida_id:
            self._escolhida_id = marco.alteracao_id
            self.update()
            self.escolhida.emit(marco.alteracao_id)

    def keyPressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        ids = self.ids()
        if event.key() in (Qt.Key_Left, Qt.Key_Right) and ids:
            atual = ids.index(self._escolhida_id) if self._escolhida_id in ids else len(ids) - 1
            novo = atual + (1 if event.key() == Qt.Key_Right else -1)
            if 0 <= novo < len(ids):
                self._ativar(next(m for m in self._marcos if m.alteracao_id == ids[novo]))
            return
        super().keyPressEvent(event)

    # ----------------------------------------------------------- desenho --
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if not self._marcos:
            return
        with pintura_segura(self) as p:
            p.setRenderHint(QPainter.Antialiasing)
            base = QFont(self.font())

            # Trecho não registrado antes da primeira alteração cadastrada.
            reais = [m for m in self._marcos if m.alteracao_id is not None]
            if self._tem_lacuna_inicial():
                primeiro = reais[0]
                faltam = min(m.numero for m in reais) - 1
                self._tracejado(p, MARGEM - 24, primeiro.x - RAIO - 6)
                texto = "Nº 1 não registrada" if faltam == 1 else f"Nº 1 a {faltam} não registradas"
                self._texto(p, base, 11, False, INK_MUTED(), QRectF(MARGEM - 40, Y_LINHA + 12, primeiro.x - MARGEM - 4, 30),
                            texto, Qt.AlignCenter | Qt.TextWordWrap)

            # Ligações entre os selos.
            for a, b in zip(self._marcos, self._marcos[1:]):
                if b.alteracao_id is None:
                    self._tracejado(p, a.x + RAIO, b.x - RAIO)
                else:
                    p.setPen(QPen(QColor(BRASS()), 2))
                    p.drawLine(QPointF(a.x + RAIO, Y_LINHA), QPointF(b.x - RAIO, Y_LINHA))

            for i, m in enumerate(self._marcos):
                self._selo(p, base, m, sobre=i == self._sobre)

    def _tracejado(self, p: QPainter, x1: float, x2: float) -> None:
        if x2 <= x1:
            return
        cor = QColor(INK_MUTED())
        cor.setAlpha(150)
        caneta = QPen(cor, 2, Qt.DashLine)
        p.setPen(caneta)
        p.drawLine(QPointF(x1, Y_LINHA), QPointF(x2, Y_LINHA))

    def _texto(self, p, base, tamanho, negrito, cor, retangulo, texto, alinhamento) -> None:
        fonte = QFont(base)
        fonte.setPixelSize(tamanho)
        fonte.setBold(negrito)
        p.setFont(fonte)
        p.setPen(QColor(cor))
        p.drawText(retangulo, alinhamento, texto)

    def _selo(self, p: QPainter, base: QFont, m: _Marco, sobre: bool) -> None:
        centro = QPointF(m.x, Y_LINHA)
        if m.alteracao_id is None:
            cor = QColor(BRASS_DARK() if sobre else INK_MUTED())
            p.setPen(QPen(cor, 1.5, Qt.DashLine))
            p.setBrush(QColor(PAPER_RAISED()))
            p.drawEllipse(centro, RAIO, RAIO)
            self._texto(p, base, 20, False, cor.name(), QRectF(m.x - RAIO, Y_LINHA - RAIO - 2, RAIO * 2, RAIO * 2),
                        "+", Qt.AlignCenter)
            self._texto(p, base, 12, sobre, cor.name(), QRectF(m.x - 55, Y_LINHA + RAIO + 8, 110, 18),
                        "Nova alteração", Qt.AlignCenter)
            return

        escolhido = m.alteracao_id == self._escolhida_id
        cor = QColor(SEAL_RED() if m.fechada else BRASS())
        raio = RAIO_ESCOLHIDO if escolhido else RAIO + (2 if sobre else 0)

        if escolhido:
            # Halo suave: marca o escolhido sem precisar de outra cor.
            halo = QColor(cor)
            halo.setAlpha(45)
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(centro, raio + 7, raio + 7)

        p.setPen(QPen(cor, 2))
        p.setBrush(cor if escolhido else QColor(PAPER_RAISED()))
        p.drawEllipse(centro, raio, raio)
        if not escolhido:
            p.setPen(QPen(cor, 1))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(centro, raio - 4, raio - 4)

        numero = str(m.numero)
        tamanho = 15 if escolhido else 13
        if len(numero) > 2:
            tamanho -= 3
        self._texto(p, base, tamanho, True, ("#FFFFFF" if m.fechada else "#203461") if escolhido else cor.name(),
                    QRectF(m.x - raio, Y_LINHA - raio, raio * 2, raio * 2), numero, Qt.AlignCenter)

        if m.fechada:
            self._cadeado(p, QPointF(m.x + raio * 0.8, Y_LINHA - raio * 0.8), cor)

        self._texto(p, base, 12, escolhido, INK() if escolhido else INK_MUTED(),
                    QRectF(m.x - 55, Y_LINHA + RAIO_ESCOLHIDO + 6, 110, 16), formatar_data_br(m.data), Qt.AlignCenter)

    def _cadeado(self, p: QPainter, centro: QPointF, cor: QColor) -> None:
        p.setPen(QPen(QColor(PAPER_RAISED()), 3))
        p.setBrush(cor)
        corpo = QRectF(centro.x() - 5, centro.y() - 2, 10, 8)
        p.drawRoundedRect(corpo, 1.5, 1.5)
        p.setPen(QPen(cor, 1.6))
        p.setBrush(cor)
        p.drawRoundedRect(corpo, 1.5, 1.5)
        p.setBrush(Qt.NoBrush)
        p.drawArc(QRectF(centro.x() - 3.5, centro.y() - 7, 7, 9), 0, 180 * 16)
