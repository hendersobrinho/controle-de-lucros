"""Painel de distribuição anual: para uma empresa/ano, mostra cada sócio com
cotas, % de capital, valor e % distribuído, e empréstimo recebido da
empresa — sócios que entraram ou saíram naquele ano ficam destacados."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import repositories as repo
from ..models import TIPOS_MOVIMENTACAO, TIPOS_MOVIMENTACAO_LABEL, Movimentacao, Socio
from ..planilha import exportar_modelo_distribuicao, importar_distribuicao
from .common import formatar_numero, formatar_valor_br, preencher_combo
from .theme import ENTROU_BG, ENTROU_FG, SAIU_BG, SAIU_FG, SEAL_GREEN
from .theme import estado as tema_estado

COLUNAS = [
    "Sócio",
    "CPF",
    "% capital",
    "Cotas",
    "Valor distribuído",
    "Pró-labore",
    "IRRF",
    "% distribuído",
    "Empréstimo (ano)",
    "Data de saída",
    "Situação",
]


class _DialogoDataVigencia(QDialog):
    """Uma data só, perguntada uma vez pra todo o lote de mudanças de %
    capital/cotas salvas junto na edição em linha — é a data efetiva da
    alteração contratual gerada por trás pra preservar o histórico."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Data da alteração")
        self.setMinimumWidth(320)

        self.data = QDateEdit(calendarPopup=True)
        self.data.setDisplayFormat("dd/MM/yyyy")
        self.data.setDate(dt.date.today())

        aviso = QLabel(
            "Uma ou mais linhas mudaram % de capital ou cotas — isso gera uma alteração "
            "contratual no histórico da empresa. A partir de quando essa mudança vale?"
        )
        aviso.setWordWrap(True)
        aviso.setProperty("role", "subtitulo")

        form = QFormLayout()
        form.addRow("Data de vigência", self.data)

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(aviso)
        layout.addLayout(form)
        layout.addWidget(botoes)


