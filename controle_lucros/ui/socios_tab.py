"""Aba de Sócios: cadastro básico (nome/cpf) + o painel de vínculos
societários do sócio selecionado — associar a empresas e editar o vínculo
(participação, capital, datas, alterações contratuais).

Associar gera a alteração contratual automática quando a entrada é do ano
corrente; entrada mais antiga fica sem ela, pra ser associada depois na
edição do vínculo. Editar corrige o registro como está, sem alteração nova."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import repositories as repo
from ..models import TIPOS_PESSOA_LABEL, Socio, VinculoSocietario
from .common import (
    aplicar_modo_formulario,
    configurar_campo_cnpj,
    configurar_campo_cpf,
    criar_aviso_formulario,
    documento_valido_ou_vazio,
    formatar_numero,
    formatar_valor_br,
    MODO_CANCELADO,
    MODO_EDICAO,
    MODO_NOVO,
    MODO_SALVO,
    MODO_VAZIO,
    TabelaLista,
)
from .diagrama_vinculos import DialogoMapaVinculos
from .informe_rendimentos_view import InformeRendimentosDialog
from .theme import SAIU_BG, SAIU_FG, SEAL_GREEN
from .theme import estado as tema_estado


def _hairline() -> QFrame:
    linha = QFrame()
    linha.setProperty("role", "hairline")
    return linha


def _campo_data(valor_iso: str | None = None) -> QDateEdit:
    campo = QDateEdit(calendarPopup=True)
    campo.setDisplayFormat("dd/MM/yyyy")
    campo.setDate(dt.date.fromisoformat(valor_iso) if valor_iso else dt.date.today())
    return campo


def _campo_numero(maximo: float, casas: int, valor: float | None = None) -> QDoubleSpinBox:
    campo = QDoubleSpinBox()
    campo.setMaximum(maximo)
    campo.setDecimals(casas)
    formatar_numero(campo)
    if valor:
        campo.setValue(valor)
    return campo


def _valor_ou_nada(campo: QDoubleSpinBox) -> float | None:
    """Capital em branco (zero) é "não informado", não "zero reais": é o que
    deixa a tela mostrar a estimativa pelas cotas no lugar."""
    return campo.value() or None


def _estimativa_por_cotas(conn, empresa_id: int | None, cotas: float) -> str:
    """O capital proporcional às cotas, pelo capital e cotas vigentes da
    empresa — o que se mostra enquanto ninguém informou o capital do sócio."""
    if empresa_id is None:
        return ""
    estado = repo.estado_atual_empresa(conn, empresa_id)
    total_cotas = estado["quantidade_cotas"]
    if not total_cotas:
        return "Sem capital e cotas da empresa cadastrados, não há como estimar pelas cotas."
    return f"Estimativa pelas cotas: R$ {formatar_valor_br(cotas * estado['capital_social'] / total_cotas)}"


def _aviso_alteracao(data_iso: str) -> str:
    """O que acontece com a alteração contratual de um movimento nessa data
    (ver repo.alteracao_automatica_cabe)."""
    if repo.alteracao_automatica_cabe(data_iso):
        return ""
    return (
        f"Entrada anterior a {repo._ano_corrente()}: não é criada alteração contratual "
        "automática. Se houver uma, associe depois em \"Editar vínculo\"."
    )


class _DialogoAssociarEmpresa(QDialog):
    def __init__(self, conn, socio_id: int, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Associar sócio a uma empresa")
        self.setMinimumWidth(400)

        vinculadas_ativas = {
            v.empresa_id
            for v in repo.listar_vinculos_socio(conn, socio_id)
            if v.data_saida is None
        }

        self.empresa = QComboBox()
        for e in repo.listar_empresas(conn):
            if e.id not in vinculadas_ativas:
                self.empresa.addItem(f"{e.nome} (nº {e.numero_chamada})", e.id)
        self.empresa.currentIndexChanged.connect(self._recalcular_estimativa)

        self.percentual = _campo_numero(100, 4)
        self.cotas = _campo_numero(1_000_000_000, 2)
        self.cotas.valueChanged.connect(self._recalcular_estimativa)
        self.capital = _campo_numero(1_000_000_000_000, 2)

        self.estimativa = QLabel()
        self.estimativa.setProperty("role", "subtitulo")
        self.estimativa.setWordWrap(True)

        self.data_entrada = _campo_data()
        self.data_entrada.dateChanged.connect(self._atualizar_aviso_alteracao)

        self.descricao = QLineEdit("Inclusão de sócio (registrado pela aba de Sócios)")
        self.descricao.setCursorPosition(0)  # senão o começo do texto fica escondido
        self.aviso_alteracao = QLabel()
        self.aviso_alteracao.setProperty("role", "subtitulo")
        self.aviso_alteracao.setWordWrap(True)

        form = QFormLayout()
        form.addRow("Empresa", self.empresa)
        form.addRow("% do capital", self.percentual)
        form.addRow("Qtde de cotas", self.cotas)
        form.addRow("Capital do sócio (R$)", self.capital)
        form.addRow("", self.estimativa)
        form.addRow("Data de entrada", self.data_entrada)
        form.addRow("Alteração contratual (descrição)", self.descricao)
        form.addRow("", self.aviso_alteracao)

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(botoes)

        self._recalcular_estimativa()
        self._atualizar_aviso_alteracao()

    def _recalcular_estimativa(self, *_args) -> None:
        self.estimativa.setText(_estimativa_por_cotas(self.conn, self.empresa.currentData(), self.cotas.value()))

    def _atualizar_aviso_alteracao(self, *_args) -> None:
        aviso = _aviso_alteracao(self.data_entrada.date().toString("yyyy-MM-dd"))
        self.aviso_alteracao.setText(aviso)
        self.aviso_alteracao.setVisible(bool(aviso))
        self.descricao.setEnabled(not aviso)

    def dados(self) -> tuple[int | None, float, float, str, str, float | None]:
        return (
            self.empresa.currentData(),
            self.percentual.value(),
            self.cotas.value(),
            self.data_entrada.date().toString("yyyy-MM-dd"),
            self.descricao.text().strip(),
            _valor_ou_nada(self.capital),
        )


class _DialogoEditarVinculo(QDialog):
    """Todos os dados do vínculo numa tela só: participação, capital, datas,
    alterações contratuais e observação — e o botão de excluir.

    Substitui as quatro ações separadas que existiam (editar datas,
    atualizar cotas, encerrar, excluir), que obrigavam a saber de antemão
    qual delas fazia o quê. Aqui tudo é correção do próprio registro: não
    abre vínculo novo nem cria alteração contratual. A alteração de entrada
    e de saída é escolhida entre as que a empresa já tem — é como se
    associa depois a alteração que a importação não criou."""

    EXCLUIDO = 2

    def __init__(self, conn, vinculo: VinculoSocietario, empresa_nome: str, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.vinculo = vinculo
        self.setWindowTitle(f"Editar vínculo — {empresa_nome}")
        self.setMinimumWidth(460)

        self.percentual = _campo_numero(100, 4, vinculo.percentual_capital)
        self.cotas = _campo_numero(1_000_000_000, 2, vinculo.quantidade_cotas)
        self.cotas.valueChanged.connect(self._recalcular_estimativa)
        self.capital = _campo_numero(1_000_000_000_000, 2, vinculo.valor_capital)
        self.estimativa = QLabel()
        self.estimativa.setProperty("role", "subtitulo")
        self.estimativa.setWordWrap(True)

        self.data_entrada = _campo_data(vinculo.data_entrada)
        self.saiu = QCheckBox("Saiu da sociedade")
        self.saiu.setChecked(vinculo.data_saida is not None)
        self.data_saida = _campo_data(vinculo.data_saida)
        self.saiu.toggled.connect(self._ajustar_saida)

        alteracoes = repo.listar_alteracoes(conn, vinculo.empresa_id)
        self.alteracao_entrada = self._combo_alteracoes(alteracoes, vinculo.alteracao_entrada_id)
        self.alteracao_saida = self._combo_alteracoes(alteracoes, vinculo.alteracao_saida_id)

        self.observacao = QLineEdit(vinculo.observacao or "")

        form = QFormLayout()
        form.addRow("% do capital", self.percentual)
        form.addRow("Qtde de cotas", self.cotas)
        form.addRow("Capital do sócio (R$)", self.capital)
        form.addRow("", self.estimativa)
        form.addRow("Data de entrada", self.data_entrada)
        form.addRow("Alteração de entrada", self.alteracao_entrada)
        form.addRow("", self.saiu)
        form.addRow("Data de saída", self.data_saida)
        form.addRow("Alteração de saída", self.alteracao_saida)
        form.addRow("Observação", self.observacao)

        aviso = QLabel(
            "Corrige este registro como está — não abre um vínculo novo nem cria alteração "
            "contratual. Para registrar uma mudança com histórico, cadastre a alteração na "
            "aba Alterações contratuais e associe-a aqui."
        )
        aviso.setProperty("role", "subtitulo")
        aviso.setWordWrap(True)

        self.btn_excluir = QPushButton("Excluir vínculo")
        self.btn_excluir.setProperty("role", "perigo")
        self.btn_excluir.clicked.connect(self._excluir)
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.clicked.connect(self.reject)
        btn_salvar = QPushButton("Salvar")
        btn_salvar.setProperty("role", "primario")
        btn_salvar.setDefault(True)
        btn_salvar.clicked.connect(self._salvar)

        botoes = QHBoxLayout()
        botoes.addWidget(self.btn_excluir)
        botoes.addStretch()
        botoes.addWidget(btn_cancelar)
        botoes.addWidget(btn_salvar)

        layout = QVBoxLayout(self)
        layout.addWidget(aviso)
        layout.addLayout(form)
        layout.addLayout(botoes)

        self._recalcular_estimativa()
        self._ajustar_saida()

    @staticmethod
    def _combo_alteracoes(alteracoes: list, atual_id: int | None) -> QComboBox:
        combo = QComboBox()
        combo.addItem("Nenhuma (associar depois)", None)
        for a in alteracoes:
            data = dt.date.fromisoformat(a.data).strftime("%d/%m/%Y")
            descricao = (a.descricao or "").strip()
            if len(descricao) > 40:
                descricao = descricao[:39] + "…"
            rotulo = f"Nº {a.numero} — {data}" + (f" — {descricao}" if descricao else "")
            if a.fechada:
                rotulo += " (trancada)"
            combo.addItem(rotulo, a.id)
        indice = combo.findData(atual_id)
        combo.setCurrentIndex(indice if indice >= 0 else 0)
        return combo

    def _recalcular_estimativa(self, *_args) -> None:
        self.estimativa.setText(_estimativa_por_cotas(self.conn, self.vinculo.empresa_id, self.cotas.value()))

    def _ajustar_saida(self, *_args) -> None:
        saiu = self.saiu.isChecked()
        self.data_saida.setEnabled(saiu)
        self.alteracao_saida.setEnabled(saiu)

    def vinculo_editado(self) -> VinculoSocietario:
        saiu = self.saiu.isChecked()
        return VinculoSocietario(
            id=self.vinculo.id,
            empresa_id=self.vinculo.empresa_id,
            socio_id=self.vinculo.socio_id,
            percentual_capital=self.percentual.value(),
            quantidade_cotas=self.cotas.value() or None,
            data_entrada=self.data_entrada.date().toString("yyyy-MM-dd"),
            data_saida=self.data_saida.date().toString("yyyy-MM-dd") if saiu else None,
            alteracao_entrada_id=self.alteracao_entrada.currentData(),
            alteracao_saida_id=self.alteracao_saida.currentData() if saiu else None,
            observacao=self.observacao.text().strip(),
            valor_capital=_valor_ou_nada(self.capital),
        )

    def _salvar(self) -> None:
        """Grava daqui mesmo, e só fecha se deu certo: com erro (período
        fechado, alteração trancada, saída antes da entrada) a pessoa corrige
        na tela em vez de perder tudo o que tinha digitado."""
        try:
            repo.salvar_vinculo(self.conn, self.vinculo_editado())
        except ValueError as exc:
            QMessageBox.warning(self, "Não foi possível salvar", str(exc))
            return
        self.accept()

    def _excluir(self) -> None:
        resposta = QMessageBox.question(
            self,
            "Excluir vínculo",
            "Excluir de vez este vínculo? O registro é apagado, sem deixar histórico.\n\n"
            "Se o sócio saiu da sociedade, marque \"Saiu da sociedade\" com a data em vez de "
            "excluir — assim os anos em que ele participou continuam aparecendo.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resposta != QMessageBox.Yes:
            return
        try:
            repo.excluir_vinculo(self.conn, self.vinculo.id)
        except ValueError as exc:
            QMessageBox.warning(self, "Não foi possível excluir", str(exc))
            return
        self.done(self.EXCLUIDO)


class SociosTab(QWidget):
    COLUNA_CAPITAL = 4
    COLUNA_SITUACAO = 7
    COLUNAS_VINCULOS = [
        "Empresa",
        "% registrado",
        "% atual",
        "Cotas",
        "Capital (R$)",
        "Entrada",
        "Saída",
        "Situação",
    ]

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._socios: list[Socio] = []
        self._socio_atual_id: int | None = None
        self._vinculos_exibidos: list[VinculoSocietario] = []
        # Definido antes de montar os painéis: ligar os campos ao
        # _procurar_semelhantes faz o textChanged disparar já na construção
        # (o ajuste da máscara limpa o campo de documento), e ele consulta o
        # modo. Sem isto o Qt engole um AttributeError a cada tela aberta.
        self._modo = MODO_VAZIO
        self._descricao_modo = ""

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        painel_socios = self._montar_painel_socios()
        painel_vinculos = self._montar_painel_vinculos()
        splitter.addWidget(painel_socios)
        splitter.addWidget(painel_vinculos)
        # O mínimo da direita é o que a barra de ações precisa pra não truncar
        # rótulo; com os botões da esquerda em grade, sobra folga pros dois. A
        # soma fica abaixo do mínimo que a tela de Distribuição trimestral já
        # impõe à janela, então isto não faz o programa abrir mais largo.
        painel_socios.setMinimumWidth(280)
        painel_vinculos.setMinimumWidth(560)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([400, 820])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self.atualizar()
        self._definir_modo(MODO_VAZIO)
        tema_estado().mudou.connect(lambda: self._definir_modo(self._modo, self._descricao_modo))

    # ------------------------------------------------------------- painéis --
    def _montar_painel_socios(self) -> QWidget:
        painel = QWidget()
        col = QVBoxLayout(painel)
        col.setSpacing(10)

        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Buscar por nome ou CPF…")
        self.busca.textChanged.connect(lambda _texto: self.atualizar())
        col.addWidget(self.busca)

        self.tabela = TabelaLista(0, 3, coluna_flexivel=0,
                                  mensagem_vazia="Nenhum sócio cadastrado ainda.")
        self.tabela.setHorizontalHeaderLabels(["Nome", "CPF/CNPJ", "Tipo"])
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela.itemSelectionChanged.connect(self._ao_selecionar_socio)
        col.addWidget(self.tabela, 1)

        self.nome = QLineEdit()
        self.nome.setPlaceholderText("Nome completo ou razão social")

        self.tipo_pessoa = QComboBox()
        for tipo, label in TIPOS_PESSOA_LABEL.items():
            self.tipo_pessoa.addItem(label, tipo)
        self.tipo_pessoa.currentIndexChanged.connect(self._ajustar_mascara_documento)

        self.cpf = QLineEdit()
        self.cpf.setProperty("role", "mono")

        form = QFormLayout()
        form.addRow("Nome", self.nome)
        form.addRow("Tipo", self.tipo_pessoa)
        self._rotulo_documento = QLabel("CPF")
        form.addRow(self._rotulo_documento, self.cpf)

        # Mesmo mecanismo do CrudTab: campos num painel próprio pra bloquear
        # tudo de uma vez enquanto não há sócio selecionado nem cadastro
        # começado — é o que mostra que a tela espera um clique em "Novo".
        self.painel_campos = QWidget()
        self.painel_campos.setLayout(form)
        self.aviso_form = criar_aviso_formulario()

        # Aviso de possível duplicata, logo abaixo dos campos: sócio repetido
        # se espalha por todas as empresas dele e só costuma aparecer na hora
        # de emitir informe, quando já é trabalhoso desfazer.
        self.aviso_duplicado = QLabel()
        self.aviso_duplicado.setWordWrap(True)
        self.aviso_duplicado.setTextFormat(Qt.RichText)
        self.aviso_duplicado.hide()

        self.btn_abrir_semelhante = QPushButton("Abrir o cadastro existente")
        self.btn_abrir_semelhante.clicked.connect(self._abrir_semelhante)
        self.btn_abrir_semelhante.hide()

        col.addWidget(self.aviso_form)
        col.addWidget(self.painel_campos)
        col.addWidget(self.aviso_duplicado)
        col.addWidget(self.btn_abrir_semelhante)

        self._semelhante_id: int | None = None
        self.nome.textChanged.connect(self._procurar_semelhantes)
        self.cpf.textChanged.connect(self._procurar_semelhantes)

        self._ajustar_mascara_documento()

        self.btn_novo = QPushButton("Novo")
        self.btn_salvar = QPushButton("Salvar")
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_excluir = QPushButton("Excluir")
        self.btn_excluir.setProperty("role", "perigo")
        self.btn_novo.clicked.connect(self._novo_socio)
        self.btn_salvar.clicked.connect(self._salvar_socio)
        self.btn_cancelar.clicked.connect(self._cancelar_socio)
        self.btn_excluir.clicked.connect(self._excluir_socio)

        # Grade 2x2 em vez de fila: quatro botões lado a lado exigiriam do
        # painel esquerdo uma largura que ele só tem em janela grande, e em
        # 1200px os rótulos truncavam ("ancel", "xclui"). Empilhados, cabem em
        # qualquer largura e sobra espaço pro painel da direita.
        botoes = QGridLayout()
        botoes.setSpacing(8)
        botoes.addWidget(self.btn_novo, 0, 0)
        botoes.addWidget(self.btn_salvar, 0, 1)
        botoes.addWidget(self.btn_cancelar, 1, 0)
        botoes.addWidget(self.btn_excluir, 1, 1)
        col.addLayout(botoes)

        return painel

    def _montar_painel_vinculos(self) -> QWidget:
        card = QFrame()
        card.setProperty("role", "card")
        col = QVBoxLayout(card)
        col.setContentsMargins(20, 16, 20, 20)
        col.setSpacing(10)

        self.titulo_vinculos = QLabel("Vínculos societários")
        self.titulo_vinculos.setProperty("role", "secao")
        self.subtitulo_vinculos = QLabel("Selecione um sócio para ver e gerenciar suas empresas.")
        self.subtitulo_vinculos.setProperty("role", "subtitulo")

        # O mapa fica no cabeçalho, não na barra de baixo: ele não age sobre
        # nada, é outra forma de ver o que este painel já mostra — e a barra de
        # ações, com mais um botão, truncava os rótulos na janela no mínimo.
        self.btn_mapa = QPushButton("Mapa de vínculos")
        self.btn_mapa.setToolTip(
            "Abre um diagrama com as empresas em que este sócio participa — dá pra exportar "
            "em PDF ou SVG para anexar a processo, contrato ou apresentação."
        )
        self.btn_mapa.clicked.connect(self._abrir_mapa_vinculos)

        linha_titulo = QHBoxLayout()
        linha_titulo.addWidget(self.titulo_vinculos)
        linha_titulo.addStretch()
        linha_titulo.addWidget(self.btn_mapa)

        col.addLayout(linha_titulo)
        col.addWidget(self.subtitulo_vinculos)
        col.addWidget(_hairline())

        self.tabela_vinculos = TabelaLista(
            0, len(self.COLUNAS_VINCULOS), coluna_flexivel=0,
            mensagem_vazia="Selecione um sócio para ver as empresas dele.",
        )
        self.tabela_vinculos.setHorizontalHeaderLabels(self.COLUNAS_VINCULOS)
        self.tabela_vinculos.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela_vinculos.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabela_vinculos.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela_vinculos.itemSelectionChanged.connect(self._atualizar_disponibilidade_botoes)
        self.tabela_vinculos.itemDoubleClicked.connect(lambda _item: self._editar_vinculo())
        col.addWidget(self.tabela_vinculos, 1)

        self.btn_associar = QPushButton("Associar a uma empresa")
        self.btn_associar.setProperty("role", "primario")
        self.btn_associar.clicked.connect(self._associar_empresa)

        # Uma ação só pro vínculo selecionado: a tela de edição tem todos os
        # campos (inclusive a saída) e o botão de excluir. Antes eram quatro
        # ações — editar datas, atualizar cotas, encerrar, excluir — e era
        # preciso saber de antemão qual delas mexia em quê.
        self.btn_editar_vinculo = QPushButton("Editar vínculo")
        self.btn_editar_vinculo.setToolTip(
            "Participação, capital, datas de entrada e saída, alterações contratuais e "
            "observação. Também dá para abrir com dois cliques no vínculo."
        )
        self.btn_editar_vinculo.clicked.connect(self._editar_vinculo)

        self.btn_informe = QPushButton("Informe de rendimentos")
        self.btn_informe.setToolTip(
            "Comprovante de Rendimentos Pagos e de Imposto sobre a Renda Retido na Fonte "
            "(IN RFB nº 2.060/2021) — um por empresa em que o sócio recebeu."
        )
        self.btn_informe.clicked.connect(self._emitir_informe)

        botoes = QHBoxLayout()
        botoes.addWidget(self.btn_associar)
        botoes.addWidget(self.btn_editar_vinculo)
        botoes.addStretch()
        botoes.addWidget(self.btn_informe)
        col.addLayout(botoes)

        self._atualizar_disponibilidade_botoes()
        return card

    # -------------------------------------------------------------- sócios --
    def atualizar(self) -> None:
        socios = repo.listar_socios(self.conn)
        termo = self.busca.text().strip().lower()
        if termo:
            socios = [s for s in socios if termo in s.nome.lower() or termo in (s.cpf or "").lower()]
        self._socios = socios
        self.tabela.setRowCount(len(self._socios))
        for row, s in enumerate(self._socios):
            self.tabela.setItem(row, 0, QTableWidgetItem(s.nome))
            self.tabela.setItem(row, 1, QTableWidgetItem(s.cpf or ""))
            self.tabela.setItem(row, 2, QTableWidgetItem(TIPOS_PESSOA_LABEL.get(s.tipo_pessoa, s.tipo_pessoa)))
        self.tabela.ajustar_colunas()
        self._atualizar_painel_vinculos()

    def _ajustar_mascara_documento(self, *_args) -> None:
        tipo = self.tipo_pessoa.currentData() or "fisica"
        self.cpf.clear()
        if tipo == "juridica":
            configurar_campo_cnpj(self.cpf)
            self._rotulo_documento.setText("CNPJ")
        else:
            configurar_campo_cpf(self.cpf)
            self._rotulo_documento.setText("CPF")

    def _procurar_semelhantes(self, *_args) -> None:
        """Procura enquanto se digita, mas só em cadastro/edição — com o
        formulário bloqueado não há nada sendo digitado pra avisar."""
        if self._modo not in (MODO_NOVO, MODO_EDICAO):
            self._esconder_aviso_duplicado()
            return

        achados = repo.socios_semelhantes(
            self.conn,
            self.nome.text(),
            documento_valido_ou_vazio(self.cpf) or self.cpf.text(),
            ignorar_id=self._socio_atual_id,
        )
        if not achados:
            self._esconder_aviso_duplicado()
            return

        socio, motivo = achados[0]
        self._semelhante_id = socio.id
        extra = f" (e mais {len(achados) - 1})" if len(achados) > 1 else ""
        self.aviso_duplicado.setText(
            f"⚠ Já existe <b>{socio.nome}</b> — {motivo}{extra}. "
            "Confira antes de cadastrar outro."
        )
        self.aviso_duplicado.setStyleSheet(
            f"color: {SAIU_FG()}; background: {SAIU_BG()}; border-radius: 4px; "
            f"padding: 7px 10px; font-size: 11px;"
        )
        self.aviso_duplicado.show()
        # Só oferece abrir o outro cadastro ao criar um novo; editando, abrir
        # outro registro no meio da edição descartaria o que está na tela.
        self.btn_abrir_semelhante.setVisible(self._modo == MODO_NOVO)

    def _esconder_aviso_duplicado(self) -> None:
        self._semelhante_id = None
        self.aviso_duplicado.hide()
        self.btn_abrir_semelhante.hide()

    def _abrir_semelhante(self) -> None:
        if self._semelhante_id is None:
            return
        self.busca.clear()
        self.atualizar()
        self._selecionar_socio_na_tabela(self._semelhante_id)

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
        self._procurar_semelhantes()

    def _ao_selecionar_socio(self) -> None:
        linhas = self.tabela.selectionModel().selectedRows()
        if not linhas:
            return
        socio = self._socios[linhas[0].row()]
        self._socio_atual_id = socio.id
        self.nome.setText(socio.nome)
        idx = self.tipo_pessoa.findData(socio.tipo_pessoa)
        self.tipo_pessoa.setCurrentIndex(idx if idx >= 0 else 0)
        self._ajustar_mascara_documento()
        self.cpf.setText(socio.cpf or "")
        self._definir_modo(MODO_EDICAO, socio.nome)
        self._atualizar_painel_vinculos()

    def _novo_socio(self) -> None:
        self._socio_atual_id = None
        self.tabela.clearSelection()
        self.nome.clear()
        self.tipo_pessoa.setCurrentIndex(0)
        self._ajustar_mascara_documento()
        self._definir_modo(MODO_NOVO)
        self.nome.setFocus()
        self._atualizar_painel_vinculos()

    def _cancelar_socio(self) -> None:
        """Sai do cadastro/edição sem gravar. O painel de vínculos volta pro
        estado sem sócio selecionado junto — senão ficaria mostrando os
        vínculos de alguém que não está mais em edição."""
        self._socio_atual_id = None
        self.tabela.clearSelection()
        self.nome.clear()
        self.tipo_pessoa.setCurrentIndex(0)
        self._ajustar_mascara_documento()
        self._definir_modo(MODO_CANCELADO)
        self._atualizar_painel_vinculos()

    def _salvar_socio(self) -> None:
        nome = self.nome.text().strip()
        if not nome:
            QMessageBox.warning(self, "Erro ao salvar", "Informe o nome do sócio.")
            return
        try:
            socio_id = repo.salvar_socio(
                self.conn,
                Socio(
                    id=self._socio_atual_id,
                    nome=nome,
                    cpf=documento_valido_ou_vazio(self.cpf),
                    tipo_pessoa=self.tipo_pessoa.currentData(),
                ),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao salvar", str(exc))
            return
        self._socio_atual_id = socio_id
        self.atualizar()
        # Seguir selecionado é de propósito: o painel de vínculos à direita é
        # do sócio atual, e limpar tudo depois de salvar tiraria da tela quem
        # a pessoa acabou de cadastrar justamente pra associar a uma empresa.
        self._selecionar_socio_na_tabela(socio_id)
        if self._modo != MODO_EDICAO:
            self._definir_modo(MODO_SALVO)

    def _excluir_socio(self) -> None:
        if self._socio_atual_id is None:
            QMessageBox.information(self, "Excluir", "Selecione um sócio na tabela.")
            return
        resposta = QMessageBox.question(self, "Excluir", "Confirma a exclusão do sócio selecionado?")
        if resposta != QMessageBox.Yes:
            return
        try:
            repo.excluir_socio(self.conn, self._socio_atual_id)
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao excluir", str(exc))
            return
        self._socio_atual_id = None
        self.tabela.clearSelection()
        self.nome.clear()
        self.tipo_pessoa.setCurrentIndex(0)
        self._ajustar_mascara_documento()
        self._definir_modo(MODO_VAZIO)
        self.atualizar()

    def _selecionar_socio_na_tabela(self, socio_id: int) -> None:
        for row, s in enumerate(self._socios):
            if s.id == socio_id:
                self.tabela.selectRow(row)
                return

    # ------------------------------------------------------------ vínculos --
    def _atualizar_painel_vinculos(self) -> None:
        if self._socio_atual_id is None:
            self.titulo_vinculos.setText("Vínculos societários")
            self.subtitulo_vinculos.setText("Selecione um sócio para ver e gerenciar suas empresas.")
            self.tabela_vinculos.setRowCount(0)
            self._vinculos_exibidos = []
            self._atualizar_disponibilidade_botoes()
            return

        socio = next((s for s in self._socios if s.id == self._socio_atual_id), None)
        nome_socio = socio.nome if socio else "?"
        self.titulo_vinculos.setText(f"Vínculos societários — {nome_socio}")

        vinculos = repo.listar_vinculos_socio(self.conn, self._socio_atual_id)
        self._vinculos_exibidos = vinculos
        empresas = {e.id: e for e in repo.listar_empresas(self.conn)}

        ativos = sum(1 for v in vinculos if v.data_saida is None)
        self.subtitulo_vinculos.setText(
            f"{ativos} vínculo(s) ativo(s) de {len(vinculos)} no total."
            if vinculos
            else "Este sócio ainda não está associado a nenhuma empresa."
        )

        self.tabela_vinculos.setRowCount(len(vinculos))
        for row, v in enumerate(vinculos):
            empresa = empresas.get(v.empresa_id)
            estado = repo.estado_atual_empresa(self.conn, v.empresa_id) if empresa else None
            percentual_atual = ""
            if estado and estado["quantidade_cotas"]:
                percentual_atual = formatar_valor_br(100 * (v.quantidade_cotas or 0) / estado["quantidade_cotas"], 4)

            ativo = v.data_saida is None
            situacao = "Ativo" if ativo else "Encerrado"
            # Capital informado vale como está; sem ele, o vínculo ativo mostra
            # a estimativa pelas cotas, marcada com "≈" pra não passar por
            # valor informado. Vínculo encerrado sem capital não tem o que
            # estimar: o capital de hoje não diz nada sobre quem já saiu.
            estimado = v.valor_capital is None and ativo
            if v.valor_capital is not None:
                capital = formatar_valor_br(v.valor_capital)
            elif estimado:
                capital = f"≈ {formatar_valor_br(repo.valor_participacao(self.conn, v))}"
            else:
                capital = "—"
            valores = [
                empresa.nome if empresa else "?",
                formatar_valor_br(v.percentual_capital, 4),
                percentual_atual,
                formatar_valor_br(v.quantidade_cotas or 0, 0),
                capital,
                v.data_entrada,
                v.data_saida or "—",
                situacao,
            ]
            for col, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                item.setData(Qt.UserRole, v.id)
                if col == self.COLUNA_CAPITAL and estimado:
                    item.setToolTip(
                        "Estimativa pelas cotas (capital social ÷ cotas da empresa × cotas do "
                        "sócio). Informe o capital do sócio em \"Editar vínculo\" para gravar o valor."
                    )
                if col == self.COLUNA_SITUACAO:
                    # A situação é a única coluna que é um julgamento, não um
                    # dado: em verde e vermelho ela se lê antes de ser lida.
                    item.setForeground(QColor(SEAL_GREEN() if ativo else SAIU_FG()))
                    if not ativo:
                        item.setBackground(QColor(SAIU_BG()))
                    fonte = item.font()
                    fonte.setBold(True)
                    item.setFont(fonte)
                self.tabela_vinculos.setItem(row, col, item)
        self.tabela_vinculos.ajustar_colunas()
        self._atualizar_disponibilidade_botoes()

    def _atualizar_disponibilidade_botoes(self) -> None:
        tem_socio = self._socio_atual_id is not None
        self.btn_associar.setEnabled(tem_socio)
        self.btn_mapa.setEnabled(tem_socio)
        self.btn_informe.setEnabled(tem_socio)
        self.btn_editar_vinculo.setEnabled(self._vinculo_selecionado() is not None)

    def _vinculo_selecionado(self) -> VinculoSocietario | None:
        linhas = self.tabela_vinculos.selectionModel().selectedRows() if self.tabela_vinculos.selectionModel() else []
        if not linhas:
            return None
        return self._vinculos_exibidos[linhas[0].row()]

    def _associar_empresa(self) -> None:
        if self._socio_atual_id is None:
            return
        dialogo = _DialogoAssociarEmpresa(self.conn, self._socio_atual_id, self)
        if dialogo.empresa.count() == 0:
            QMessageBox.information(
                self, "Associar a uma empresa", "Não há empresas disponíveis (o sócio já está em todas, ou nenhuma empresa foi cadastrada)."
            )
            return
        if dialogo.exec() != QDialog.Accepted:
            return
        empresa_id, percentual, cotas, data_entrada, descricao, capital = dialogo.dados()
        try:
            repo.associar_socio_a_empresa(
                self.conn, empresa_id, self._socio_atual_id, percentual, cotas, data_entrada,
                descricao or "Inclusão de sócio", valor_capital=capital,
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao associar", str(exc))
            return
        self._atualizar_painel_vinculos()

    def _editar_vinculo(self) -> None:
        vinculo = self._vinculo_selecionado()
        if vinculo is None:
            return
        empresa = repo.buscar_empresa(self.conn, vinculo.empresa_id)
        dialogo = _DialogoEditarVinculo(self.conn, vinculo, empresa.nome if empresa else "?", self)
        # A tela grava (ou exclui) por conta própria e só fecha se deu certo;
        # aqui é só redesenhar quando algo mudou.
        if dialogo.exec() != QDialog.Rejected:
            self._atualizar_painel_vinculos()

    def _emitir_informe(self) -> None:
        """Abre a conferência e emissão do informe de rendimentos do sócio
        selecionado. A janela é por sócio (não por vínculo) porque um sócio de
        três empresas recebe três comprovantes e é bom conferir os três de uma
        vez, na mesma sessão."""
        if self._socio_atual_id is None:
            return
        socio = next((s for s in self._socios if s.id == self._socio_atual_id), None)
        if socio is None:
            return
        InformeRendimentosDialog(self.conn, socio, self).exec()

    def _abrir_mapa_vinculos(self) -> None:
        """Mostra num desenho o que a tabela ao lado mostra em linhas.

        A tabela responde "quais empresas"; o mapa mostra a forma — onde a
        participação é grande, onde é simbólica, de onde a pessoa já saiu. É o
        que se leva para uma reunião ou se anexa a um processo, e por isso sai
        em PDF e em SVG."""
        socio = next((s for s in self._socios if s.id == self._socio_atual_id), None)
        if socio is None:
            return
        empresas = {e.id: e for e in repo.listar_empresas(self.conn)}
        vinculos = [
            {
                "empresa_nome": empresas[v.empresa_id].nome if v.empresa_id in empresas else "?",
                # O percentual registrado no vínculo, o mesmo da coluna
                # "% registrado" da tabela — não o recalculado por cotas, que
                # muda com o capital da empresa e faria o desenho discordar
                # do que está ao lado dele na tela.
                "percentual": v.percentual_capital,
                "data_entrada": v.data_entrada,
                "data_saida": v.data_saida,
                "capital": v.valor_capital,
            }
            for v in repo.listar_vinculos_socio(self.conn, socio.id)
        ]
        DialogoMapaVinculos(socio.nome, socio.cpf or "", vinculos, self).exec()
