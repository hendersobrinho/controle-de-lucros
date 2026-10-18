"""A ficha de uma alteração contratual (só leitura, em blocos), a janela de
cadastro/edição dela — com o número livre, pra começar pelo número real do
contrato — e as janelas de movimentação de sócios dentro da alteração."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import Qt
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
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
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
    campo_cotas,
    configurar_campo_moeda,
    formatar_data_br,
    formatar_percentual,
    formatar_valor_br,
    formatar_valor_cota,
    TabelaLista,
)
from .cartao_participacao import FaixaParticipacao
from . import formulario as form_ui
from .destino_alteracao import DialogoDestinoAlteracao
from .empresas_tab import _dica, _limpar, _rotulo, _secao
from .importacao_cadastro_view import DialogoRevisaoCadastro, ler_relatorio_arquivo
from .leitor_pdf import PdfIlegivel
from .ocupado import Progresso, ocupado
from .selo import Selo
from .socios_tab import _CamposParticipacao
from .theme import BRASS_DARK, SAIU_FG, SEAL_RED


_FILTRO_RELATORIO_SOCIOS = (
    "Relatório de sócios — PDF ou Excel (*.pdf *.xls *.xlsx *.csv);;"
    "Relatório em PDF (*.pdf);;"
    "Planilha do Excel (*.xls *.xlsx);;"
    "Texto separado por ponto e vírgula (*.csv);;"
    "Todos os arquivos (*)"
)


def _documentos_do_relatorio(linhas: list[dict]) -> set[str]:
    return {repo.normalizar_documento(l["socio_cpf"]) for l in linhas if l.get("socio_cpf")}


def _resumo_das_baixas(encerrados: list[str]) -> str:
    """Quem a opção "o relatório é o quadro completo" encerrou — nominalmente,
    porque é a parte da importação que tira sócio da sociedade."""
    if not encerrados:
        return ""
    lista = ", ".join(encerrados[:6])
    if len(encerrados) > 6:
        lista += f" (e mais {len(encerrados) - 6})"
    return f"\n\n{len(encerrados)} saída(s) por ausência no relatório: {lista}."


def _aviso_fora_do_relatorio(conn, empresa_id: int, linhas: list[dict], data_corte: str) -> str:
    """O relatório é o quadro societário vigente: sócio que continua ativo
    aqui e não aparece nele é saída que ninguém registrou, e é o que faz a
    soma das participações passar de 100%.

    Roda depois de tudo gravado, inclusive das baixas: é o retrato do que
    ficou, não do que entrou. Usa a mesma definição de ausente da opção de
    dar baixa (repo.vinculos_ativos_fora_da_lista), pra o aviso nunca
    discordar da caixa que a pessoa acabou de marcar (ou não)."""
    ausentes = repo.vinculos_ativos_fora_da_lista(
        conn, empresa_id, _documentos_do_relatorio(linhas), data_corte
    )
    ativos = [
        v
        for v in repo.listar_vinculos_empresa(conn, empresa_id)
        if v.data_entrada <= data_corte and (v.data_saida is None or v.data_saida > data_corte)
    ]
    soma = round(sum(v.percentual_capital or 0.0 for v in ativos), 4)

    if not ausentes and abs(soma - 100.0) < 0.01:
        return ""

    partes = []
    if ausentes:
        lista = ", ".join(socio.nome for _v, socio in ausentes[:5])
        if len(ausentes) > 5:
            lista += f" (e mais {len(ausentes) - 5})"
        partes.append(
            f"{len(ausentes)} sócio(s) continuam ativos aqui e não aparecem no relatório: {lista}. "
            "Se eles saíram, marque a opção de dar baixa na próxima importação ou registre a "
            "saída pela aba de Sócios."
        )
    if abs(soma - 100.0) >= 0.01:
        partes.append(f"A soma das participações ficou em {soma}%.")
    return "\n\n⚠ " + " ".join(partes)


def _aviso_nao_atualizadas(aplicado: dict) -> str:
    """Participação que ficou como estava porque a alteração escolhida é
    anterior à entrada do sócio. Dizer é obrigatório: o relatório mostra um
    número e o sistema ficou com outro."""
    quantidade = aplicado.get("participacoes_nao_atualizadas") or 0
    if not quantidade:
        return ""
    return (
        f"\n\n⚠ {quantidade} participação(ões) não foram atualizadas: a data desta alteração é "
        "anterior à entrada desses sócios. Registre a mudança numa alteração com data posterior."
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

    def __init__(self, conn, empresa_id: int, ja_vinculados: set[int], parent=None,
                 alteracao: AlteracaoContratual | None = None):
        super().__init__(parent)
        self.conn = conn
        self._ja_vinculados = ja_vinculados
        self._socios: list = []
        self.setWindowTitle(
            f"Incluir sócio na alteração Nº {alteracao.numero}" if alteracao else "Incluir sócio nesta alteração"
        )
        self.setMinimumSize(760, 820)

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
        self.tabela.setMinimumHeight(170)
        # Duplo clique escolhe e fecha: é o gesto que se espera de uma lista
        # de busca, e evita a viagem até o botão pra quem já achou.
        self.tabela.itemDoubleClicked.connect(self._confirmar_se_valido)

        self.vazio = QLabel()
        self.vazio.setProperty("role", "subtitulo")
        self.vazio.setWordWrap(True)
        self.vazio.hide()

        self.btn_novo_socio = QPushButton("Cadastrar sócio novo…")
        self.btn_novo_socio.clicked.connect(self._cadastrar_socio)

        # Data de entrada e capital entram aqui também, e não só na aba
        # Sócios: quem começa pelo contrato de hoje lança sócios que entraram
        # anos antes desta alteração, e o capital de cada um é o que o
        # relatório do outro sistema não traz.
        self.data_entrada = QDateEdit(calendarPopup=True)
        self.data_entrada.setDisplayFormat("dd/MM/yyyy")
        self.data_entrada.setDate(
            dt.datetime.strptime(alteracao.data, "%Y-%m-%d").date() if alteracao else dt.date.today()
        )
        dica_data = form_ui.dica("Já vem com a data da alteração. Mude se ele entrou antes.")
        self.data_entrada.setMaximumWidth(180)

        self.campos = _CamposNaAlteracao(conn, empresa_id, alteracao)
        self.cotas = self.campos.cotas
        self.percentual = self.campos.percentual
        self.capital = self.campos.capital


        self.botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.botoes.button(QDialogButtonBox.Ok).setText("Incluir sócio")
        self.botoes.button(QDialogButtonBox.Ok).setProperty("role", "primario")
        self.botoes.button(QDialogButtonBox.Cancel).setText("Cancelar")
        self.botoes.accepted.connect(self.accept)
        self.botoes.rejected.connect(self.reject)

        linha_busca = QHBoxLayout()
        linha_busca.addWidget(self.busca, 1)
        linha_busca.addWidget(self.btn_novo_socio)

        bloco_quem, col = form_ui.secao("Quem entra", "1")
        col.addLayout(linha_busca)
        col.addWidget(self.tabela, 1)
        col.addWidget(self.vazio)

        bloco_participacao, col = form_ui.secao("Participação", "2")
        col.addWidget(form_ui.campo(
            "Data de entrada", self.data_entrada, dica_data,
        ))
        col.addWidget(self.campos.montar_visual())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 18, 22, 16)
        layout.setSpacing(12)
        layout.addLayout(form_ui.cabecalho(self.windowTitle()))
        layout.addWidget(bloco_quem, 1)
        layout.addWidget(bloco_participacao)
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

    def dados(self) -> tuple[int | None, float, float, str, float | None]:
        """(sócio, % do capital, cotas, data de entrada, capital do sócio)."""
        socio = self._socio_selecionado()
        return (
            socio.id if socio else None,
            self.percentual.value(),
            self.cotas.value(),
            self.data_entrada.date().toString("yyyy-MM-dd"),
            self.capital.value() or None,
        )


class _CamposNaAlteracao(_CamposParticipacao):
    """Os campos de participação da aba Sócios, mas tomando como total de
    cotas o desta alteração, e não o de hoje: o % de quem entra é sobre o
    capital que o contrato tinha naquela data."""

    def __init__(self, conn, empresa_id: int, alteracao: AlteracaoContratual | None):
        self._alteracao = alteracao
        super().__init__(conn, lambda: empresa_id)

    def _estado(self) -> dict | None:
        if self._alteracao is None:
            return super()._estado()
        a = self._alteracao
        return {"nome": a.nome_empresa, "capital_social": a.capital_social, "quantidade_cotas": a.quantidade_cotas}

    def _atualizar_referencia(self) -> None:
        super()._atualizar_referencia()
        estado = self._estado()
        if self._alteracao is not None and estado and estado["quantidade_cotas"]:
            self.total_cotas.setText(
                f"de {formatar_valor_br(estado['quantidade_cotas'], 0)} cotas da empresa nesta alteração"
            )


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


def confirmar_e_excluir(parent, conn, alteracao: AlteracaoContratual) -> bool:
    """Excluir desfaz o que a alteração registrou (ver repo.excluir_alteracao):
    a pergunta diz quem entra e sai disso, pra ninguém ser pego de surpresa,
    e já vem em "Não". Devolve True se excluiu."""
    afetados = repo.resumo_exclusao_alteracao(conn, alteracao.id)
    texto = f"Excluir a alteração contratual Nº {alteracao.numero}?"
    if afetados["entradas"]:
        texto += (
            "\n\nEntraram por ela — o vínculo é apagado:\n"
            + "\n".join(f"• {nome}" for nome in afetados["entradas"])
        )
    if afetados["saidas"]:
        texto += (
            "\n\nSaíram por ela — voltam a ficar ativos:\n"
            + "\n".join(f"• {nome}" for nome in afetados["saidas"])
        )
    texto += "\n\nIsso não pode ser desfeito. Confirma?"
    resposta = QMessageBox.warning(
        parent, "Excluir alteração contratual", texto, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
    )
    if resposta != QMessageBox.Yes:
        return False
    try:
        repo.excluir_alteracao(conn, alteracao.id)
    except ValueError as exc:
        QMessageBox.warning(parent, "Erro ao excluir", str(exc))
        return False
    return True


class DialogoAlteracao(QDialog):
    """Cadastrar uma alteração contratual nova ou mudar uma existente.

    O número é livre: quem começa a usar o sistema hoje não lança o passado,
    e a primeira alteração registrada pode ser a Nº 7 do contrato de
    verdade. O sistema só sugere o próximo e avisa se o número já existe."""

    EXCLUIDA = 2

    def __init__(self, conn, empresa_id: int, alteracao: AlteracaoContratual | None = None, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.empresa_id = empresa_id
        self.alteracao = alteracao
        self.alteracao_id: int | None = alteracao.id if alteracao else None
        self.setWindowTitle("Editar alteração contratual" if alteracao else "Nova alteração contratual")
        self.setMinimumWidth(540)

        existentes = repo.listar_alteracoes(conn, empresa_id)
        estado = repo.estado_atual_empresa(conn, empresa_id)
        sugerido = repo.proximo_numero_alteracao(conn, empresa_id)

        self.numero = QSpinBox()
        self.numero.setRange(1, 9999)
        self.numero.setPrefix("Nº ")
        self.numero.setValue(alteracao.numero if alteracao else sugerido)
        self.numero.setMinimumWidth(130)
        self.numero.valueChanged.connect(self._conferir_numero)
        if alteracao is not None:
            explicacao = "O número que está no contrato. Pode ser corrigido aqui, desde que não repita outro desta empresa."
        elif not existentes:
            explicacao = (
                "Use o número que está no contrato. Se a empresa já está na 7ª alteração, informe 7 — "
                "não é preciso cadastrar as anteriores."
            )
        else:
            explicacao = (
                f"Sugerido o próximo depois da Nº {sugerido - 1}. Mude se o contrato tiver outro número."
            )
        self.dica_numero = form_ui.dica(explicacao)
        self.aviso_numero = QLabel()
        self.aviso_numero.setProperty("role", "alerta")
        self.aviso_numero.setWordWrap(True)
        self.aviso_numero.hide()

        self.data = QDateEdit(calendarPopup=True)
        self.data.setDisplayFormat("dd/MM/yyyy")
        self.data.setDate(
            dt.datetime.strptime(alteracao.data, "%Y-%m-%d").date() if alteracao else dt.date.today()
        )

        self.nome_empresa = QLineEdit(alteracao.nome_empresa if alteracao else estado["nome"])
        self.nome_empresa.setPlaceholderText("Razão social como ficou nesta alteração")

        self.capital = configurar_campo_moeda(QDoubleSpinBox())
        self.capital.setValue(alteracao.capital_social if alteracao else estado["capital_social"])
        self.cotas = campo_cotas()
        self.cotas.setValue(alteracao.quantidade_cotas if alteracao else estado["quantidade_cotas"])
        self.conta_cota = form_ui.dica()
        self.capital.valueChanged.connect(self._mostrar_valor_cota)
        self.cotas.valueChanged.connect(self._mostrar_valor_cota)

        self.descricao = QTextEdit()
        self.descricao.setPlaceholderText("O que esta alteração mudou: entrada de sócio, aumento de capital…")
        self.descricao.setFixedHeight(72)
        if alteracao and alteracao.descricao:
            self.descricao.setPlainText(alteracao.descricao)

        bloco_contrato, col = form_ui.secao("O contrato", "1")
        col.addLayout(form_ui.linha(
            form_ui.campo("Nº da alteração", self.numero),
            form_ui.campo("Data", self.data),
            form_ui.campo("Razão social", self.nome_empresa),
            esticar=(1, 1, 3),
        ))
        col.addWidget(self.dica_numero)
        col.addWidget(self.aviso_numero)

        bloco_capital, col = form_ui.secao("Capital e cotas", "2")
        col.addLayout(form_ui.linha(
            form_ui.campo("Capital social", self.capital),
            form_ui.campo("Quantidade de cotas", self.cotas),
        ))
        col.addWidget(self.conta_cota)

        bloco_descricao, col = form_ui.secao("O que mudou", "3")
        col.addWidget(self.descricao)

        self.btn_salvar = QPushButton("Salvar alteração" if alteracao else "Cadastrar alteração")
        self.btn_salvar.setProperty("role", "primario")
        self.btn_salvar.setDefault(True)
        self.btn_salvar.clicked.connect(self._salvar)
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.clicked.connect(self.reject)
        self.btn_excluir = QPushButton("Excluir alteração")
        self.btn_excluir.setProperty("role", "perigo")
        self.btn_excluir.clicked.connect(self._excluir)
        self.btn_excluir.setVisible(alteracao is not None)

        form_ui.montar_janela(
            self,
            form_ui.cabecalho(
                f"Alteração contratual Nº {alteracao.numero}" if alteracao else "Nova alteração contratual",
                estado["nome"],
            ),
            [bloco_contrato, bloco_capital, bloco_descricao],
            form_ui.botoes_rodape(self.btn_excluir, direita=(btn_cancelar, self.btn_salvar)),
            largura=680,
        )

        self._mostrar_valor_cota()
        self._conferir_numero()
        self.numero.setFocus()
        self.numero.selectAll()

    def _mostrar_valor_cota(self, *_args) -> None:
        capital, cotas = self.capital.value(), self.cotas.value()
        if capital and cotas:
            self.conta_cota.setText(f"Valor da cota: {formatar_valor_cota(capital / cotas)} (capital ÷ cotas)")
        else:
            self.conta_cota.setText("Informe capital e cotas para ver o valor de cada cota.")

    def _conferir_numero(self, *_args) -> bool:
        livre = not repo.numero_alteracao_em_uso(self.conn, self.empresa_id, self.numero.value(), self.alteracao_id)
        self.aviso_numero.setText(
            "" if livre else f"Esta empresa já tem a alteração Nº {self.numero.value()}. Escolha outro número."
        )
        self.aviso_numero.setVisible(not livre)
        self.btn_salvar.setEnabled(livre)
        return livre

    def alteracao_editada(self) -> AlteracaoContratual:
        return AlteracaoContratual(
            id=self.alteracao_id,
            empresa_id=self.empresa_id,
            numero=self.numero.value(),
            data=self.data.date().toString("yyyy-MM-dd"),
            nome_empresa=self.nome_empresa.text().strip(),
            capital_social=self.capital.value(),
            quantidade_cotas=self.cotas.value(),
            descricao=self.descricao.toPlainText().strip(),
            fechada=self.alteracao.fechada if self.alteracao else False,
        )

    def _salvar(self) -> None:
        registro = self.alteracao_editada()
        if not registro.nome_empresa:
            QMessageBox.warning(self, "Falta a razão social", "Informe a razão social da empresa nesta alteração.")
            return
        if not self._conferir_numero():
            return
        try:
            self.alteracao_id = repo.salvar_alteracao(self.conn, registro)
        except ValueError as exc:
            QMessageBox.warning(self, "Não foi possível salvar", str(exc))
            return
        self.accept()

    def _excluir(self) -> None:
        if self.alteracao is not None and confirmar_e_excluir(self, self.conn, self.alteracao):
            self.done(self.EXCLUIDA)


class _LinhaSocio(QWidget):
    """Um sócio no quadro depois da alteração: nome e documento, a faixa da
    fatia, o percentual, as cotas e, se for o caso, a etiqueta dizendo que
    ele entrou ou teve a participação refeita nesta alteração."""

    ETIQUETAS = {"entrou": ("Entrou nesta alteração", "ativo"), "mudou": ("Participação refeita", "mudou")}

    def __init__(self, socio: dict, parent=None):
        super().__init__(parent)
        nome = QLabel(socio["nome"])
        nome.setProperty("role", "valorCampo")
        nome.setWordWrap(True)
        identificacao = QVBoxLayout()
        identificacao.setSpacing(0)
        identificacao.addWidget(nome)
        identificacao.addWidget(_dica(socio["documento"] or "sem documento cadastrado"))

        linha_nome = QHBoxLayout()
        linha_nome.setSpacing(8)
        linha_nome.addLayout(identificacao, 1)
        if socio["movimento"] in self.ETIQUETAS:
            texto, tom = self.ETIQUETAS[socio["movimento"]]
            self.etiqueta = QLabel(texto)
            self.etiqueta.setProperty("role", "etiquetaSituacao")
            self.etiqueta.setProperty("tom", tom)
            linha_nome.addWidget(self.etiqueta, 0, Qt.AlignVCenter)

        percentual = QLabel(formatar_percentual(socio["percentual"]))
        percentual.setProperty("role", "valorCampo")
        percentual.setMinimumWidth(78)
        percentual.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        cotas = _dica(
            f"{formatar_valor_br(socio['cotas'], 0)} cotas" if socio["cotas"] else "cotas não informadas"
        )
        cotas.setWordWrap(False)
        cotas.setMinimumWidth(120)
        cotas.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 4, 0, 4)
        linha.setSpacing(14)
        linha.addLayout(linha_nome, 4)
        linha.addWidget(FaixaParticipacao(socio["percentual"] or 0, True), 2)
        linha.addWidget(percentual)
        linha.addWidget(cotas)


class AlteracaoCard(QWidget):
    """A ficha de uma alteração contratual: só mostra. Mudar os dados abre
    DialogoAlteracao; incluir sócio, registrar saída e importar o relatório
    lançam a movimentação dentro desta alteração.

    Sem alteração (a empresa ainda não tem nenhuma), mostra o convite pra
    cadastrar a primeira — com o número real do contrato — ou importar o
    relatório de sócios, que cadastra a alteração no caminho."""

    def __init__(self, conn, empresa_id: int, alteracao: AlteracaoContratual | None, ao_mudar, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.empresa_id = empresa_id
        self.alteracao = alteracao
        self._ao_mudar = ao_mudar

        # A ficha é um documento só, lido de cima pra baixo: qual alteração
        # e em que estado; os números do contrato; o que aconteceu com os
        # sócios; como a sociedade ficou. Separado por fios, e não em quatro
        # quadros soltos — em blocos separados o olho não sabia por onde
        # começar.
        self.documento = QFrame()
        self.documento.setProperty("role", "card")
        miolo = QVBoxLayout(self.documento)
        miolo.setContentsMargins(24, 20, 24, 20)
        miolo.setSpacing(14)

        # ---- cabeçalho: qual alteração, em que estado, e o que dá pra fazer
        self.selo = Selo()
        self.titulo = QLabel()
        self.titulo.setProperty("role", "titulo")
        self.situacao = QLabel()
        self.situacao.setProperty("role", "etiquetaSituacao")
        linha_titulo = QHBoxLayout()
        linha_titulo.setSpacing(10)
        linha_titulo.addWidget(self.titulo)
        linha_titulo.addWidget(self.situacao, 0, Qt.AlignVCenter)
        linha_titulo.addStretch()
        self.subtitulo = QLabel()
        self.subtitulo.setProperty("role", "subtitulo")
        self.subtitulo.setWordWrap(True)
        self.descricao = QLabel()
        self.descricao.setProperty("role", "descricaoAlteracao")
        self.descricao.setWordWrap(True)
        self.descricao.setTextInteractionFlags(Qt.TextSelectableByMouse)
        texto = QVBoxLayout()
        texto.setSpacing(3)
        texto.addLayout(linha_titulo)
        texto.addWidget(self.subtitulo)
        texto.addWidget(self.descricao)

        self.btn_editar = QPushButton("Editar alteração")
        self.btn_editar.clicked.connect(self._editar)
        self.btn_trancar = QPushButton("Fechar período")
        self.btn_trancar.clicked.connect(self._alternar_trancamento)
        acoes = QVBoxLayout()
        acoes.setSpacing(6)
        acoes.addWidget(self.btn_editar)
        acoes.addWidget(self.btn_trancar)
        acoes.addStretch()

        topo = QHBoxLayout()
        topo.setSpacing(16)
        topo.addWidget(self.selo, 0, Qt.AlignTop)
        topo.addLayout(texto, 1)
        topo.addLayout(acoes)
        miolo.addLayout(topo)

        # ---- os números do contrato
        miolo.addWidget(_hairline())
        self._numeros = QGridLayout()
        self._numeros.setHorizontalSpacing(28)
        self._numeros.setVerticalSpacing(2)
        miolo.addLayout(self._numeros)

        # ---- o que aconteceu com os sócios
        miolo.addWidget(_hairline())
        miolo.addWidget(_secao("O que aconteceu com os sócios"))
        self._movimentos = QVBoxLayout()
        self._movimentos.setSpacing(6)
        miolo.addLayout(self._movimentos)
        self.btn_incluir_socio = QPushButton("+ Incluir sócio")
        self.btn_incluir_socio.setToolTip("Lança a entrada de um sócio nesta alteração, com a data de entrada e o capital dele.")
        self.btn_incluir_socio.clicked.connect(self._incluir_socio)
        self.btn_saida_socio = QPushButton("Registrar saída")
        self.btn_saida_socio.setToolTip("Encerra a participação de um sócio na data desta alteração.")
        self.btn_saida_socio.clicked.connect(self._registrar_saida)
        self.btn_importar_relatorio = QPushButton("Importar relatório de sócios…")
        self.btn_importar_relatorio.setToolTip(
            "Lê o relatório \"Cadastro de Sócios\" de outro sistema contábil — em PDF ou "
            "planilha — e lança a movimentação desta empresa direto nesta alteração "
            "contratual. Linhas de outras empresas no mesmo arquivo são ignoradas."
        )
        self.btn_importar_relatorio.clicked.connect(self._importar_relatorio_socios)
        self._botoes_movimento = QHBoxLayout()
        self._botoes_movimento.setSpacing(8)
        self._botoes_movimento.addWidget(self.btn_incluir_socio)
        self._botoes_movimento.addWidget(self.btn_saida_socio)
        self._botoes_movimento.addWidget(self.btn_importar_relatorio)
        self._botoes_movimento.addStretch()
        miolo.addLayout(self._botoes_movimento)

        # ---- como a sociedade ficou
        miolo.addWidget(_hairline())
        cabecalho_quadro = QHBoxLayout()
        cabecalho_quadro.addWidget(_secao("Como ficou a sociedade"))
        cabecalho_quadro.addStretch()
        self.resumo_quadro = _dica()
        self.resumo_quadro.setWordWrap(False)
        cabecalho_quadro.addWidget(self.resumo_quadro, 0, Qt.AlignBottom)
        miolo.addLayout(cabecalho_quadro)
        self._quadro = QVBoxLayout()
        self._quadro.setSpacing(0)
        miolo.addLayout(self._quadro)
        self.aviso_quadro = _dica()
        self.aviso_quadro.setStyleSheet(f"color: {SAIU_FG()};")
        miolo.addWidget(self.aviso_quadro)

        corpo = QWidget()
        coluna_corpo = QVBoxLayout(corpo)
        coluna_corpo.setContentsMargins(0, 0, 8, 12)
        coluna_corpo.addWidget(self.documento)
        coluna_corpo.addStretch()
        self.rolagem = QScrollArea()
        self.rolagem.setProperty("role", "listaCartoes")
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setFrameShape(QFrame.NoFrame)
        self.rolagem.setWidget(corpo)

        # ---- empresa sem nenhuma alteração ainda
        vazio_titulo = QLabel("Nenhuma alteração contratual registrada")
        vazio_titulo.setProperty("role", "vazioTitulo")
        vazio_titulo.setAlignment(Qt.AlignCenter)
        vazio_texto = QLabel(
            "Comece pela alteração em vigor hoje, com o número que está no contrato — se a empresa "
            "já está na 7ª alteração, cadastre a Nº 7. As anteriores não precisam ser lançadas.\n\n"
            "Também dá pra importar o relatório de sócios: ele cadastra a alteração no caminho."
        )
        vazio_texto.setProperty("role", "vazioTexto")
        vazio_texto.setAlignment(Qt.AlignCenter)
        vazio_texto.setWordWrap(True)
        vazio_texto.setMaximumWidth(560)
        self.btn_primeira = QPushButton("Cadastrar alteração")
        self.btn_primeira.setProperty("role", "primario")
        self.btn_primeira.clicked.connect(self._nova)
        botoes_vazio = QHBoxLayout()
        botoes_vazio.addStretch()
        botoes_vazio.addWidget(self.btn_primeira)
        self._lugar_importar_vazio = botoes_vazio
        botoes_vazio.addStretch()
        self.painel_vazio = QWidget()
        coluna_vazio = QVBoxLayout(self.painel_vazio)
        coluna_vazio.setSpacing(10)
        coluna_vazio.addStretch(2)
        coluna_vazio.addWidget(vazio_titulo)
        coluna_vazio.addWidget(vazio_texto, 0, Qt.AlignHCenter)
        coluna_vazio.addSpacing(6)
        coluna_vazio.addLayout(botoes_vazio)
        coluna_vazio.addStretch(3)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        layout.addWidget(self.rolagem, 1)
        layout.addWidget(self.painel_vazio, 1)

        self._preencher()

    # -------------------------------------------------------------- estado --
    def _preencher(self) -> None:
        for layout in (self._numeros, self._movimentos, self._quadro):
            _limpar(layout)
        ficha = repo.ficha_alteracao(self.conn, self.alteracao.id) if self.alteracao else None
        if self.alteracao is not None and ficha is None:
            self.alteracao = None
        tem = ficha is not None
        self.rolagem.setVisible(tem)
        self.painel_vazio.setVisible(not tem)

        if not tem:
            # No vazio, importar é um dos dois caminhos pra primeira
            # alteração: a tela de destino cadastra a alteração nova.
            self._lugar_importar_vazio.insertWidget(2, self.btn_importar_relatorio)
            self.btn_importar_relatorio.setEnabled(True)
            self.btn_incluir_socio.setEnabled(False)
            self.btn_saida_socio.setEnabled(False)
            return
        if self.btn_importar_relatorio.parent() is not self.documento:
            self._botoes_movimento.insertWidget(2, self.btn_importar_relatorio)

        a = ficha["alteracao"]
        self.alteracao = a
        self.selo.definir_estado(a.numero, fechada=a.fechada)
        self.titulo.setText(f"Alteração contratual Nº {a.numero}")
        self.situacao.setText("Fechada" if a.fechada else "Aberta")
        self.situacao.setProperty("tom", "saiu" if a.fechada else "ativo")
        self.situacao.style().unpolish(self.situacao)
        self.situacao.style().polish(self.situacao)
        self.subtitulo.setText(f"Registrada em {formatar_data_br(a.data)} · {a.nome_empresa}")
        self.descricao.setText(f"“{a.descricao}”" if a.descricao else "Sem descrição — dá pra escrever em Editar alteração.")
        self.descricao.setProperty("vazia", not a.descricao)
        self.descricao.style().unpolish(self.descricao)
        self.descricao.style().polish(self.descricao)

        editavel = not a.fechada
        self.btn_editar.setEnabled(editavel)
        self.btn_editar.setToolTip(
            "Nº, data, razão social, capital, cotas e descrição. Também dá pra excluir por lá."
            if editavel else "Alteração fechada: destranque o período para editar."
        )
        self.btn_trancar.setText("Destrancar período" if a.fechada else "Fechar período")
        self.btn_trancar.setToolTip(
            "Volta a permitir mudanças nesta alteração." if a.fechada
            else "Trava esta alteração para ninguém mudar o que já foi conferido."
        )
        for botao in (self.btn_incluir_socio, self.btn_saida_socio, self.btn_importar_relatorio):
            botao.setEnabled(editavel)

        self._mostrar_numeros(ficha)
        self._mostrar_movimentos(ficha)
        self._mostrar_quadro(ficha)

    def _mostrar_numeros(self, ficha: dict) -> None:
        a = ficha["alteracao"]

        def mudanca(atual: float, antes: float, formatar) -> str:
            if ficha["anterior"] is None and not antes:
                return ""
            if round(atual or 0, 2) == round(antes or 0, 2):
                return "igual à anterior"
            return f"era {formatar(antes)}"

        reais = lambda v: f"R$ {formatar_valor_br(v or 0)}"  # noqa: E731
        cotas = lambda v: formatar_valor_br(v or 0, 0)  # noqa: E731
        numeros = (
            ("Capital social", reais(a.capital_social) if a.capital_social else "Não informado",
             mudanca(a.capital_social, ficha["capital_antes"], reais)),
            ("Cotas", cotas(a.quantidade_cotas) if a.quantidade_cotas else "Não informado",
             mudanca(a.quantidade_cotas, ficha["cotas_antes"], cotas)),
            ("Valor de cada cota", formatar_valor_cota(ficha["valor_cota"]) if ficha["valor_cota"] else "Não informado",
             "capital ÷ cotas" if ficha["valor_cota"] else ""),
        )
        for coluna, (rotulo, valor, nota) in enumerate(numeros):
            self._numeros.addWidget(_rotulo(rotulo), 0, coluna)
            numero = QLabel(valor)
            numero.setProperty("role", "numeroFicha" if valor != "Não informado" else "subtitulo")
            self._numeros.addWidget(numero, 1, coluna)
            if nota:
                dica = _dica(nota)
                if nota.startswith("era"):
                    dica.setStyleSheet(f"color: {BRASS_DARK()}; font-weight: 600;")
                self._numeros.addWidget(dica, 2, coluna)
            self._numeros.setColumnStretch(coluna, 1)

    def _mostrar_movimentos(self, ficha: dict) -> None:
        linhas = (
            [(nome, "Entrou", "ativo") for nome in ficha["entradas"]]
            + [(s["nome"], "Saiu", "saiu") for s in ficha["saidas"]]
            + [(nome, "Participação refeita", "mudou") for nome in ficha["mudancas"]]
        )
        if not linhas:
            self._movimentos.addWidget(_dica(
                "Nenhum sócio entrou ou saiu por esta alteração ainda. Inclua quem entrou, registre "
                "quem saiu, ou importe o relatório de sócios do outro sistema."
            ))
            return
        for nome, texto, tom in linhas:
            # Layout, e não QWidget: widget solto herda o fundo da página e
            # vira uma faixa colorida dentro do cartão branco.
            arranjo = QHBoxLayout()
            arranjo.setSpacing(12)
            etiqueta = QLabel(texto)
            etiqueta.setProperty("role", "etiquetaSituacao")
            etiqueta.setProperty("tom", tom)
            etiqueta.setFixedWidth(150)
            etiqueta.setAlignment(Qt.AlignCenter)
            arranjo.addWidget(etiqueta)
            rotulo_nome = QLabel(nome)
            rotulo_nome.setProperty("role", "valorCampo")
            arranjo.addWidget(rotulo_nome, 1)
            self._movimentos.addLayout(arranjo)

    def _mostrar_quadro(self, ficha: dict) -> None:
        quantidade = len(ficha["quadro"])
        soma = ficha["soma_percentual"]
        if not quantidade:
            self.resumo_quadro.setText("")
            self._quadro.addWidget(_dica("Ninguém na sociedade na data desta alteração."))
            self.aviso_quadro.hide()
            return
        self.resumo_quadro.setText(
            f"{quantidade} sócio{'' if quantidade == 1 else 's'} · somam {formatar_percentual(soma)}"
        )
        for i, socio in enumerate(ficha["quadro"]):
            if i:
                self._quadro.addWidget(_hairline())
            self._quadro.addWidget(_LinhaSocio(socio))
        diferente = abs(soma - 100) > 0.01
        self.aviso_quadro.setVisible(diferente)
        if diferente:
            self.aviso_quadro.setText(
                f"⚠ As participações somam {formatar_percentual(soma)}, não 100% — falta lançar "
                "entrada ou saída de alguém, ou algum percentual está desatualizado."
            )

    # -------------------------------------------------------------- ações --
    def _nova(self) -> None:
        dialogo = DialogoAlteracao(self.conn, self.empresa_id, None, self)
        if dialogo.exec() != QDialog.Accepted:
            return
        self.alteracao = repo.buscar_alteracao(self.conn, dialogo.alteracao_id)
        self._preencher()
        self._ao_mudar(self)

    def _editar(self) -> None:
        if self.alteracao is None:
            return
        dialogo = DialogoAlteracao(self.conn, self.empresa_id, self.alteracao, self)
        resultado = dialogo.exec()
        if resultado == QDialog.Rejected:
            return
        self.alteracao = None if resultado == DialogoAlteracao.EXCLUIDA else repo.buscar_alteracao(self.conn, self.alteracao.id)
        self._preencher()
        self._ao_mudar(self)

    def _excluir(self) -> None:
        if self.alteracao is None:
            return
        if confirmar_e_excluir(self, self.conn, self.alteracao):
            self.alteracao = None
            self._ao_mudar(self)

    def _alternar_trancamento(self) -> None:
        if self.alteracao is None:
            return
        if self.alteracao.fechada:
            resposta = QMessageBox.question(
                self,
                "Destrancar período",
                "Destrancar esta alteração contratual permite editá-la novamente. Confirma?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if resposta != QMessageBox.Yes:
                return
            repo.reabrir_alteracao(self.conn, self.alteracao.id)
        else:
            resposta = QMessageBox.question(
                self,
                "Fechar período",
                "Fechar esta alteração contratual trava a edição para preservar a integridade dos dados. "
                "Só será possível editar novamente destrancando-a. Confirma?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if resposta != QMessageBox.Yes:
                return
            repo.fechar_alteracao(self.conn, self.alteracao.id)
        self._preencher()
        self._ao_mudar(self)

    def _incluir_socio(self) -> None:
        if self.alteracao is None:
            return
        vinculos = repo.listar_vinculos_empresa(self.conn, self.empresa_id)
        ativos_ids = {
            v.socio_id
            for v in vinculos
            if v.data_saida is None or v.data_saida > self.alteracao.data
        }
        # Sem sócio disponível o diálogo abre assim mesmo: ele diz o que
        # houve e deixa cadastrar um novo ali dentro, que é justamente o caso
        # em que antes a tela só avisava e fechava.
        dialogo = _DialogoIncluirSocio(self.conn, self.empresa_id, ativos_ids, self, alteracao=self.alteracao)
        if dialogo.exec() != QDialog.Accepted:
            return
        socio_id, percentual, cotas, data_entrada, capital = dialogo.dados()
        novo = VinculoSocietario(
            id=None,
            empresa_id=self.empresa_id,
            socio_id=socio_id,
            percentual_capital=percentual,
            quantidade_cotas=cotas,
            data_entrada=data_entrada,
            data_saida=None,
            alteracao_entrada_id=self.alteracao.id,
            valor_capital=capital,
        )
        try:
            repo.salvar_vinculo(self.conn, novo)
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao incluir sócio", str(exc))
            return
        dialogo.campos.gravar_valor_da_cota()
        self._preencher()
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
        self._preencher()
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
        documentos = _documentos_do_relatorio(linhas_importadas)
        data_provavel = (
            self.alteracao.data if self.alteracao
            else (empresas_da_alteracao[0].data_quadro or dt.date.today().isoformat())
        )
        ausentes = [
            socio.nome
            for _v, socio in repo.vinculos_ativos_fora_da_lista(
                self.conn, self.empresa_id, documentos, data_provavel
            )
        ]

        destino = DialogoDestinoAlteracao(
            self.conn,
            self.empresa_id,
            f'Li {resumo_do_relatorio(empresas_da_alteracao)} para "{empresa.nome}".'
            f"{aviso_outras}{alerta}",
            data_sugerida=empresas_da_alteracao[0].data_quadro,
            alteracao_atual_id=self.alteracao.id if self.alteracao else None,
            ausentes=ausentes,
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
                    atualizar_participacao=True,
                )
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao importar", str(exc))
            return

        # O card pode ter entrado aqui como rascunho, ou apontando pra outra
        # alteração que não a escolhida no destino: passa a ser a que recebeu
        # a importação, pra a tela recarregar já em cima dela.
        self.alteracao = repo.buscar_alteracao(self.conn, alteracao_id)

        baixas = []
        if destino.dar_baixa_ausentes.isChecked() and self.alteracao is not None:
            try:
                baixas = repo.encerrar_vinculos_fora_da_lista(
                    self.conn, self.empresa_id, documentos, self.alteracao.data, alteracao_id
                )
            except ValueError as exc:
                QMessageBox.warning(self, "Erro ao dar baixa nos ausentes", str(exc))

        alteracao_nova = (
            f"\n\nLançado na alteração contratual Nº {self.alteracao.numero}."
            if self.alteracao
            else ""
        )
        resumo_txt = (
            f"{aplicado['vinculos_criados']} sócio(s) incluído(s) · "
            f"{aplicado['participacoes_atualizadas']} participação(ões) atualizada(s) · "
            f"{aplicado['vinculos_encerrados']} saída(s) registrada(s) · "
            f"{aplicado['vinculos_ja_existentes']} sem mudança."
            f"{_resumo_das_baixas(baixas)}"
            f"{_aviso_nao_atualizadas(aplicado)}"
            f"{_aviso_fora_do_relatorio(self.conn, self.empresa_id, linhas_importadas, self.alteracao.data)}"
            f"{alteracao_nova}"
        )
        QMessageBox.information(self, "Importação concluída", resumo_txt)
        self._preencher()
        self._ao_mudar(self)