class _DialogoMovimentacoes(QDialog):
    """Lista e gerencia todos os lançamentos financeiros entre a empresa e
    este sócio naquele ano — empréstimo nos dois sentidos, adiantamento de
    lucro e devolução de capital, tudo no mesmo lugar. A soma do tipo
    "empréstimo da empresa ao sócio" alimenta automaticamente a coluna
    "Empréstimo (ano)" da tela principal."""

    def __init__(self, conn, empresa_id: int, socio_id: int, socio_nome: str, ano_base: int, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.empresa_id = empresa_id
        self.socio_id = socio_id
        self.ano_base = ano_base
        self.setWindowTitle(f"Movimentações — {socio_nome} ({ano_base})")
        self.setMinimumWidth(480)

        self.tabela = QTableWidget(0, 3)
        self.tabela.setHorizontalHeaderLabels(["Tipo", "Data", "Valor"])
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.verticalHeader().setVisible(False)

        self.tipo = QComboBox()
        for tipo in TIPOS_MOVIMENTACAO:
            self.tipo.addItem(TIPOS_MOVIMENTACAO_LABEL[tipo], tipo)

        self.data = QDateEdit(calendarPopup=True)
        self.data.setDisplayFormat("dd/MM/yyyy")
        data_padrao = dt.date.today() if ano_base == dt.date.today().year else dt.date(ano_base, 12, 31)
        self.data.setDate(data_padrao)

        self.valor = QDoubleSpinBox()
        self.valor.setMaximum(1_000_000_000)
        self.valor.setDecimals(2)
        self.valor.setPrefix("R$ ")
        formatar_numero(self.valor)

        btn_adicionar = QPushButton("Adicionar lançamento")
        btn_adicionar.setProperty("role", "primario")
        btn_adicionar.clicked.connect(self._adicionar)

        btn_excluir = QPushButton("Excluir selecionado")
        btn_excluir.setProperty("role", "perigo")
        btn_excluir.clicked.connect(self._excluir)

        form = QFormLayout()
        form.addRow("Tipo", self.tipo)
        form.addRow("Data", self.data)
        form.addRow("Valor", self.valor)

        botoes_linha = QHBoxLayout()
        botoes_linha.addWidget(btn_adicionar)
        botoes_linha.addWidget(btn_excluir)
        botoes_linha.addStretch()

        btn_fechar = QPushButton("Fechar")
        btn_fechar.clicked.connect(self.accept)

        layout = QVBoxLayout(self)
        layout.addWidget(self.tabela, 1)
        layout.addLayout(form)
        layout.addLayout(botoes_linha)
        layout.addWidget(btn_fechar)

        self._atualizar_tabela()

    def _atualizar_tabela(self) -> None:
        self._entradas = repo.listar_movimentacoes(self.conn, self.empresa_id, self.socio_id, self.ano_base)
        self.tabela.setRowCount(len(self._entradas))
        for row, m in enumerate(self._entradas):
            self.tabela.setItem(row, 0, QTableWidgetItem(TIPOS_MOVIMENTACAO_LABEL.get(m.tipo, m.tipo)))
            self.tabela.setItem(row, 1, QTableWidgetItem(m.data))
            self.tabela.setItem(row, 2, QTableWidgetItem(f"R$ {formatar_valor_br(m.valor)}"))
        self.tabela.resizeColumnsToContents()

    def _adicionar(self) -> None:
        if self.valor.value() <= 0:
            QMessageBox.warning(self, "Adicionar lançamento", "Informe um valor maior que zero.")
            return
        try:
            repo.salvar_movimentacao(
                self.conn,
                Movimentacao(
                    id=None,
                    empresa_id=self.empresa_id,
                    socio_id=self.socio_id,
                    tipo=self.tipo.currentData(),
                    valor=self.valor.value(),
                    data=self.data.date().toString("yyyy-MM-dd"),
                ),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao adicionar", str(exc))
            return
        self.valor.setValue(0)
        self._atualizar_tabela()

    def _excluir(self) -> None:
        linhas = self.tabela.selectionModel().selectedRows()
        if not linhas:
            return
        entrada = self._entradas[linhas[0].row()]
        try:
            repo.excluir_movimentacao(self.conn, entrada.id)
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao excluir", str(exc))
            return
        self._atualizar_tabela()


class _DialogoRevisaoImportacao(QDialog):
    """Linhas da planilha que não bateram com segurança contra um sócio já
    cadastrado (CPF ausente, nome ambíguo, ou sócio sem vínculo com esta
    empresa) — cada uma exige uma decisão humana antes de aplicar, pra nunca
    duplicar sócio por engano."""

    def __init__(self, conn, pendencias: list[dict], parent=None):
        super().__init__(parent)
        self.conn = conn
        self._socios = repo.listar_socios(conn)
        self._linhas_ui: list[tuple[dict, QComboBox]] = []

        self.setWindowTitle("Revisar linhas da planilha")
        self.setMinimumSize(680, 480)

        aviso = QLabel(
            f"{len(pendencias)} linha(s) da planilha não puderam ser associadas automaticamente a um "
            "sócio já cadastrado. Confira cada uma abaixo — nada é aplicado sem sua confirmação."
        )
        aviso.setWordWrap(True)
        aviso.setProperty("role", "subtitulo")

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        conteudo = QWidget()
        coluna = QVBoxLayout(conteudo)
        coluna.setSpacing(10)
        for pendencia in pendencias:
            coluna.addWidget(self._montar_linha(pendencia))
        coluna.addStretch()
        area.setWidget(conteudo)

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.button(QDialogButtonBox.Ok).setText("Aplicar selecionados")
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(aviso)
        layout.addWidget(area, 1)
        layout.addWidget(botoes)

    def _montar_linha(self, pendencia: dict) -> QWidget:
        caixa = QFrame()
        caixa.setProperty("role", "card")
        col = QVBoxLayout(caixa)
        col.setContentsMargins(14, 10, 14, 10)
        col.setSpacing(6)

        cpf_texto = pendencia["cpf"] or "não informado"
        nome_texto = pendencia["nome"] or "(sem nome na planilha)"
        titulo = QLabel(
            f"<b>{nome_texto}</b> — CPF: {cpf_texto} — R$ {formatar_valor_br(pendencia['valor_distribuido'])}"
        )
        col.addWidget(titulo)

        if pendencia.get("aviso"):
            rotulo_aviso = QLabel(f"⚠ {pendencia['aviso']}")
            rotulo_aviso.setWordWrap(True)
            rotulo_aviso.setStyleSheet(f"color: {SAIU_FG()}; font-size: 11px;")
            col.addWidget(rotulo_aviso)

        linha_acoes = QHBoxLayout()
        combo = QComboBox()
        self._preencher_combo_socios(combo)
        sugestao = pendencia.get("sugestao")
        if sugestao is not None:
            idx = combo.findData(sugestao.id)
            if idx >= 0:
                combo.setCurrentIndex(idx)

        btn_cadastrar = QPushButton("Cadastrar como novo sócio")
        btn_cadastrar.clicked.connect(lambda: self._cadastrar_novo(pendencia, combo, btn_cadastrar))

        linha_acoes.addWidget(QLabel("Vincular a:"))
        linha_acoes.addWidget(combo, 1)
        linha_acoes.addWidget(btn_cadastrar)
        col.addLayout(linha_acoes)

        self._linhas_ui.append((pendencia, combo))
        return caixa

    def _preencher_combo_socios(self, combo: QComboBox) -> None:
        combo.clear()
        combo.addItem("— não importar esta linha —", None)
        for s in self._socios:
            combo.addItem(f"{s.nome} ({s.cpf or 'sem CPF'})", s.id)

    def _cadastrar_novo(self, pendencia: dict, combo: QComboBox, botao: QPushButton) -> None:
        if not pendencia["nome"]:
            QMessageBox.warning(
                self, "Cadastrar sócio",
                "Esta linha não tem nome na planilha — cadastre manualmente na aba Sócios e volte aqui pra vincular.",
            )
            return
        resposta = QMessageBox.question(
            self,
            "Cadastrar novo sócio",
            f'Cadastrar "{pendencia["nome"]}" (CPF: {pendencia["cpf"] or "não informado"}) como um sócio novo?',
        )
        if resposta != QMessageBox.Yes:
            return
        try:
            novo_id = repo.salvar_socio(self.conn, Socio(id=None, nome=pendencia["nome"], cpf=pendencia["cpf"] or ""))
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao cadastrar sócio", str(exc))
            return
        self._socios = repo.listar_socios(self.conn)
        self._preencher_combo_socios(combo)
        idx = combo.findData(novo_id)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        botao.setEnabled(False)
        botao.setText("Sócio cadastrado ✓")

    def resolvidos(self) -> list[tuple[dict, int]]:
        """Pares (linha da planilha, id do sócio) que a pessoa confirmou."""
        return [
            (pendencia, combo.currentData())
            for pendencia, combo in self._linhas_ui
            if combo.currentData() is not None
        ]


class DistribuicaoAnualView(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._linhas: list[dict] = []

        self.empresa = QComboBox()
        self.empresa.currentIndexChanged.connect(lambda _: self._carregar())

        self.ano = QSpinBox()
        self.ano.setRange(2000, 2100)
        self.ano.setValue(dt.date.today().year)
        self.ano.valueChanged.connect(lambda _: self._carregar())

        self._periodo_fechado = False
        self.rotulo_trancamento = QLabel()
        self.rotulo_trancamento.setProperty("role", "subtitulo")
        self.btn_trancar = QPushButton()
        self.btn_trancar.setProperty("role", "perigo")
        self.btn_trancar.clicked.connect(self._alternar_trancamento)

        topo = QHBoxLayout()
        topo.addWidget(QLabel("Empresa:"))
        topo.addWidget(self.empresa, 1)
        topo.addWidget(QLabel("Ano:"))
        topo.addWidget(self.ano)
        topo.addSpacing(12)
        topo.addWidget(self.rotulo_trancamento)
        topo.addWidget(self.btn_trancar)

        self.info_capital = QLabel()
        self.info_capital.setProperty("role", "secao")

        self.aviso_cotas = QLabel()
        self.aviso_cotas.setWordWrap(True)
        self.aviso_cotas.hide()

        self.aviso_percentual = QLabel()
        self.aviso_percentual.setWordWrap(True)
        self.aviso_percentual.hide()

        self.resumo = QLabel()
        self.resumo.setProperty("role", "subtitulo")

        self.tabela = QTableWidget(0, len(COLUNAS))
        self.tabela.setHorizontalHeaderLabels(COLUNAS)
        self.tabela.setAlternatingRowColors(True)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.itemSelectionChanged.connect(self._atualizar_disponibilidade_botoes)

        self._editando = False
        self._widgets_edicao: list[dict] = []

        self.btn_editar = QPushButton("Editar")
        self.btn_editar.setProperty("role", "primario")
        self.btn_editar.clicked.connect(self._iniciar_edicao)

        self.btn_salvar_edicao = QPushButton("Salvar")
        self.btn_salvar_edicao.setProperty("role", "primario")
        self.btn_salvar_edicao.clicked.connect(self._salvar_edicao)

        self.btn_cancelar_edicao = QPushButton("Cancelar")
        self.btn_cancelar_edicao.clicked.connect(self._cancelar_edicao)

        self.btn_movimentacoes = QPushButton("Gerenciar movimentações")
        self.btn_movimentacoes.clicked.connect(self._gerenciar_movimentacoes)

        self.btn_exportar_modelo = QPushButton("Exportar modelo")
        self.btn_exportar_modelo.clicked.connect(self._exportar_modelo)

        self.btn_importar = QPushButton("Importar planilha")
        self.btn_importar.clicked.connect(self._importar_planilha)

        botoes = QHBoxLayout()
        botoes.addWidget(self.btn_editar)
        botoes.addWidget(self.btn_salvar_edicao)
        botoes.addWidget(self.btn_cancelar_edicao)
        botoes.addWidget(self.btn_movimentacoes)
        botoes.addSpacing(8)
        botoes.addWidget(self.btn_exportar_modelo)
        botoes.addWidget(self.btn_importar)
        botoes.addStretch()
        self._legenda_entrou = self._legenda("Entrou neste ano")
        self._legenda_saiu = self._legenda("Saiu neste ano")
        botoes.addWidget(self._legenda_entrou)
        botoes.addWidget(self._legenda_saiu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(topo)
        layout.addWidget(self.info_capital)
        layout.addWidget(self.aviso_cotas)
        layout.addWidget(self.aviso_percentual)
        layout.addWidget(self.resumo)
        layout.addWidget(self.tabela, 1)
        layout.addLayout(botoes)

        self._aplicar_cores()
        tema_estado().mudou.connect(self._aplicar_cores)
        self.atualizar()

    def _legenda(self, texto: str) -> QLabel:
        rotulo = QLabel(f"●  {texto}")
        return rotulo

    def _aplicar_cores(self) -> None:
        estilo_aviso = (
            f"background: {ENTROU_BG()}; color: {ENTROU_FG()}; border-radius: 4px; "
            f"padding: 8px 12px; font-weight: 600; font-size: 12px;"
        )
        self.aviso_cotas.setStyleSheet(estilo_aviso)
        self.aviso_percentual.setStyleSheet(estilo_aviso)
        self._legenda_entrou.setStyleSheet(f"color: {ENTROU_FG()}; font-size: 11px; font-weight: 600; padding-left: 12px;")
        self._legenda_saiu.setStyleSheet(f"color: {SAIU_FG()}; font-size: 11px; font-weight: 600; padding-left: 12px;")

    def atualizar(self) -> None:
        empresa_id_anterior = self.empresa.currentData()
        preencher_combo(self.empresa, repo.listar_empresas(self.conn))
        if empresa_id_anterior is not None:
            idx = self.empresa.findData(empresa_id_anterior)
            if idx >= 0:
                self.empresa.setCurrentIndex(idx)
        self._carregar()

    def selecionar_empresa(self, empresa_id: int) -> None:
        idx = self.empresa.findData(empresa_id)
        if idx >= 0 and idx != self.empresa.currentIndex():
            self.empresa.setCurrentIndex(idx)
        elif idx >= 0:
            self._carregar()

    def _carregar(self) -> None:
        self._editando = False
        self._widgets_edicao = []
        empresa_id = self.empresa.currentData()
        if empresa_id is None:
            self._linhas = []
            self._periodo_fechado = False
            self.tabela.setRowCount(0)
            self.info_capital.setText("")
            self.aviso_cotas.hide()
            self.aviso_percentual.hide()
            self.resumo.setText("Cadastre uma empresa primeiro.")
            self.rotulo_trancamento.setText("")
            self.btn_trancar.setVisible(False)
            self._atualizar_disponibilidade_botoes()
            return

        ano_base = self.ano.value()
        self._periodo_fechado = repo.periodo_esta_fechado(self.conn, empresa_id, ano_base)
        self.btn_trancar.setVisible(True)
        if self._periodo_fechado:
            self.rotulo_trancamento.setText(f"🔒 Período de {ano_base} trancado")
            self.btn_trancar.setText("Destrancar período")
        else:
            self.rotulo_trancamento.setText("")
            self.btn_trancar.setText("Trancar período")

        self._linhas = repo.panorama_distribuicao_anual(self.conn, empresa_id, ano_base)
        total = repo.total_distribuido_empresa_ano(self.conn, empresa_id, ano_base)
        self.resumo.setText(f"Lucro total distribuído em {ano_base}: R$ {formatar_valor_br(total)}")

        estado = repo.estado_empresa_no_periodo(self.conn, empresa_id, ano_base)
        texto_capital = f"Capital atual: R$ {formatar_valor_br(estado['capital_fim'])}"
        if estado["variacao_capital"] > 0:
            texto_capital += (
                f'  ·  <span style="color:{SEAL_GREEN()};">▲ Aumento de capital no ano: '
                f'R$ {formatar_valor_br(estado["variacao_capital"])}</span>'
            )
        elif estado["variacao_capital"] < 0:
            texto_capital += (
                f'  ·  <span style="color:{SAIU_FG()};">▼ Redução de capital no ano: '
                f'R$ {formatar_valor_br(abs(estado["variacao_capital"]))}</span>'
            )
        self.info_capital.setText(texto_capital)

        consistencia = repo.consistencia_cotas_socios(self.conn, empresa_id, ano_base)
        if consistencia["diferenca"] != 0:
            self.aviso_cotas.setText(
                f"⚠ As cotas totais da empresa ({formatar_valor_br(consistencia['cotas_totais_empresa'], 0)}) não conferem com a "
                f"soma das cotas dos sócios ({formatar_valor_br(consistencia['soma_cotas_socios'], 0)}). O capital ou as cotas da "
                f"empresa mudaram numa alteração contratual, mas não foram redistribuídas entre os sócios — "
                f"selecione o sócio abaixo e use \"Atualizar cotas do sócio\" para corrigir."
            )
            self.aviso_cotas.show()
        else:
            self.aviso_cotas.hide()

        consistencia_pct = repo.consistencia_percentual_socios(self.conn, empresa_id, ano_base)
        if round(consistencia_pct["diferenca"], 4) != 0:
            sinal = "falta" if consistencia_pct["diferenca"] > 0 else "sobra"
            self.aviso_percentual.setText(
                f"⚠ Os percentuais de capital dos sócios ativos somam {formatar_valor_br(consistencia_pct['soma_percentual'], 4)}%, "
                f"não 100% ({sinal} {formatar_valor_br(abs(consistencia_pct['diferenca']), 4)} p.p.). "
                f"Confira o cadastro societário desta empresa na aba Empresas."
            )
            self.aviso_percentual.show()
        else:
            self.aviso_percentual.hide()

        self.tabela.setRowCount(len(self._linhas))
        for row, linha in enumerate(self._linhas):
            situacao = "Ativo"
            if linha["reentrou_no_ano"]:
                situacao = f"Saiu em {linha['data_saida_anterior']} e reentrou em {linha['data_entrada']}"
            elif linha["saiu_no_ano"]:
                situacao = "Saiu este ano"
            elif linha["entrou_no_ano"]:
                situacao = "Entrou este ano"

            valores = [
                linha["socio_nome"],
                linha["socio_cpf"] or "—",
                formatar_valor_br(linha["percentual_capital"], 4),
                formatar_valor_br(linha["quantidade_cotas"], 0),
                f"R$ {formatar_valor_br(linha['valor_distribuido'])}",
                f"R$ {formatar_valor_br(linha['pro_labore'])}" if linha["pro_labore"] else "—",
                f"R$ {formatar_valor_br(linha['irrf'])}" if linha["irrf"] else "—",
                formatar_valor_br(linha["percentual_distribuido"], 3),
                f"R$ {formatar_valor_br(linha['emprestimo_recebido'])}" if linha["emprestimo_recebido"] else "—",
                linha["data_saida"] or "—",
                situacao,
            ]

            cor_fundo = cor_texto = None
            if linha["saiu_no_ano"]:
                cor_fundo, cor_texto = SAIU_BG(), SAIU_FG()
            elif linha["entrou_no_ano"]:
                cor_fundo, cor_texto = ENTROU_BG(), ENTROU_FG()

            for col, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                item.setData(Qt.UserRole, linha["socio_id"])
                if cor_fundo:
                    item.setBackground(QColor(cor_fundo))
                    item.setForeground(QColor(cor_texto))
                self.tabela.setItem(row, col, item)
        self.tabela.resizeColumnsToContents()
        self._atualizar_disponibilidade_botoes()

    def _atualizar_disponibilidade_botoes(self) -> None:
        linha = self._linha_selecionada()
        tem_empresa = self.empresa.currentData() is not None
        editavel = not self._periodo_fechado

        self.btn_editar.setVisible(not self._editando)
        self.btn_salvar_edicao.setVisible(self._editando)
        self.btn_cancelar_edicao.setVisible(self._editando)
        self.btn_editar.setEnabled(tem_empresa and editavel and bool(self._linhas))

        self.btn_movimentacoes.setEnabled(linha is not None and editavel and not self._editando)
        self.btn_exportar_modelo.setEnabled(tem_empresa and not self._editando)
        self.btn_importar.setEnabled(tem_empresa and editavel and not self._editando)

        self.empresa.setEnabled(not self._editando)
        self.ano.setEnabled(not self._editando)
        self.btn_trancar.setEnabled(not self._editando)

    def _alternar_trancamento(self) -> None:
        empresa_id = self.empresa.currentData()
        if empresa_id is None:
            return
        ano_base = self.ano.value()
        if self._periodo_fechado:
            resposta = QMessageBox.question(
                self, "Destrancar período",
                f"Destrancar o período de {ano_base} permite alterar distribuição, movimentações e vínculos "
                "de sócio novamente. Confirma?",
            )
            if resposta != QMessageBox.Yes:
                return
            repo.reabrir_periodo(self.conn, empresa_id, ano_base)
        else:
            resposta = QMessageBox.question(
                self, "Trancar período",
                f"Trancar o período de {ano_base} impede qualquer alteração em distribuição, pró-labore, IRRF, "
                "movimentações e entrada/saída/cotas de sócio datadas dentro desse ano, até destrancar de novo. "
                "Confirma?",
            )
            if resposta != QMessageBox.Yes:
                return
            repo.fechar_periodo(self.conn, empresa_id, ano_base)
        self._carregar()

    def _linha_selecionada(self) -> dict | None:
        linhas = self.tabela.selectionModel().selectedRows() if self.tabela.selectionModel() else []
        if not linhas:
            return None
        return self._linhas[linhas[0].row()]

    def _gerenciar_movimentacoes(self) -> None:
        linha = self._linha_selecionada()
        if linha is None:
            return
        dialogo = _DialogoMovimentacoes(
            self.conn, self.empresa.currentData(), linha["socio_id"], linha["socio_nome"], self.ano.value(), self
        )
        dialogo.exec()
        self._carregar()

    # ---------------------------------------------------------- edição em linha --
    def _iniciar_edicao(self) -> None:
        if not self._linhas:
            return
        self._editando = True
        self._widgets_edicao = []

        for row, linha in enumerate(self._linhas):
            socio_ativo = linha["data_saida"] is None

            pct = QDoubleSpinBox()
            pct.setMaximum(100)
            pct.setDecimals(4)
            formatar_numero(pct)
            pct.setValue(linha["percentual_capital"])
            pct.setEnabled(socio_ativo)

            cotas = QDoubleSpinBox()
            cotas.setMaximum(1_000_000_000)
            cotas.setDecimals(0)
            formatar_numero(cotas)
            cotas.setValue(linha["quantidade_cotas"])
            cotas.setEnabled(socio_ativo)

            valor = QDoubleSpinBox()
            valor.setMaximum(1_000_000_000)
            valor.setDecimals(2)
            valor.setPrefix("R$ ")
            formatar_numero(valor)
            valor.setValue(linha["valor_distribuido"])

            pro_labore = QDoubleSpinBox()
            pro_labore.setMaximum(1_000_000_000)
            pro_labore.setDecimals(2)
            pro_labore.setPrefix("R$ ")
            formatar_numero(pro_labore)
            pro_labore.setValue(linha["pro_labore"])

            irrf = QDoubleSpinBox()
            irrf.setMaximum(1_000_000_000)
            irrf.setDecimals(2)
            irrf.setPrefix("R$ ")
            formatar_numero(irrf)
            irrf.setValue(linha["irrf"])

            saida = QDateEdit(calendarPopup=True)
            saida.setDisplayFormat("dd/MM/yyyy")
            saida.setMinimumDate(QDate(1900, 1, 1))
            saida.setSpecialValueText("— (ativo)")
            if linha["data_saida"]:
                saida.setDate(QDate.fromString(linha["data_saida"], "yyyy-MM-dd"))
            else:
                saida.setDate(saida.minimumDate())

            self.tabela.setCellWidget(row, 2, pct)
            self.tabela.setCellWidget(row, 3, cotas)
            self.tabela.setCellWidget(row, 4, valor)
            self.tabela.setCellWidget(row, 5, pro_labore)
            self.tabela.setCellWidget(row, 6, irrf)
            self.tabela.setCellWidget(row, 9, saida)

            self._widgets_edicao.append(
                {"percentual": pct, "cotas": cotas, "valor": valor, "pro_labore": pro_labore, "irrf": irrf, "data_saida": saida}
            )

        for col, largura in ((2, 110), (3, 100), (4, 150), (5, 140), (6, 140), (9, 130)):
            if self.tabela.columnWidth(col) < largura:
                self.tabela.setColumnWidth(col, largura)

        self._atualizar_disponibilidade_botoes()

    def _cancelar_edicao(self) -> None:
        self._carregar()

    @staticmethod
    def _mudou(novo: float, antigo: float, tolerancia: float = 1e-6) -> bool:
        return abs((novo or 0) - (antigo or 0)) > tolerancia

    def _salvar_edicao(self) -> None:
        empresa_id = self.empresa.currentData()
        ano_base = self.ano.value()

        mudancas_distribuicao = []
        mudancas_vinculo = []

        for row, linha in enumerate(self._linhas):
            widgets = self._widgets_edicao[row]

            novo_valor = widgets["valor"].value()
            novo_pro_labore = widgets["pro_labore"].value()
            novo_irrf = widgets["irrf"].value()
            if (
                self._mudou(novo_valor, linha["valor_distribuido"])
                or self._mudou(novo_pro_labore, linha["pro_labore"])
                or self._mudou(novo_irrf, linha["irrf"])
            ):
                mudancas_distribuicao.append((linha, novo_valor, novo_pro_labore, novo_irrf))

            socio_ativo = linha["data_saida"] is None
            novo_pct = widgets["percentual"].value()
            novas_cotas = widgets["cotas"].value()
            pct_ou_cotas_mudou = socio_ativo and (
                self._mudou(novo_pct, linha["percentual_capital"]) or self._mudou(novas_cotas, linha["quantidade_cotas"])
            )

            saida_widget = widgets["data_saida"]
            nova_saida = None if saida_widget.date() == saida_widget.minimumDate() else saida_widget.date().toString("yyyy-MM-dd")
            saida_mudou = nova_saida != linha["data_saida"]

            if pct_ou_cotas_mudou or saida_mudou:
                mudancas_vinculo.append(
                    {
                        "linha": linha,
                        "novo_pct": novo_pct,
                        "novas_cotas": novas_cotas,
                        "nova_saida": nova_saida,
                        "pct_ou_cotas_mudou": pct_ou_cotas_mudou,
                        "saida_mudou": saida_mudou,
                    }
                )

        if not mudancas_distribuicao and not mudancas_vinculo:
            QMessageBox.information(self, "Salvar", "Nenhuma alteração pra salvar.")
            self._carregar()
            return

        data_vigencia = None
        if any(m["pct_ou_cotas_mudou"] for m in mudancas_vinculo):
            dialogo_data = _DialogoDataVigencia(self)
            if dialogo_data.exec() != QDialog.Accepted:
                return
            data_vigencia = dialogo_data.data.date().toString("yyyy-MM-dd")

        try:
            for linha, valor, pro_labore, irrf in mudancas_distribuicao:
                repo.salvar_distribuicao(
                    self.conn, empresa_id, ano_base, linha["socio_id"], valor, pro_labore=pro_labore, irrf=irrf
                )

            for mudanca in mudancas_vinculo:
                linha = mudanca["linha"]
                vinculo_id_atual = linha["vinculo_id"]
                if mudanca["pct_ou_cotas_mudou"]:
                    vinculo = repo.buscar_vinculo(self.conn, vinculo_id_atual)
                    vinculo_id_atual = repo.atualizar_cotas_vinculo(
                        self.conn, vinculo, mudanca["novo_pct"], mudanca["novas_cotas"], data_vigencia,
                        "Atualização de cotas (editado na Distribuição anual)",
                    )
                if mudanca["saida_mudou"]:
                    vinculo = repo.buscar_vinculo(self.conn, vinculo_id_atual)
                    if linha["data_saida"] is None and mudanca["nova_saida"] is not None:
                        repo.encerrar_vinculo_registrando_alteracao(
                            self.conn, vinculo, mudanca["nova_saida"], "Saída de sócio (editado na Distribuição anual)"
                        )
                    else:
                        vinculo.data_saida = mudanca["nova_saida"]
                        repo.salvar_vinculo(self.conn, vinculo)
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao salvar", str(exc))
            self._carregar()
            return

        total_mudancas = len(mudancas_distribuicao) + len(mudancas_vinculo)
        self._carregar()
        QMessageBox.information(self, "Salvo", f"{total_mudancas} linha(s) com alteração salvas com sucesso.")

    def _exportar_modelo(self) -> None:
        empresa_id = self.empresa.currentData()
        if empresa_id is None:
            return
        ano_base = self.ano.value()
        sugestao = f"distribuicao_{self.empresa.currentText()}_{ano_base}.xlsx".replace(" ", "_")
        caminho, _ = QFileDialog.getSaveFileName(
            self, "Exportar modelo de distribuição", sugestao, "Planilha Excel (*.xlsx)"
        )
        if not caminho:
            return
        if not caminho.lower().endswith(".xlsx"):
            caminho += ".xlsx"

        linhas = [
            {
                "cpf": linha["socio_cpf"],
                "nome": linha["socio_nome"],
                "valor_distribuido": linha["valor_distribuido"],
                "pro_labore": linha["pro_labore"],
                "irrf": linha["irrf"],
            }
            for linha in self._linhas
            if linha["data_saida"] is None
        ]
        if not linhas:
            QMessageBox.information(self, "Exportar modelo", "Não há sócios ativos nesta empresa/ano pra exportar.")
            return
        try:
            exportar_modelo_distribuicao(Path(caminho), linhas)
        except OSError as exc:
            QMessageBox.warning(self, "Erro ao exportar", str(exc))
            return
        QMessageBox.information(
            self, "Modelo exportado", f"Modelo salvo com {len(linhas)} sócio(s) em:\n{caminho}"
        )

    def _importar_planilha(self) -> None:
        empresa_id = self.empresa.currentData()
        if empresa_id is None:
            return
        if repo.periodo_esta_fechado(self.conn, empresa_id, self.ano.value()):
            QMessageBox.warning(
                self, "Importar planilha",
                f"O período de {self.ano.value()} desta empresa está trancado. Destranque-o antes de importar.",
            )
            return
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Importar planilha de distribuição", "", "Planilhas (*.xlsx *.csv)"
        )
        if not caminho:
            return
        try:
            linhas_importadas = importar_distribuicao(Path(caminho))
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao importar", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(self, "Erro ao abrir arquivo", str(exc))
            return

        if not linhas_importadas:
            QMessageBox.information(self, "Importar planilha", "A planilha não tem nenhuma linha com dados.")
            return

        ano_base = self.ano.value()
        resolvidos, pendencias = self._associar_linhas(linhas_importadas, ano_base)

        if pendencias:
            dialogo = _DialogoRevisaoImportacao(self.conn, pendencias, self)
            if dialogo.exec() == QDialog.Accepted:
                resolvidos.extend(dialogo.resolvidos())

        if not resolvidos:
            QMessageBox.information(self, "Importar planilha", "Nenhuma linha foi aplicada.")
            return

        try:
            for linha, socio_id in resolvidos:
                repo.salvar_distribuicao(
                    self.conn, empresa_id, ano_base, socio_id, linha["valor_distribuido"],
                    pro_labore=linha.get("pro_labore") or 0.0, irrf=linha.get("irrf") or 0.0,
                )
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao importar", str(exc))
            self._carregar()
            return

        self._carregar()

        nao_aplicadas = len(linhas_importadas) - len(resolvidos)
        resumo = f"{len(resolvidos)} sócio(s) atualizado(s) com sucesso."
        if nao_aplicadas > 0:
            resumo += f"\n{nao_aplicadas} linha(s) não foram aplicadas."
        QMessageBox.information(self, "Importação concluída", resumo)

    def _associar_linhas(self, linhas_importadas: list[dict], ano_base: int) -> tuple[list[tuple[dict, int]], list[dict]]:
        """Reconhece cada linha da planilha contra os sócios já cadastrados
        (por CPF, com nome como retaguarda) pra nunca criar duplicata — o que
        não bate com segurança vira pendência pra revisão humana."""
        todos_socios = repo.listar_socios(self.conn)
        por_cpf = {repo.normalizar_documento(s.cpf): s for s in todos_socios if s.cpf and s.cpf.strip()}
        por_nome: dict[str, list] = {}
        for s in todos_socios:
            por_nome.setdefault(s.nome.strip().lower(), []).append(s)

        ativos_nesta_empresa = {l["socio_id"] for l in self._linhas if l["data_saida"] is None}

        resolvidos: list[tuple[dict, int]] = []
        pendencias: list[dict] = []

        for linha in linhas_importadas:
            socio = por_cpf.get(repo.normalizar_documento(linha["cpf"])) if linha["cpf"] else None
            motivo = None

            if socio is None and linha["nome"]:
                candidatos = por_nome.get(linha["nome"].strip().lower(), [])
                if len(candidatos) == 1:
                    socio = candidatos[0]
                elif len(candidatos) > 1:
                    motivo = f'Encontrei {len(candidatos)} sócios cadastrados com o nome "{linha["nome"]}" — escolha o correto.'

            if socio is not None and socio.id not in ativos_nesta_empresa:
                pendencias.append(
                    {
                        **linha,
                        "sugestao": socio,
                        "aviso": f"Sócio já cadastrado, mas sem vínculo ativo com esta empresa em {ano_base}. Confirme antes de aplicar.",
                    }
                )
                continue

            if socio is not None:
                resolvidos.append((linha, socio.id))
                continue

            if motivo is None:
                motivo = "Nenhum sócio cadastrado bate com esse CPF/nome — cadastre um novo ou vincule manualmente."
            pendencias.append({**linha, "sugestao": None, "aviso": motivo})

        return resolvidos, pendencias
