"""Aba de Sócios: cadastro básico (nome/cpf) + o painel de vínculos
societários do sócio selecionado — associar a empresas, atualizar cotas e
encerrar vínculo. Qualquer mudança feita por aqui gera automaticamente uma
alteração contratual na empresa correspondente, então o histórico da empresa
sempre reflete o que foi feito na aba de Sócios, e vice-versa."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
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
    QMenu,
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
    MODO_CANCELADO,
    MODO_EDICAO,
    MODO_NOVO,
    MODO_SALVO,
    MODO_VAZIO,
    aplicar_modo_formulario,
    configurar_campo_cnpj,
    configurar_campo_cpf,
    criar_aviso_formulario,
    documento_valido_ou_vazio,
    formatar_numero,
    formatar_valor_br,
)
from .informe_rendimentos_view import InformeRendimentosDialog
from .theme import SAIU_BG, SAIU_FG
from .theme import estado as tema_estado


def _hairline() -> QFrame:
    linha = QFrame()
    linha.setProperty("role", "hairline")
    return linha


class _DialogoAssociarEmpresa(QDialog):
    def __init__(self, conn, socio_id: int, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Associar sócio a uma empresa")
        self.setMinimumWidth(360)

        vinculadas_ativas = {
            v.empresa_id
            for v in repo.listar_vinculos_socio(conn, socio_id)
            if v.data_saida is None
        }

        self.empresa = QComboBox()
        for e in repo.listar_empresas(conn):
            if e.id not in vinculadas_ativas:
                self.empresa.addItem(f"{e.nome} (nº {e.numero_chamada})", e.id)
        self.empresa.currentIndexChanged.connect(self._recalcular_valor)

        self.percentual = QDoubleSpinBox()
        self.percentual.setMaximum(100)
        self.percentual.setDecimals(4)
        formatar_numero(self.percentual)

        self.cotas = QDoubleSpinBox()
        self.cotas.setMaximum(1_000_000_000)
        formatar_numero(self.cotas)
        self.cotas.valueChanged.connect(self._recalcular_valor)

        self.data_entrada = QDateEdit(calendarPopup=True)
        self.data_entrada.setDisplayFormat("dd/MM/yyyy")
        self.data_entrada.setDate(dt.date.today())

        self.descricao = QLineEdit("Inclusão de sócio (registrado pela aba de Sócios)")

        self.valor_participacao = QLabel("R$ 0,00")
        self.valor_participacao.setProperty("role", "subtitulo")

        form = QFormLayout()
        form.addRow("Empresa", self.empresa)
        form.addRow("% do capital", self.percentual)
        form.addRow("Qtde de cotas", self.cotas)
        form.addRow("Valor da participação (hoje)", self.valor_participacao)
        form.addRow("Data de entrada", self.data_entrada)
        form.addRow("Alteração contratual (descrição)", self.descricao)

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(botoes)

        self._recalcular_valor()

    def _recalcular_valor(self, *_args) -> None:
        empresa_id = self.empresa.currentData()
        if empresa_id is None:
            self.valor_participacao.setText("R$ 0,00")
            return
        estado = repo.estado_atual_empresa(self.conn, empresa_id)
        total_cotas = estado["quantidade_cotas"]
        valor_por_cota = (estado["capital_social"] / total_cotas) if total_cotas else 0
        self.valor_participacao.setText(f"R$ {formatar_valor_br(self.cotas.value() * valor_por_cota)}")

    def dados(self) -> tuple[int | None, float, float, str, str]:
        return (
            self.empresa.currentData(),
            self.percentual.value(),
            self.cotas.value(),
            self.data_entrada.date().toString("yyyy-MM-dd"),
            self.descricao.text().strip(),
        )


class _DialogoAtualizarCotas(QDialog):
    def __init__(self, conn, vinculo: VinculoSocietario, empresa_nome: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Atualizar cotas — {empresa_nome}")
        self.setMinimumWidth(360)

        self.percentual = QDoubleSpinBox()
        self.percentual.setMaximum(100)
        self.percentual.setDecimals(4)
        formatar_numero(self.percentual)
        self.percentual.setValue(vinculo.percentual_capital)

        self.cotas = QDoubleSpinBox()
        self.cotas.setMaximum(1_000_000_000)
        formatar_numero(self.cotas)
        self.cotas.setValue(vinculo.quantidade_cotas or 0)

        self.data = QDateEdit(calendarPopup=True)
        self.data.setDisplayFormat("dd/MM/yyyy")
        self.data.setDate(dt.date.today())

        self.descricao = QLineEdit("Atualização de cotas (registrado pela aba de Sócios)")

        form = QFormLayout()
        form.addRow("Novo % do capital", self.percentual)
        form.addRow("Nova qtde de cotas", self.cotas)
        form.addRow("Data da atualização", self.data)
        form.addRow("Alteração contratual (descrição)", self.descricao)

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Isto encerra o vínculo atual e abre um novo com os valores informados, preservando o histórico."))
        layout.addLayout(form)
        layout.addWidget(botoes)

    def dados(self) -> tuple[float, float, str, str]:
        return (
            self.percentual.value(),
            self.cotas.value(),
            self.data.date().toString("yyyy-MM-dd"),
            self.descricao.text().strip(),
        )


class _DialogoEncerrarVinculo(QDialog):
    def __init__(self, empresa_nome: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Encerrar vínculo — {empresa_nome}")
        self.setMinimumWidth(360)

        self.data_saida = QDateEdit(calendarPopup=True)
        self.data_saida.setDisplayFormat("dd/MM/yyyy")
        self.data_saida.setDate(dt.date.today())

        self.descricao = QLineEdit("Saída de sócio (registrado pela aba de Sócios)")

        form = QFormLayout()
        form.addRow("Data de saída", self.data_saida)
        form.addRow("Alteração contratual (descrição)", self.descricao)

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(botoes)

    def dados(self) -> tuple[str, str]:
        return self.data_saida.date().toString("yyyy-MM-dd"), self.descricao.text().strip()


class _DialogoEditarVinculo(QDialog):
    """Corrige as datas (e observação) de um vínculo já existente — não é um
    evento societário novo, então não gera alteração contratual."""

    def __init__(self, vinculo: VinculoSocietario, empresa_nome: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Editar vínculo — {empresa_nome}")
        self.setMinimumWidth(360)

        self.data_entrada = QDateEdit(calendarPopup=True)
        self.data_entrada.setDisplayFormat("dd/MM/yyyy")
        self.data_entrada.setDate(dt.datetime.strptime(vinculo.data_entrada, "%Y-%m-%d").date())

        self.tem_saida = vinculo.data_saida is not None
        self.data_saida = QDateEdit(calendarPopup=True)
        self.data_saida.setDisplayFormat("dd/MM/yyyy")
        if self.tem_saida:
            self.data_saida.setDate(dt.datetime.strptime(vinculo.data_saida, "%Y-%m-%d").date())

        self.observacao = QLineEdit(vinculo.observacao or "")

        form = QFormLayout()
        form.addRow("Data de entrada", self.data_entrada)
        if self.tem_saida:
            form.addRow("Data de saída", self.data_saida)
        form.addRow("Observação", self.observacao)

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        aviso = QLabel(
            "Isto corrige o registro existente (não abre uma nova alteração contratual)."
            if not self.tem_saida
            else "Este vínculo já está encerrado; a saída só pode ser editada aqui."
        )
        aviso.setProperty("role", "subtitulo")
        aviso.setWordWrap(True)
        layout.addWidget(aviso)
        layout.addLayout(form)
        layout.addWidget(botoes)

    def dados(self) -> tuple[str, str | None, str]:
        data_saida = self.data_saida.date().toString("yyyy-MM-dd") if self.tem_saida else None
        return self.data_entrada.date().toString("yyyy-MM-dd"), data_saida, self.observacao.text().strip()


class SociosTab(QWidget):
    COLUNAS_VINCULOS = [
        "Empresa",
        "% registrado",
        "% atual",
        "Cotas",
        "Valor da participação",
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

        self.tabela = QTableWidget(0, 3)
        self.tabela.setHorizontalHeaderLabels(["Nome", "CPF/CNPJ", "Tipo"])
        self.tabela.setAlternatingRowColors(True)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela.verticalHeader().setVisible(False)
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

        col.addWidget(self.titulo_vinculos)
        col.addWidget(self.subtitulo_vinculos)
        col.addWidget(_hairline())

        self.tabela_vinculos = QTableWidget(0, len(self.COLUNAS_VINCULOS))
        self.tabela_vinculos.setHorizontalHeaderLabels(self.COLUNAS_VINCULOS)
        self.tabela_vinculos.setAlternatingRowColors(True)
        self.tabela_vinculos.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela_vinculos.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabela_vinculos.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela_vinculos.verticalHeader().setVisible(False)
        self.tabela_vinculos.itemSelectionChanged.connect(self._atualizar_disponibilidade_botoes)
        col.addWidget(self.tabela_vinculos, 1)

        self.btn_associar = QPushButton("Associar a uma empresa")
        self.btn_associar.setProperty("role", "primario")
        self.btn_associar.clicked.connect(self._associar_empresa)

        # As quatro ações sobre o vínculo selecionado ficam num menu só:
        # todas dependem da mesma seleção e nenhuma é de uso frequente, então
        # como botões soltos só enchiam a barra. "Associar" fica de fora
        # porque é a única que não precisa de vínculo selecionado — é a ação
        # com que se começa.
        self.btn_acoes_vinculo = QPushButton("Ações do vínculo")
        menu = QMenu(self.btn_acoes_vinculo)
        self.acao_editar = menu.addAction("Editar datas", self._editar_vinculo)
        self.acao_atualizar_cotas = menu.addAction("Atualizar cotas", self._atualizar_cotas)
        # As duas de baixo mexem no histórico; a separação é o aviso visual
        # que o vermelho dos botões dava antes.
        menu.addSeparator()
        self.acao_encerrar = menu.addAction("Encerrar vínculo", self._encerrar_vinculo)
        self.acao_excluir = menu.addAction("Excluir vínculo", self._excluir_vinculo)
        self.btn_acoes_vinculo.setMenu(menu)

        self.btn_informe = QPushButton("Informe de rendimentos")
        self.btn_informe.setToolTip(
            "Comprovante de Rendimentos Pagos e de Imposto sobre a Renda Retido na Fonte "
            "(IN RFB nº 2.060/2021) — um por empresa em que o sócio recebeu."
        )
        self.btn_informe.clicked.connect(self._emitir_informe)

        # Com as quatro ações no menu, tudo volta a caber numa linha só na
        # largura padrão da janela.
        botoes = QHBoxLayout()
        botoes.addWidget(self.btn_associar)
        botoes.addWidget(self.btn_acoes_vinculo)
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
        self.tabela.resizeColumnsToContents()
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
            valores = [
                empresa.nome if empresa else "?",
                formatar_valor_br(v.percentual_capital, 4),
                percentual_atual,
                formatar_valor_br(v.quantidade_cotas or 0, 0),
                f"R$ {formatar_valor_br(repo.valor_participacao(self.conn, v))}" if ativo else "—",
                v.data_entrada,
                v.data_saida or "—",
                situacao,
            ]
            for col, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                item.setData(Qt.UserRole, v.id)
                self.tabela_vinculos.setItem(row, col, item)
        self.tabela_vinculos.resizeColumnsToContents()
        self._atualizar_disponibilidade_botoes()

    def _atualizar_disponibilidade_botoes(self) -> None:
        tem_socio = self._socio_atual_id is not None
        self.btn_associar.setEnabled(tem_socio)
        self.btn_informe.setEnabled(tem_socio)
        tem_vinculo = self._vinculo_selecionado() is not None
        vinculo_ativo_selecionado = self._vinculo_ativo_selecionado() is not None
        # Sem vínculo selecionado nenhuma das ações do menu vale, então o
        # botão inteiro trava — abrir um menu com tudo apagado não ajuda.
        self.btn_acoes_vinculo.setEnabled(tem_vinculo)
        self.acao_editar.setEnabled(tem_vinculo)
        self.acao_atualizar_cotas.setEnabled(vinculo_ativo_selecionado)
        self.acao_encerrar.setEnabled(vinculo_ativo_selecionado)
        self.acao_excluir.setEnabled(tem_vinculo)

    def _vinculo_selecionado(self) -> VinculoSocietario | None:
        linhas = self.tabela_vinculos.selectionModel().selectedRows() if self.tabela_vinculos.selectionModel() else []
        if not linhas:
            return None
        return self._vinculos_exibidos[linhas[0].row()]

    def _vinculo_ativo_selecionado(self) -> VinculoSocietario | None:
        vinculo = self._vinculo_selecionado()
        return vinculo if vinculo is not None and vinculo.data_saida is None else None

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
        empresa_id, percentual, cotas, data_entrada, descricao = dialogo.dados()
        try:
            repo.associar_socio_a_empresa(
                self.conn, empresa_id, self._socio_atual_id, percentual, cotas, data_entrada, descricao or "Inclusão de sócio"
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
        dialogo = _DialogoEditarVinculo(vinculo, empresa.nome if empresa else "?", self)
        if dialogo.exec() != QDialog.Accepted:
            return
        data_entrada, data_saida, observacao = dialogo.dados()
        vinculo.data_entrada = data_entrada
        vinculo.data_saida = data_saida
        vinculo.observacao = observacao
        try:
            repo.salvar_vinculo(self.conn, vinculo)
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao editar vínculo", str(exc))
            return
        self._atualizar_painel_vinculos()

    def _atualizar_cotas(self) -> None:
        vinculo = self._vinculo_ativo_selecionado()
        if vinculo is None:
            return
        empresa = repo.buscar_empresa(self.conn, vinculo.empresa_id)
        dialogo = _DialogoAtualizarCotas(self.conn, vinculo, empresa.nome if empresa else "?", self)
        if dialogo.exec() != QDialog.Accepted:
            return
        percentual, cotas, data, descricao = dialogo.dados()
        try:
            repo.atualizar_cotas_vinculo(self.conn, vinculo, percentual, cotas, data, descricao or "Atualização de cotas")
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao atualizar cotas", str(exc))
            return
        self._atualizar_painel_vinculos()

    def _encerrar_vinculo(self) -> None:
        vinculo = self._vinculo_ativo_selecionado()
        if vinculo is None:
            return
        empresa = repo.buscar_empresa(self.conn, vinculo.empresa_id)
        dialogo = _DialogoEncerrarVinculo(empresa.nome if empresa else "?", self)
        if dialogo.exec() != QDialog.Accepted:
            return
        data_saida, descricao = dialogo.dados()
        try:
            repo.encerrar_vinculo_registrando_alteracao(self.conn, vinculo, data_saida, descricao or "Saída de sócio")
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao encerrar vínculo", str(exc))
            return
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

    def _excluir_vinculo(self) -> None:
        """Apaga o vínculo de vez — diferente de "Encerrar", que só marca a
        saída preservando o histórico. Serve pra corrigir um vínculo criado
        por engano (empresa errada, sócio errado, etc.), não pra registrar
        uma saída de verdade."""
        vinculo = self._vinculo_selecionado()
        if vinculo is None:
            return
        empresa = repo.buscar_empresa(self.conn, vinculo.empresa_id)
        resposta = QMessageBox.question(
            self,
            "Excluir vínculo",
            f"Excluir de vez o vínculo com {empresa.nome if empresa else '?'}? Isso apaga o registro, "
            "diferente de \"Encerrar vínculo\" (que preserva o histórico marcando a saída). Use isso só "
            "pra corrigir um vínculo cadastrado por engano.",
        )
        if resposta != QMessageBox.Yes:
            return
        try:
            repo.excluir_vinculo(self.conn, vinculo.id)
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao excluir vínculo", str(exc))
            return
        self._atualizar_painel_vinculos()
