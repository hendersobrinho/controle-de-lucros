"""Peças visuais das telas de distribuição (anual e trimestral).

A ideia que amarra tudo: **cada sócio tem uma cor**, a mesma no gráfico e na
tabela. Olhando a rosca (ou as barras dos trimestres) e depois a tabela, o
olho liga a fatia ao nome sem ler legenda nenhuma.

- `Rosca`: a divisão do lucro do ano entre os sócios, com o total no meio.
- `BarrasTrimestres`: os quatro trimestres do ano, empilhados por sócio;
  clicar numa barra escolhe o trimestre.
- Delegados da tabela: o sócio com a bolinha das iniciais (na cor dele) e o
  CPF embaixo; o percentual com uma barrinha; a situação em etiqueta.
- `kpi()`/`divisor_hero()`: os números grandes do painel de destaque.

Os gráficos crescem numa animação curta ao trocar de empresa ou de ano — é
o que diz "isto mudou" sem precisar de aviso.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QEasingCurve, QPointF, QRectF, QSize, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .common import formatar_percentual, formatar_valor_br, pintura_segura
from .theme import estado as tema_estado
from .theme import cor

# Paleta dos sócios: abre com as cores da marca (laranja, turquesa e um azul
# da família do marinho — o marinho puro sumiria em cima do painel, que é
# marinho) e segue com tons que convivem com elas.
_CORES_CLARO = ["#F29A2E", "#2FA7B9", "#5B79C0", "#D9644A", "#6BA368", "#8C6BC8", "#C9A227", "#4F7FC0"]
_CORES_ESCURO = ["#F9B259", "#4BBDCD", "#8FA8E0", "#E8846C", "#8CC489", "#B39BE6", "#E8C547", "#7FA6DD"]

PAPEL_COR = Qt.UserRole + 10
PAPEL_DETALHE = Qt.UserRole + 11
PAPEL_PERCENTUAL = Qt.UserRole + 12
PAPEL_TOM = Qt.UserRole + 13


def cor_da_vez(indice: int) -> QColor:
    """A cor do sócio pela posição dele (maior fatia primeiro). Passou das
    oito cores, os demais ficam num cinza só: repetir a paleta faria dois
    sócios diferentes parecerem o mesmo."""
    cores = _CORES_ESCURO if tema_estado().modo == "escuro" else _CORES_CLARO
    if indice >= len(cores):
        return QColor("#8C97AD")
    return QColor(cores[indice])


def ordem_de_cores(linhas: list[dict]) -> dict[int, int]:
    """socio_id -> índice de cor. Quem mais recebeu primeiro (e, empatado,
    a maior fatia do capital): são as mesmas fatias que a rosca mostra
    separadas, então as cores da rosca e da tabela batem mesmo quando o
    resto vira "Outros"."""
    ordenadas = sorted(linhas, key=lambda l: (
        -(l.get("valor_distribuido") or 0), -(l.get("percentual_capital") or 0), l["socio_nome"]))
    return {l["socio_id"]: i for i, l in enumerate(ordenadas)}


LIMITE_FATIAS = 6


def agrupar_fatias(fatias: list[tuple[float, QColor, str]], limite: int = LIMITE_FATIAS) -> list:
    """As maiores fatias e, se houver mais sócios que isso, uma fatia
    "Outros" com o resto. Empresa com cem sócios viraria uma rosca de cem
    riscos e uma legenda sem fim; assim o gráfico continua legível e a lista
    completa fica na tabela, que rola."""
    positivas = [f for f in fatias if f[0] > 0]
    if len(positivas) <= limite:
        return positivas
    maiores = sorted(positivas, key=lambda f: -f[0])[: limite - 1]
    resto = [f for f in positivas if f not in maiores]
    cinza = QColor(cor("HERO_MUTED"))
    return maiores + [(sum(f[0] for f in resto), cinza, f"Outros {len(resto)} sócios")]


def navegador_ano(spin, anterior, proximo) -> QWidget:
    """‹ 2025 ›: o ano em destaque, grande, com as setas coladas nele. O ano
    é o que mais muda o que a tela mostra, e num campo pequeno passava
    despercebido."""
    spin.setProperty("role", "anoGrande")
    spin.setAlignment(Qt.AlignCenter)
    spin.setFixedWidth(104)
    caixa = QWidget()
    linha = QHBoxLayout(caixa)
    linha.setContentsMargins(0, 0, 0, 0)
    linha.setSpacing(4)
    linha.addWidget(anterior)
    linha.addWidget(spin)
    linha.addWidget(proximo)
    return caixa


def iniciais(nome: str) -> str:
    partes = [p for p in nome.replace(".", " ").split() if p[:1].isalpha() and len(p) > 2]
    if not partes:
        return (nome[:1] or "?").upper()
    return (partes[0][0] + (partes[-1][0] if len(partes) > 1 else "")).upper()


def kpi(rotulo: str, valor: str = "", grande: bool = False) -> tuple[QWidget, QLabel, QLabel]:
    """Um número do painel de destaque: rótulo pequeno em cima, valor embaixo
    e uma nota opcional. Devolve (bloco, valor, nota)."""
    bloco = QWidget()
    bloco.setAttribute(Qt.WA_TranslucentBackground)
    bloco.setStyleSheet("background: transparent;")
    coluna = QVBoxLayout(bloco)
    coluna.setContentsMargins(0, 0, 0, 0)
    coluna.setSpacing(2)
    titulo = QLabel(rotulo.upper())
    titulo.setProperty("role", "heroRotulo")
    numero = QLabel(valor)
    numero.setProperty("role", "heroValor" if grande else "heroValorMenor")
    nota = QLabel()
    nota.setProperty("role", "heroNota")
    nota.setWordWrap(True)
    coluna.addWidget(titulo)
    coluna.addWidget(numero)
    coluna.addWidget(nota)
    coluna.addStretch()
    return bloco, numero, nota


def divisor_hero() -> QFrame:
    linha = QFrame()
    linha.setProperty("role", "heroDivisor")
    linha.setFixedWidth(1)
    return linha


class _Animado(QWidget):
    """Base dos gráficos: um progresso de 0 a 1 que cresce em ~0,5 s."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._progresso = 1.0
        self._animacao = QVariantAnimation(self)
        self._animacao.setDuration(520)
        self._animacao.setEasingCurve(QEasingCurve.OutCubic)
        self._animacao.valueChanged.connect(self._ao_animar)
        tema_estado().mudou.connect(self.update)

    def _ao_animar(self, valor) -> None:
        self._progresso = float(valor)
        self.update()

    def animar(self) -> None:
        if not self.isVisible():
            self._progresso = 1.0
            return
        self._animacao.stop()
        self._animacao.setStartValue(0.0)
        self._animacao.setEndValue(1.0)
        self._animacao.start()


