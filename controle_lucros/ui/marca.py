"""A marca do programa: o símbolo, o painel das telas de entrada, a tela de
carregamento e o cabeçalho do menu.

O símbolo (assets/logo.svg) são três fatias verticais de círculos do mesmo
raio, cada uma um degrau acima da anterior — barras subindo, desenhadas como
um gráfico de pizza fatiado. Aqui ele é desenhado em código, a partir da
mesma geometria do SVG, e não lido do arquivo: assim a tela de carregamento
pode animar cada barra separada, e o símbolo sai nítido em qualquer tamanho.
"""
from __future__ import annotations

import math
import threading
import time

from PySide6.QtCore import QEasingCurve, QEventLoop, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from . import theme

MARINHO_CLARO = QColor("#2C4680")
MARINHO_ESCURO = QColor("#1A2A50")
MARINHO = QColor("#203461")
BRANCO = QColor("#FFFFFF")
TURQUESA = QColor("#4BBDCD")
LARANJA = QColor("#F9B259")

NOME = "Controle de Lucros"
SLOGAN = "Distribuição de lucros, quadro societário e informes de rendimentos."

# Geometria do logo.svg, no quadro de 512: cada fatia é o pedaço de um
# círculo de raio 150 entre duas verticais; os centros sobem 32 de uma fatia
# para a outra.
_FATIAS = (
    # (x inicial, x final, y do centro)
    (106.0, 224.0, 279.25),
    (242.0, 328.0, 247.25),
    (346.0, 406.0, 207.25),
)
_RAIO = 150.0
_CENTRO_X = 256.0


def _fatia(indice: int) -> QPainterPath:
    x0, x1, cy = _FATIAS[indice]
    circulo = QPainterPath()
    circulo.addEllipse(QPointF(_CENTRO_X, cy), _RAIO, _RAIO)
    faixa = QPainterPath()
    faixa.addRect(QRectF(x0, cy - _RAIO - 1, x1 - x0, 2 * _RAIO + 2))
    return circulo.intersected(faixa)


_CAMINHOS = [_fatia(i) for i in range(3)]


def desenhar_simbolo(
    pintor: QPainter,
    area: QRectF,
    cores=(BRANCO, TURQUESA, LARANJA),
    fundo: QColor | None = None,
    alturas=(1.0, 1.0, 1.0),
    deslocamentos=(0.0, 0.0, 0.0),
    opacidades=(1.0, 1.0, 1.0),
) -> None:
    """O símbolo dentro de `area` (quadrada). fundo desenha o quadrado
    arredondado do ícone por trás. alturas (0 a 1) recortam cada barra de
    baixo para cima — é como a tela de carregamento faz as barras
    "crescerem" —, e deslocamentos as sobem (em unidades do quadro de 512)."""
    pintor.save()
    pintor.setRenderHint(QPainter.Antialiasing)
    escala = area.width() / 512.0
    pintor.translate(area.topLeft())
    pintor.scale(escala, escala)
    if fundo is not None:
        gradiente = QLinearGradient(0, 0, 0, 512)
        # #203461 vira #2C4680 → #1A2A50, o degradê do logo.svg.
        gradiente.setColorAt(0, fundo.lighter(137))
        gradiente.setColorAt(1, fundo.darker(122))
        pintor.setPen(Qt.NoPen)
        pintor.setBrush(gradiente)
        pintor.drawRoundedRect(QRectF(0, 0, 512, 512), 116, 116)
    pintor.setPen(Qt.NoPen)
    for i, caminho in enumerate(_CAMINHOS):
        if alturas[i] <= 0 or opacidades[i] <= 0:
            continue
        caixa = caminho.boundingRect()
        recorte = QPainterPath()
        visivel = caixa.height() * min(alturas[i], 1.0)
        recorte.addRect(QRectF(caixa.left() - 1, caixa.bottom() - visivel, caixa.width() + 2, visivel + 1))
        pintor.save()
        pintor.setOpacity(pintor.opacity() * opacidades[i])
        pintor.translate(0, -deslocamentos[i])
        pintor.setBrush(cores[i])
        pintor.drawPath(caminho.intersected(recorte))
        pintor.restore()
    pintor.restore()


def _fonte(tamanho: float, peso: QFont.Weight = QFont.Normal) -> QFont:
    fonte = QFont()
    fonte.setFamilies(["Segoe UI Variable Display", "Segoe UI", "Inter", "Noto Sans", "Cantarell"])
    fonte.setPointSizeF(tamanho)
    fonte.setWeight(peso)
    return fonte


