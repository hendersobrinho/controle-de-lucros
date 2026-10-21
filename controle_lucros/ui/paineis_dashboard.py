"""Peças visuais dos dashboards.

- `SeletorPeriodo`: os anos com lançamento em fichas; um clique escolhe o
  ano, Shift+clique estende até outro, "Todo o período" pega tudo.
- `EvolucaoAnos`: uma barra por ano (empilhada por sócio, se vier assim), o
  período escolhido realçado; clicar numa barra escolhe aquele ano.
- `Ranking`: os que mais distribuíram/receberam, em barras horizontais com
  o valor e a fatia do total; clicar numa linha abre o detalhe.
- `CartaoAtencao`: um ponto de atenção — título, número grande, explicação
  curta e alguns nomes.
- `ComparacaoSocios`: para cada sócio, a fatia do capital × a fatia do que
  recebeu, e a diferença em reais.

Tudo desenhado aqui (QPainter), nas cores do tema: os gráficos prontos do Qt
não deixam chegar nesse acabamento, e os dashboards são o que se mostra ao
cliente.
"""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .common import formatar_percentual, formatar_valor_br, pintura_segura
from .marca import desenhar_simbolo
from .painel_distribuicao import _Animado, _compacto, iniciais
from .theme import cor
from .theme import estado as tema_estado


def reais(valor: float) -> str:
    return f"R$ {formatar_valor_br(valor or 0)}"


_reais = reais


def nomes_unicos(nomes) -> list[str]:
    """Na ordem, sem repetir (um sócio de várias empresas aparece uma vez)."""
    vistos, saida = set(), []
    for nome in nomes:
        if nome not in vistos:
            vistos.add(nome)
            saida.append(nome)
    return saida


# ------------------------------------------------------------- período --
class SeletorPeriodo(QWidget):
    """Fichas de ano. Emite `mudou(ano_de, ano_ate)`."""

    mudou = Signal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._anos: list[int] = []
        self._de = self._ate = 0
        self._ancora = 0  # o ano do último clique simples: o Shift+clique vai dele até o outro
        self._linha = QHBoxLayout(self)
        self._linha.setContentsMargins(0, 0, 0, 0)
        self._linha.setSpacing(6)
        self.botoes: dict[int, QPushButton] = {}
        self.btn_tudo = QPushButton("Todo o período")
        self.btn_tudo.setProperty("role", "fichaAno")
        self.btn_tudo.setCheckable(True)
        self.btn_tudo.setCursor(Qt.PointingHandCursor)
        self.btn_tudo.clicked.connect(self._tudo)

    def definir_anos(self, anos: list[int], de: int, ate: int) -> None:
        while self._linha.count():
            item = self._linha.takeAt(0)
            if item.widget() is not None and item.widget() is not self.btn_tudo:
                item.widget().hide()
                item.widget().deleteLater()
        self._anos = sorted(anos)
        self.botoes = {}
        for ano in self._anos:
            botao = QPushButton(str(ano))
            botao.setProperty("role", "fichaAno")
            botao.setCheckable(True)
            botao.setCursor(Qt.PointingHandCursor)
            botao.setToolTip("Clique para ver só este ano. Shift+clique para ver de um ano até outro.")
            botao.clicked.connect(lambda _c=False, a=ano: self._clicar(a))
            self._linha.addWidget(botao)
            self.botoes[ano] = botao
        self._linha.addSpacing(6)
        self._linha.addWidget(self.btn_tudo)
        self._linha.addStretch()
        self.escolher(de, ate, avisar=False)

    @property
    def ano_de(self) -> int:
        return self._de

    @property
    def ano_ate(self) -> int:
        return self._ate

    def escolher(self, de: int, ate: int, avisar: bool = True) -> None:
        self._de, self._ate = min(de, ate), max(de, ate)
        for ano, botao in self.botoes.items():
            botao.setChecked(self._de <= ano <= self._ate)
        self.btn_tudo.setChecked(bool(self._anos) and (self._de, self._ate) == (self._anos[0], self._anos[-1]))
        if avisar:
            self.mudou.emit(self._de, self._ate)

    def _clicar(self, ano: int) -> None:
        from PySide6.QtWidgets import QApplication

        if QApplication.keyboardModifiers() & Qt.ShiftModifier and self._ancora:
            # Do ano clicado por último até este — pode aumentar ou diminuir.
            self.escolher(self._ancora, ano)
        else:
            self._ancora = ano
            self.escolher(ano, ano)

    def _tudo(self) -> None:
        if self._anos:
            self._ancora = self._anos[0]
            self.escolher(self._anos[0], self._anos[-1])


