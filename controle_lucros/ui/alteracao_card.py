"""Um card do carrossel: snapshot de uma alteração contratual, com o
formulário de edição, o quadro de sócios movimentados e o controle de
trancamento (fechamento) do período."""
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
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import repositories as repo
from ..models import AlteracaoContratual, VinculoSocietario
from .common import formatar_numero, formatar_valor_br
from .selo import Selo


def _hairline() -> QFrame:
    linha = QFrame()
    linha.setProperty("role", "hairline")
    return linha


class _DialogoIncluirSocio(QDialog):
    def __init__(self, conn, empresa_id: int, ja_vinculados: set[int], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Incluir sócio nesta alteração")

        self.socio = QComboBox()
        for s in repo.listar_socios(conn):
            if s.id not in ja_vinculados:
                self.socio.addItem(s.nome, s.id)

        self.percentual = QDoubleSpinBox()
        self.percentual.setMaximum(100)
        self.percentual.setDecimals(4)
        formatar_numero(self.percentual)

        self.cotas = QDoubleSpinBox()
        self.cotas.setMaximum(1_000_000_000)
        formatar_numero(self.cotas)

        form = QFormLayout()
        form.addRow("Sócio", self.socio)
        form.addRow("% do capital", self.percentual)
        form.addRow("Qtde de cotas", self.cotas)

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(botoes)

    def dados(self) -> tuple[int | None, float, float]:
        return self.socio.currentData(), self.percentual.value(), self.cotas.value()


class _DialogoSaidaSocio(QDialog):
    def __init__(self, vinculos_ativos: list[VinculoSocietario], nomes: dict[int, str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar saída de sócio")

        self.vinculo = QComboBox()
        for v in vinculos_ativos:
            self.vinculo.addItem(nomes.get(v.socio_id, "?"), v.id)

        form = QFormLayout()
        form.addRow("Sócio", self.vinculo)

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(botoes)

    def vinculo_id(self) -> int | None:
        return self.vinculo.currentData()


class AlteracaoCard(QWidget):
    def __init__(self, conn, empresa_id: int, alteracao: AlteracaoContratual | None, ao_mudar, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.empresa_id = empresa_id
        self.alteracao = alteracao
        self._ao_mudar = ao_mudar

        conteudo = QWidget()
        conteudo.setProperty("role", "card")

        self.selo = Selo()

        self.titulo = QLabel()
        self.titulo.setProperty("role", "titulo")
        self.subtitulo = QLabel("Sem alterações contratuais registradas ainda.")
        self.subtitulo.setProperty("role", "subtitulo")

        cabecalho_texto = QVBoxLayout()
        cabecalho_texto.addWidget(self.titulo)
        cabecalho_texto.addWidget(self.subtitulo)

        self.btn_trancar = QPushButton("Fechar período")
        self.btn_trancar.setProperty("role", "perigo")
        self.btn_trancar.clicked.connect(self._alternar_trancamento)

        cabecalho = QHBoxLayout()
        cabecalho.addWidget(self.selo)
        cabecalho.addLayout(cabecalho_texto, 1)
        cabecalho.addWidget(self.btn_trancar)

        self.data = QDateEdit(calendarPopup=True)
        self.data.setDisplayFormat("dd/MM/yyyy")
        self.data.setDate(dt.date.today())

        self.nome_empresa = QLineEdit()
        self.capital = QDoubleSpinBox()
        self.capital.setMaximum(1_000_000_000)
        self.capital.setDecimals(2)
        self.capital.setPrefix("R$ ")
        formatar_numero(self.capital)
        self.cotas = QDoubleSpinBox()
        self.cotas.setMaximum(1_000_000_000)
        self.cotas.setDecimals(0)
        formatar_numero(self.cotas)
        self.descricao = QTextEdit()
        self.descricao.setPlaceholderText("Motivo / teor da alteração contratual…")
        self.descricao.setFixedHeight(60)

        form = QFormLayout()
        form.addRow("Data", self.data)
        form.addRow("Nome da empresa", self.nome_empresa)
        form.addRow("Capital social", self.capital)
        form.addRow("Quantidade de cotas", self.cotas)
        form.addRow("Descrição", self.descricao)

        self.btn_salvar = QPushButton("Salvar alteração")
        self.btn_salvar.setProperty("role", "primario")
        self.btn_salvar.clicked.connect(self._salvar)

        secao_socios = QLabel("Sócios após esta alteração")
        secao_socios.setProperty("role", "secao")

        self.tabela_socios = QTableWidget(0, 4)
        self.tabela_socios.setHorizontalHeaderLabels(["Sócio", "% capital", "Cotas", "Situação"])
        self.tabela_socios.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela_socios.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela_socios.verticalHeader().setVisible(False)
        self.tabela_socios.setAlternatingRowColors(True)
        self.tabela_socios.setMinimumHeight(140)

        self.btn_incluir_socio = QPushButton("Incluir sócio")
        self.btn_incluir_socio.clicked.connect(self._incluir_socio)
        self.btn_saida_socio = QPushButton("Registrar saída de sócio")
        self.btn_saida_socio.clicked.connect(self._registrar_saida)

        botoes_socios = QHBoxLayout()
        botoes_socios.addWidget(self.btn_incluir_socio)
        botoes_socios.addWidget(self.btn_saida_socio)
        botoes_socios.addStretch()

        miolo = QVBoxLayout(conteudo)
        miolo.setContentsMargins(20, 16, 20, 20)
        miolo.setSpacing(12)
        miolo.addLayout(cabecalho)
        miolo.addWidget(_hairline())
        miolo.addLayout(form)
        miolo.addWidget(self.btn_salvar)
        miolo.addWidget(_hairline())
        miolo.addWidget(secao_socios)
        miolo.addWidget(self.tabela_socios)
        miolo.addLayout(botoes_socios)
        miolo.addStretch()

        rolagem = QScrollArea()
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.NoFrame)
        rolagem.setWidget(conteudo)

        layout_externo = QVBoxLayout(self)
        layout_externo.setContentsMargins(4, 4, 4, 4)
        layout_externo.addWidget(rolagem)

        self._preencher()

    # -------------------------------------------------------------- estado --
    def _preencher(self) -> None:
        if self.alteracao is None:
            numero = repo.proximo_numero_alteracao(self.conn, self.empresa_id)
            estado = repo.estado_atual_empresa(self.conn, self.empresa_id)
            self.titulo.setText(f"Nova alteração contratual — Nº {numero}")
            self.subtitulo.setText("Rascunho: ainda não salva.")
            self.selo.definir_estado(numero, fechada=False)
            self.data.setDate(dt.date.today())
            self.nome_empresa.setText(estado["nome"])
            self.capital.setValue(estado["capital_social"])
            self.cotas.setValue(estado["quantidade_cotas"])
            self.descricao.clear()
            self.btn_trancar.setVisible(False)
        else:
            a = self.alteracao
            self.titulo.setText(f"Alteração contratual Nº {a.numero}")
            self.subtitulo.setText(
                "Período fechado — destranque para editar." if a.fechada else "Período aberto para edição."
            )
            self.selo.definir_estado(a.numero, fechada=a.fechada)
            self.data.setDate(dt.datetime.strptime(a.data, "%Y-%m-%d").date())
            self.nome_empresa.setText(a.nome_empresa)
            self.capital.setValue(a.capital_social)
            self.cotas.setValue(a.quantidade_cotas)
            self.descricao.setPlainText(a.descricao or "")
            self.btn_trancar.setVisible(True)
            self.btn_trancar.setText("Destrancar período" if a.fechada else "Fechar período")

        editavel = self.alteracao is None or not self.alteracao.fechada
        for campo in (self.data, self.nome_empresa, self.capital, self.cotas, self.descricao):
            campo.setEnabled(editavel)
        self.btn_salvar.setEnabled(editavel)
        self.btn_incluir_socio.setEnabled(editavel and self.alteracao is not None)
        self.btn_saida_socio.setEnabled(editavel and self.alteracao is not None)

        self._preencher_tabela_socios()

    def _preencher_tabela_socios(self) -> None:
        vinculos = repo.listar_vinculos_empresa(self.conn, self.empresa_id)
        nomes = {s.id: s.nome for s in repo.listar_socios(self.conn)}
        data_corte = self.alteracao.data if self.alteracao else dt.date.today().isoformat()

        ativos = [
            v
            for v in vinculos
            if v.data_entrada <= data_corte and (v.data_saida is None or v.data_saida > data_corte)
        ]

        self.tabela_socios.setRowCount(len(ativos))
        for row, v in enumerate(ativos):
            situacao = "—"
            if self.alteracao is not None:
                if v.alteracao_entrada_id == self.alteracao.id:
                    situacao = "Entrou nesta alteração"
                elif v.alteracao_saida_id == self.alteracao.id:
                    situacao = "Saiu nesta alteração"
            self.tabela_socios.setItem(row, 0, QTableWidgetItem(nomes.get(v.socio_id, "?")))
            self.tabela_socios.setItem(row, 1, QTableWidgetItem(formatar_valor_br(v.percentual_capital, 4)))
            self.tabela_socios.setItem(row, 2, QTableWidgetItem(formatar_valor_br(v.quantidade_cotas or 0, 0)))
            self.tabela_socios.setItem(row, 3, QTableWidgetItem(situacao))
        self.tabela_socios.resizeColumnsToContents()

    # -------------------------------------------------------------- ações --
    def _salvar(self) -> None:
        nome = self.nome_empresa.text().strip()
        if not nome:
            QMessageBox.warning(self, "Erro ao salvar", "Informe o nome da empresa.")
            return
        registro = AlteracaoContratual(
            id=self.alteracao.id if self.alteracao else None,
            empresa_id=self.empresa_id,
            numero=self.alteracao.numero if self.alteracao else repo.proximo_numero_alteracao(self.conn, self.empresa_id),
            data=self.data.date().toString("yyyy-MM-dd"),
            nome_empresa=nome,
            capital_social=self.capital.value(),
            quantidade_cotas=self.cotas.value(),
            descricao=self.descricao.toPlainText().strip(),
            fechada=self.alteracao.fechada if self.alteracao else False,
        )
        try:
            novo_id = repo.salvar_alteracao(self.conn, registro)
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao salvar", str(exc))
            return
        registro.id = novo_id
        self.alteracao = registro
        self._preencher()
        self._ao_mudar(self)

    def _alternar_trancamento(self) -> None:
        if self.alteracao is None:
            return
        if self.alteracao.fechada:
            resposta = QMessageBox.question(
                self,
                "Destrancar período",
                "Destrancar esta alteração contratual permite editá-la novamente. Confirma?",
            )
            if resposta != QMessageBox.Yes:
                return
            repo.reabrir_alteracao(self.conn, self.alteracao.id)
            self.alteracao.fechada = False
        else:
            resposta = QMessageBox.question(
                self,
                "Fechar período",
                "Fechar esta alteração contratual trava a edição para preservar a integridade dos dados. "
                "Só será possível editar novamente destrancando-a. Confirma?",
            )
            if resposta != QMessageBox.Yes:
                return
            repo.fechar_alteracao(self.conn, self.alteracao.id)
            self.alteracao.fechada = True
        self._preencher()
        self._ao_mudar(self)

    def _incluir_socio(self) -> None:
        if self.alteracao is None:
            return
        vinculos = repo.listar_vinculos_empresa(self.conn, self.empresa_id)
        ativos_ids = {
            v.socio_id
            for v in vinculos
            if v.data_entrada <= self.alteracao.data and (v.data_saida is None or v.data_saida > self.alteracao.data)
        }
        dialogo = _DialogoIncluirSocio(self.conn, self.empresa_id, ativos_ids, self)
        if dialogo.socio.count() == 0:
            QMessageBox.information(self, "Incluir sócio", "Todos os sócios cadastrados já estão vinculados.")
            return
        if dialogo.exec() != QDialog.Accepted:
            return
        socio_id, percentual, cotas = dialogo.dados()
        novo = VinculoSocietario(
            id=None,
            empresa_id=self.empresa_id,
            socio_id=socio_id,
            percentual_capital=percentual,
            quantidade_cotas=cotas,
            data_entrada=self.alteracao.data,
            data_saida=None,
            alteracao_entrada_id=self.alteracao.id,
        )
        try:
            repo.salvar_vinculo(self.conn, novo)
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao incluir sócio", str(exc))
            return
        self._preencher_tabela_socios()
        self._ao_mudar(self)

    def _registrar_saida(self) -> None:
        if self.alteracao is None:
            return
        vinculos = repo.listar_vinculos_empresa(self.conn, self.empresa_id)
        ativos = [
            v
            for v in vinculos
            if v.data_entrada <= self.alteracao.data and (v.data_saida is None or v.data_saida > self.alteracao.data)
        ]
        if not ativos:
            QMessageBox.information(self, "Registrar saída", "Não há sócios ativos para retirar.")
            return
        nomes = {s.id: s.nome for s in repo.listar_socios(self.conn)}
        dialogo = _DialogoSaidaSocio(ativos, nomes, self)
        if dialogo.exec() != QDialog.Accepted:
            return
        try:
            repo.encerrar_vinculo(self.conn, dialogo.vinculo_id(), self.alteracao.data, self.alteracao.id)
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao registrar saída", str(exc))
            return
        self._preencher_tabela_socios()
        self._ao_mudar(self)
