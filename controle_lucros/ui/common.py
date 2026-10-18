"""Peças de tela usadas pelo programa inteiro: a tabela com cara de lista,
os campos de número com unidade à vista (percentual, cotas, reais, valor da
cota), os formatadores (percentual, data, dinheiro) e o cartão de número dos
dashboards — pra que o mesmo dado apareça do mesmo jeito em toda tela."""
from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtCore import QEvent, QLocale, QObject, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from . import theme


@contextmanager
def pintura_segura(dispositivo):
    """QPainter que termina sempre, mesmo se o desenho levantar exceção.

    Erro dentro de um paintEvent não é só um erro: o PySide imprime o
    traceback e devolve o controle ao Qt com o QPainter ainda ATIVO. O Qt
    então bate em "QBackingStore::endPaint() called with active painter" e o
    processo morre por falha de segmentação — pra quem está usando, o
    programa simplesmente fecha sozinho, sem mensagem nenhuma.

    Terminar o pintor num finally é o que transforma um desenho que falhou
    numa tela feia, em vez de num programa fechado. Vale para todo paintEvent
    daqui: o desenho é a única parte do sistema em que uma exceção derruba
    tudo em vez de aparecer numa caixa de aviso."""
    pintor = QPainter(dispositivo)
    try:
        yield pintor
    finally:
        if pintor.isActive():
            pintor.end()

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
        with pintura_segura(self.viewport()) as pintor:
            pintor.setPen(QColor(theme.INK_MUTED()))
            pintor.drawText(self.viewport().rect(), Qt.AlignCenter, self.mensagem_vazia)

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
    # O seletor de empresa (código + nome) recebe as empresas inteiras.
    if hasattr(combo, "definir_empresas"):
        combo.definir_empresas(itens)
        return
    combo.clear()
    for item in itens:
        combo.addItem(getattr(item, texto_attr), item.id)


def selecionar_combo_por_id(combo: QComboBox, id_) -> None:
    idx = combo.findData(id_)
    combo.setCurrentIndex(idx if idx >= 0 else 0)


def formatar_numero(spin: QDoubleSpinBox) -> None:
    """Aplica separador de milhar (ponto) e decimal (vírgula) — ex.: 1.234.567,89
    — pra números grandes (capital, cotas, valores) ficarem legíveis.

    E formata ENQUANTO se digita: "1500000" vira "1.500.000" na hora, sem
    ninguém precisar contar zeros. Ao entrar no campo o número já vem
    selecionado, pra digitar por cima em vez de emendar no "0,00"."""
    spin.setLocale(LOCALE_BR)
    spin.setGroupSeparatorShown(True)
    spin.setButtonSymbols(QAbstractSpinBox.NoButtons)
    if getattr(spin, "_formatador_ao_digitar", None) is None:
        spin._formatador_ao_digitar = _FormatadorAoDigitar(spin)


def formatar_digitacao(texto: str, casas: int) -> tuple[str, int]:
    """O número digitado reescrito no padrão brasileiro: pontos de milhar
    refeitos, uma vírgula só, no máximo `casas` decimais. Pontos digitados
    são ignorados (o separador de milhar é a tela que põe). Devolve o texto e
    quantos "caracteres que contam" (dígitos e vírgula) ele tem."""
    digitos_e_virgula = "".join(c for c in texto if c.isdigit() or c == ",")
    if casas == 0:
        digitos_e_virgula = digitos_e_virgula.replace(",", "")
    inteiro, tem_virgula, decimais = digitos_e_virgula.partition(",")
    decimais = decimais.replace(",", "")[:casas]
    inteiro = inteiro.lstrip("0") or ("0" if inteiro or tem_virgula else "")
    grupos = []
    while len(inteiro) > 3:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    if inteiro:
        grupos.insert(0, inteiro)
    resultado = ".".join(grupos) + ("," + decimais if tem_virgula else "")
    return resultado, sum(1 for c in resultado if c.isdigit() or c == ",")


class _FormatadorAoDigitar(QObject):
    def __init__(self, spin: QDoubleSpinBox):
        super().__init__(spin)
        self._spin = spin
        self._ocupado = False
        editor = spin.lineEdit()
        editor.textEdited.connect(self._reformatar)
        editor.installEventFilter(self)

    def eventFilter(self, objeto, evento) -> bool:  # noqa: N802 (Qt override)
        if evento.type() == QEvent.FocusIn:
            QTimer.singleShot(0, self._spin.selectAll)
        return False

    def _reformatar(self, texto: str) -> None:
        if self._ocupado:
            return
        spin, editor = self._spin, self._spin.lineEdit()
        prefixo, sufixo = spin.prefix(), spin.suffix()
        miolo = texto
        cursor = editor.cursorPosition()
        if prefixo and miolo.startswith(prefixo):
            miolo = miolo[len(prefixo):]
            cursor -= len(prefixo)
        if sufixo and miolo.endswith(sufixo):
            miolo = miolo[: -len(sufixo)]
        cursor = max(0, min(cursor, len(miolo)))
        # Quantos dígitos/vírgula havia antes do cursor: é por eles que o
        # cursor volta ao lugar certo depois que os pontos mudam de posição.
        antes = sum(1 for c in miolo[:cursor] if c.isdigit() or c == ",")
        novo, _ = formatar_digitacao(miolo, spin.decimals())
        if novo == miolo:
            return
        posicao, contados = 0, 0
        while posicao < len(novo) and contados < antes:
            if novo[posicao].isdigit() or novo[posicao] == ",":
                contados += 1
            posicao += 1
        self._ocupado = True
        try:
            editor.setText(prefixo + novo + sufixo)
            editor.setCursorPosition(len(prefixo) + posicao)
        finally:
            self._ocupado = False


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