class Rosca(_Animado):
    """Divisão do total entre os sócios. Passar o mouse numa fatia diz de
    quem é e quanto."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fatias: list[tuple[float, QColor, str]] = []
        self._total_texto = ""
        self._legenda_centro = ""
        self.setMinimumSize(170, 170)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(180, 180)

    def definir(self, fatias: list[tuple[float, QColor, str]], total_texto: str, legenda_centro: str,
                animar: bool = True) -> None:
        self._fatias = [(v, c, n) for v, c, n in fatias if v > 0]
        self._total_texto = total_texto
        self._legenda_centro = legenda_centro
        if animar:
            self.animar()
        self.update()

    def _anel(self) -> QRectF:
        lado = min(self.width(), self.height()) - 8
        return QRectF((self.width() - lado) / 2, (self.height() - lado) / 2, lado, lado)

    def paintEvent(self, _event) -> None:  # noqa: N802
        with pintura_segura(self) as p:
            p.setRenderHint(QPainter.Antialiasing)
            anel = self._anel()
            espessura = anel.width() * 0.17
            interno = anel.adjusted(espessura / 2, espessura / 2, -espessura / 2, -espessura / 2)
            trilho = QColor(cor("HERO_FG"))
            trilho.setAlpha(36)
            p.setPen(QPen(trilho, espessura, Qt.SolidLine, Qt.FlatCap))
            p.drawEllipse(interno)

            total = sum(v for v, _c, _n in self._fatias)
            if total > 0:
                inicio = 90.0
                varrer_total = 360.0 * self._progresso
                for valor, cor_fatia, _nome in self._fatias:
                    angulo = varrer_total * valor / total
                    # Um respiro de 1,5° entre as fatias separa as cores
                    # sem precisar de contorno.
                    vao = 1.5 if len(self._fatias) > 1 and angulo > 3 else 0
                    p.setPen(QPen(cor_fatia, espessura, Qt.SolidLine, Qt.FlatCap))
                    p.drawArc(interno, int((inicio - vao / 2) * 16), int(-(angulo - vao) * 16))
                    inicio -= angulo

            p.setPen(QColor(cor("HERO_FG")))
            fonte = QFont(self.font())
            fonte.setPixelSize(max(13, int(anel.width() * 0.105)))
            fonte.setBold(True)
            p.setFont(fonte)
            meio = QRectF(anel.left(), anel.center().y() - 22, anel.width(), 24)
            p.drawText(meio, Qt.AlignCenter, self._total_texto)
            fonte.setPixelSize(11)
            fonte.setBold(False)
            p.setFont(fonte)
            p.setPen(QColor(cor("HERO_MUTED")))
            p.drawText(QRectF(anel.left(), anel.center().y() + 4, anel.width(), 18), Qt.AlignCenter,
                       self._legenda_centro)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        anel = self._anel()
        centro = anel.center()
        dx, dy = event.position().x() - centro.x(), event.position().y() - centro.y()
        distancia = math.hypot(dx, dy)
        raio = anel.width() / 2
        total = sum(v for v, _c, _n in self._fatias)
        if not total or not (raio * 0.6 <= distancia <= raio + 2):
            QToolTip.hideText()
            return
        # Ângulo no sentido horário a partir do topo, como as fatias.
        angulo = (math.degrees(math.atan2(dx, -dy)) + 360) % 360
        acumulado = 0.0
        for valor, _cor, nome in self._fatias:
            acumulado += 360 * valor / total
            if angulo <= acumulado:
                QToolTip.showText(
                    event.globalPosition().toPoint(),
                    f"{nome}\nR$ {formatar_valor_br(valor)} · {formatar_percentual(100 * valor / total)}",
                    self,
                )
                return


class BarrasTrimestres(_Animado):
    """Os quatro trimestres do ano em colunas empilhadas por sócio. A coluna
    escolhida fica realçada; clicar noutra escolhe aquele trimestre."""

    clicado = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._colunas: dict[int, list[tuple[float, QColor, str]]] = {t: [] for t in (1, 2, 3, 4)}
        self._escolhido = 1
        self._futuros: set[int] = set()
        self._sobre: int | None = None
        self.setMinimumHeight(200)
        self.setMinimumWidth(360)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def definir(self, colunas: dict[int, list[tuple[float, QColor, str]]], escolhido: int, futuros: set[int],
                animar: bool = True) -> None:
        self._colunas = colunas
        self._escolhido = escolhido
        self._futuros = futuros
        if animar:
            self.animar()
        self.update()

    def escolher(self, trimestre: int) -> None:
        self._escolhido = trimestre
        self.update()

    def total(self, trimestre: int) -> float:
        return sum(v for v, _c, _n in self._colunas.get(trimestre, []))

    def _area_coluna(self, trimestre: int) -> QRectF:
        margem = 10
        largura = (self.width() - 2 * margem) / 4
        return QRectF(margem + (trimestre - 1) * largura, 0, largura, self.height())

    def paintEvent(self, _event) -> None:  # noqa: N802
        with pintura_segura(self) as p:
            p.setRenderHint(QPainter.Antialiasing)
            maximo = max([self.total(t) for t in (1, 2, 3, 4)] + [1.0])
            fonte = QFont(self.font())
            branco = QColor(cor("HERO_FG"))
            apagado = QColor(cor("HERO_MUTED"))

            topo_barras, base = 30.0, self.height() - 44.0
            altura_util = base - topo_barras
            for t in (1, 2, 3, 4):
                area = self._area_coluna(t)
                escolhido = t == self._escolhido
                if escolhido or t == self._sobre:
                    fundo = QColor(branco)
                    fundo.setAlpha(26 if escolhido else 14)
                    p.setPen(Qt.NoPen)
                    p.setBrush(fundo)
                    p.drawRoundedRect(area.adjusted(4, 0, -4, 0), 10, 10)

                largura_barra = min(64.0, area.width() * 0.46)
                x = area.center().x() - largura_barra / 2
                total = self.total(t)
                if total > 0:
                    altura = altura_util * (total / maximo) * self._progresso
                    y = base
                    caminho_barra = QPainterPath()
                    caminho_barra.addRoundedRect(QRectF(x, base - altura, largura_barra, altura), 6, 6)
                    p.save()
                    p.setClipPath(caminho_barra)
                    for valor, cor_fatia, _nome in self._colunas[t]:
                        h = altura * valor / total
                        p.fillRect(QRectF(x, y - h, largura_barra, h), cor_fatia)
                        y -= h
                    p.restore()
                    fonte.setPixelSize(12)
                    fonte.setBold(True)
                    p.setFont(fonte)
                    p.setPen(branco)
                    p.drawText(QRectF(area.left(), base - altura - 22, area.width(), 18), Qt.AlignCenter,
                               f"R$ {_compacto(total)}")
                else:
                    # Trimestre sem lançamento: só o contorno, tracejado.
                    caneta = QPen(apagado, 1.4, Qt.DashLine)
                    p.setPen(caneta)
                    p.setBrush(Qt.NoBrush)
                    p.drawRoundedRect(QRectF(x, base - 34, largura_barra, 34), 6, 6)
                    fonte.setPixelSize(11)
                    fonte.setBold(False)
                    p.setFont(fonte)
                    p.drawText(QRectF(area.left(), base - 56, area.width(), 18), Qt.AlignCenter,
                               "a lançar" if t not in self._futuros else "")

                fonte.setPixelSize(13)
                fonte.setBold(escolhido)
                p.setFont(fonte)
                p.setPen(branco if escolhido else apagado)
                p.drawText(QRectF(area.left(), base + 8, area.width(), 18), Qt.AlignCenter, f"{t}º trimestre")
                if escolhido:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(cor("BRASS")))
                    p.drawRoundedRect(QRectF(area.center().x() - 14, base + 30, 28, 4), 2, 2)

            p.setPen(QPen(QColor(255, 255, 255, 50), 1))
            p.drawLine(QPointF(10, base), QPointF(self.width() - 10, base))

    def _trimestre_em(self, x: float) -> int | None:
        for t in (1, 2, 3, 4):
            if self._area_coluna(t).left() <= x <= self._area_coluna(t).right():
                return t
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        t = self._trimestre_em(event.position().x())
        if t != self._sobre:
            self._sobre = t
            self.update()
        if t is not None and self._colunas.get(t):
            linhas = "\n".join(f"{n}: R$ {formatar_valor_br(v)}" for v, _c, n in self._colunas[t])
            QToolTip.showText(event.globalPosition().toPoint(), f"{t}º trimestre\n{linhas}", self)
        else:
            QToolTip.hideText()

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._sobre = None
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        t = self._trimestre_em(event.position().x())
        if event.button() == Qt.LeftButton and t is not None and self.isEnabled():
            self.clicado.emit(t)


def _compacto(valor: float) -> str:
    """R$ 1.234.567 -> "1,23 mi"; 45.000 -> "45 mil": cabe em cima da barra."""
    if valor >= 1_000_000:
        return f"{formatar_valor_br(valor / 1_000_000, 2)} mi"
    if valor >= 10_000:
        return f"{formatar_valor_br(valor / 1000, 0)} mil"
    return formatar_valor_br(valor, 0)


# --------------------------------------------------------------- tabela --


def _pintar_fundo(painter, option, index, delegado) -> QStyleOptionViewItem:
    opcao = QStyleOptionViewItem(option)
    delegado.initStyleOption(opcao, index)
    opcao.text = ""
    estilo = opcao.widget.style() if opcao.widget else None
    if estilo is not None:
        estilo.drawControl(QStyle.CE_ItemViewItem, opcao, painter, opcao.widget)
    return opcao


class DelegadoSocio(QStyledItemDelegate):
    """A bolinha com as iniciais na cor do sócio, o nome e o CPF embaixo."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        fonte = QFont(option.font)
        fonte.setPixelSize(14)
        largura = QFontMetrics(fonte).horizontalAdvance(index.data(Qt.DisplayRole) or "")
        return QSize(largura + 70, 54)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        try:
            _pintar_fundo(painter, option, index, self)
            painter.setRenderHint(QPainter.Antialiasing)
            r = option.rect
            cor_socio = index.data(PAPEL_COR) or QColor(cor("INK_MUTED"))
            diametro = 32
            circulo = QRectF(r.left() + 12, r.center().y() - diametro / 2, diametro, diametro)
            painter.setPen(Qt.NoPen)
            painter.setBrush(cor_socio)
            painter.drawEllipse(circulo)
            fonte = QFont(option.font)
            fonte.setPixelSize(12)
            fonte.setBold(True)
            painter.setFont(fonte)
            painter.setPen(QColor("#FFFFFF") if cor_socio.lightness() < 170 else QColor("#203461"))
            nome = index.data(Qt.DisplayRole) or ""
            painter.drawText(circulo, Qt.AlignCenter, iniciais(nome))

            texto_x = circulo.right() + 12
            largura = r.right() - texto_x - 8
            selecionado = bool(option.state & QStyle.State_Selected)
            cor_texto = index.data(Qt.ForegroundRole)
            cor_nome = cor_texto.color() if cor_texto is not None and not selecionado else QColor(cor("INK"))
            fonte.setPixelSize(14)
            fonte.setBold(False)
            fonte.setWeight(QFont.DemiBold)
            painter.setFont(fonte)
            painter.setPen(cor_nome)
            metricas = QFontMetrics(fonte)
            detalhe = index.data(PAPEL_DETALHE) or ""
            y_nome = r.center().y() - (18 if detalhe else 9)
            painter.drawText(QRectF(texto_x, y_nome, largura, 18), Qt.AlignLeft | Qt.AlignVCenter,
                             metricas.elidedText(nome, Qt.ElideRight, int(largura)))
            if detalhe:
                fonte.setPixelSize(12)
                fonte.setWeight(QFont.Normal)
                painter.setFont(fonte)
                painter.setPen(QColor(cor("INK_MUTED")))
                painter.drawText(QRectF(texto_x, r.center().y() + 1, largura, 16), Qt.AlignLeft | Qt.AlignVCenter,
                                 detalhe)
        finally:
            painter.restore()


