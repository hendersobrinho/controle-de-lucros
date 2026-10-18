"""Peças das janelas de cadastro: o mesmo desenho em todas.

As janelas antigas eram formulários de rótulo à esquerda e parágrafos de
explicação entre os campos — liam-se como texto. Aqui:

- o rótulo vai **em cima** do campo, pequeno e em maiúsculas, e os campos
  ficam lado a lado quando cabem;
- cada assunto é um bloco branco com título (e número, quando há ordem);
- a explicação longa vira um "ⓘ" ao lado do rótulo, com a dica no mouse; na
  tela fica no máximo uma linha curta;
- contas viram **equação**: [Cotas] × [Valor da cota] = [Capital], que mostra
  o que preencher e como o sistema chega no resultado.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QScrollArea,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


class Caixa(QWidget):
    """Contêiner sem fundo próprio. Um QWidget puro pinta o fundo da página
    (a regra de QSS do tema) e, dentro de um bloco branco, vira faixa cinza;
    uma subclasse não pinta, e fica transparente."""


def rotulo(texto: str, info: str = "") -> QWidget:
    """Rótulo pequeno em maiúsculas; com `info`, um ⓘ que explica no mouse."""
    caixa = Caixa()
    linha = QHBoxLayout(caixa)
    linha.setContentsMargins(0, 0, 0, 0)
    linha.setSpacing(5)
    texto_rotulo = QLabel(texto.upper())
    texto_rotulo.setProperty("role", "rotuloCampo")
    linha.addWidget(texto_rotulo)
    if info:
        icone = QLabel("ⓘ")
        icone.setProperty("role", "info")
        icone.setToolTip(info)
        icone.setCursor(Qt.WhatsThisCursor)
        linha.addWidget(icone)
    linha.addStretch()
    return caixa


def dica(texto: str = "") -> QLabel:
    rotulo_dica = QLabel(texto)
    rotulo_dica.setProperty("role", "dicaCampo")
    rotulo_dica.setWordWrap(True)
    return rotulo_dica


def campo(texto: str, widget: QWidget, nota: QLabel | str | None = None, info: str = "") -> QWidget:
    """Um campo: rótulo em cima, o widget e, se houver, uma nota curta."""
    caixa = Caixa()
    coluna = QVBoxLayout(caixa)
    coluna.setContentsMargins(0, 0, 0, 0)
    coluna.setSpacing(4)
    coluna.addWidget(rotulo(texto, info))
    coluna.addWidget(widget)
    if nota is not None:
        coluna.addWidget(nota if isinstance(nota, QLabel) else dica(nota))
    return caixa


def linha(*campos: QWidget, esticar: tuple[int, ...] | None = None) -> QHBoxLayout:
    arranjo = QHBoxLayout()
    arranjo.setSpacing(14)
    for indice, item in enumerate(campos):
        arranjo.addWidget(item, esticar[indice] if esticar else 1, Qt.AlignTop)
    return arranjo


def secao(titulo: str, numero: str = "", info: str = "") -> tuple[QFrame, QVBoxLayout]:
    """Um bloco branco com título — e o número do passo, quando há ordem."""
    bloco = QFrame()
    bloco.setProperty("role", "card")
    coluna = QVBoxLayout(bloco)
    coluna.setContentsMargins(18, 14, 18, 16)
    coluna.setSpacing(10)
    topo = QHBoxLayout()
    topo.setSpacing(8)
    if numero:
        circulo = QLabel(numero)
        circulo.setProperty("role", "numeroPasso")
        circulo.setAlignment(Qt.AlignCenter)
        circulo.setFixedSize(24, 24)
        circulo.setStyleSheet("border-radius: 12px; font-size: 12px;")
        topo.addWidget(circulo)
    nome = QLabel(titulo)
    nome.setProperty("role", "secao")
    topo.addWidget(nome)
    if info:
        icone = QLabel("ⓘ")
        icone.setProperty("role", "info")
        icone.setToolTip(info)
        topo.addWidget(icone)
    topo.addStretch()
    coluna.addLayout(topo)
    return bloco, coluna


def cabecalho(titulo: str, subtitulo: str = "") -> QVBoxLayout:
    coluna = QVBoxLayout()
    coluna.setSpacing(2)
    nome = QLabel(titulo)
    nome.setProperty("role", "titulo")
    nome.setWordWrap(True)
    coluna.addWidget(nome)
    if subtitulo:
        sub = QLabel(subtitulo)
        sub.setProperty("role", "subtitulo")
        sub.setWordWrap(True)
        coluna.addWidget(sub)
    return coluna


def operador(simbolo: str) -> QLabel:
    sinal = QLabel(simbolo)
    sinal.setProperty("role", "operador")
    sinal.setAlignment(Qt.AlignCenter)
    sinal.setFixedWidth(22)
    return sinal


def equacao(*partes) -> QWidget:
    """Campos e sinais numa linha: equacao(campo_a, "×", campo_b, "=", campo_c).
    Os sinais ficam na altura dos campos, não dos rótulos."""
    caixa = Caixa()
    arranjo = QHBoxLayout(caixa)
    arranjo.setContentsMargins(0, 0, 0, 0)
    arranjo.setSpacing(6)
    for parte in partes:
        if isinstance(parte, str):
            coluna = QVBoxLayout()
            coluna.setSpacing(0)
            coluna.addSpacing(18)  # a altura do rótulo dos campos
            coluna.addWidget(operador(parte))
            coluna.addStretch()
            arranjo.addLayout(coluna)
        else:
            arranjo.addWidget(parte, 1, Qt.AlignTop)
    return caixa


def botoes_rodape(*botoes_esquerda: QPushButton, direita: tuple[QPushButton, ...] = ()) -> QHBoxLayout:
    arranjo = QHBoxLayout()
    arranjo.setSpacing(8)
    for botao in botoes_esquerda:
        arranjo.addWidget(botao)
    arranjo.addStretch()
    for botao in direita:
        arranjo.addWidget(botao)
    return arranjo


class OpcoesLadoALado(QWidget):
    """Duas (ou mais) opções em botões lado a lado, uma escolhida — no lugar
    de uma lista suspensa quando as opções cabem à vista. Imita o pedaço da
    QComboBox que as telas usam (currentData, findData, setCurrentIndex,
    currentIndexChanged)."""

    currentIndexChanged = Signal(int)  # noqa: N815 — mesmo nome da QComboBox

    def __init__(self, opcoes: list[tuple[str, object]], parent=None):
        super().__init__(parent)
        self._dados = [dado for _texto, dado in opcoes]
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        arranjo = QHBoxLayout(self)
        arranjo.setContentsMargins(0, 0, 0, 0)
        arranjo.setSpacing(0)
        self.botoes = []
        for indice, (texto, _dado) in enumerate(opcoes):
            botao = QPushButton(texto)
            botao.setCheckable(True)
            botao.setProperty("role", "segmento")
            posicao = "unico" if len(opcoes) == 1 else (
                "inicio" if indice == 0 else "fim" if indice == len(opcoes) - 1 else "meio")
            botao.setProperty("posicao", posicao)
            botao.setCursor(Qt.PointingHandCursor)
            botao.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            self._grupo.addButton(botao, indice)
            arranjo.addWidget(botao)
            self.botoes.append(botao)
        self._grupo.idClicked.connect(self.currentIndexChanged.emit)
        if self.botoes:
            self.botoes[0].setChecked(True)

    def currentIndex(self) -> int:  # noqa: N802
        return self._grupo.checkedId()

    def currentData(self):  # noqa: N802
        indice = self.currentIndex()
        return self._dados[indice] if 0 <= indice < len(self._dados) else None

    def findData(self, dado) -> int:  # noqa: N802
        return self._dados.index(dado) if dado in self._dados else -1

    def setCurrentIndex(self, indice: int) -> None:  # noqa: N802
        if 0 <= indice < len(self.botoes) and indice != self.currentIndex():
            self.botoes[indice].setChecked(True)
            self.currentIndexChanged.emit(indice)

    def count(self) -> int:
        return len(self.botoes)


def montar_janela(dialogo: QDialog, topo, blocos: list, rodape, largura: int = 620) -> None:
    """Cabeçalho em cima, os blocos no meio (rolando, se a tela for baixa) e
    os botões sempre à vista embaixo."""
    dialogo.setMinimumWidth(largura)
    corpo = Caixa()
    coluna = QVBoxLayout(corpo)
    coluna.setContentsMargins(0, 0, 4, 0)
    coluna.setSpacing(12)
    for bloco in blocos:
        if isinstance(bloco, QWidget):
            coluna.addWidget(bloco)
        else:
            coluna.addLayout(bloco)
    coluna.addStretch()
    rolagem = QScrollArea()
    rolagem.setProperty("role", "listaCartoes")
    rolagem.setWidgetResizable(True)
    rolagem.setFrameShape(QFrame.NoFrame)
    rolagem.setWidget(corpo)
    rolagem.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    externo = QVBoxLayout(dialogo)
    externo.setContentsMargins(22, 18, 22, 16)
    externo.setSpacing(12)
    externo.addLayout(topo)
    externo.addWidget(rolagem, 1)
    externo.addLayout(rodape)
    # Abre do tamanho do conteúdo, sem rolagem — até o limite da tela.
    corpo.adjustSize()
    tela = dialogo.screen().availableGeometry().height() if dialogo.screen() else 900
    rolagem.setMinimumHeight(min(corpo.sizeHint().height() + 4, int(tela * 0.72)))
