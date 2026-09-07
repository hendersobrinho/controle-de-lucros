"""Aba genérica de CRUD: tabela de registros + formulário de edição.

O formulário tem três estados visíveis (ver aplicar_modo_formulario): enquanto
nada está selecionado ele fica desabilitado e o destaque de botão primário vai
pro "Novo" — sem isso, a tela abre com campos aparentemente editáveis e nada
indicando que digitar ali por cima de um registro selecionado ALTERA aquele
registro em vez de criar um novo."""
from __future__ import annotations

from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QAbstractSpinBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import theme

LOCALE_BR = QLocale(QLocale.Portuguese, QLocale.Brazil)


def preencher_combo(combo: QComboBox, itens, texto_attr: str = "nome") -> None:
    combo.clear()
    for item in itens:
        combo.addItem(getattr(item, texto_attr), item.id)


def selecionar_combo_por_id(combo: QComboBox, id_) -> None:
    idx = combo.findData(id_)
    combo.setCurrentIndex(idx if idx >= 0 else 0)


def formatar_numero(spin: QDoubleSpinBox) -> None:
    """Aplica separador de milhar (ponto) e decimal (vírgula) — ex.: 1.234.567,89
    — pra números grandes (capital, cotas, valores) ficarem legíveis."""
    spin.setLocale(LOCALE_BR)
    spin.setGroupSeparatorShown(True)
    spin.setButtonSymbols(QAbstractSpinBox.NoButtons)


def configurar_campo_cnpj(campo: QLineEdit) -> None:
    """Máscara do CNPJ alfanumérico (Receita Federal, formato vigente desde
    jul/2026): 12 posições alfanuméricas (letra maiúscula ou dígito) + 2
    dígitos verificadores numéricos, no padrão AA.AAA.AAA/AAAA-DV. CNPJs
    antigos (só números) continuam cabendo na mesma máscara."""
    campo.setInputMask(">NN.NNN.NNN/NNNN-99;_")


def configurar_campo_cpf(campo: QLineEdit) -> None:
    """Máscara do CPF: 11 dígitos no padrão AAA.AAA.AAA-DV."""
    campo.setInputMask("000.000.000-00;_")


def documento_valido_ou_vazio(campo: QLineEdit) -> str:
    """Mesma regra do CNPJ: retorna o documento formatado se completo, senão
    vazio — nunca guarda CPF/CNPJ pela metade."""
    return campo.text() if campo.hasAcceptableInput() else ""


def formatar_valor_br(valor: float, casas: int = 2) -> str:
    """1234567.5 -> '1.234.567,50' — mesmo padrão (ponto de milhar, vírgula
    decimal) usado nos QDoubleSpinBox, pra tabelas ficarem consistentes com
    os formulários."""
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "|").replace(".", ",").replace("|", ".")


MODO_VAZIO = "vazio"
MODO_NOVO = "novo"
MODO_EDICAO = "edicao"
MODO_SALVO = "salvo"
MODO_CANCELADO = "cancelado"

MODOS_COM_FORMULARIO_ABERTO = (MODO_NOVO, MODO_EDICAO)

AVISOS_FORMULARIO = {
    MODO_VAZIO: (
        "Formulário bloqueado. Clique em <b>Novo</b> para cadastrar, "
        "ou selecione um registro na tabela para editar."
    ),
    MODO_NOVO: "<b>Novo registro</b> — preencha os campos e clique em Salvar.",
    MODO_EDICAO: (
        "Editando <b>{descricao}</b> — o que for salvo substitui esse registro. "
        "Para cadastrar outro, clique em <b>Novo</b>."
    ),
    MODO_SALVO: (
        "Registro salvo. Clique em <b>Novo</b> para cadastrar outro, "
        "ou selecione um na tabela para editar."
    ),
    MODO_CANCELADO: (
        "Cancelado — nada foi alterado. Clique em <b>Novo</b> para cadastrar, "
        "ou selecione um registro na tabela para editar."
    ),
}