# ------------------------------------------------------------ evolução --
class EvolucaoAnos(_Animado):
    """Barras por ano. `colunas`: lista de (ano, total, partes), onde partes
    é [(valor, cor, rótulo)] para empilhar — ou vazio para uma barra só."""

    clicado = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._colunas: list[tuple[int, float, list]] = []
        self._de = self._ate = 0
        self._sobre: int | None = None
        self.setMinimumHeight(230)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def definir(self, colunas: list, de: int, ate: int, animar: bool = True) -> None:
        self._colunas = colunas
        self._de, self._ate = de, ate
        if animar:
            self.animar()
        self.update()

    def _area(self, indice: int) -> QRectF:
        largura = (self.width() - 20) / max(1, len(self._colunas))
        return QRectF(10 + indice * largura, 0, largura, self.height())

    def paintEvent(self, _event) -> None:  # noqa: N802
        with pintura_segura(self) as p:
            p.setRenderHint(QPainter.Antialiasing)
            if not self._colunas:
                p.setPen(QColor(cor("INK_MUTED")))
                p.drawText(self.rect(), Qt.AlignCenter, "Nenhuma distribuição lançada ainda.")
                return
            maximo = max([c[1] for c in self._colunas] + [1.0])
            topo, base = 26.0, self.height() - 30.0
            fonte = QFont(self.font())
            for i, (ano, total, partes) in enumerate(self._colunas):
                area = self._area(i)
                no_periodo = self._de <= ano <= self._ate
                if i == self._sobre:
                    fundo = QColor(cor("ALT_ROW"))
                    p.setPen(Qt.NoPen)
                    p.setBrush(fundo)
                    p.drawRoundedRect(area.adjusted(3, 0, -3, 0), 8, 8)
                largura = min(56.0, area.width() * 0.56)
                x = area.center().x() - largura / 2
                altura = (base - topo) * (total / maximo) * self._progresso if total > 0 else 0
                if altura > 0:
                    caminho = QPainterPath()
                    caminho.addRoundedRect(QRectF(x, base - altura, largura, altura), 5, 5)
                    p.save()
                    p.setClipPath(caminho)
                    if partes:
                        y = base
                        for valor, cor_parte, _nome in partes:
                            h = altura * valor / total
                            c = QColor(cor_parte)
                            if not no_periodo:
                                c.setAlpha(70)
                            p.fillRect(QRectF(x, y - h, largura, h), c)
                            y -= h
                    else:
                        c = QColor(cor("BRASS") if no_periodo else cor("HAIRLINE"))
                        p.fillRect(QRectF(x, base - altura, largura, altura), c)
                    p.restore()
                fonte.setPixelSize(11)
                fonte.setBold(no_periodo)
                p.setFont(fonte)
                p.setPen(QColor(cor("INK") if no_periodo else cor("INK_MUTED")))
                if total > 0:
                    p.drawText(QRectF(area.left(), base - altura - 20, area.width(), 16), Qt.AlignCenter,
                               f"R$ {_compacto(total)}")
                fonte.setPixelSize(13)
                p.setFont(fonte)
                p.drawText(QRectF(area.left(), base + 6, area.width(), 18), Qt.AlignCenter, str(ano))
            p.setPen(QPen(QColor(cor("HAIRLINE")), 1))
            p.drawLine(10, int(base), self.width() - 10, int(base))

    def _indice_em(self, x: float) -> int | None:
        for i in range(len(self._colunas)):
            area = self._area(i)
            if area.left() <= x <= area.right():
                return i
        return None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        i = self._indice_em(event.position().x())
        if i != self._sobre:
            self._sobre = i
            self.update()
        if i is not None:
            ano, total, partes = self._colunas[i]
            texto = f"{ano}: {_reais(total)}"
            if partes:
                texto += "\n" + "\n".join(f"{n}: {_reais(v)}" for v, _c, n in sorted(partes, key=lambda x: -x[0])[:8])
            QToolTip.showText(event.globalPosition().toPoint(), texto, self)

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._sobre = None
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        i = self._indice_em(event.position().x())
        if event.button() == Qt.LeftButton and i is not None:
            self.clicado.emit(self._colunas[i][0])


