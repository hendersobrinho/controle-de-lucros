"""A grade de campos onde se diz, por letra, em que coluna da planilha está
cada informação.

É o coração da importação configurável: em vez de exigir que a planilha tenha
o cabeçalho que o sistema conhece, a pessoa descreve a planilha que ela já
tem. Cada quadradinho recebe a letra que aparece no topo da coluna no Excel —
o mesmo endereço que ela usaria numa fórmula — e campo em branco é campo que
aquela origem não traz.

A parte que decide o que é válido, o que é obrigatório e como ler o arquivo
fica em controle_lucros.layout_importacao; aqui é só a tela.
"""
from __future__ import annotations

from PySide6.QtCore import QRegularExpression, Qt, Signal
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..layout_importacao import (
    CAMPO_OBRIGATORIO,
    GRUPOS_CAMPOS,
    LINHA_INICIAL_PADRAO,
    LayoutImportacao,
    ROTULOS_CAMPOS,
    limpar_colunas,
)

# Três letras cobrem até a coluna ZZ (702 colunas) — muito além de qualquer
# planilha de cadastro real, e curto o bastante pro campo caber ao lado do
# rótulo sem espremer a grade.
_MAXIMO_LETRAS = 3


class CampoLetra(QLineEdit):
    """Caixinha de uma coluna. Aceita só letras e já mostra em maiúsculo, pra
    "c" e "C" não parecerem configurações diferentes."""

    def __init__(self, campo: str, parent=None):
        super().__init__(parent)
        self.campo = campo
        self.setMaxLength(_MAXIMO_LETRAS)
        self.setFixedWidth(52)
        self.setAlignment(Qt.AlignCenter)
        self.setProperty("role", "mono")
        self.setPlaceholderText("—")
        self.setValidator(QRegularExpressionValidator(QRegularExpression("[A-Za-z]{0,3}")))
        self.setToolTip(
            f"Coluna da planilha com \"{ROTULOS_CAMPOS.get(campo, campo)}\". "
            "Deixe em branco se a planilha não tiver essa informação."
        )
        self.textChanged.connect(self._para_maiusculo)

    def _para_maiusculo(self, texto: str) -> None:
        maiusculo = texto.upper()
        if maiusculo != texto:
            posicao = self.cursorPosition()
            self.blockSignals(True)
            self.setText(maiusculo)
            self.blockSignals(False)
            self.setCursorPosition(posicao)
            self.textChanged.emit(maiusculo)


class EditorLayout(QWidget):
    """Nome do layout, linha em que os dados começam e a grade de colunas."""

    alterado = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._campos: dict[str, CampoLetra] = {}
        self._id_atual: int | None = None

        self.nome = QLineEdit()
        self.nome.setPlaceholderText("Ex.: Relatório de sócios — sistema antigo")
        self.nome.setToolTip("Como este formato aparece na lista. Use o nome da origem do arquivo.")
        self.nome.textChanged.connect(lambda _t: self.alterado.emit())

        self.linha_inicial = QSpinBox()
        self.linha_inicial.setRange(1, 10000)
        self.linha_inicial.setValue(LINHA_INICIAL_PADRAO)
        self.linha_inicial.setFixedWidth(80)
        self.linha_inicial.setToolTip(
            "Número da primeira linha com dados, como o Excel mostra na lateral. "
            "Planilha com uma linha de cabeçalho começa na linha 2."
        )
        self.linha_inicial.valueChanged.connect(lambda _v: self.alterado.emit())

        cabecalho = QHBoxLayout()
        cabecalho.setSpacing(8)
        cabecalho.addWidget(QLabel("Nome do layout:"))
        cabecalho.addWidget(self.nome, 1)
        cabecalho.addSpacing(12)
        cabecalho.addWidget(QLabel("Dados começam na linha:"))
        cabecalho.addWidget(self.linha_inicial)

        grade = QGridLayout()
        grade.setHorizontalSpacing(18)
        grade.setVerticalSpacing(12)
        for indice, grupo in enumerate(GRUPOS_CAMPOS):
            grade.addWidget(self._montar_grupo(grupo), indice // 2, indice % 2)
        grade.setColumnStretch(0, 1)
        grade.setColumnStretch(1, 1)

        self.dica = QLabel(
            "Digite em cada campo a <b>letra da coluna</b> onde a informação está na planilha "
            "(A, B, C… como no topo do Excel). Campo em branco é informação que aquela planilha "
            "não traz — ela simplesmente não é importada. O campo marcado com <b>*</b> é o único "
            "obrigatório: sem o nome da empresa não há a que ligar a linha."
        )
        self.dica.setWordWrap(True)
        self.dica.setProperty("role", "subtitulo")

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(12)
        coluna.addLayout(cabecalho)
        coluna.addWidget(self.dica)
        coluna.addLayout(grade)

    # ------------------------------------------------------------ montagem --
    def _montar_grupo(self, grupo) -> QWidget:
        caixa = QFrame()
        caixa.setProperty("role", "card")
        col = QVBoxLayout(caixa)
        col.setContentsMargins(16, 12, 16, 14)
        col.setSpacing(6)

        titulo = QLabel(grupo.nome)
        titulo.setProperty("role", "secao")
        ajuda = QLabel(grupo.ajuda)
        ajuda.setProperty("role", "subtitulo")
        ajuda.setWordWrap(True)
        col.addWidget(titulo)
        col.addWidget(ajuda)

        grade = QGridLayout()
        grade.setHorizontalSpacing(10)
        grade.setVerticalSpacing(6)
        for linha, campo in enumerate(grupo.campos):
            rotulo = ROTULOS_CAMPOS[campo]
            if campo == CAMPO_OBRIGATORIO:
                # O único campo sem o qual nenhuma linha pode ser aproveitada;
                # dizer isso aqui evita descobrir só na hora de salvar.
                rotulo += " *"
            etiqueta = QLabel(rotulo)
            etiqueta.setWordWrap(True)
            caixa_letra = CampoLetra(campo)
            caixa_letra.textChanged.connect(lambda _t: self.alterado.emit())
            self._campos[campo] = caixa_letra
            grade.addWidget(etiqueta, linha, 0)
            grade.addWidget(caixa_letra, linha, 1)
        grade.setColumnStretch(0, 1)
        col.addLayout(grade)
        col.addStretch()
        return caixa

    # -------------------------------------------------------------- estado --
    def carregar(self, layout: LayoutImportacao | None) -> None:
        """Mostra um layout salvo — ou limpa tudo, pra começar um novo."""
        anterior = self.blockSignals(True)
        self._id_atual = layout.id if layout else None
        self.nome.setText(layout.nome if layout else "")
        self.linha_inicial.setValue(layout.linha_inicial if layout else LINHA_INICIAL_PADRAO)
        for campo, caixa in self._campos.items():
            caixa.blockSignals(True)
            caixa.setText(layout.letra(campo) if layout else "")
            caixa.blockSignals(False)
        self.blockSignals(anterior)
        self.alterado.emit()

    def layout_atual(self) -> LayoutImportacao:
        """O que está na tela agora, salvo ou não."""
        return LayoutImportacao(
            id=self._id_atual,
            nome=self.nome.text().strip(),
            linha_inicial=self.linha_inicial.value(),
            colunas=limpar_colunas({campo: caixa.text() for campo, caixa in self._campos.items()}),
        )

    def definir_id(self, layout_id: int | None) -> None:
        self._id_atual = layout_id

    def limpar(self) -> None:
        self.carregar(None)

    def primeiro_campo(self) -> QLineEdit:
        return self.nome
