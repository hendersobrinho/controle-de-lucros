"""Aba genérica de CRUD: tabela de registros + formulário de edição.

O formulário tem três estados visíveis (ver aplicar_modo_formulario): enquanto
nada está selecionado ele fica desabilitado e o destaque de botão primário vai
pro "Novo" — sem isso, a tela abre com campos aparentemente editáveis e nada
indicando que digitar ali por cima de um registro selecionado ALTERA aquele
registro em vez de criar um novo."""
from __future__ import annotations

from PySide6.QtCore import QLocale, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
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
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from . import theme

LOCALE_BR = QLocale(QLocale.Portuguese, QLocale.Brazil)

ALTURA_LINHA_TABELA = 34

# Até onde a coluna flexível pode encolher para o resto caber na tela. Abaixo
# disso ela para de dizer qualquer coisa, e aí a barra de rolagem é melhor.
LARGURA_MINIMA_COLUNA_FLEXIVEL = 100


def larguras_ajustadas(conteudo: list[int], disponivel: int, flexivel: int = 0) -> list[int]:
    """Quanto cada coluna deve ocupar para a soma bater com a largura da tabela.

    Sobrando espaço, tudo vai para a coluna flexível — é ela que se beneficia,
    e o vão morto à direita desaparece. Faltando, é dela que sai, até um
    mínimo; só se ainda faltar é que a barra de rolagem aparece.

    Quem cede é sempre a mesma, e só ela, porque a largura que o Qt calcula é a
    exata do conteúdo: tirar um pixel de uma coluna de data já corta o "2010-
    01-05" no meio. Distribuir o aperto entre todas espalharia reticências pela
    tabela inteira para ganhar os vinte pixels que faltavam — e a coluna de
    nome, que é onde reticência não atrapalha (o nome inteiro está no
    formulário ao lado), é justamente a flexível.

    Função pura de propósito: é a regra que decide se a tabela vai parecer
    inteira ou quebrada, e testá-la não deveria exigir abrir uma janela."""
    if not conteudo:
        return []
    larguras = list(conteudo)
    if not (0 <= flexivel < len(larguras)):
        flexivel = 0

    folga = disponivel - sum(larguras)
    if folga >= 0:
        larguras[flexivel] += folga
        return larguras

    # Encolher só compensa se for o bastante para tudo caber. Numa tabela larga
    # demais (onze colunas de distribuição, por exemplo) a barra de rolagem vai
    # aparecer de qualquer jeito, e aí espremer o nome do sócio junto seria
    # perder de graça: fica a largura cheia, e quem precisa rola.
    piso = min(larguras[flexivel], LARGURA_MINIMA_COLUNA_FLEXIVEL)
    if -folga <= larguras[flexivel] - piso:
        larguras[flexivel] += folga
    return larguras