# -------------------------------------------------------------- ranking --
class Ranking(QWidget):
    """Linhas: (id, nome, detalhe, valor). As barras são relativas ao maior
    da lista; a porcentagem, ao `total` informado."""

    clicado = Signal(int)
    ALTURA = 44

    def __init__(self, parent=None):
        super().__init__(parent)
        self._linhas: list[tuple] = []
        self._total = 0.0
        self._sobre: int | None = None
        self._vazio = "Nada no período."
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tema_estado().mudou.connect(self.update)

    def definir(self, linhas: list[tuple], total: float, vazio: str = "Nada no período.") -> None:
        self._linhas, self._total, self._vazio = linhas, total, vazio
        self.setFixedHeight(max(1, len(linhas)) * self.ALTURA + 4)
        self.update()

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(380, max(1, len(self._linhas)) * self.ALTURA + 4)

    def paintEvent(self, _event) -> None:  # noqa: N802
        with pintura_segura(self) as p:
            p.setRenderHint(QPainter.Antialiasing)
            fonte = QFont(self.font())
            if not self._linhas:
                p.setPen(QColor(cor("INK_MUTED")))
                p.drawText(self.rect(), Qt.AlignCenter, self._vazio)
                return
            maior = max(l[3] for l in self._linhas) or 1.0
            largura_valor = 128
            for i, (_id, nome, detalhe, valor) in enumerate(self._linhas):
                topo = i * self.ALTURA
                linha = QRectF(0, topo, self.width(), self.ALTURA)
                if i == self._sobre:
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(cor("ALT_ROW")))
                    p.drawRoundedRect(linha.adjusted(0, 1, 0, -1), 6, 6)
                # posição
                fonte.setPixelSize(12)
                fonte.setBold(True)
                p.setFont(fonte)
                p.setPen(QColor(cor("BRASS_DARK") if i < 3 else cor("INK_MUTED")))
                p.drawText(QRectF(4, topo, 24, 22), Qt.AlignCenter, f"{i + 1}º")
                # nome e detalhe
                area_texto = self.width() - 34 - largura_valor
                fonte.setPixelSize(13)
                fonte.setBold(True)
                p.setFont(fonte)
                p.setPen(QColor(cor("INK")))
                p.drawText(QRectF(34, topo + 3, area_texto, 18), Qt.AlignLeft | Qt.AlignVCenter,
                           QFontMetrics(fonte).elidedText(nome, Qt.ElideRight, int(area_texto)))
                fonte.setPixelSize(11)
                fonte.setBold(False)
                p.setFont(fonte)
                p.setPen(QColor(cor("INK_MUTED")))
                p.drawText(QRectF(34, topo + 21, area_texto, 14), Qt.AlignLeft | Qt.AlignVCenter, detalhe)
                # barra
                trilho = QRectF(34, topo + self.ALTURA - 7, area_texto, 4)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(cor("HAIRLINE")))
                p.drawRoundedRect(trilho, 2, 2)
                p.setBrush(QColor(cor("BRASS")))
                p.drawRoundedRect(QRectF(trilho.left(), trilho.top(), max(4.0, trilho.width() * valor / maior), 4), 2, 2)
                # valor e %
                fonte.setPixelSize(13)
                fonte.setBold(True)
                p.setFont(fonte)
                p.setPen(QColor(cor("INK")))
                direita = QRectF(self.width() - largura_valor, topo + 3, largura_valor - 4, 18)
                p.drawText(direita, Qt.AlignRight | Qt.AlignVCenter, _reais(valor))
                if self._total:
                    fonte.setPixelSize(11)
                    fonte.setBold(False)
                    p.setFont(fonte)
                    p.setPen(QColor(cor("INK_MUTED")))
                    p.drawText(QRectF(direita.left(), topo + 21, direita.width(), 14), Qt.AlignRight | Qt.AlignVCenter,
                               f"{formatar_valor_br(100 * valor / self._total, 1)}% do total")

    def _indice(self, y: float) -> int | None:
        i = int(y // self.ALTURA)
        return i if 0 <= i < len(self._linhas) else None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        i = self._indice(event.position().y())
        if i != self._sobre:
            self._sobre = i
            self.setCursor(Qt.PointingHandCursor if i is not None else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._sobre = None
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        i = self._indice(event.position().y())
        if event.button() == Qt.LeftButton and i is not None:
            self.clicado.emit(self._linhas[i][0])


# ------------------------------------------------------------- atenção --
class CartaoAtencao(QFrame):
    """Um ponto de atenção. `tom`: "alerta" (vermelho), "aviso" (laranja),
    "ok" (verde) ou "info"."""

    def __init__(self, titulo: str, parent=None):
        super().__init__(parent)
        self.setProperty("role", "cartaoAtencao")
        self.setProperty("tom", "info")
        self.titulo = QLabel(titulo.upper())
        self.titulo.setProperty("role", "rotuloCampo")
        self.valor = QLabel("—")
        self.valor.setProperty("role", "numeroAtencao")
        self.explicacao = QLabel()
        self.explicacao.setProperty("role", "subtitulo")
        self.explicacao.setWordWrap(True)
        self.nomes = QLabel()
        self.nomes.setProperty("role", "dicaCampo")
        self.nomes.setWordWrap(True)
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(16, 12, 16, 14)
        coluna.setSpacing(4)
        coluna.addWidget(self.titulo)
        coluna.addWidget(self.valor)
        coluna.addWidget(self.explicacao)
        coluna.addWidget(self.nomes)
        coluna.addStretch()

    def definir(self, valor: str, explicacao: str, nomes: list[str], tom: str) -> None:
        self.valor.setText(valor)
        self.explicacao.setText(explicacao)
        mostrados = nomes[:3]
        resto = len(nomes) - len(mostrados)
        self.nomes.setText(" · ".join(mostrados) + (f" · e mais {resto}" if resto > 0 else ""))
        self.nomes.setVisible(bool(nomes))
        self.setProperty("tom", tom)
        for widget in (self, self.valor):
            widget.style().unpolish(widget)
            widget.style().polish(widget)


# ----------------------------------------------------- capital × recebido --
class ComparacaoSocios(QWidget):
    """Itens: (nome, % do capital, % recebido, valor recebido, desvio R$, cor)."""

    ALTURA = 50

    def __init__(self, parent=None):
        super().__init__(parent)
        self._itens: list[tuple] = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        tema_estado().mudou.connect(self.update)

    def definir(self, itens: list[tuple]) -> None:
        self._itens = itens
        self.setFixedHeight(max(1, len(itens)) * self.ALTURA + 30)
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        with pintura_segura(self) as p:
            p.setRenderHint(QPainter.Antialiasing)
            fonte = QFont(self.font())
            if not self._itens:
                p.setPen(QColor(cor("INK_MUTED")))
                p.drawText(self.rect(), Qt.AlignCenter, "Nenhuma distribuição no período.")
                return
            # legenda
            fonte.setPixelSize(11)
            p.setFont(fonte)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(cor("HAIRLINE")))
            p.drawRoundedRect(QRectF(0, 6, 22, 8), 3, 3)
            p.setPen(QColor(cor("INK_MUTED")))
            p.drawText(QRectF(28, 0, 120, 20), Qt.AlignLeft | Qt.AlignVCenter, "% do capital")
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(cor("BRASS")))
            p.drawRoundedRect(QRectF(130, 6, 22, 8), 3, 3)
            p.setPen(QColor(cor("INK_MUTED")))
            p.drawText(QRectF(158, 0, 160, 20), Qt.AlignLeft | Qt.AlignVCenter, "% do que foi distribuído")

            largura_nome = min(260, self.width() * 0.32)
            largura_desvio = 150
            x_barra = largura_nome + 16
            largura_barra = self.width() - x_barra - largura_desvio - 12
            maior = max([max(i[1], i[2]) for i in self._itens] + [1.0])
            for n, (nome, capital, recebido, valor, desvio, cor_socio) in enumerate(self._itens):
                topo = 26 + n * self.ALTURA
                # bolinha + nome
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(cor_socio))
                circulo = QRectF(0, topo + 9, 28, 28)
                p.drawEllipse(circulo)
                fonte.setPixelSize(10)
                fonte.setBold(True)
                p.setFont(fonte)
                p.setPen(QColor("#FFFFFF") if QColor(cor_socio).lightness() < 170 else QColor("#203461"))
                p.drawText(circulo, Qt.AlignCenter, iniciais(nome))
                fonte.setPixelSize(13)
                p.setFont(fonte)
                p.setPen(QColor(cor("INK")))
                metricas = QFontMetrics(fonte)
                p.drawText(QRectF(36, topo + 6, largura_nome - 36, 18), Qt.AlignLeft | Qt.AlignVCenter,
                           metricas.elidedText(nome, Qt.ElideRight, int(largura_nome - 36)))
                fonte.setPixelSize(11)
                fonte.setBold(False)
                p.setFont(fonte)
                p.setPen(QColor(cor("INK_MUTED")))
                p.drawText(QRectF(36, topo + 24, largura_nome - 36, 16), Qt.AlignLeft | Qt.AlignVCenter,
                           f"recebeu {_reais(valor)}")
                # barras
                for deslocamento, percentual, cor_barra in ((10, capital, cor("HAIRLINE")), (24, recebido, cor_socio)):
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(cor_barra))
                    largura = max(3.0, largura_barra * percentual / maior)
                    p.drawRoundedRect(QRectF(x_barra, topo + deslocamento, largura, 10), 4, 4)
                    fonte.setPixelSize(10)
                    p.setFont(fonte)
                    p.setPen(QColor(cor("INK_MUTED")))
                    p.drawText(QRectF(x_barra + largura + 6, topo + deslocamento - 3, 90, 16),
                               Qt.AlignLeft | Qt.AlignVCenter, formatar_percentual(percentual))
                # desvio
                fonte.setPixelSize(12)
                fonte.setBold(True)
                p.setFont(fonte)
                if abs(desvio) < 0.01:
                    texto, tom = "na proporção", cor("SEAL_GREEN")
                elif desvio > 0:
                    texto, tom = f"+ {_reais(desvio)}", cor("BRASS_DARK")
                else:
                    texto, tom = f"− {_reais(-desvio)}", cor("SAIU_FG")
                p.setPen(QColor(tom))
                p.drawText(QRectF(self.width() - largura_desvio, topo + 6, largura_desvio, 18),
                           Qt.AlignRight | Qt.AlignVCenter, texto)
                fonte.setPixelSize(10)
                fonte.setBold(False)
                p.setFont(fonte)
                p.setPen(QColor(cor("INK_MUTED")))
                p.drawText(QRectF(self.width() - largura_desvio, topo + 24, largura_desvio, 14),
                           Qt.AlignRight | Qt.AlignVCenter,
                           "acima da proporção" if desvio > 0.01 else "abaixo da proporção" if desvio < -0.01 else "")


