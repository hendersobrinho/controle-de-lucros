"""Aba Empresas · Cadastro: a lista à esquerda e, à direita, a ficha da
empresa selecionada — o capital como está hoje, o valor da cota, o quadro
societário, as alterações contratuais e o lucro distribuído por ano.

Ver e editar ficam separados: a ficha só mostra, e cadastrar ou mudar os
dados abre uma janela própria (DialogoEmpresa). Antes, uma tabela com cinco
colunas e um formulário sempre aberto ao lado mostravam só os valores de
fundação, e não diziam nada sobre quem está na empresa hoje."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import repositories as repo
from ..mapa_vinculos import PAPEL_EMPRESA
from ..models import Empresa
from .cartao_participacao import FaixaParticipacao
from .common import (
    CampoValorCota,
    campo_cotas,
    cnpj_valido_ou_vazio,
    configurar_campo_cnpj,
    configurar_campo_moeda,
    formatar_data_br,
    formatar_percentual,
    formatar_valor_br,
    formatar_valor_cota,
)
from .diagrama_vinculos import DialogoMapaVinculos
from . import formulario as form_ui
from .lista_fichas import ListaFichas
from .theme import SAIU_FG

# Diferença a partir da qual a soma dos percentuais do quadro deixa de ser
# arredondamento e passa a ser sócio faltando ou sobrando.
_TOLERANCIA_SOMA = 0.01


def _rotulo(texto: str) -> QLabel:
    rotulo = QLabel(texto.upper())
    rotulo.setProperty("role", "rotuloCampo")
    return rotulo


def _dica(texto: str = "") -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setProperty("role", "subtitulo")
    rotulo.setWordWrap(True)
    return rotulo


def _secao(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setProperty("role", "secao")
    return rotulo


def _bloco() -> tuple[QFrame, QVBoxLayout]:
    bloco = QFrame()
    bloco.setProperty("role", "card")
    coluna = QVBoxLayout(bloco)
    coluna.setContentsMargins(18, 14, 18, 14)
    coluna.setSpacing(8)
    return bloco, coluna


def _formulario() -> QFormLayout:
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    form.setHorizontalSpacing(14)
    form.setVerticalSpacing(8)
    return form


def _limpar(layout) -> None:
    """Esvazia o layout já tirando os widgets da tela: o deleteLater só apaga
    depois, e até lá o bloco da empresa anterior aparecia por cima do novo."""
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout() is not None:
            _limpar(item.layout())


class DialogoEmpresa(QDialog):
    """Cadastrar uma empresa nova ou mudar os dados de uma existente.

    Capital social, cotas e valor da cota andam juntos — capital = cotas ×
    valor da cota: mudar as cotas ou o valor da cota refaz o capital, e
    mudar o capital refaz o valor da cota. É o que o contrato social diz, e
    poupa a conta de quem só tem dois dos três números."""

    EXCLUIDA = 2

    def __init__(self, conn, empresa: Empresa | None = None, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.empresa = empresa
        self.empresa_id: int | None = empresa.id if empresa else None
        self._sincronizando = False
        self._valor_cota_mexido = False
        self.setWindowTitle("Editar empresa" if empresa else "Nova empresa")
        self.setMinimumWidth(520)

        self.numero_chamada = QLineEdit(empresa.numero_chamada if empresa else "")
        self.numero_chamada.setProperty("role", "mono")
        self.numero_chamada.setPlaceholderText("ex.: 042")
        self.nome = QLineEdit(empresa.nome if empresa else "")
        self.nome.setPlaceholderText("Razão social")
        self.cnpj = QLineEdit()
        self.cnpj.setProperty("role", "mono")
        configurar_campo_cnpj(self.cnpj)
        self.cnpj.setText(empresa.cnpj or "" if empresa else "")

        self.cotas = campo_cotas()
        self.valor_cota = CampoValorCota()
        self.capital = configurar_campo_moeda(QDoubleSpinBox())
        if empresa is not None:
            self.cotas.setValue(empresa.quantidade_cotas or 0)
            self.capital.setValue(empresa.capital_social or 0)
            valor = empresa.valor_cota or (
                empresa.capital_social / empresa.quantidade_cotas
                if empresa.capital_social and empresa.quantidade_cotas else None
            )
            self.valor_cota.setValue(valor or 1.0)
        else:
            self.valor_cota.setValue(1.0)
        self.conta = form_ui.dica()
        self._mostrar_conta()
        self.cotas.valueChanged.connect(self._ao_mudar_cotas_ou_valor)
        self.valor_cota.valueChanged.connect(self._ao_mudar_valor_cota)
        self.capital.valueChanged.connect(self._ao_mudar_capital)

        bloco_id, col = form_ui.secao("Identificação", "1")
        col.addLayout(form_ui.linha(
            form_ui.campo("Nº da empresa", self.numero_chamada),
            form_ui.campo("Razão social", self.nome),
            esticar=(1, 4),
        ))
        col.addLayout(form_ui.linha(form_ui.campo("CNPJ", self.cnpj), form_ui.Caixa(), esticar=(2, 3)))

        bloco_capital, col = form_ui.secao(
            "Capital social", "2",
            info="Como está no contrato de constituição. Mudanças depois — aumento de capital, novas "
                 "cotas — entram como alteração contratual, e a ficha mostra o valor vigente.",
        )
        col.addWidget(form_ui.equacao(
            form_ui.campo("Quantidade de cotas", self.cotas),
            "×",
            form_ui.campo("Valor da cota", self.valor_cota),
            "=",
            form_ui.campo("Capital social", self.capital,
                          info="Preencha dois dos três números: o terceiro é calculado."),
        ))
        col.addWidget(self.conta)

        esquerda = []
        if empresa is not None:
            self.btn_excluir = QPushButton("Excluir empresa")
            self.btn_excluir.setProperty("role", "perigo")
            self.btn_excluir.clicked.connect(self._excluir)
            esquerda.append(self.btn_excluir)
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.clicked.connect(self.reject)
        self.btn_salvar = QPushButton("Salvar" if empresa else "Cadastrar empresa")
        self.btn_salvar.setProperty("role", "primario")
        self.btn_salvar.setDefault(True)
        self.btn_salvar.clicked.connect(self._salvar)

        form_ui.montar_janela(
            self,
            form_ui.cabecalho(empresa.nome if empresa else "Nova empresa",
                              "" if empresa else "O número, o nome e o capital do contrato social."),
            [bloco_id, bloco_capital],
            form_ui.botoes_rodape(*esquerda, direita=(btn_cancelar, self.btn_salvar)),
            largura=720,
        )
        self.numero_chamada.setFocus()

    # ---- capital = cotas × valor da cota
    def _mostrar_conta(self) -> None:
        cotas, valor = self.cotas.value(), self.valor_cota.value()
        if cotas and valor:
            self.conta.setText(
                f"{formatar_valor_br(cotas, 0)} cotas × {formatar_valor_cota(valor)} "
                f"= R$ {formatar_valor_br(cotas * valor)}"
            )
        else:
            self.conta.setText("Informe dois dos três números — o terceiro é calculado.")

    def _sincronizar(self, acao) -> None:
        if self._sincronizando:
            return
        self._sincronizando = True
        try:
            acao()
        finally:
            self._sincronizando = False
        self._mostrar_conta()

    def _ao_mudar_cotas_ou_valor(self, *_args) -> None:
        def refazer_capital():
            if self.cotas.value() and self.valor_cota.value():
                self.capital.setValue(round(self.cotas.value() * self.valor_cota.value(), 2))
        self._sincronizar(refazer_capital)

    def _ao_mudar_valor_cota(self, *_args) -> None:
        if not self._sincronizando:
            self._valor_cota_mexido = True
        self._ao_mudar_cotas_ou_valor()

    def _ao_mudar_capital(self, *_args) -> None:
        def refazer_valor_cota():
            if self.cotas.value() and self.capital.value():
                self.valor_cota.setValue(self.capital.value() / self.cotas.value())
        self._sincronizar(refazer_valor_cota)

    # ---- gravar
    def empresa_editada(self) -> Empresa:
        # O valor da cota só é gravado se entrou em alguma conta (há cotas)
        # ou se alguém o escolheu: o R$ 1,00 que o campo sugere numa empresa
        # sem cotas não é informação, é só o padrão do campo.
        guardar_valor = bool(self.cotas.value()) or self._valor_cota_mexido
        return Empresa(
            id=self.empresa_id,
            numero_chamada=self.numero_chamada.text().strip(),
            nome=self.nome.text().strip(),
            cnpj=cnpj_valido_ou_vazio(self.cnpj),
            capital_social=self.capital.value(),
            quantidade_cotas=self.cotas.value(),
            valor_cota=self.valor_cota.value() if guardar_valor else (self.empresa.valor_cota if self.empresa else None),
        )

    def _salvar(self) -> None:
        empresa = self.empresa_editada()
        if not empresa.numero_chamada:
            QMessageBox.warning(self, "Falta o número", "Informe o nº da empresa.")
            return
        if not empresa.nome:
            QMessageBox.warning(self, "Falta a razão social", "Informe a razão social da empresa.")
            return
        try:
            self.empresa_id = repo.salvar_empresa(self.conn, empresa)
        except ValueError as exc:
            QMessageBox.warning(self, "Não foi possível salvar", str(exc))
            return
        self.accept()

    def _excluir(self) -> None:
        """Excluir a empresa leva junto tudo o que é dela, de uma vez — por
        isso a pergunta diz exatamente o quê, e o botão já vem em "Não"."""
        resumo = repo.resumo_exclusao_empresa(self.conn, self.empresa.id)
        texto = f"Excluir a empresa {self.empresa.nome}?"
        if resumo:
            texto += "\n\nVão junto, sem volta:\n" + "\n".join(f"• {item}" for item in resumo)
        texto += (
            "\n\nOs sócios continuam cadastrados (podem estar em outras empresas). "
            "Faça um backup antes se tiver dúvida.\n\nConfirma a exclusão?"
        )
        resposta = QMessageBox.warning(
            self, "Excluir empresa", texto, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )
        if resposta != QMessageBox.Yes:
            return
        try:
            repo.excluir_empresa(self.conn, self.empresa.id)
        except ValueError as exc:
            QMessageBox.warning(self, "Não foi possível excluir", str(exc))
            return
        self.done(self.EXCLUIDA)


class _LinhaQuadro(QWidget):
    """Um sócio no quadro da ficha: nome e documento, a faixa da fatia dele,
    o percentual e o capital. Dois cliques abrem o sócio na aba Sócios."""

    def __init__(self, socio: dict, ao_abrir, parent=None):
        super().__init__(parent)
        self._ao_abrir = ao_abrir
        self._socio_id = socio["socio_id"]
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Dois cliques para abrir este sócio")

        nome = QLabel(socio["nome"])
        nome.setProperty("role", "valorCampo")
        nome.setWordWrap(True)
        documento = _dica(socio["documento"] or "sem documento cadastrado")
        identificacao = QVBoxLayout()
        identificacao.setSpacing(0)
        identificacao.addWidget(nome)
        identificacao.addWidget(documento)

        percentual = QLabel(formatar_percentual(socio["percentual"]))
        percentual.setProperty("role", "valorCampo")
        percentual.setMinimumWidth(78)
        percentual.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        if socio["capital"] is None:
            capital = _dica("capital não informado")
        else:
            capital = QLabel(f"R$ {formatar_valor_br(socio['capital'])}")
            capital.setProperty("role", "valorCampo")
            if socio["capital_calculado"]:
                capital.setToolTip("Cotas do sócio × valor da cota.")
        capital.setMinimumWidth(130)
        capital.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 4, 0, 4)
        linha.setSpacing(14)
        linha.addLayout(identificacao, 3)
        linha.addWidget(FaixaParticipacao(socio["percentual"], True), 2)
        linha.addWidget(percentual)
        linha.addWidget(capital)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._ao_abrir is not None:
            self._ao_abrir(self._socio_id)
        event.accept()


class EmpresasTab(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._empresas: list[Empresa] = []
        self._empresa_atual_id: int | None = None
        self._callback_selecao = None
        # A janela principal liga estes dois: ir pras alterações da empresa e
        # abrir um sócio do quadro na aba Sócios.
        self.ao_abrir_alteracoes = None
        self.ao_abrir_socio = None

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        painel_lista = self._montar_painel_lista()
        painel_ficha = self._montar_painel_ficha()
        splitter.addWidget(painel_lista)
        splitter.addWidget(painel_ficha)
        painel_lista.setMinimumWidth(280)
        painel_ficha.setMinimumWidth(560)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([360, 860])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self.atualizar()

    def definir_callback_selecao(self, callback) -> None:
        self._callback_selecao = callback

    # ------------------------------------------------------------- painéis --
    def _montar_painel_lista(self) -> QWidget:
        painel = QWidget()
        col = QVBoxLayout(painel)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(10)

        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Buscar por nome, nº ou CNPJ…")
        self.busca.setClearButtonEnabled(True)
        self.busca.textChanged.connect(lambda _texto: self.atualizar())
        self.btn_novo = QPushButton("Nova empresa")
        self.btn_novo.setProperty("role", "primario")
        self.btn_novo.clicked.connect(self._nova_empresa)
        cabecalho = QHBoxLayout()
        cabecalho.addWidget(self.busca, 1)
        cabecalho.addWidget(self.btn_novo)

        self.lista = ListaFichas("Nenhuma empresa cadastrada ainda.\nClique em Nova empresa para começar.")
        # itemSelectionChanged, e não currentItemChanged: no clique do mouse o
        # Qt avisa que o item atual mudou ANTES de selecioná-lo, e a ficha
        # perguntava pelo selecionado cedo demais — e ficava vazia.
        self.lista.itemSelectionChanged.connect(self._ao_selecionar)
        self.lista.itemDoubleClicked.connect(lambda _item: self._editar_empresa())

        self.contagem = QLabel()
        self.contagem.setProperty("role", "subtitulo")

        col.addLayout(cabecalho)
        col.addWidget(self.lista, 1)
        col.addWidget(self.contagem)
        return painel

    def _montar_painel_ficha(self) -> QWidget:
        painel = QWidget()
        col = QVBoxLayout(painel)
        col.setContentsMargins(20, 6, 6, 0)
        col.setSpacing(6)

        # ---- cabeçalho: quem é a empresa e o que dá pra fazer
        self.titulo_empresa = QLabel()
        self.titulo_empresa.setProperty("role", "titulo")
        self.titulo_empresa.setWordWrap(True)
        self.identificacao_empresa = QLabel()
        self.identificacao_empresa.setProperty("role", "subtitulo")
        self.identificacao_empresa.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.btn_editar = QPushButton("Editar dados")
        self.btn_editar.setToolTip("Nº, razão social, CNPJ, capital, cotas e valor da cota. Também dá pra excluir por lá.")
        self.btn_editar.clicked.connect(self._editar_empresa)
        # O outro lado do mapa da aba Sócios: lá o sócio está no meio e as
        # empresas em volta; aqui a empresa está no meio e os sócios em volta.
        self.btn_quadro = QPushButton("Quadro societário")
        self.btn_quadro.setToolTip(
            "Abre um diagrama com os sócios ligados a esta empresa e a participação de cada "
            "um — dá pra exportar em PDF ou SVG para anexar a processo ou apresentação."
        )
        self.btn_quadro.clicked.connect(self._abrir_quadro_societario)
        self.btn_alteracoes = QPushButton("Alterações contratuais")
        self.btn_alteracoes.setToolTip("Abre as alterações contratuais desta empresa.")
        self.btn_alteracoes.clicked.connect(self._abrir_alteracoes)

        identificacao = QVBoxLayout()
        identificacao.setSpacing(2)
        identificacao.addWidget(self.titulo_empresa)
        identificacao.addWidget(self.identificacao_empresa)
        # Mesmo arranjo da aba Sócios: ações numa linha própria, abaixo do nome.
        acoes = QHBoxLayout()
        acoes.setSpacing(8)
        acoes.addWidget(self.btn_editar)
        acoes.addWidget(self.btn_quadro)
        acoes.addWidget(self.btn_alteracoes)
        acoes.addStretch()
        cabecalho = QVBoxLayout()
        cabecalho.setSpacing(8)
        cabecalho.addLayout(identificacao)
        cabecalho.addLayout(acoes)

        # ---- corpo rolável: números, quadro, alterações, distribuição
        self._corpo = QWidget()
        self._layout_corpo = QVBoxLayout(self._corpo)
        self._layout_corpo.setContentsMargins(0, 8, 8, 12)
        self._layout_corpo.setSpacing(14)
        self.rolagem = QScrollArea()
        self.rolagem.setProperty("role", "listaCartoes")
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setFrameShape(QFrame.NoFrame)
        self.rolagem.setWidget(self._corpo)

        self.cabecalho_empresa = QWidget()
        coluna_cabecalho = QVBoxLayout(self.cabecalho_empresa)
        coluna_cabecalho.setContentsMargins(0, 0, 0, 0)
        coluna_cabecalho.addLayout(cabecalho)

        # ---- nenhuma empresa selecionada
        self.vazio_titulo = QLabel("Nenhuma empresa selecionada")
        self.vazio_titulo.setProperty("role", "vazioTitulo")
        self.vazio_titulo.setAlignment(Qt.AlignCenter)
        self.vazio_texto = QLabel(
            "Escolha uma empresa na lista para ver o capital, o quadro societário, as alterações "
            "e o lucro distribuído — ou clique em Nova empresa para cadastrar outra."
        )
        self.vazio_texto.setProperty("role", "vazioTexto")
        self.vazio_texto.setAlignment(Qt.AlignCenter)
        self.vazio_texto.setWordWrap(True)
        self.painel_vazio = QWidget()
        coluna_vazio = QVBoxLayout(self.painel_vazio)
        coluna_vazio.setSpacing(8)
        coluna_vazio.addStretch(2)
        coluna_vazio.addWidget(self.vazio_titulo)
        coluna_vazio.addWidget(self.vazio_texto)
        coluna_vazio.addStretch(3)

        col.addWidget(self.cabecalho_empresa)
        col.addWidget(self.rolagem, 1)
        col.addWidget(self.painel_vazio, 1)
        return painel

    # ------------------------------------------------------------- lista --
    def atualizar(self) -> None:
        todas = repo.listar_empresas(self.conn)
        termo = self.busca.text().strip().lower()
        digitos = "".join(c for c in termo if c.isalnum())
        empresas = [
            e for e in todas
            if not termo
            or termo in e.nome.lower()
            or termo == (e.numero_chamada or "").strip().lower()
            or (digitos and len(digitos) >= 3 and digitos in repo.normalizar_documento(e.cnpj).lower())
        ]
        self._empresas = empresas
        socios = repo.quantidade_socios_ativos_por_empresa(self.conn)

        self.lista.blockSignals(True)
        self.lista.clear()
        for e in empresas:
            quantidade = socios.get(e.id, 0)
            detalhe = f"nº {e.numero_chamada}" if e.numero_chamada else "sem nº"
            detalhe += f" · CNPJ {e.cnpj}" if e.cnpj else " · sem CNPJ"
            self.lista.adicionar(
                e.id,
                e.nome,
                detalhe,
                "sem sócios" if quantidade == 0 else f"{quantidade} sócio" + ("" if quantidade == 1 else "s"),
                apagado=quantidade == 0,
            )
        self.lista.blockSignals(False)
        if not self.lista.selecionar_id(self._empresa_atual_id):
            self._empresa_atual_id = None

        if termo:
            self.contagem.setText(f"{len(empresas)} de {len(todas)} empresas")
        else:
            self.contagem.setText(f"{len(todas)} empresa" + ("" if len(todas) == 1 else "s"))
        self._atualizar_ficha()

    def _ao_selecionar(self) -> None:
        self._empresa_atual_id = self.lista.id_selecionado()
        self._atualizar_ficha()
        empresa = next((e for e in self._empresas if e.id == self._empresa_atual_id), None)
        if empresa is not None and self._callback_selecao is not None:
            self._callback_selecao(empresa)

    def selecionar_empresa(self, empresa_id: int) -> None:
        if not self.lista.selecionar_id(empresa_id):
            self.busca.clear()
            self.lista.selecionar_id(empresa_id)

    # ------------------------------------------------------------- ficha --
    def _atualizar_ficha(self) -> None:
        _limpar(self._layout_corpo)
        ficha = repo.ficha_empresa(self.conn, self._empresa_atual_id) if self._empresa_atual_id else None
        tem = ficha is not None
        for botao in (self.btn_editar, self.btn_quadro, self.btn_alteracoes):
            botao.setEnabled(tem)
        self.cabecalho_empresa.setVisible(tem)
        self.rolagem.setVisible(tem)
        self.painel_vazio.setVisible(not tem)
        if not tem:
            return

        empresa = ficha["empresa"]
        self.titulo_empresa.setText(empresa.nome)
        partes = [f"nº {empresa.numero_chamada}" if empresa.numero_chamada else "sem nº"]
        partes.append(f"CNPJ {empresa.cnpj}" if empresa.cnpj else "sem CNPJ cadastrado")
        self.identificacao_empresa.setText(" · ".join(partes))

        self._layout_corpo.addWidget(self._bloco_numeros(ficha))
        self._layout_corpo.addWidget(self._bloco_quadro(ficha))
        linha = QHBoxLayout()
        linha.setSpacing(14)
        linha.addWidget(self._bloco_alteracoes(ficha), 1, Qt.AlignTop)
        linha.addWidget(self._bloco_distribuicao(ficha), 1, Qt.AlignTop)
        self._layout_corpo.addLayout(linha)
        self._layout_corpo.addStretch()

    def _bloco_numeros(self, ficha: dict) -> QFrame:
        bloco, coluna = _bloco()
        grade = QGridLayout()
        grade.setHorizontalSpacing(28)
        grade.setVerticalSpacing(2)

        valor_cota = ficha["valor_cota"]
        if valor_cota is None:
            texto_cota, nota_cota = "Não informado", "informe em Editar dados"
        else:
            texto_cota = formatar_valor_cota(valor_cota)
            nota_cota = "informado" if ficha["valor_cota_informado"] else "capital ÷ cotas"
        numeros = (
            ("Capital social", f"R$ {formatar_valor_br(ficha['capital_social'])}" if ficha["capital_social"] else "Não informado", ""),
            ("Cotas", formatar_valor_br(ficha["quantidade_cotas"], 0) if ficha["quantidade_cotas"] else "Não informado", ""),
            ("Valor da cota", texto_cota, nota_cota),
            ("Sócios hoje", str(len(ficha["quadro"])), ""),
        )
        for coluna_grade, (rotulo, valor, nota) in enumerate(numeros):
            grade.addWidget(_rotulo(rotulo), 0, coluna_grade)
            numero = QLabel(valor)
            numero.setProperty("role", "numeroFicha" if valor != "Não informado" else "subtitulo")
            grade.addWidget(numero, 1, coluna_grade)
            if nota:
                grade.addWidget(_dica(nota), 2, coluna_grade)
            grade.setColumnStretch(coluna_grade, 1)
        coluna.addLayout(grade)

        ultima = ficha["ultima_alteracao"]
        if ficha["fundacao_diferente"] and ultima is not None:
            empresa = ficha["empresa"]
            coluna.addWidget(_dica(
                f"Valores vigentes pela alteração Nº {ultima.numero}, de {formatar_data_br(ultima.data)}. "
                f"Na fundação: R$ {formatar_valor_br(empresa.capital_social)} em "
                f"{formatar_valor_br(empresa.quantidade_cotas, 0)} cotas."
            ))
        return bloco

    def _bloco_quadro(self, ficha: dict) -> QFrame:
        bloco, coluna = _bloco()
        coluna.addWidget(_secao("Quadro societário"))
        if not ficha["quadro"]:
            coluna.addWidget(_dica(
                "Ninguém na sociedade hoje. Associe sócios pela aba Sócios, ou importe o quadro em "
                "Importação."
            ))
        for socio in ficha["quadro"]:
            coluna.addWidget(_LinhaQuadro(socio, self.ao_abrir_socio))

        if ficha["quadro"]:
            soma = ficha["soma_percentual"]
            rodape = QLabel(f"Soma das participações: {formatar_percentual(soma)}")
            rodape.setProperty("role", "subtitulo")
            if abs(soma - 100) > _TOLERANCIA_SOMA:
                rodape.setText(
                    f"⚠ As participações somam {formatar_percentual(soma)}, não 100% — falta ou sobra "
                    "sócio no quadro, ou algum percentual está desatualizado."
                )
                rodape.setStyleSheet(f"color: {SAIU_FG()};")
                rodape.setWordWrap(True)
            coluna.addWidget(rodape)
        if ficha["saidas"]:
            nomes = "; ".join(f"{s['nome']} (em {formatar_data_br(s['data_saida'])})" for s in ficha["saidas"][:5])
            extra = f" e mais {len(ficha['saidas']) - 5}" if len(ficha["saidas"]) > 5 else ""
            coluna.addWidget(_dica(f"Saíram: {nomes}{extra}."))
        return bloco

    def _bloco_alteracoes(self, ficha: dict) -> QFrame:
        bloco, coluna = _bloco()
        coluna.addWidget(_secao("Alterações contratuais"))
        total = ficha["total_alteracoes"]
        ultima = ficha["ultima_alteracao"]
        if total == 0:
            coluna.addWidget(_dica("Nenhuma alteração cadastrada."))
        else:
            coluna.addWidget(QLabel(f"{total} alteraç{'ão' if total == 1 else 'ões'} cadastrada{'' if total == 1 else 's'}"))
            descricao = f" — {ultima.descricao}" if ultima.descricao else ""
            trancada = " (trancada)" if ultima.fechada else ""
            coluna.addWidget(_dica(f"Mais recente: Nº {ultima.numero}, de {formatar_data_br(ultima.data)}{trancada}{descricao}"))
        return bloco

    def _bloco_distribuicao(self, ficha: dict) -> QFrame:
        bloco, coluna = _bloco()
        coluna.addWidget(_secao("Lucro distribuído"))
        if not ficha["distribuicoes"]:
            coluna.addWidget(_dica("Nenhuma distribuição lançada."))
        grade = QGridLayout()
        grade.setHorizontalSpacing(16)
        grade.setVerticalSpacing(4)
        for linha, d in enumerate(ficha["distribuicoes"]):
            ano = QLabel(str(d["ano"]))
            ano.setProperty("role", "valorCampo")
            total = QLabel(f"R$ {formatar_valor_br(d['total'])}")
            total.setProperty("role", "valorCampo")
            total.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            situacao = _dica("período fechado" if d["fechado"] else f"{d['socios']} sócio" + ("" if d["socios"] == 1 else "s"))
            grade.addWidget(ano, linha, 0)
            grade.addWidget(total, linha, 1)
            grade.addWidget(situacao, linha, 2)
        grade.setColumnStretch(1, 1)
        coluna.addLayout(grade)
        return bloco

    # ------------------------------------------------------------- ações --
    def _nova_empresa(self) -> None:
        dialogo = DialogoEmpresa(self.conn, parent=self)
        if dialogo.exec() != QDialog.Accepted:
            return
        self._empresa_atual_id = dialogo.empresa_id
        self.busca.clear()
        self.atualizar()
        self.selecionar_empresa(dialogo.empresa_id)

    def _editar_empresa(self) -> None:
        empresa = repo.buscar_empresa(self.conn, self._empresa_atual_id) if self._empresa_atual_id else None
        if empresa is None:
            return
        dialogo = DialogoEmpresa(self.conn, empresa, self)
        resultado = dialogo.exec()
        if resultado == DialogoEmpresa.EXCLUIDA:
            self._empresa_atual_id = None
        if resultado != QDialog.Rejected:
            self.atualizar()

    def _abrir_alteracoes(self) -> None:
        if self._empresa_atual_id is not None and self.ao_abrir_alteracoes is not None:
            self.ao_abrir_alteracoes(self._empresa_atual_id)

    def _abrir_quadro_societario(self) -> None:
        """O quadro societário desenhado: quem está na empresa, com quanto, e
        quem já saiu. A ficha responde "quem"; o desenho mostra o peso de cada
        um de relance, que é o que se leva pra reunião."""
        empresa = next((e for e in self._empresas if e.id == self._empresa_atual_id), None)
        if empresa is None:
            return
        socios = {s.id: s for s in repo.listar_socios(self.conn)}
        vinculos = [
            {
                "socio_nome": socios[v.socio_id].nome if v.socio_id in socios else "?",
                # O percentual registrado no vínculo, igual ao que a aba
                # Sócios usa no mapa do outro lado — não o recalculado por
                # cotas, que muda com o capital e faria os dois desenhos
                # discordarem sobre a mesma participação.
                "percentual": v.percentual_capital,
                "data_entrada": v.data_entrada,
                "data_saida": v.data_saida,
                "capital": v.valor_capital,
            }
            for v in repo.listar_vinculos_empresa(self.conn, empresa.id)
        ]
        DialogoMapaVinculos(
            empresa.nome, empresa.cnpj or "", vinculos, self, papel=PAPEL_EMPRESA
        ).exec()
