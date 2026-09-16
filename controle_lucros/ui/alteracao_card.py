"""Um card do carrossel: snapshot de uma alteração contratual, com o
formulário de edição, o quadro de sócios movimentados e o controle de
trancamento (fechamento) do período."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

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
from ..leitor_xls import XlsIlegivel
from ..models import TIPOS_PESSOA_LABEL, AlteracaoContratual, Empresa, Socio, VinculoSocietario
from ..relatorio_socios import EmpresaDoRelatorio, RelatorioInvalido, linhas_para_importacao, resumo as resumo_do_relatorio
from .common import (
    configurar_campo_cnpj,
    configurar_campo_cpf,
    documento_valido_ou_vazio,
    formatar_numero,
    formatar_valor_br,
    TabelaLista,
)
from .destino_alteracao import DialogoDestinoAlteracao
from .importacao_cadastro_view import DialogoRevisaoCadastro, ler_relatorio_arquivo
from .leitor_pdf import PdfIlegivel
from .ocupado import Progresso, ocupado
from .selo import Selo
from .theme import SEAL_RED


_FILTRO_RELATORIO_SOCIOS = (
    "Relatório de sócios — PDF ou Excel (*.pdf *.xls *.xlsx *.csv);;"
    "Relatório em PDF (*.pdf);;"
    "Planilha do Excel (*.xls *.xlsx);;"
    "Texto separado por ponto e vírgula (*.csv);;"
    "Todos os arquivos (*)"
)


def _empresa_do_relatorio_bate(empresa: Empresa, relatorio_empresa: EmpresaDoRelatorio) -> bool:
    """Mesmo critério de casamento de repo.preparar_importacao_cadastro,
    aplicado a uma empresa já conhecida em vez de buscá-la pelo cadastro
    inteiro — aqui já se sabe qual é a empresa (a da alteração aberta), só
    falta achar as linhas do relatório que são dela."""
    if relatorio_empresa.numero and empresa.numero_chamada and relatorio_empresa.numero.strip() == empresa.numero_chamada.strip():
        return True
    if relatorio_empresa.cnpj and empresa.cnpj and repo.normalizar_documento(relatorio_empresa.cnpj) == repo.normalizar_documento(empresa.cnpj):
        return True
    return relatorio_empresa.nome.strip().lower() == empresa.nome.strip().lower()


def _hairline() -> QFrame:
    linha = QFrame()
    linha.setProperty("role", "hairline")
    return linha


class _DialogoIncluirSocio(QDialog):
    """Escolhe o sócio numa tabela com busca, não numa lista suspensa: com
    algumas dezenas de sócios cadastrados, a lista virava um rolo comprido em
    que era preciso procurar de olho, sem dar pra filtrar nem conferir o CPF
    antes de escolher.

    Traz também o cadastro de um sócio novo aqui dentro — quem está montando
    uma alteração contratual quase sempre está incluindo alguém que ainda não
    existe no sistema, e antes era preciso sair pra aba Sócios e voltar."""

    COLUNAS = ["Nome", "CPF/CNPJ", "Tipo"]

    def __init__(self, conn, empresa_id: int, ja_vinculados: set[int], parent=None):
        super().__init__(parent)
        self.conn = conn
        self._ja_vinculados = ja_vinculados
        self._socios: list = []
        self.setWindowTitle("Incluir sócio nesta alteração")
        self.setMinimumSize(560, 460)

        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Buscar por nome ou CPF/CNPJ…")
        self.busca.setClearButtonEnabled(True)
        self.busca.textChanged.connect(self._filtrar)

        self.tabela = TabelaLista(0, len(self.COLUNAS), coluna_flexivel=0)
        self.tabela.setHorizontalHeaderLabels(self.COLUNAS)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela.horizontalHeader().setStretchLastSection(True)
        self.tabela.itemSelectionChanged.connect(self._ao_selecionar)
        # Duplo clique escolhe e fecha: é o gesto que se espera de uma lista
        # de busca, e evita a viagem até o botão pra quem já achou.
        self.tabela.itemDoubleClicked.connect(self._confirmar_se_valido)

        self.vazio = QLabel()
        self.vazio.setProperty("role", "subtitulo")
        self.vazio.setWordWrap(True)
        self.vazio.hide()

        self.btn_novo_socio = QPushButton("Cadastrar sócio novo…")
        self.btn_novo_socio.clicked.connect(self._cadastrar_socio)

        self.percentual = QDoubleSpinBox()
        self.percentual.setMaximum(100)
        self.percentual.setDecimals(4)
        formatar_numero(self.percentual)

        self.cotas = QDoubleSpinBox()
        self.cotas.setMaximum(1_000_000_000)
        formatar_numero(self.cotas)

        form = QFormLayout()
        form.addRow("% do capital", self.percentual)
        form.addRow("Qtde de cotas", self.cotas)

        self.botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.botoes.button(QDialogButtonBox.Ok).setText("Incluir")
        self.botoes.accepted.connect(self.accept)
        self.botoes.rejected.connect(self.reject)

        linha_busca = QHBoxLayout()
        linha_busca.addWidget(self.busca, 1)
        linha_busca.addWidget(self.btn_novo_socio)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addLayout(linha_busca)
        layout.addWidget(self.tabela, 1)
        layout.addWidget(self.vazio)
        layout.addWidget(_hairline())
        layout.addLayout(form)
        layout.addWidget(self.botoes)

        self._recarregar()
        self.busca.setFocus()

    # ------------------------------------------------------------ lista --
    def _disponiveis(self) -> list:
        """Sócios que ainda não estão nesta empresa nesta data — incluir de
        novo quem já está criaria vínculo duplicado."""
        return [s for s in repo.listar_socios(self.conn) if s.id not in self._ja_vinculados]

    def _recarregar(self, selecionar_id: int | None = None) -> None:
        self._todos = self._disponiveis()
        self._filtrar()
        if selecionar_id is not None:
            self._selecionar(selecionar_id)

    def _filtrar(self, *_args) -> None:
        termo = self.busca.text().strip().lower()
        alvo = repo.normalizar_documento(termo)
        self._socios = [
            s
            for s in self._todos
            if not termo
            or termo in s.nome.lower()
            or (alvo and alvo in repo.normalizar_documento(s.cpf))
        ]

        self.tabela.setRowCount(len(self._socios))
        for row, s in enumerate(self._socios):
            valores = [s.nome, s.cpf or "—", TIPOS_PESSOA_LABEL.get(s.tipo_pessoa, s.tipo_pessoa)]
            for col, valor in enumerate(valores):
                self.tabela.setItem(row, col, QTableWidgetItem(valor))
        self.tabela.ajustar_colunas()

        if self._socios:
            self.vazio.hide()
        else:
            self.vazio.setText(
                "Nenhum sócio encontrado com esse termo. Confira a busca ou cadastre um novo."
                if termo
                else "Todos os sócios cadastrados já estão nesta empresa. "
                "Cadastre um novo pra incluir aqui."
            )
            self.vazio.show()
        self._ao_selecionar()

    def _selecionar(self, socio_id: int) -> None:
        for row, s in enumerate(self._socios):
            if s.id == socio_id:
                self.tabela.selectRow(row)
                return

    def _socio_selecionado(self):
        linhas = self.tabela.selectionModel().selectedRows() if self.tabela.selectionModel() else []
        return self._socios[linhas[0].row()] if linhas else None

    def _ao_selecionar(self) -> None:
        # Sem sócio escolhido não há o que incluir; travar o botão evita o
        # diálogo aceitar e o chamador receber None.
        self.botoes.button(QDialogButtonBox.Ok).setEnabled(self._socio_selecionado() is not None)

    def _confirmar_se_valido(self, *_args) -> None:
        if self._socio_selecionado() is not None:
            self.accept()

    def _cadastrar_socio(self) -> None:
        dialogo = _DialogoNovoSocio(self)
        if dialogo.exec() != QDialog.Accepted:
            return
        try:
            novo_id = repo.salvar_socio(self.conn, dialogo.socio())
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao cadastrar sócio", str(exc))
            return
        # Limpa a busca pra o recém-cadastrado não ficar escondido por um
        # filtro que não casa com ele.
        self.busca.clear()
        self._recarregar(selecionar_id=novo_id)

    def dados(self) -> tuple[int | None, float, float]:
        socio = self._socio_selecionado()
        return (socio.id if socio else None), self.percentual.value(), self.cotas.value()


class _DialogoNovoSocio(QDialog):
    """Cadastro rápido de sócio, sem sair da alteração contratual."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Cadastrar sócio")
        self.setMinimumWidth(380)

        self.nome = QLineEdit()
        self.nome.setPlaceholderText("Nome completo ou razão social")

        self.tipo_pessoa = QComboBox()
        for tipo, label in TIPOS_PESSOA_LABEL.items():
            self.tipo_pessoa.addItem(label, tipo)
        self.tipo_pessoa.currentIndexChanged.connect(self._ajustar_mascara)

        self.documento = QLineEdit()
        self.documento.setProperty("role", "mono")
        self._rotulo_documento = QLabel("CPF")

        form = QFormLayout()
        form.addRow("Nome", self.nome)
        form.addRow("Tipo", self.tipo_pessoa)
        form.addRow(self._rotulo_documento, self.documento)
        self._ajustar_mascara()

        self.erro = QLabel()
        self.erro.setStyleSheet(f"color: {SEAL_RED()}; font-size: 11px;")
        self.erro.setWordWrap(True)
        self.erro.hide()

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.button(QDialogButtonBox.Ok).setText("Cadastrar")
        botoes.accepted.connect(self._validar)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.erro)
        layout.addWidget(botoes)
        self.nome.setFocus()

    def _ajustar_mascara(self, *_args) -> None:
        tipo = self.tipo_pessoa.currentData() or "fisica"
        self.documento.clear()
        if tipo == "juridica":
            configurar_campo_cnpj(self.documento)
            self._rotulo_documento.setText("CNPJ")
        else:
            configurar_campo_cpf(self.documento)
            self._rotulo_documento.setText("CPF")

    def _validar(self) -> None:
        if not self.nome.text().strip():
            self.erro.setText("Informe o nome do sócio.")
            self.erro.show()
            return
        self.accept()

    def socio(self) -> Socio:
        return Socio(
            id=None,
            nome=self.nome.text().strip(),
            cpf=documento_valido_ou_vazio(self.documento),
            tipo_pessoa=self.tipo_pessoa.currentData(),
        )


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

        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.clicked.connect(self._cancelar)

        self.btn_excluir = QPushButton("Excluir alteração")
        self.btn_excluir.setProperty("role", "perigo")
        self.btn_excluir.clicked.connect(self._excluir)

        linha_salvar = QHBoxLayout()
        linha_salvar.addWidget(self.btn_salvar, 1)
        linha_salvar.addWidget(self.btn_cancelar)
        linha_salvar.addWidget(self.btn_excluir)

        secao_socios = QLabel("Sócios após esta alteração")
        secao_socios.setProperty("role", "secao")

        self.tabela_socios = TabelaLista(0, 4, coluna_flexivel=0)
        self.tabela_socios.setHorizontalHeaderLabels(["Sócio", "% capital", "Cotas", "Situação"])
        self.tabela_socios.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela_socios.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela_socios.setMinimumHeight(140)

        self.btn_incluir_socio = QPushButton("Incluir sócio")
        self.btn_incluir_socio.clicked.connect(self._incluir_socio)
        self.btn_saida_socio = QPushButton("Registrar saída de sócio")
        self.btn_saida_socio.clicked.connect(self._registrar_saida)
        self.btn_importar_relatorio = QPushButton("Importar relatório de sócios…")
        self.btn_importar_relatorio.setToolTip(
            "Lê o relatório \"Cadastro de Sócios\" de outro sistema contábil — em PDF ou "
            "planilha — e lança a movimentação desta empresa direto nesta alteração "
            "contratual. Linhas de outras empresas no mesmo arquivo são ignoradas."
        )
        self.btn_importar_relatorio.clicked.connect(self._importar_relatorio_socios)

        botoes_socios = QHBoxLayout()
        botoes_socios.addWidget(self.btn_incluir_socio)
        botoes_socios.addWidget(self.btn_saida_socio)
        botoes_socios.addWidget(self.btn_importar_relatorio)
        botoes_socios.addStretch()

        miolo = QVBoxLayout(conteudo)
        miolo.setContentsMargins(20, 16, 20, 20)
        miolo.setSpacing(12)
        miolo.addLayout(cabecalho)
        miolo.addWidget(_hairline())
        miolo.addLayout(form)
        miolo.addLayout(linha_salvar)
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
        # Diferente dos dois acima, importar vale no rascunho: a tela de
        # destino cadastra a alteração nova na hora, e era justamente aí que
        # o botão morto travava quem clicou em "Nova alteração contratual"
        # pra importar o quadro societário dentro dela.
        self.btn_importar_relatorio.setEnabled(editavel)

        self.btn_cancelar.setVisible(self.alteracao is None)
        self.btn_excluir.setVisible(self.alteracao is not None)
        self.btn_excluir.setEnabled(editavel and self.alteracao is not None)

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
        self.tabela_socios.ajustar_colunas()

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

    def _cancelar(self) -> None:
        """Só existe no rascunho — descarta o card sem gravar nada no banco
        e volta pra última alteração de verdade (ou o carrossel vazio, se
        essa empresa ainda não tiver nenhuma)."""
        if self.alteracao is not None:
            return
        self._ao_mudar(self)

    def _excluir(self) -> None:
        if self.alteracao is None:
            return
        resposta = QMessageBox.question(
            self,
            "Excluir alteração contratual",
            f"Excluir a alteração contratual Nº {self.alteracao.numero}? Isso não pode ser desfeito.",
        )
        if resposta != QMessageBox.Yes:
            return
        try:
            repo.excluir_alteracao(self.conn, self.alteracao.id)
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao excluir", str(exc))
            return
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
        # Sem sócio disponível o diálogo abre assim mesmo: ele diz o que
        # houve e deixa cadastrar um novo ali dentro, que é justamente o caso
        # em que antes a tela só avisava e fechava.
        dialogo = _DialogoIncluirSocio(self.conn, self.empresa_id, ativos_ids, self)
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

    def _importar_relatorio_socios(self) -> None:
        """Lê o relatório "Cadastro de Sócios" de outro sistema contábil e
        lança a movimentação direto nesta alteração contratual — a mesma
        leitura usada na tela de Importação de cadastro, mas já amarrada à
        empresa e à alteração abertas aqui, sem perguntar qual é.

        O relatório pode trazer várias empresas no mesmo arquivo; só as
        linhas da empresa desta alteração entram, o resto é ignorado (com
        aviso de quantas linhas ficaram de fora).

        Vale também no rascunho (alteração ainda não salva): a tela de
        destino cadastra a alteração nova antes de gravar a movimentação."""
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Importar relatório de sócios", "", _FILTRO_RELATORIO_SOCIOS
        )
        if not caminho:
            return
        try:
            with ocupado(self, "Importar relatório", f"Lendo {Path(caminho).name}…"):
                leitura = ler_relatorio_arquivo(Path(caminho))
        except (PdfIlegivel, XlsIlegivel, RelatorioInvalido) as exc:
            QMessageBox.warning(self, "Não consegui ler o relatório", str(exc))
            return
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao ler o relatório", str(exc))
            return
        except OSError as exc:
            QMessageBox.warning(self, "Erro ao abrir arquivo", str(exc))
            return

        empresa = repo.buscar_empresa(self.conn, self.empresa_id)
        empresas_da_alteracao = [e for e in leitura.empresas if _empresa_do_relatorio_bate(empresa, e)]
        ignoradas_outra_empresa = len(leitura.empresas) - len(empresas_da_alteracao)

        # Nome e nº da empresa no relatório do outro sistema raramente são os
        # mesmos do cadastro daqui ("91 - ENDOGASTRO CLINICA MEDICA LTDA" x
        # "Endogastro"). Quando o arquivo tem uma empresa só, não faz sentido
        # recusar: a pessoa escolheu a empresa ao abrir este card, e o arquivo
        # não tem ambiguidade nenhuma — basta perguntar se é ela mesma.
        if not empresas_da_alteracao and len(leitura.empresas) == 1:
            unica = leitura.empresas[0]
            identificacao = f"{unica.numero} - {unica.nome}" if unica.numero else unica.nome
            usar_assim_mesmo = QMessageBox.question(
                self,
                "Importar relatório de sócios",
                f'O relatório é de "{identificacao}", que não bate com o cadastro desta '
                f'alteração ("{empresa.nome}", nº {empresa.numero_chamada or "sem número"}).\n\n'
                "Lançar o quadro societário deste relatório nesta empresa mesmo assim?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if usar_assim_mesmo != QMessageBox.Yes:
                return
            empresas_da_alteracao = [unica]
            ignoradas_outra_empresa = 0

        if not empresas_da_alteracao:
            QMessageBox.information(
                self,
                "Importar relatório de sócios",
                f'Entre as {len(leitura.empresas)} empresas do relatório, nenhuma bate com '
                f'"{empresa.nome}". Confira se é o arquivo certo.',
            )
            return

        linhas_importadas = linhas_para_importacao(empresas_da_alteracao)
        # Força o casamento nesta empresa (já conhecida) em vez de deixar
        # repo.preparar_importacao_cadastro casar pelo nome como veio escrito
        # no relatório — que pode divergir em maiúscula/pontuação do cadastro
        # e criar uma empresa duplicada em vez de reconhecer esta.
        for linha in linhas_importadas:
            linha["numero_chamada"] = empresa.numero_chamada
            linha["cnpj"] = empresa.cnpj
            linha["empresa_nome"] = empresa.nome
        if not linhas_importadas:
            QMessageBox.information(
                self,
                "Importar relatório de sócios",
                f'Li a empresa "{empresa.nome}" no relatório, mas ela não tem nenhum sócio listado.',
            )
            return

        aviso_outras = (
            f"\n\n{ignoradas_outra_empresa} outra(s) empresa(s) do arquivo foram ignoradas — esta "
            "importação entra só no quadro societário desta empresa, dentro da alteração selecionada."
            if ignoradas_outra_empresa
            else ""
        )
        alerta = ""
        if leitura.ignoradas:
            exemplos = "\n".join(f"   {linha[:90]}" for linha in leitura.ignoradas[:3])
            if len(leitura.ignoradas) > 3:
                exemplos += f"\n   (e mais {len(leitura.ignoradas) - 3})"
            alerta = (
                f"\n\n⚠ {len(leitura.ignoradas)} linha(s) com cara de sócio não foram "
                f"reconhecidas e ficarão de fora:\n{exemplos}"
            )

        # A tela de destino é a confirmação: ela diz o que foi lido e pergunta
        # em qual alteração isso entra — nova ou já aberta. Cancelar ali não
        # grava nada.
        destino = DialogoDestinoAlteracao(
            self.conn,
            self.empresa_id,
            f'Li {resumo_do_relatorio(empresas_da_alteracao)} para "{empresa.nome}".'
            f"{aviso_outras}{alerta}",
            data_sugerida=empresas_da_alteracao[0].data_quadro,
            alteracao_atual_id=self.alteracao.id if self.alteracao else None,
            parent=self,
        )
        if destino.exec() != QDialog.Accepted:
            return
        try:
            alteracao_id = destino.resolver()
        except ValueError as exc:
            QMessageBox.warning(self, "Não foi possível abrir a alteração", str(exc))
            return
        if alteracao_id is None:
            return

        resultado = repo.preparar_importacao_cadastro(self.conn, linhas_importadas)
        prontas = list(resultado["prontas"])
        pendencias = resultado["pendencias"]
        conflitos = resultado["conflitos"]

        if conflitos:
            detalhe = "\n\n".join(
                f'Linha de "{c["empresa_nome"]}" / "{c["socio_nome"]}":\n{c["aviso"]}' for c in conflitos[:5]
            )
            if len(conflitos) > 5:
                detalhe += f"\n\n(e mais {len(conflitos) - 5} linha(s) com o mesmo tipo de problema)"
            QMessageBox.warning(
                self,
                "Linhas com dados contraditórios",
                f"{len(conflitos)} linha(s) não serão importadas:\n\n{detalhe}",
            )

        if pendencias:
            dialogo = DialogoRevisaoCadastro(self.conn, pendencias, self)
            if dialogo.exec() == QDialog.Accepted:
                prontas.extend(dialogo.resolvidos())

        if not prontas:
            QMessageBox.information(
                self,
                "Importar relatório de sócios",
                "Nenhuma linha foi aplicada."
                + (" Corrija os dados contraditórios apontados acima." if conflitos else ""),
            )
            return

        try:
            with Progresso(self, "Importar relatório de sócios", len(prontas), "Gravando o que foi importado…") as barra:
                aplicado = repo.aplicar_importacao_cadastro(
                    self.conn,
                    prontas,
                    progresso=lambda feitas, total: barra.passo(
                        feitas, total, f"Gravando linha {feitas} de {total}…"
                    ),
                    alteracao_id=alteracao_id,
                )
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao importar", str(exc))
            return

        # O card pode ter entrado aqui como rascunho, ou apontando pra outra
        # alteração que não a escolhida no destino: passa a ser a que recebeu
        # a importação, pra o carrossel recarregar já em cima dela.
        self.alteracao = repo.buscar_alteracao(self.conn, alteracao_id)

        alteracao_nova = (
            f"\n\nLançado na alteração contratual Nº {self.alteracao.numero}."
            if self.alteracao
            else ""
        )
        resumo_txt = (
            f"{aplicado['vinculos_criados']} vínculo(s) criado(s) · "
            f"{aplicado['vinculos_ja_existentes']} já existiam (ignorados) · "
            f"{aplicado['vinculos_encerrados']} vínculo(s) com saída registrada."
            f"{alteracao_nova}"
        )
        QMessageBox.information(self, "Importação concluída", resumo_txt)
        self._preencher()
        self._ao_mudar(self)