def realcar_botao(botao: QPushButton, realcado: bool) -> None:
    """Liga/desliga o destaque de botão primário. Trocar a property depois de
    o QSS já ter sido aplicado exige repolir o widget — o Qt não reavalia o
    seletor sozinho, e o botão ficaria com a aparência antiga."""
    botao.setProperty("role", "primario" if realcado else "")
    botao.style().unpolish(botao)
    botao.style().polish(botao)


def aplicar_modo_formulario(
    painel_campos: QWidget,
    aviso: QLabel,
    botoes: dict,
    modo: str,
    descricao: str = "",
) -> None:
    """Deixa o formulário coerente com o estado atual: campos habilitados só
    quando há o que editar, botões conforme o que faz sentido apertar, e uma
    linha de texto dizendo em que pé a coisa está.

    O destaque de primário acompanha a próxima ação esperada — bloqueado, o
    olho vai pro "Novo"; aberto, vai pro "Salvar" — que é o efeito visual que
    faltava pra deixar claro que o cadastro começa pelo botão.

    `botoes` traz "novo", "salvar" e (opcionalmente) "cancelar" e "excluir"."""
    aberto = modo in MODOS_COM_FORMULARIO_ABERTO
    painel_campos.setEnabled(aberto)
    botoes["salvar"].setEnabled(aberto)
    if "excluir" in botoes:
        botoes["excluir"].setEnabled(modo == MODO_EDICAO)
    if "cancelar" in botoes:
        # Só aparece com o formulário aberto: com ele bloqueado não há o que
        # cancelar, e um botão morto no meio dos outros só polui.
        botoes["cancelar"].setVisible(aberto)
    realcar_botao(botoes["novo"], not aberto)
    realcar_botao(botoes["salvar"], aberto)
    aviso.setText(AVISOS_FORMULARIO[modo].format(descricao=descricao))
    aviso.setProperty("modo", modo)
    aviso.setStyleSheet(_estilo_aviso(modo))


def _estilo_aviso(modo: str) -> str:
    cores = {
        MODO_VAZIO: theme.INK_MUTED(),
        MODO_NOVO: theme.BRASS_DARK(),
        MODO_EDICAO: theme.BRASS_DARK(),
        MODO_SALVO: theme.SEAL_GREEN(),
        MODO_CANCELADO: theme.INK_MUTED(),
    }
    cor = cores[modo]
    return (
        f"color: {cor}; font-size: 11px; padding: 7px 10px; "
        f"border-left: 3px solid {cor}; background: {theme.PAPER()}; border-radius: 3px;"
    )


def criar_aviso_formulario() -> QLabel:
    aviso = QLabel()
    aviso.setTextFormat(Qt.RichText)
    aviso.setWordWrap(True)
    return aviso


def cnpj_valido_ou_vazio(campo: QLineEdit) -> str:
    """Retorna o CNPJ formatado se estiver completo, senão string vazia —
    não guarda formato pela metade no banco."""
    return campo.text() if campo.hasAcceptableInput() else ""


class CartaoEstatistica(QFrame):
    """Cartão pequeno com título, valor em destaque e uma linha de contexto
    opcional — usado nas telas de dashboard para métricas rápidas."""

    def __init__(self, titulo: str, parent=None):
        super().__init__(parent)
        self.setProperty("role", "card")

        self._rotulo_titulo = QLabel(titulo)
        self._rotulo_titulo.setProperty("role", "subtitulo")
        self._rotulo_titulo.setWordWrap(True)

        self._rotulo_valor = QLabel("—")
        self._rotulo_valor.setProperty("role", "titulo")
        self._rotulo_valor.setWordWrap(True)

        self._rotulo_contexto = QLabel("")
        self._rotulo_contexto.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(2)
        layout.addWidget(self._rotulo_titulo)
        layout.addWidget(self._rotulo_valor)
        layout.addWidget(self._rotulo_contexto)

        self._aplicar_cores()
        theme.estado().mudou.connect(self._aplicar_cores)

    def _aplicar_cores(self) -> None:
        self._rotulo_contexto.setStyleSheet(f"color: {theme.INK_MUTED()}; font-size: 11px;")

    def definir(self, valor: str, contexto: str = "", cor: str | None = None) -> None:
        self._rotulo_valor.setText(valor)
        self._rotulo_valor.setStyleSheet(f"color: {cor};" if cor else "")
        self._rotulo_contexto.setText(contexto)
        self._rotulo_contexto.setVisible(bool(contexto))


