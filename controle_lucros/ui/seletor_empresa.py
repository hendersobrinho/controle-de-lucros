"""Escolher empresa por código ou por nome, em todo o programa.

Uma lista suspensa com dezenas de empresas obrigava a rolar e procurar de
olho. Aqui são dois campos lado a lado:

- **Código** (o nº da empresa): digita e aperta Enter (ou sai do campo) — a
  empresa aparece na hora. É o caminho de quem já sabe o número de cabeça.
- **Nome**: digita parte do nome e aperta Enter — abre a janela de busca já
  filtrada.

**F2** em qualquer dos dois abre a janela de busca, que acha pelo nome, pelo
código ou pelo CNPJ. O botão da lupa faz o mesmo, pra quem usa o mouse.

A classe imita a parte da QComboBox que as telas usavam (currentData,
findData, setCurrentIndex, currentIndexChanged…), pra trocar uma pela outra
sem reescrever as telas.
"""
from __future__ import annotations

from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import repositories as repo
from .lista_fichas import ListaFichas
from .theme import SEAL_RED


def _codigo_igual(digitado: str, codigo: str | None) -> bool:
    """"42", "042" e " 42 " são a mesma empresa nº 042."""
    a, b = digitado.strip(), (codigo or "").strip()
    if not a or not b:
        return False
    if a.isdigit() and b.isdigit():
        return int(a) == int(b)
    return a.lower() == b.lower()


class DialogoBuscaEmpresa(QDialog):
    """A janelinha de busca: digita, a lista filtra, Enter ou dois cliques
    escolhem."""

    def __init__(self, empresas: list, termo: str = "", parent=None):
        super().__init__(parent)
        self._empresas = empresas
        self.empresa_id: int | None = None
        self.setWindowTitle("Buscar empresa")
        self.setMinimumSize(520, 480)

        self.busca = QLineEdit(termo)
        self.busca.setPlaceholderText("Nome, código ou CNPJ…")
        self.busca.setClearButtonEnabled(True)
        self.busca.textChanged.connect(self._filtrar)
        self.busca.installEventFilter(self)

        self.lista = ListaFichas("Nenhuma empresa encontrada com esse termo.")
        self.lista.itemDoubleClicked.connect(lambda _item: self._escolher())
        self.lista.itemSelectionChanged.connect(self._ajustar_botao)

        self.botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.botoes.button(QDialogButtonBox.Ok).setText("Escolher")
        self.botoes.accepted.connect(self._escolher)
        self.botoes.rejected.connect(self.reject)

        dica = QLabel("↑ ↓ para andar na lista · Enter escolhe · Esc fecha")
        dica.setProperty("role", "subtitulo")

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(self.busca)
        layout.addWidget(self.lista, 1)
        layout.addWidget(dica)
        layout.addWidget(self.botoes)

        self._filtrar()
        self.busca.setFocus()
        self.busca.setCursorPosition(len(termo))

    def _filtrar(self, *_args) -> None:
        termo = self.busca.text().strip().lower()
        digitos = "".join(c for c in termo if c.isdigit())
        self.lista.clear()
        for e in self._empresas:
            if (
                not termo
                or termo in e.nome.lower()
                or _codigo_igual(termo, e.numero_chamada)
                or (len(digitos) >= 3 and digitos in repo.normalizar_documento(e.cnpj))
            ):
                detalhe = f"código {e.numero_chamada}" if e.numero_chamada else "sem código"
                if e.cnpj:
                    detalhe += f" · CNPJ {e.cnpj}"
                self.lista.adicionar(e.id, e.nome, detalhe)
        if self.lista.count():
            self.lista.setCurrentRow(0)
        self._ajustar_botao()

    def _ajustar_botao(self) -> None:
        self.botoes.button(QDialogButtonBox.Ok).setEnabled(self.lista.id_selecionado() is not None)

    def _escolher(self) -> None:
        escolhido = self.lista.id_selecionado()
        if escolhido is None:
            return
        self.empresa_id = escolhido
        self.accept()

    def eventFilter(self, objeto, evento) -> bool:  # noqa: N802 (Qt override)
        # Setas no campo de busca andam na lista, sem precisar tirar o foco
        # de onde se digita.
        if objeto is self.busca and evento.type() == QEvent.KeyPress:
            tecla = evento.key()
            if tecla in (Qt.Key_Down, Qt.Key_Up) and self.lista.count():
                passo = 1 if tecla == Qt.Key_Down else -1
                linha = max(0, min(self.lista.count() - 1, self.lista.currentRow() + passo))
                self.lista.setCurrentRow(linha)
                return True
            if tecla in (Qt.Key_Return, Qt.Key_Enter):
                self._escolher()
                return True
        return super().eventFilter(objeto, evento)


