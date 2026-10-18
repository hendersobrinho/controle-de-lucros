"""As peças da ficha do sócio separada em abas (aba Sócios).

Um sócio de várias empresas tinha todas as participações e movimentações
numa coluna só, e ficava difícil saber o que era de qual empresa. Agora a
ficha tem uma aba "Visão geral" — todas as empresas lado a lado e todas as
movimentações numa linha do tempo — e uma aba por empresa, com a
participação e o histórico só daquela empresa.
"""
from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .common import formatar_data_br, formatar_percentual, formatar_valor_br

LIMITE_NOME_ABA = 24

ETIQUETAS_MOVIMENTO = {
    "entrou": ("Entrou", "ativo"),
    "saiu": ("Saiu", "saiu"),
    "mudou": ("Participação refeita", "mudou"),
}


def _dica(texto: str = "") -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setProperty("role", "subtitulo")
    rotulo.setWordWrap(True)
    return rotulo


def _secao(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setProperty("role", "secao")
    return rotulo


def _hairline() -> QFrame:
    linha = QFrame()
    linha.setProperty("role", "hairline")
    return linha


def bloco(titulo: str = "") -> tuple[QFrame, QVBoxLayout]:
    quadro = QFrame()
    quadro.setProperty("role", "card")
    coluna = QVBoxLayout(quadro)
    coluna.setContentsMargins(20, 16, 20, 16)
    coluna.setSpacing(10)
    if titulo:
        coluna.addWidget(_secao(titulo))
    return quadro, coluna


_SUFIXOS = (" LTDA", " ME", " EPP", " S/A", " S.A.", " SA", " EIRELI", " SLU")


def nome_curto(nome: str) -> str:
    """Nome pra aba: sem o "LTDA" e afins (todas têm, não distingue nada) e
    cortado com "…" se ainda for comprido. O nome inteiro fica na dica."""
    curto = nome.strip()
    for sufixo in _SUFIXOS:
        if curto.upper().endswith(sufixo):
            curto = curto[: -len(sufixo)].rstrip(" -.,")
            break
    return curto if len(curto) <= LIMITE_NOME_ABA else curto[: LIMITE_NOME_ABA - 1].rstrip() + "…"


class _Fluxo(QLayout):
    """Layout que quebra linha quando não cabe, como texto: as abas de um
    sócio de muitas empresas descem pra linha de baixo em vez de sumirem
    atrás de uma barra de rolagem."""

    def __init__(self, parent=None, espaco: int = 8):
        super().__init__(parent)
        self._itens: list = []
        self._espaco = espaco

    def addItem(self, item) -> None:  # noqa: N802 (Qt override)
        self._itens.append(item)

    def count(self) -> int:
        return len(self._itens)

    def itemAt(self, indice: int):  # noqa: N802 (Qt override)
        return self._itens[indice] if 0 <= indice < len(self._itens) else None

    def takeAt(self, indice: int):  # noqa: N802 (Qt override)
        return self._itens.pop(indice) if 0 <= indice < len(self._itens) else None

    def expandingDirections(self):  # noqa: N802 (Qt override)
        return Qt.Orientations(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802 (Qt override)
        return True

    def heightForWidth(self, largura: int) -> int:  # noqa: N802 (Qt override)
        return self._arrumar(QRect(0, 0, largura, 0), so_medir=True)

    def setGeometry(self, retangulo) -> None:  # noqa: N802 (Qt override)
        super().setGeometry(retangulo)
        self._arrumar(retangulo, so_medir=False)

    def sizeHint(self):  # noqa: N802 (Qt override)
        return self.minimumSize()

    def minimumSize(self):  # noqa: N802 (Qt override)
        tamanho = QSize()
        for item in self._itens:
            tamanho = tamanho.expandedTo(item.minimumSize())
        return tamanho

    def _arrumar(self, retangulo, so_medir: bool) -> int:
        x, y, altura_linha = retangulo.x(), retangulo.y(), 0
        for item in self._itens:
            dica = item.sizeHint()
            if x + dica.width() > retangulo.right() and altura_linha > 0:
                x = retangulo.x()
                y += altura_linha + self._espaco
                altura_linha = 0
            if not so_medir:
                item.setGeometry(QRect(QPoint(x, y), dica))
            x += dica.width() + self._espaco
            altura_linha = max(altura_linha, dica.height())
        return y + altura_linha - retangulo.y()


class BarraAbas(QWidget):
    """Abas em pílulas: a escolhida em marinho, as outras em branco. Botões e
    não QTabBar: o QTabBar não quebra linha nem deixa estilizar diferente a
    aba de uma empresa de onde o sócio já saiu."""

    escolhida = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.botoes: list[QPushButton] = []
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self._grupo.idClicked.connect(self.escolhida.emit)
        self._fluxo = _Fluxo(self, espaco=8)
        self._fluxo.setContentsMargins(0, 0, 0, 0)
        politica = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        politica.setHeightForWidth(True)
        self.setSizePolicy(politica)

    def definir(self, abas: list[tuple[str, str, bool]]) -> None:
        """abas: (texto, dica, apagada)."""
        for botao in self.botoes:
            self._grupo.removeButton(botao)
            self._fluxo.removeWidget(botao)
            botao.hide()
            botao.deleteLater()
        self.botoes = []
        for indice, (texto, dica, apagada) in enumerate(abas):
            botao = QPushButton(texto, self)
            botao.setProperty("role", "abaFicha")
            botao.setProperty("apagada", "true" if apagada else "false")
            botao.setCheckable(True)
            botao.setCursor(Qt.PointingHandCursor)
            botao.setToolTip(dica)
            self._grupo.addButton(botao, indice)
            self._fluxo.addWidget(botao)
            botao.show()
            self.botoes.append(botao)
        self._fluxo.invalidate()
        self.updateGeometry()

    def escolher(self, indice: int) -> None:
        if 0 <= indice < len(self.botoes):
            self.botoes[indice].setChecked(True)

    def indice_atual(self) -> int:
        return self._grupo.checkedId()


def texto_do_movimento(evento: dict) -> str:
    """O detalhe do evento em palavras: quanto, e por qual alteração."""
    cotas = lambda v: f"{formatar_valor_br(v, 0)} cotas"  # noqa: E731
    if evento["tipo"] == "mudou":
        antes, depois = evento["percentual_antes"] or 0, evento["percentual"] or 0
        partes = (
            [f"{formatar_percentual(antes)} → {formatar_percentual(depois)}"] if abs(antes - depois) > 0.004
            else [f"continua com {formatar_percentual(depois)}"]
        )
        if (evento["cotas_antes"] or 0) != (evento["cotas"] or 0):
            partes.append(f"{formatar_valor_br(evento['cotas_antes'] or 0, 0)} → {cotas(evento['cotas'] or 0)}")
    elif evento["tipo"] == "saiu":
        partes = [f"tinha {formatar_percentual(evento['percentual'])}"]
        if evento["cotas"]:
            partes.append(cotas(evento["cotas"]))
        if evento.get("refeita"):
            partes.append("encerrada para refazer a participação — continua na empresa")
    else:
        partes = [formatar_percentual(evento["percentual"])]
        if evento["cotas"]:
            partes.append(cotas(evento["cotas"]))
        if evento["capital"]:
            partes.append(f"R$ {formatar_valor_br(evento['capital'])}")
    numero = evento["alteracao_numero"]
    partes.append(f"alteração Nº {numero}" if numero else "sem alteração contratual")
    return " · ".join(partes)


class LinhaMovimento(QWidget):
    """Uma movimentação: data, o que aconteceu e o detalhe. Clicar abre a
    "foto" da participação daquela época (ver socios_tab) — é onde mora o
    histórico, em vez de um cartão grande por participação antiga."""

    abrir = Signal(int)

    def __init__(self, evento: dict, parent=None):
        super().__init__(parent)
        self._vinculo_id = evento["vinculo_id"]
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Clique para ver como era a participação nessa época")

        data = QLabel(formatar_data_br(evento["data"]))
        data.setProperty("role", "valorCampo")
        data.setFixedWidth(92)

        texto, tom = ETIQUETAS_MOVIMENTO[evento["tipo"]]
        if evento.get("refeita"):
            texto = "Saída (refeita)"
        self.etiqueta = QLabel(texto)
        self.etiqueta.setProperty("role", "etiquetaSituacao")
        self.etiqueta.setProperty("tom", tom)
        self.etiqueta.setFixedWidth(150)
        self.etiqueta.setAlignment(Qt.AlignCenter)

        self.detalhe = _dica(texto_do_movimento(evento))
        seta = QLabel("›")
        seta.setProperty("role", "subtitulo")

        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 6, 0, 6)
        linha.setSpacing(14)
        linha.addWidget(data)
        linha.addWidget(self.etiqueta)
        linha.addWidget(self.detalhe, 1)
        linha.addWidget(seta)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.LeftButton:
            self.abrir.emit(self._vinculo_id)
        event.accept()


def montar_movimentos(coluna: QVBoxLayout, eventos: list[dict], ao_abrir) -> list[LinhaMovimento]:
    if not eventos:
        coluna.addWidget(_dica("Nenhuma movimentação registrada."))
        return []
    linhas = []
    for i, evento in enumerate(eventos):
        if i:
            coluna.addWidget(_hairline())
        linha = LinhaMovimento(evento)
        linha.abrir.connect(ao_abrir)
        coluna.addWidget(linha)
        linhas.append(linha)
    return linhas