class CrudTab(QWidget):
    colunas: list[tuple[str, str]] = []

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._registro_atual_id = None
        self._registros: list = []
        self._callback_selecao = None

        self.busca = QLineEdit()
        self.busca.setPlaceholderText(self.placeholder_busca())
        self.busca.textChanged.connect(lambda _texto: self.atualizar())

        self.tabela = QTableWidget(0, len(self.colunas))
        self.tabela.setHorizontalHeaderLabels([c[0] for c in self.colunas])
        self.tabela.setAlternatingRowColors(True)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.itemSelectionChanged.connect(self._ao_selecionar)

        self.form_layout = QFormLayout()
        self.form_layout.setSpacing(10)
        self.montar_formulario(self.form_layout)

        # Os campos vão num container próprio pra dar pra bloquear o
        # formulário inteiro com um setEnabled só — o QSS já escurece tudo
        # junto, e é esse escurecimento que mostra que a tela está esperando
        # um clique em "Novo" (ou a seleção de uma linha).
        self.painel_campos = QWidget()
        self.painel_campos.setLayout(self.form_layout)

        self.aviso_form = criar_aviso_formulario()

        self.btn_novo = QPushButton("Novo")
        self.btn_salvar = QPushButton("Salvar")
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_excluir = QPushButton("Excluir")
        self.btn_excluir.setProperty("role", "perigo")
        self.btn_novo.clicked.connect(self.novo)
        self.btn_salvar.clicked.connect(self.salvar)
        self.btn_cancelar.clicked.connect(self.cancelar)
        self.btn_excluir.clicked.connect(self.excluir)

        botoes = QHBoxLayout()
        botoes.addWidget(self.btn_novo)
        botoes.addWidget(self.btn_salvar)
        botoes.addWidget(self.btn_cancelar)
        botoes.addWidget(self.btn_excluir)
        botoes.addStretch()

        form_container = QVBoxLayout()
        form_container.addWidget(self.aviso_form)
        form_container.addWidget(self.painel_campos)
        form_container.addLayout(botoes)
        form_container.addStretch()

        coluna_tabela = QVBoxLayout()
        coluna_tabela.setSpacing(8)
        coluna_tabela.addWidget(self.busca)
        coluna_tabela.addWidget(self.tabela)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(20)
        layout.addLayout(coluna_tabela, 2)
        layout.addLayout(form_container, 1)

        self._modo = MODO_VAZIO
        self._descricao_modo = ""
        self.atualizar()
        self._definir_modo(MODO_VAZIO)
        theme.estado().mudou.connect(lambda: self._definir_modo(self._modo, self._descricao_modo))

    # -------- a sobrescrever nas subclasses --------
    def montar_formulario(self, form_layout: QFormLayout) -> None:
        raise NotImplementedError

    def listar(self) -> list:
        raise NotImplementedError

    def ler_form(self, id_atual):
        raise NotImplementedError

    def carregar_form(self, registro) -> None:
        raise NotImplementedError

    def limpar_form(self) -> None:
        raise NotImplementedError

    def salvar_registro(self, registro) -> None:
        raise NotImplementedError

    def excluir_registro(self, id_) -> None:
        raise NotImplementedError

    def antes_atualizar(self) -> None:
        """Ponto de extensão: recarregar combos dependentes de outras tabelas."""

    def definir_callback_selecao(self, callback) -> None:
        """Chamado com o registro sempre que uma linha é selecionada — usado
        para sincronizar outra aba com o item selecionado aqui."""
        self._callback_selecao = callback

    def ao_selecionar(self, registro) -> None:
        if self._callback_selecao is not None:
            self._callback_selecao(registro)

    def valor_coluna(self, registro, attr):
        return getattr(registro, attr, None)

    def placeholder_busca(self) -> str:
        """Sobrescrever pra ajustar o texto de dica do campo de busca."""
        return "Buscar por nome ou código…"

    def corresponde_busca(self, registro, termo: str) -> bool:
        """Sobrescrever pra incluir outros campos (código, CPF, CNPJ…) na busca."""
        return termo in str(getattr(registro, "nome", "")).lower()

    # -------- comportamento comum --------
    def atualizar(self) -> None:
        self.antes_atualizar()
        registros = self.listar()
        termo = self.busca.text().strip().lower()
        if termo:
            registros = [r for r in registros if self.corresponde_busca(r, termo)]
        self._registros = registros
        self.tabela.setRowCount(len(self._registros))
        for row, registro in enumerate(self._registros):
            for col, (_, attr) in enumerate(self.colunas):
                valor = self.valor_coluna(registro, attr)
                item = QTableWidgetItem("" if valor is None else str(valor))
                item.setData(Qt.UserRole, registro.id)
                self.tabela.setItem(row, col, item)
        self.tabela.resizeColumnsToContents()

    def _definir_modo(self, modo: str, descricao: str = "") -> None:
        self._modo = modo
        self._descricao_modo = descricao
        aplicar_modo_formulario(
            self.painel_campos,
            self.aviso_form,
            {
                "novo": self.btn_novo,
                "salvar": self.btn_salvar,
                "cancelar": self.btn_cancelar,
                "excluir": self.btn_excluir,
            },
            modo,
            descricao,
        )

    def descricao_registro(self, registro) -> str:
        """Como o registro em edição é chamado no aviso. Sobrescrever quando
        "nome" não for o campo que identifica a coisa pra quem olha."""
        return str(getattr(registro, "nome", "") or "este registro")

    def _ao_selecionar(self) -> None:
        linhas = self.tabela.selectionModel().selectedRows()
        if not linhas:
            return
        registro = self._registros[linhas[0].row()]
        self._registro_atual_id = registro.id
        self.carregar_form(registro)
        self._definir_modo(MODO_EDICAO, self.descricao_registro(registro))
        self.ao_selecionar(registro)

    def novo(self) -> None:
        self._registro_atual_id = None
        self.tabela.clearSelection()
        self.limpar_form()
        self._definir_modo(MODO_NOVO)
        self._focar_primeiro_campo()

    def _focar_primeiro_campo(self) -> None:
        """Depois de destravar o formulário, o cursor já vai pro primeiro
        campo — sem isso o clique em "Novo" libera a digitação mas ainda
        exige um segundo clique pra começar a digitar."""
        campo = self.form_layout.itemAt(0, QFormLayout.FieldRole)
        if campo is not None and campo.widget() is not None:
            campo.widget().setFocus()

    def cancelar(self) -> None:
        """Sai do cadastro/edição sem gravar nada. Descarta o que estiver
        digitado — é o que "Cancelar" quer dizer, e sem ele a única saída de
        um formulário aberto era salvar."""
        self._registro_atual_id = None
        self.tabela.clearSelection()
        self.limpar_form()
        self._definir_modo(MODO_CANCELADO)

    def salvar(self) -> None:
        try:
            registro = self.ler_form(self._registro_atual_id)
            self.salvar_registro(registro)
        except Exception as exc:
            QMessageBox.warning(self, "Erro ao salvar", str(exc))
            return
        self.atualizar()
        self._registro_atual_id = None
        self.tabela.clearSelection()
        self.limpar_form()
        self._definir_modo(MODO_SALVO)

    def excluir(self) -> None:
        if self._registro_atual_id is None:
            QMessageBox.information(self, "Excluir", "Selecione um registro na tabela.")
            return
        resposta = QMessageBox.question(
            self, "Excluir", "Confirma a exclusão do registro selecionado?"
        )
        if resposta != QMessageBox.Yes:
            return
        try:
            self.excluir_registro(self._registro_atual_id)
        except Exception as exc:
            QMessageBox.warning(self, "Erro ao excluir", str(exc))
            return
        self.atualizar()
        self._registro_atual_id = None
        self.tabela.clearSelection()
        self.limpar_form()
        self._definir_modo(MODO_VAZIO)