CASAS_PERCENTUAL = 4


def formatar_percentual(valor: float | None) -> str:
    """46.94 -> '46,9400%'; 33.3333 -> '33,3333%'; 100 -> '100,0000%'.

    O mesmo formato em todas as telas, sempre com o símbolo e sempre com
    quatro casas: sem o símbolo, um número numa tabela ao lado de cotas e
    reais não diz o que é; e com as casas fixas, um sócio com 50% e outro com
    33,3333% ficam alinhados e comparáveis de relance. Quatro casas cobrem a
    sociedade dividida em três (33,3333%) sem a soma deixar de fechar 100%."""
    return f"{formatar_valor_br(round(float(valor or 0.0), CASAS_PERCENTUAL), CASAS_PERCENTUAL)}%"


def formatar_valor_cota(valor: float) -> str:
    """1 -> 'R$ 1,00'; 0.01 -> 'R$ 0,01'; 0.001 -> 'R$ 0,001'. Duas casas como
    todo valor em reais, e mais só quando a cota vale menos de um centavo."""
    numero = round(float(valor or 0.0), 6)
    casas = 2
    while casas < 6 and round(numero, casas) != numero:
        casas += 1
    return f"R$ {formatar_valor_br(numero, casas)}"


def formatar_data_br(iso: str | None, vazio: str = "—") -> str:
    """'2007-03-23' -> '23/03/2007'. As datas moram no banco em ISO, mas na
    tela são lidas por gente: data em ISO numa tabela parece código."""
    if not iso:
        return vazio
    try:
        ano, mes, dia = str(iso)[:10].split("-")
        return f"{dia}/{mes}/{ano}"
    except ValueError:
        return str(iso)


class CampoNumeroEnxuto(QDoubleSpinBox):
    """QDoubleSpinBox que mostra só as casas decimais que o número tem.

    O padrão do Qt escreve sempre todas as casas configuradas: um percentual
    que aceita quatro casas aparece como "46,9400 %", e cotas que aceitam
    duas como "469,00" — zeros que não dizem nada e destoam do resto da tela,
    onde o mesmo número aparece "46,94%" e "469". As casas aceitas na
    digitação continuam as mesmas; muda só como o valor é escrito."""

    def __init__(self, casas_minimas: int = 0, casas_maximas: int = 2, parent=None):
        super().__init__(parent)
        self._casas_minimas = casas_minimas
        self.setDecimals(casas_maximas)
        formatar_numero(self)

    def textFromValue(self, valor: float) -> str:  # noqa: N802 (Qt override)
        casas = self._casas_minimas
        while casas < self.decimals() and round(valor, casas) != round(valor, self.decimals()):
            casas += 1
        return self.locale().toString(float(valor), "f", casas)


def campo_percentual() -> CampoNumeroEnxuto:
    """Campo de percentual com a unidade à vista (" %"): até quatro casas — o
    mesmo limite que o banco guarda e que formatar_percentual mostra — e
    escrito do mesmo jeito que ela ("46,94 %", "33,3333 %")."""
    campo = CampoNumeroEnxuto(casas_minimas=CASAS_PERCENTUAL, casas_maximas=CASAS_PERCENTUAL)
    campo.setMaximum(100)
    campo.setSuffix(" %")
    return campo


def campo_cotas() -> CampoNumeroEnxuto:
    """Quantidade de cotas: inteira na quase totalidade dos contratos, então
    sem ",00" — mas aceita fração quando o contrato tem."""
    campo = CampoNumeroEnxuto(casas_minimas=0, casas_maximas=2)
    campo.setMaximum(1_000_000_000)
    return campo


class CampoValorCota(QWidget):
    """Valor nominal de uma cota, com atalhos de um clique pros dois valores
    que aparecem em quase todo contrato (R$ 1,00 e R$ 0,01) — e o campo
    livre pro resto. Aceita até seis casas: há cota de R$ 0,001."""

    ATALHOS = (1.0, 0.01)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.campo = CampoNumeroEnxuto(casas_minimas=2, casas_maximas=6)
        self.campo.setMaximum(1_000_000)
        self.campo.setPrefix("R$ ")
        self.valueChanged = self.campo.valueChanged
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.campo, 1)
        self.atalhos: list[QPushButton] = []
        for valor in self.ATALHOS:
            botao = QPushButton(f"R$ {formatar_valor_br(valor)}")
            botao.setProperty("role", "atalho")
            botao.setCursor(Qt.PointingHandCursor)
            botao.setToolTip(f"Cota de R$ {formatar_valor_br(valor)}")
            botao.clicked.connect(lambda _marcado=False, v=valor: self.campo.setValue(v))
            layout.addWidget(botao)
            self.atalhos.append(botao)

    def value(self) -> float:
        return self.campo.value()

    def setValue(self, valor: float) -> None:  # noqa: N802 — mesma interface do QDoubleSpinBox
        self.campo.setValue(valor)


def configurar_campo_moeda(campo: QDoubleSpinBox, maximo: float = 1_000_000_000_000) -> QDoubleSpinBox:
    """Campo de valor em reais, com "R$" à vista."""
    campo.setMaximum(maximo)
    campo.setDecimals(2)
    campo.setPrefix("R$ ")
    formatar_numero(campo)
    return campo


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