class SeletorEmpresa(QWidget):
    """Código + nome + lupa. Ver o docstring do módulo."""

    currentIndexChanged = Signal(int)  # noqa: N815 — mesmo nome da QComboBox

    def __init__(self, parent=None):
        super().__init__(parent)
        self._empresas: list = []
        self._indice = -1

        self.codigo = QLineEdit()
        self.codigo.setPlaceholderText("Código")
        self.codigo.setFixedWidth(84)
        self.codigo.setToolTip("Digite o código da empresa e aperte Enter. F2 abre a busca.")
        self.codigo.returnPressed.connect(self._aplicar_codigo)
        self.codigo.editingFinished.connect(self._aplicar_codigo)
        self.codigo.installEventFilter(self)

        self.nome = QLineEdit()
        self.nome.setPlaceholderText("Nome da empresa — Enter ou F2 para buscar")
        self.nome.setToolTip("Digite parte do nome e aperte Enter, ou F2, para buscar.")
        self.nome.returnPressed.connect(lambda: self.abrir_busca(self.nome.text()))
        self.nome.editingFinished.connect(self._restaurar_nome)
        self.nome.installEventFilter(self)

        self.btn_buscar = QPushButton("Buscar")
        self.btn_buscar.setToolTip("Buscar empresa pelo nome, código ou CNPJ (F2)")
        self.btn_buscar.setFocusPolicy(Qt.NoFocus)
        self.btn_buscar.clicked.connect(lambda: self.abrir_busca())

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.codigo)
        layout.addWidget(self.nome, 1)
        layout.addWidget(self.btn_buscar)

    # ------------------------------------------------- API de QComboBox --
    def definir_empresas(self, empresas) -> None:
        anterior = self.currentData()
        self._empresas = list(empresas)
        indice = self.findData(anterior)
        if indice < 0:
            indice = 0 if self._empresas else -1
        self._indice = -2  # força o aviso, como a QComboBox ao ser preenchida
        self.setCurrentIndex(indice)

    def clear(self) -> None:
        self.definir_empresas([])

    def count(self) -> int:
        return len(self._empresas)

    def currentIndex(self) -> int:  # noqa: N802
        return self._indice

    def currentData(self):  # noqa: N802
        return self._empresas[self._indice].id if 0 <= self._indice < len(self._empresas) else None

    def currentText(self) -> str:  # noqa: N802
        return self._empresas[self._indice].nome if 0 <= self._indice < len(self._empresas) else ""

    def findData(self, empresa_id) -> int:  # noqa: N802
        for i, e in enumerate(self._empresas):
            if e.id == empresa_id:
                return i
        return -1

    def setCurrentIndex(self, indice: int) -> None:  # noqa: N802
        if not -1 <= indice < len(self._empresas):
            indice = -1
        mudou = indice != self._indice
        self._indice = indice
        self._mostrar()
        if mudou:
            self.currentIndexChanged.emit(indice)

    def selecionar_id(self, empresa_id) -> bool:
        indice = self.findData(empresa_id)
        if indice >= 0:
            self.setCurrentIndex(indice)
        return indice >= 0

    # ------------------------------------------------------- comportamento --
    def _mostrar(self) -> None:
        empresa = self._empresas[self._indice] if 0 <= self._indice < len(self._empresas) else None
        self.codigo.setText((empresa.numero_chamada or "") if empresa else "")
        self.nome.setText(empresa.nome if empresa else "")
        self.nome.setCursorPosition(0)
        self._marcar_erro(False)

    def _restaurar_nome(self) -> None:
        # Texto digitado e abandonado não é escolha: volta o nome da escolhida.
        if self.nome.text() != self.currentText():
            self._mostrar()

    def _aplicar_codigo(self) -> None:
        digitado = self.codigo.text().strip()
        atual = self._empresas[self._indice] if 0 <= self._indice < len(self._empresas) else None
        if atual is not None and _codigo_igual(digitado, atual.numero_chamada):
            self._marcar_erro(False)
            return
        if not digitado:
            self._mostrar()
            return
        for i, e in enumerate(self._empresas):
            if _codigo_igual(digitado, e.numero_chamada):
                self.setCurrentIndex(i)
                return
        self._marcar_erro(True, f"Nenhuma empresa com o código {digitado}. F2 abre a busca.")

    def _marcar_erro(self, erro: bool, texto: str = "") -> None:
        self.codigo.setStyleSheet(f"border: 1px solid {SEAL_RED()};" if erro else "")
        self.codigo.setToolTip(texto or "Digite o código da empresa e aperte Enter. F2 abre a busca.")

    def abrir_busca(self, termo: str = "") -> None:
        if not self._empresas:
            return
        if termo == self.currentText():
            termo = ""
        dialogo = DialogoBuscaEmpresa(self._empresas, termo.strip(), self)
        if dialogo.exec() == QDialog.Accepted and dialogo.empresa_id is not None:
            self.selecionar_id(dialogo.empresa_id)
        else:
            self._mostrar()

    def eventFilter(self, objeto, evento) -> bool:  # noqa: N802 (Qt override)
        if evento.type() == QEvent.KeyPress and evento.key() == Qt.Key_F2:
            self.abrir_busca(self.nome.text() if objeto is self.nome else "")
            return True
        return super().eventFilter(objeto, evento)