def _fundo_marinho(pintor: QPainter, area: QRectF, raio: float = 0.0) -> None:
    """O marinho do ícone, com um brilho turquesa discreto no alto — a mesma
    luz de cima para baixo do gradiente do logo."""
    gradiente = QLinearGradient(area.topLeft(), area.bottomRight())
    gradiente.setColorAt(0, MARINHO_CLARO)
    gradiente.setColorAt(1, MARINHO_ESCURO)
    caminho = QPainterPath()
    caminho.addRoundedRect(area, raio, raio)
    pintor.fillPath(caminho, gradiente)
    brilho = QRadialGradient(QPointF(area.left() + area.width() * 0.15, area.top()), area.width() * 0.9)
    brilho.setColorAt(0, QColor(75, 189, 205, 46))
    brilho.setColorAt(1, QColor(75, 189, 205, 0))
    pintor.fillPath(caminho, brilho)


# ------------------------------------------------------- telas de entrada --


class PainelMarca(QWidget):
    """O lado marinho das telas de entrada: o símbolo e o nome no alto, a
    frase da tela no meio, o que o programa faz embaixo, e o símbolo grande,
    quase apagado, saindo pelo canto — dá profundidade sem competir com o
    texto."""

    def __init__(self, titulo: str, texto: str, parent=None):
        super().__init__(parent)
        self.titulo = titulo
        self.texto = texto
        self.setFixedWidth(360)
        self.setAttribute(Qt.WA_OpaquePaintEvent)

    def paintEvent(self, _evento) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        area = QRectF(self.rect())
        _fundo_marinho(p, area)

        # Marca d'água: o símbolo enorme, cortado pela borda.
        lado = area.height() * 0.95
        p.setOpacity(0.07)
        desenhar_simbolo(p, QRectF(area.right() - lado * 0.62, area.bottom() - lado * 0.78, lado, lado))
        p.setOpacity(1.0)

        margem = 36.0
        # As fatias ocupam o miolo do quadro de 512 (x 106–406): o quadro
        # começa antes da margem para o desenho alinhar com o texto.
        desenhar_simbolo(p, QRectF(margem - 15, margem - 12, 70, 70))
        p.setPen(BRANCO)
        p.setFont(_fonte(13.5, QFont.DemiBold))
        p.drawText(QRectF(margem + 54, margem, 260, 22), Qt.AlignLeft | Qt.AlignVCenter, "Controle")
        p.setFont(_fonte(13.5, QFont.Normal))
        p.setPen(QColor(255, 255, 255, 200))
        p.drawText(QRectF(margem + 54, margem + 20, 260, 22), Qt.AlignLeft | Qt.AlignVCenter, "de Lucros")

        # Frase da tela, no terço do meio.
        largura = area.width() - 2 * margem
        p.setPen(BRANCO)
        p.setFont(_fonte(22, QFont.DemiBold))
        y = area.height() * 0.34
        titulo = p.boundingRect(QRectF(margem, y, largura, 200), Qt.TextWordWrap, self.titulo)
        p.drawText(titulo, Qt.TextWordWrap, self.titulo)
        p.setFont(_fonte(10.5))
        p.setPen(QColor(255, 255, 255, 190))
        corpo = QRectF(margem, titulo.bottom() + 12, largura, 200)
        p.drawText(corpo, Qt.TextWordWrap, self.texto)

        # Um traço em cada cor da marca, como um sublinhado do título.
        y_traco = titulo.top() - 16
        for i, cor in enumerate((BRANCO, TURQUESA, LARANJA)):
            p.setPen(Qt.NoPen)
            p.setBrush(cor)
            p.drawRoundedRect(QRectF(margem + i * 22, y_traco, 16, 4), 2, 2)

        # O que o programa faz, com as cores do símbolo.
        itens = (
            (BRANCO, "Quadro societário e alterações contratuais"),
            (TURQUESA, "Distribuição anual e trimestral"),
            (LARANJA, "Informes de rendimentos e análises"),
        )
        p.setFont(_fonte(9.5))
        y = area.bottom() - margem - 3 * 26 - 20
        for cor, texto in itens:
            p.setPen(Qt.NoPen)
            p.setBrush(cor)
            p.drawEllipse(QPointF(margem + 4, y + 10), 4, 4)
            p.setPen(QColor(255, 255, 255, 215))
            p.drawText(QRectF(margem + 18, y, largura - 18, 20), Qt.AlignLeft | Qt.AlignVCenter, texto)
            y += 26
        p.setPen(QColor(255, 255, 255, 120))
        p.setFont(_fonte(8.5))
        p.drawText(QRectF(margem, area.bottom() - margem + 4, largura, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   f"Versão {__version__}  ·  HenderLab")


class LadoFormulario(QFrame):
    """O lado claro, do formulário. Subclasse de QFrame só para o QSS achar
    pelo papel e pintar o fundo (um QWidget puro deixaria passar o fundo da
    janela)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setProperty("role", "entradaFormulario")


class TelaDeEntrada(QDialog):
    """Base das telas antes de entrar no programa (login, primeiro acesso,
    conexão com o banco, escolha do Claude): o painel da marca à esquerda e
    o formulário à direita. Cada tela põe o que é dela em self.corpo."""

    def __init__(self, titulo_janela: str, frase: str, texto: str, parent=None, altura: int = 580):
        super().__init__(parent)
        self.setWindowTitle(f"{titulo_janela} — {NOME}")
        self.setFixedSize(920, altura)
        self.setModal(True)

        self.painel = PainelMarca(frase, texto)
        self.lado = LadoFormulario()
        self.corpo = QVBoxLayout(self.lado)
        self.corpo.setContentsMargins(52, 46, 52, 30)
        self.corpo.setSpacing(0)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.painel)
        layout.addWidget(self.lado, 1)

    def cabecalho(self, titulo: str, subtitulo: str = "") -> None:
        rotulo = QLabel(titulo)
        rotulo.setProperty("role", "entradaTitulo")
        rotulo.setWordWrap(True)
        self.corpo.addWidget(rotulo)
        if subtitulo:
            self.corpo.addSpacing(6)
            texto = QLabel(subtitulo)
            texto.setProperty("role", "entradaSubtitulo")
            texto.setWordWrap(True)
            self.corpo.addWidget(texto)
        self.corpo.addSpacing(26)


def campo_de_entrada(rotulo: str, texto_de_apoio: str = "", senha: bool = False) -> tuple[QLabel, QLineEdit]:
    """Rótulo em cima e campo grande embaixo — nas telas de entrada o rótulo
    fica à vista mesmo depois de digitado, ao contrário do texto de apoio."""
    titulo = QLabel(rotulo)
    titulo.setProperty("role", "entradaRotulo")
    campo = QLineEdit()
    campo.setProperty("role", "entrada")
    campo.setPlaceholderText(texto_de_apoio)
    if senha:
        campo.setEchoMode(QLineEdit.Password)
    titulo.setBuddy(campo)
    return titulo, campo


def botao_link(texto: str) -> QPushButton:
    """Ação secundária das telas de entrada: texto discreto, sem moldura, pra
    não competir com o botão principal."""
    botao = QPushButton(texto)
    botao.setProperty("role", "entradaLink")
    botao.setCursor(Qt.PointingHandCursor)
    return botao


def aviso_de_entrada() -> QLabel:
    """Faixa de aviso dentro do formulário (erro de login, resultado do
    teste de conexão). Nasce escondida."""
    aviso = QLabel("")
    aviso.setProperty("role", "entradaAviso")
    aviso.setProperty("tom", "erro")
    aviso.setWordWrap(True)
    aviso.hide()
    return aviso


def mostrar_aviso(aviso: QLabel, texto: str, tom: str = "erro") -> None:
    aviso.setText(texto)
    aviso.setProperty("tom", tom)
    aviso.style().unpolish(aviso)
    aviso.style().polish(aviso)
    aviso.show()



# --------------------------------------------------------- carregamento --


class TelaCarregando(QWidget):
    """A tela de abertura. As três barras do símbolo crescem uma depois da
    outra, como um gráfico subindo; depois respiram devagar, defasadas,
    enquanto o trabalho anda. Embaixo, o que está sendo feito agora e uma
    linha de progresso que corre — sem número inventado de porcentagem,
    porque conectar num servidor não tem como saber quanto falta.

    executar() roda o trabalho pesado numa thread e mantém a animação viva;
    o que precisa ser feito na thread da tela (montar janelas) é feito
    entre um passo e outro, com a mensagem já trocada."""

    DURACAO_ENTRADA_MS = 1100

    def __init__(self):
        super().__init__(None, Qt.SplashScreen | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setFixedSize(560, 360)
        self.setWindowTitle(NOME)
        self._mensagem = "Iniciando…"
        self._inicio = time.monotonic()
        self._relogio = QTimer(self)
        self._relogio.setInterval(16)
        self._relogio.timeout.connect(self.update)
        self._sumindo: QVariantAnimation | None = None

    # -- ciclo de vida --

    def mostrar(self) -> None:
        tela = QApplication.primaryScreen()
        if tela is not None:
            centro = tela.availableGeometry().center()
            self.move(centro.x() - self.width() // 2, centro.y() - self.height() // 2)
        self._inicio = time.monotonic()
        self.setWindowOpacity(1.0)
        self.show()
        self.raise_()
        self._relogio.start()
        QApplication.processEvents()

    def mensagem(self, texto: str) -> None:
        self._mensagem = texto
        self.update()
        QApplication.processEvents()

    def executar(self, texto: str, trabalho):
        """Roda trabalho() fora da thread da tela, com a animação girando, e
        devolve o resultado (ou levanta o erro dele aqui)."""
        self.mensagem(texto)
        resultado: dict = {}

        def rodar():
            try:
                resultado["valor"] = trabalho()
            except BaseException as erro:  # noqa: BLE001 — devolvido para quem chamou
                resultado["erro"] = erro

        linha = threading.Thread(target=rodar, daemon=True)
        linha.start()
        laco = QEventLoop()
        vigia = QTimer()
        vigia.setInterval(15)
        vigia.timeout.connect(lambda: linha.is_alive() or laco.quit())
        vigia.start()
        if linha.is_alive():
            laco.exec()
        vigia.stop()
        linha.join()
        if "erro" in resultado:
            raise resultado["erro"]
        return resultado.get("valor")

    def esperar_entrada(self) -> None:
        """Deixa a animação de entrada terminar antes de sair da frente: uma
        abertura rápida não deve virar um piscar de tela."""
        falta = self.DURACAO_ENTRADA_MS / 1000 - (time.monotonic() - self._inicio)
        if falta > 0:
            laco = QEventLoop()
            QTimer.singleShot(int(falta * 1000), laco.quit)
            laco.exec()

    def esconder(self) -> None:
        self._relogio.stop()
        self.hide()

    def sumir(self) -> None:
        """Some com um esmaecer curto, por cima da janela principal já aberta."""
        self._sumindo = QVariantAnimation(self)
        self._sumindo.setDuration(260)
        self._sumindo.setStartValue(1.0)
        self._sumindo.setEndValue(0.0)
        self._sumindo.setEasingCurve(QEasingCurve.InCubic)
        self._sumindo.valueChanged.connect(self.setWindowOpacity)
        self._sumindo.finished.connect(self.esconder)
        self._sumindo.start()

    # -- desenho --

    def _tempo(self) -> float:
        return (time.monotonic() - self._inicio) * 1000

    def paintEvent(self, _evento) -> None:
        t = self._tempo()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        area = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        _fundo_marinho(p, area, 18)
        p.setPen(QPen(QColor(255, 255, 255, 28), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(area, 18, 18)

        # Marca d'água no canto, quase apagada — recortada pelo cartão, para
        # não vazar pelo canto arredondado.
        moldura = QPainterPath()
        moldura.addRoundedRect(area, 18, 18)
        p.save()
        p.setClipPath(moldura)
        p.setOpacity(0.05)
        desenhar_simbolo(p, QRectF(area.right() - 250, area.bottom() - 230, 330, 330))
        p.restore()

        # As barras: cada uma cresce com atraso de 160 ms, com um leve passar
        # do ponto (OutBack) — e depois respiram, fora de fase.
        curva = QEasingCurve(QEasingCurve.OutBack)
        curva.setOvershoot(1.4)
        alturas, deslocamentos, opacidades = [], [], []
        for i in range(3):
            fase = min(max((t - 120 - i * 160) / 620, 0.0), 1.0)
            alturas.append(curva.valueForProgress(fase) if fase < 1 else 1.0)
            opacidades.append(min(fase * 8, 1.0))
            respiro = 0.0
            if t > 1100:
                respiro = 9 * (0.5 - 0.5 * math.cos((t - 1100) / 520 + i * 0.9))
            deslocamentos.append(respiro)
        lado = 156.0
        simbolo = QRectF(area.center().x() - lado / 2, 26, lado, lado)
        # Um halo turquesa atrás do símbolo, que acende junto com as barras.
        acende = min(max((t - 100) / 900, 0.0), 1.0)
        halo = QRadialGradient(simbolo.center(), lado * 0.62)
        halo.setColorAt(0, QColor(75, 189, 205, int(60 * acende)))
        halo.setColorAt(1, QColor(75, 189, 205, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(halo)
        p.drawEllipse(simbolo.center(), lado * 0.62, lado * 0.62)
        desenhar_simbolo(p, simbolo, alturas=alturas, deslocamentos=deslocamentos, opacidades=opacidades)

        # Nome e frase entram depois das barras, subindo um pouco.
        texto = min(max((t - 520) / 450, 0.0), 1.0)
        suave = QEasingCurve(QEasingCurve.OutCubic).valueForProgress(texto)
        p.setOpacity(suave)
        p.setPen(BRANCO)
        p.setFont(_fonte(22, QFont.DemiBold))
        p.drawText(QRectF(area.left(), 186 + (1 - suave) * 10, area.width(), 36), Qt.AlignCenter, NOME)
        p.setFont(_fonte(10))
        p.setPen(QColor(255, 255, 255, 175))
        p.drawText(QRectF(area.left() + 40, 222 + (1 - suave) * 10, area.width() - 80, 22), Qt.AlignCenter,
                   "Distribuição de lucros e quadro societário")
        p.setOpacity(1.0)

        # O que está acontecendo agora e a linha que corre.
        base = area.bottom() - 46
        p.setFont(_fonte(9.5))
        p.setPen(QColor(255, 255, 255, 200))
        p.drawText(QRectF(area.left() + 44, base - 26, area.width() - 88, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   self._mensagem)
        p.setPen(QColor(255, 255, 255, 110))
        p.drawText(QRectF(area.left() + 44, base - 26, area.width() - 88, 20), Qt.AlignRight | Qt.AlignVCenter,
                   f"v{__version__}")
        trilho = QRectF(area.left() + 44, base, area.width() - 88, 3)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 30))
        p.drawRoundedRect(trilho, 1.5, 1.5)
        # Um segmento laranja que atravessa e volta a entrar, acelerando no
        # meio — o ritmo de "trabalhando", sem prometer porcentagem.
        ciclo = ((t - 300) % 1500) / 1500 if t > 300 else 0.0
        posicao = QEasingCurve(QEasingCurve.InOutCubic).valueForProgress(ciclo)
        comprimento = trilho.width() * 0.28
        x = trilho.left() - comprimento + (trilho.width() + comprimento) * posicao
        segmento = QRectF(max(x, trilho.left()), trilho.top(), 0, trilho.height())
        segmento.setRight(min(x + comprimento, trilho.right()))
        if segmento.width() > 0 and t > 300:
            gradiente = QLinearGradient(segmento.topLeft(), segmento.topRight())
            gradiente.setColorAt(0, QColor(249, 178, 89, 0))
            gradiente.setColorAt(0.6, LARANJA)
            gradiente.setColorAt(1, QColor("#FFD59A"))
            p.setBrush(gradiente)
            p.drawRoundedRect(segmento, 1.5, 1.5)


# ------------------------------------------------------------- menu --


class MarcaMenu(QWidget):
    """O cabeçalho do menu lateral: o ícone do programa e o nome. No modo
    escuro o quadrado do ícone sai mais claro que o fundo, para não sumir."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(76)
        theme.estado().mudou.connect(self.update)

    def paintEvent(self, _evento) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        escuro = theme.estado().modo == "escuro"
        icone = QRectF(20, 16, 42, 42)
        desenhar_simbolo(p, icone, fundo=QColor("#35508F") if escuro else MARINHO)
        p.setPen(QColor(theme.INK()))
        p.setFont(_fonte(12.5, QFont.DemiBold))
        p.drawText(QRectF(74, 17, self.width() - 80, 22), Qt.AlignLeft | Qt.AlignVCenter, "Controle")
        p.setPen(QColor(theme.INK_MUTED()))
        p.setFont(_fonte(10.5))
        p.drawText(QRectF(74, 37, self.width() - 80, 20), Qt.AlignLeft | Qt.AlignVCenter, "de Lucros")