def bloco(titulo: str, subtitulo: str = "") -> tuple[QFrame, QVBoxLayout]:
    quadro = QFrame()
    quadro.setProperty("role", "card")
    coluna = QVBoxLayout(quadro)
    coluna.setContentsMargins(18, 14, 18, 16)
    coluna.setSpacing(8)
    cabeca = QVBoxLayout()
    cabeca.setSpacing(0)
    nome = QLabel(titulo)
    nome.setProperty("role", "secao")
    cabeca.addWidget(nome)
    if subtitulo:
        sub = QLabel(subtitulo)
        sub.setProperty("role", "subtitulo")
        sub.setWordWrap(True)
        cabeca.addWidget(sub)
    coluna.addLayout(cabeca)
    return quadro, coluna



class CarregandoAnalise(QWidget):
    """O aviso de "analisando" por cima do dashboard enquanto a conta das
    empresas roda em segundo plano. Antes, a conta rodava na frente e a
    janela congelava — o sistema chegava a oferecer "forçar fechamento".

    Cobre o painel inteiro com um véu e mostra, num cartão, as barras do
    símbolo se mexendo, a empresa da vez e quanto já foi feito. Só aparece
    se a conta passar de um instante: análise rápida não pisca na tela."""

    cancelar = Signal()

    ATRASO_MS = 180

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.hide()
        self._titulo = "Analisando as empresas…"
        self._detalhe = ""
        self._feitas = 0
        self._total = 0
        self._inicio = 0.0
        self._relogio = QTimer(self)
        # 30 quadros por segundo: suave, e deixa a conta das empresas (que
        # roda ao lado, no mesmo processo) com o processador quase todo.
        self._relogio.setInterval(33)
        self._relogio.timeout.connect(self._quadro)
        self._espera = QTimer(self)
        self._espera.setSingleShot(True)
        self._espera.timeout.connect(self._aparecer)
        self.botao_cancelar = QPushButton("Cancelar", self)
        self.botao_cancelar.setCursor(Qt.PointingHandCursor)
        self.botao_cancelar.clicked.connect(self.cancelar.emit)
        # Até onde o véu sobe: quem usa a tela diz (o dashboard deixa de fora a
        # barra do período, que continua clicável durante a análise).
        self.topo = lambda: 0
        parent.installEventFilter(self)

    # -- ciclo --

    def comecar(self, titulo: str) -> None:
        self._titulo = titulo
        self._detalhe = "Preparando…"
        self._feitas = self._total = 0
        if not self.isVisible() and not self._espera.isActive():
            self._espera.start(self.ATRASO_MS)

    def andamento(self, feitas: int, total: int, detalhe: str) -> None:
        self._feitas, self._total, self._detalhe = feitas, total, detalhe

    def _quadro(self) -> None:
        """Enquanto o véu escurece, redesenha tudo; depois, só o cartão. O
        véu é transparente: redesenhá-lo inteiro a cada quadro obrigava o
        dashboard por baixo (gráficos, rankings) a se redesenhar junto, e a
        animação roubava da conta o dobro do tempo."""
        if (time.monotonic() - self._inicio) * 1000 < 260:
            self.update()
        else:
            self.update(self._cartao().toAlignedRect().adjusted(-16, -12, 16, 20))

    def terminar(self) -> None:
        self._espera.stop()
        self._relogio.stop()
        self.hide()

    def _aparecer(self) -> None:
        self._inicio = time.monotonic()
        self._posicionar()
        self.raise_()
        self.show()
        self._relogio.start()

    def _posicionar(self) -> None:
        area = self.parentWidget().rect()
        area.setTop(max(0, min(self.topo(), area.height() - 260)))
        self.setGeometry(area)

    def eventFilter(self, objeto, evento):
        if objeto is self.parentWidget() and evento.type() == evento.Type.Resize and self.isVisible():
            self._posicionar()
        return False

    # -- desenho --

    def _cartao(self) -> QRectF:
        largura, altura = 440.0, 250.0
        centro = QRectF(self.rect()).center()
        return QRectF(centro.x() - largura / 2, min(centro.y() - altura / 2, 120), largura, altura)

    def resizeEvent(self, _evento) -> None:
        cartao = self._cartao()
        self.botao_cancelar.adjustSize()
        self.botao_cancelar.move(int(cartao.center().x() - self.botao_cancelar.width() / 2),
                                 int(cartao.bottom() - self.botao_cancelar.height() - 18))

    def paintEvent(self, _evento) -> None:
        t = (time.monotonic() - self._inicio) * 1000
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)

        veu = QColor(cor("PAPER"))
        veu.setAlpha(min(int(t / 200 * 205), 205))
        p.fillRect(self.rect(), veu)

        cartao = self._cartao()
        sombra = QColor(0, 0, 0, 28)
        for i in range(6):
            sombra.setAlpha(14 - i * 2)
            p.setPen(Qt.NoPen)
            p.setBrush(sombra)
            p.drawRoundedRect(cartao.adjusted(-i * 2, -i * 2 + 4, i * 2, i * 2 + 4), 16 + i, 16 + i)
        p.setBrush(QColor(cor("PAPER_RAISED")))
        p.setPen(QPen(QColor(cor("HAIRLINE")), 1))
        p.drawRoundedRect(cartao, 16, 16)

        # As barras do símbolo, subindo e descendo fora de fase — o mesmo
        # movimento da tela de carregamento do programa.
        alturas = [0.62 + 0.38 * (0.5 + 0.5 * math.sin(t / 260 + i * 1.1)) for i in range(3)]
        icone = QRectF(cartao.left() + 26, cartao.top() + 22, 64, 64)
        desenhar_simbolo(p, icone, fundo=QColor("#203461"), alturas=alturas)

        p.setPen(QColor(cor("INK")))
        fonte = QFont(self.font())
        fonte.setPointSizeF(13.5)
        fonte.setWeight(QFont.DemiBold)
        p.setFont(fonte)
        texto = QRectF(icone.right() + 16, cartao.top() + 28, cartao.right() - icone.right() - 40, 24)
        p.drawText(texto, Qt.AlignLeft | Qt.AlignVCenter, self._titulo)
        fonte.setPointSizeF(9.5)
        fonte.setWeight(QFont.Normal)
        p.setFont(fonte)
        p.setPen(QColor(cor("INK_MUTED")))
        if self._total:
            andamento = f"Empresa {min(self._feitas + 1, self._total)} de {self._total}"
        else:
            andamento = "Preparando…"
        p.drawText(texto.translated(0, 24), Qt.AlignLeft | Qt.AlignVCenter, andamento)
        detalhe = QFontMetrics(fonte).elidedText(self._detalhe if self._total else "", Qt.ElideRight,
                                                 int(texto.width()))
        p.drawText(texto.translated(0, 42), Qt.AlignLeft | Qt.AlignVCenter, detalhe)

        # A barra de progresso: o que já foi, em laranja, com a porcentagem.
        trilho = QRectF(cartao.left() + 26, cartao.top() + 126, cartao.width() - 52, 8)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(cor("HAIRLINE")))
        p.drawRoundedRect(trilho, 4, 4)
        fracao = self._feitas / self._total if self._total else 0.0
        if fracao > 0:
            cheio = QRectF(trilho)
            cheio.setWidth(max(trilho.height(), trilho.width() * fracao))
            p.setBrush(QColor(cor("BRASS")))
            p.drawRoundedRect(cheio, 4, 4)
        # A porcentagem em cima da barra, à direita; o recado embaixo, sozinho
        # na linha.
        p.setPen(QColor(cor("INK")))
        fonte.setWeight(QFont.DemiBold)
        p.setFont(fonte)
        p.drawText(QRectF(trilho.left(), trilho.top() - 22, trilho.width(), 18), Qt.AlignRight | Qt.AlignVCenter,
                   f"{fracao * 100:.0f}%")
        fonte.setWeight(QFont.Normal)
        fonte.setPointSizeF(9)
        p.setFont(fonte)
        p.setPen(QColor(cor("INK_MUTED")))
        p.drawText(QRectF(trilho.left(), trilho.bottom() + 8, trilho.width(), 18), Qt.AlignLeft | Qt.AlignVCenter,
                   "O programa continua respondendo: dá para trocar o período.")