class TabelaLista(QTableWidget):
    """Tabela com cara de lista: sem os trilhos verticais da grade e com a
    largura toda ocupada.

    A grade quadriculada do Qt desenha linhas verticais que descem só até o
    último registro e param no ar, e o resto do espaço fica sendo um retângulo
    vazio ao lado de meia tabela — a tela parece cortada no meio. Sem os
    trilhos, cada registro vira uma linha de lista separada da seguinte, e
    onde a lista acaba é simplesmente onde ela acaba.

    A sobra horizontal também tem dono: em vez de deixar um vão morto à
    direita (ou uma barra de rolagem com a tela inteira vazia ao lado), o
    espaço que sobra vai para uma coluna escolhida — a do nome, quase sempre,
    que é a que se beneficia."""

    def __init__(self, linhas: int = 0, colunas: int = 0, parent=None, coluna_flexivel: int = 0,
                 mensagem_vazia: str = "Nada por aqui ainda."):
        super().__init__(linhas, colunas, parent)
        self.coluna_flexivel = coluna_flexivel
        self.mensagem_vazia = mensagem_vazia
        self._larguras_do_conteudo: list[int] = []

        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setCornerButtonEnabled(False)
        self.setWordWrap(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(ALTURA_LINHA_TABELA)
        self.horizontalHeader().setHighlightSections(False)

    def ajustar_colunas(self) -> None:
        """Ajusta as colunas ao conteúdo e entrega a sobra à coluna flexível.
        Chamar depois de preencher a tabela."""
        self.resizeColumnsToContents()
        # O Qt mede só o conteúdo das células; com a tabela vazia (ou com
        # valores curtos sob um título comprido) isso deixa o próprio cabeçalho
        # cortado, tipo "r da particip".
        cabecalho = self.horizontalHeader()
        self._larguras_do_conteudo = [
            max(self.columnWidth(i), cabecalho.sectionSizeHint(i)) for i in range(self.columnCount())
        ]
        self._distribuir_sobra()
        self._explicar_o_que_ficou_cortado()

    def _larguras_base(self) -> list[int]:
        """As larguras de partida. Antes do primeiro preenchimento não há
        conteúdo medido, e aí vale o cabeçalho — sem isso a tabela vazia abre
        com as colunas de 100px do Qt, que somam mais do que a tela e trazem
        barra de rolagem para não mostrar nada."""
        if len(self._larguras_do_conteudo) == self.columnCount():
            return list(self._larguras_do_conteudo)
        cabecalho = self.horizontalHeader()
        return [cabecalho.sectionSizeHint(i) for i in range(self.columnCount())]

    def showEvent(self, evento) -> None:
        super().showEvent(evento)
        self._distribuir_sobra()

    def _explicar_o_que_ficou_cortado(self) -> None:
        """Célula que não coube inteira ganha o texto completo como dica.

        A coluna flexível é a que encolhe quando falta espaço, então é nela que
        aparece reticência — e "ENDOGAST..." sem jeito de ver o resto seria
        trocar um incômodo por outro."""
        indice = self.coluna_flexivel
        if not (0 <= indice < self.columnCount()):
            return
        metrica = QFontMetrics(self.font())
        largura = self.columnWidth(indice) - 20  # desconta o padding do estilo
        for linha in range(self.rowCount()):
            item = self.item(linha, indice)
            if item is None:
                continue
            texto = item.text()
            item.setToolTip(texto if metrica.horizontalAdvance(texto) > largura else "")

    def paintEvent(self, evento) -> None:
        super().paintEvent(evento)
        if self.rowCount():
            return
        # Tabela vazia sem nada escrito parece tela que não carregou. Uma linha
        # no meio do espaço diz que o espaço está vazio de propósito.
        pintor = QPainter(self.viewport())
        pintor.setPen(QColor(theme.INK_MUTED()))
        pintor.drawText(self.viewport().rect(), Qt.AlignCenter, self.mensagem_vazia)
        pintor.end()

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        # Redistribui ao redimensionar a janela: sem isto, a coluna flexível
        # guardaria a largura de quando a tabela foi preenchida e o vão morto
        # voltaria assim que alguém arrastasse a borda da janela.
        self._distribuir_sobra()

    def _distribuir_sobra(self) -> None:
        """Aplica larguras_ajustadas às colunas de verdade."""
        if not self.columnCount():
            return
        larguras = larguras_ajustadas(
            self._larguras_base(), self.viewport().width(), self.coluna_flexivel
        )
        for indice, largura in enumerate(larguras):
            if self.columnWidth(indice) != largura:
                self.setColumnWidth(indice, largura)


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
    """Cartão de indicador: rótulo em cima, número em destaque, uma linha de
    contexto embaixo.

    A altura do rótulo é fixa em duas linhas de propósito. Ele varia de
    "Empresas no período" a "Distribuído desproporcionalmente", e com altura
    livre o número de cada cartão parava numa altura diferente do vizinho —
    uma fileira de números desalinhados é o que mais entrega uma tela montada
    às pressas. Fixando o rótulo, todos os números ficam na mesma linha.

    O contexto é de uma linha só, cortado com reticências e com o texto
    inteiro na dica. Antes era livre, e o cartão "Sem distribuição" — que
    lista as empresas — virava uma parede de nomes que esticava o cartão e
    empurrava a fileira toda."""

    LINHAS_DO_ROTULO = 2
    LARGURA_MINIMA = 150
    TAMANHO_DO_VALOR = 21
    TAMANHO_MINIMO_DO_VALOR = 13

    def __init__(self, titulo: str, parent=None, descricao: str = ""):
        super().__init__(parent)
        self.setProperty("role", "card")
        # Rótulo curto no cartão, frase inteira na dica: num cartão estreito,
        # "Distribuído desproporcionalmente" não cabe e sai cortado no meio da
        # palavra, que é pior do que a versão curta.
        self.setToolTip(descricao or titulo)
        # Largura idêntica entre os cartões da fileira: com o tamanho vindo do
        # conteúdo, o cartão de texto mais longo ficava o dobro do vizinho e a
        # fileira saía irregular. "Ignored" faz o layout dividir a linha em
        # partes iguais, e o mínimo evita que virem tiras num monitor estreito.
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.setMinimumWidth(self.LARGURA_MINIMA)

        self._rotulo_titulo = QLabel(titulo.upper())
        self._rotulo_titulo.setWordWrap(True)
        self._rotulo_titulo.setAlignment(Qt.AlignLeft | Qt.AlignTop)

        self._rotulo_valor = QLabel("—")
        self._rotulo_valor.setProperty("role", "titulo")
        self._rotulo_valor.setWordWrap(False)
        self._cor_do_valor: str | None = None

        self._rotulo_contexto = QLabel("")
        self._rotulo_contexto.setWordWrap(False)
        self._contexto_inteiro = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(6)
        layout.addWidget(self._rotulo_titulo)
        layout.addWidget(self._rotulo_valor)
        layout.addWidget(self._rotulo_contexto)
        layout.addStretch()

        self._aplicar_cores()
        theme.estado().mudou.connect(self._aplicar_cores)

    def _aplicar_cores(self) -> None:
        self._rotulo_titulo.setStyleSheet(
            f"color: {theme.INK_MUTED()}; font-size: 11px; font-weight: 600;"
            " letter-spacing: 0.6px;"
        )
        self._rotulo_contexto.setStyleSheet(f"color: {theme.INK_MUTED()}; font-size: 11px;")
        altura = QFontMetrics(self._rotulo_titulo.font()).height() * self.LINHAS_DO_ROTULO
        self._rotulo_titulo.setFixedHeight(altura)

    def definir(self, valor: str, contexto: str = "", cor: str | None = None) -> None:
        self._rotulo_valor.setText(valor)
        self._cor_do_valor = cor
        self._ajustar_valor()
        self._contexto_inteiro = contexto
        # Ocupa o lugar mesmo vazio: sem isso, um cartão sem contexto fica mais
        # baixo que os vizinhos e a fileira perde a linha de base.
        self._rotulo_contexto.setVisible(True)
        self._ajustar_contexto()

    def resizeEvent(self, evento) -> None:
        super().resizeEvent(evento)
        self._ajustar_valor()
        self._ajustar_contexto()

    def _ajustar_valor(self) -> None:
        """Encolhe o número até ele caber inteiro no cartão.

        "R$ 900.000,00" não cabe na largura de um sexto da tela e saía cortado
        em "R$ 900.000," — que não é só feio, é um número diferente. Diminuir
        o corpo é melhor do que cortar: o valor continua exato, só menor."""
        largura = max(0, self._rotulo_valor.width())
        texto = self._rotulo_valor.text()
        tamanho = self.TAMANHO_DO_VALOR
        if largura and texto:
            fonte = QFont(self._rotulo_valor.font())
            while tamanho > self.TAMANHO_MINIMO_DO_VALOR:
                fonte.setPixelSize(tamanho)
                if QFontMetrics(fonte).horizontalAdvance(texto) <= largura:
                    break
                tamanho -= 1
        cor = f"color: {self._cor_do_valor};" if self._cor_do_valor else ""
        self._rotulo_valor.setStyleSheet(f"{cor} font-size: {tamanho}px; font-weight: 600;")

    def _ajustar_contexto(self) -> None:
        largura = max(0, self._rotulo_contexto.width())
        if not self._contexto_inteiro:
            self._rotulo_contexto.setText(" ")
            self._rotulo_contexto.setToolTip("")
            return
        metrica = QFontMetrics(self._rotulo_contexto.font())
        self._rotulo_contexto.setText(
            metrica.elidedText(self._contexto_inteiro, Qt.ElideRight, largura) if largura
            else self._contexto_inteiro
        )
        self._rotulo_contexto.setToolTip(
            self._contexto_inteiro
            if metrica.horizontalAdvance(self._contexto_inteiro) > largura
            else ""
        )


class CrudTab(QWidget):
    colunas: list[tuple[str, str]] = []
    # Qual coluna recebe o espaço que sobra na largura da tabela. O padrão é a
    # primeira; quem tem um código curto na frente (o nº da empresa) aponta
    # para a coluna do nome, que é a que ganha em ficar larga.
    coluna_flexivel = 0
    mensagem_tabela_vazia = "Nada por aqui ainda."

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._registro_atual_id = None
        self._registros: list = []
        self._callback_selecao = None

        self.busca = QLineEdit()
        self.busca.setPlaceholderText(self.placeholder_busca())
        self.busca.textChanged.connect(lambda _texto: self.atualizar())

        self.tabela = TabelaLista(
            0, len(self.colunas),
            coluna_flexivel=self.coluna_flexivel,
            mensagem_vazia=self.mensagem_tabela_vazia,
        )
        self.tabela.setHorizontalHeaderLabels([c[0] for c in self.colunas])
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
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
        self.tabela.ajustar_colunas()

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