class DelegadoPercentual(QStyledItemDelegate):
    """O número em cima e uma barrinha embaixo, na cor do sócio."""

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        largura = QFontMetrics(option.font).horizontalAdvance(index.data(Qt.DisplayRole) or "")
        return QSize(max(largura, 84) + 24, 54)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        try:
            _pintar_fundo(painter, option, index, self)
            painter.setRenderHint(QPainter.Antialiasing)
            r = option.rect.adjusted(12, 0, -12, 0)
            texto = index.data(Qt.DisplayRole) or ""
            cor_texto = index.data(Qt.ForegroundRole)
            painter.setPen(cor_texto.color() if cor_texto is not None else QColor(cor("INK")))
            painter.setFont(option.font)
            painter.drawText(QRectF(r.left(), r.center().y() - 16, r.width(), 18), Qt.AlignRight | Qt.AlignVCenter, texto)
            percentual = index.data(PAPEL_PERCENTUAL)
            if percentual is not None:
                largura = min(84.0, float(r.width()))
                trilho = QRectF(r.right() - largura, r.center().y() + 8, largura, 5)
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(cor("HAIRLINE")))
                painter.drawRoundedRect(trilho, 2.5, 2.5)
                cheio = trilho.width() * max(0.0, min(100.0, float(percentual))) / 100
                if cheio > 0:
                    painter.setBrush(index.data(PAPEL_COR) or QColor(cor("BRASS")))
                    painter.drawRoundedRect(QRectF(trilho.left(), trilho.top(), max(cheio, 5), 5), 2.5, 2.5)
        finally:
            painter.restore()


class DelegadoEtiqueta(QStyledItemDelegate):
    """Situação do sócio em etiqueta: Ativo, Entrou, Saiu."""

    _TONS = {
        "ativo": ("SEAL_GREEN", None),
        "entrou": ("ENTROU_FG", "ENTROU_BG"),
        "saiu": ("SAIU_FG", "SAIU_BG"),
        "neutro": ("INK_MUTED", None),
    }

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        fonte = QFont(option.font)
        fonte.setPixelSize(11)
        largura = QFontMetrics(fonte).horizontalAdvance(index.data(Qt.DisplayRole) or "")
        return QSize(largura + 44, 54)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        try:
            opcao = QStyleOptionViewItem(option)
            self.initStyleOption(opcao, index)
            opcao.text = ""
            opcao.backgroundBrush = Qt.NoBrush
            estilo = opcao.widget.style() if opcao.widget else None
            if estilo is not None:
                estilo.drawControl(QStyle.CE_ItemViewItem, opcao, painter, opcao.widget)
            painter.setRenderHint(QPainter.Antialiasing)
            texto = index.data(Qt.DisplayRole) or ""
            borda_nome, fundo_nome = self._TONS.get(index.data(PAPEL_TOM) or "ativo", self._TONS["ativo"])
            fonte = QFont(option.font)
            fonte.setPixelSize(11)
            fonte.setBold(True)
            painter.setFont(fonte)
            largura = QFontMetrics(fonte).horizontalAdvance(texto) + 20
            r = option.rect
            pilula = QRectF(r.right() - largura - 12, r.center().y() - 11, largura, 22)
            cor_borda = QColor(cor(borda_nome))
            painter.setPen(QPen(cor_borda, 1))
            painter.setBrush(QColor(cor(fundo_nome)) if fundo_nome else Qt.NoBrush)
            painter.drawRoundedRect(pilula, 11, 11)
            painter.setPen(cor_borda)
            painter.drawText(pilula, Qt.AlignCenter, texto)
        finally:
            painter.restore()
