"""Aba de Sócios: a lista à esquerda e, à direita, a ficha do sócio
selecionado com uma ficha de participação por empresa.

Ver e editar ficam separados: a ficha só mostra, e cadastrar ou mudar os
dados do sócio abre uma janela própria (DialogoSocio). O formulário que
ficava sempre à mostra ao lado da lista confundia — não dava pra saber se
digitar ali alterava o selecionado ou criava outro.

Associar gera a alteração contratual automática quando a entrada é do ano
corrente; entrada mais antiga fica sem ela, pra ser associada depois na
edição da participação. Editar corrige o registro como está."""
from __future__ import annotations

import datetime as dt

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .seletor_empresa import SeletorEmpresa
from .. import repositories as repo
from ..models import TIPOS_PESSOA_LABEL, Socio, VinculoSocietario
from .cartao_participacao import CartaoParticipacao
from .common import (
    CampoValorCota,
    campo_cotas,
    campo_percentual,
    configurar_campo_cnpj,
    configurar_campo_cpf,
    configurar_campo_moeda,
    documento_valido_ou_vazio,
    formatar_data_br,
    formatar_valor_br,
    formatar_valor_cota,
)
from .diagrama_vinculos import DialogoMapaVinculos
from .ficha_socio import BarraAbas, bloco, montar_movimentos, nome_curto
from .informe_rendimentos_view import InformeRendimentosDialog
from . import formulario as form_ui
from .lista_fichas import ListaFichas
from .theme import SAIU_BG, SAIU_FG


def _hairline() -> QFrame:
    linha = QFrame()
    linha.setProperty("role", "hairline")
    return linha


def _campo_data(valor_iso: str | None = None) -> QDateEdit:
    campo = QDateEdit(calendarPopup=True)
    campo.setDisplayFormat("dd/MM/yyyy")
    campo.setDate(dt.date.fromisoformat(valor_iso) if valor_iso else dt.date.today())
    return campo


def _secao(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setProperty("role", "secao")
    return rotulo


def _dica(texto: str = "") -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setProperty("role", "subtitulo")
    rotulo.setWordWrap(True)
    return rotulo


def _valor_ou_nada(campo: QDoubleSpinBox) -> float | None:
    """Capital em branco (zero) é "não informado", não "zero reais": é o que
    deixa a tela mostrar o capital pelas cotas no lugar."""
    return campo.value() or None


def _aviso_alteracao(data_iso: str) -> str:
    """O que acontece com a alteração contratual de um movimento nessa data
    (ver repo.alteracao_automatica_cabe)."""
    if repo.alteracao_automatica_cabe(data_iso):
        return ""
    return (
        f"Entrada anterior a {repo._ano_corrente()}: não é criada alteração contratual "
        "automática. Se houver uma, associe depois em \"Editar participação\"."
    )


def _contar(quantidade: int, singular: str, plural: str) -> str:
    """"1 participação ativa", "2 participações ativas", "nenhuma participação
    ativa" — sem os "(ões)" e "(s)" que fazem a frase parecer formulário.
    Os textos daqui são todos femininos (participação), daí o "nenhuma"."""
    if quantidade == 0:
        return f"nenhuma {singular}"
    return f"{quantidade} {singular if quantidade == 1 else plural}"


def _formulario() -> QFormLayout:
    form = QFormLayout()
    form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
    form.setHorizontalSpacing(14)
    form.setVerticalSpacing(8)
    return form


class _CamposParticipacao:
    """Cotas, valor da cota, capital do sócio e % do capital — os números de
    uma participação, nos dois diálogos (associar e editar), com o mesmo
    comportamento.

    O capital do sócio é cotas × valor da cota, recalculado a cada mudança
    numa das duas: o relatório de sócios não traz o capital, e o valor da
    cota (R$ 1,00 na maioria, R$ 0,01 em algumas) é o que falta pra chegar
    nele. O campo continua editável pra quando o contrato diz outra coisa.

    O percentual, ao contrário, só é calculado quando se pede: o contrato
    pode registrar um percentual que não é a conta exata das cotas, e ele
    não pode ser trocado sem ninguém pedir."""

    def __init__(self, conn, empresa_id_atual, vinculo: VinculoSocietario | None = None):
        self.conn = conn
        self._empresa_id_atual = empresa_id_atual
        self.cotas = campo_cotas()
        self.valor_cota = CampoValorCota()
        self.capital = configurar_campo_moeda(QDoubleSpinBox())
        self.percentual = campo_percentual()
        if vinculo is not None:
            self.cotas.setValue(vinculo.quantidade_cotas or 0)
            self.percentual.setValue(vinculo.percentual_capital or 0)
            self.capital.setValue(vinculo.valor_capital or 0)

        self.total_cotas = _dica()
        self.dica_valor_cota = _dica()
        self.conta_capital = _dica()
        self.btn_percentual = QPushButton("Calcular % pelas cotas")
        self.btn_percentual.setToolTip("Cotas do sócio ÷ total de cotas da empresa.")
        self.btn_percentual.clicked.connect(self.calcular_percentual)
        self._percentual_automatico = False
        self.percentual.valueChanged.connect(self._ao_editar_percentual)

        self.carregar_empresa(recalcular=vinculo is None)
        # Ligados depois de preencher: abrir a edição não pode trocar um
        # capital informado só porque os campos foram carregados.
        self.cotas.valueChanged.connect(self._ao_mudar_cotas)
        self.valor_cota.valueChanged.connect(self._ao_mudar_valor_cota)

    def _estado(self) -> dict | None:
        empresa_id = self._empresa_id_atual()
        return repo.estado_atual_empresa(self.conn, empresa_id) if empresa_id is not None else None

    def carregar_empresa(self, recalcular: bool = True) -> None:
        """O valor da cota vem da empresa: o informado nela, ou capital ÷
        cotas, ou R$ 1,00 — o caso mais comum — quando não há como saber."""
        empresa_id = self._empresa_id_atual()
        empresa = repo.buscar_empresa(self.conn, empresa_id) if empresa_id is not None else None
        valor = repo.valor_da_cota(self.conn, empresa_id) if empresa_id is not None else None
        self.valor_cota.blockSignals(True)
        self.valor_cota.setValue(valor or 1.0)
        self.valor_cota.blockSignals(False)
        if empresa is not None and empresa.valor_cota:
            self.dica_valor_cota.setText("Valor informado no cadastro da empresa.")
        elif valor:
            self.dica_valor_cota.setText("Capital ÷ cotas da empresa — confira.")
        else:
            self.dica_valor_cota.setText("A empresa ainda não tem o valor da cota. Em geral, R$ 1,00.")
        self.dica_valor_cota.setToolTip(
            "O valor da cota é da empresa: o que for usado aqui fica gravado no cadastro dela "
            "e vale para todos os sócios."
        )
        self._atualizar_referencia()
        if recalcular:
            self._recalcular_capital()
        else:
            self._mostrar_conta()

    def _atualizar_referencia(self) -> None:
        estado = self._estado()
        if estado and estado["quantidade_cotas"]:
            self.total_cotas.setText(f"de {formatar_valor_br(estado['quantidade_cotas'], 0)} cotas da empresa")
            self.btn_percentual.setEnabled(self.cotas.value() > 0)
        else:
            self.total_cotas.setText("A empresa não tem o total de cotas cadastrado.")
            self.btn_percentual.setEnabled(False)

    def _mostrar_conta(self) -> None:
        cotas, valor = self.cotas.value(), self.valor_cota.value()
        if cotas and valor:
            self.conta_capital.setText(
                f"{formatar_valor_br(cotas, 0)} cotas × {formatar_valor_cota(valor)} "
                f"= R$ {formatar_valor_br(cotas * valor)}"
            )
        else:
            self.conta_capital.setText("calculado sozinho")

    def _recalcular_capital(self) -> None:
        cotas, valor = self.cotas.value(), self.valor_cota.value()
        if cotas and valor:
            self.capital.setValue(round(cotas * valor, 2))
        self._mostrar_conta()

    def _ao_mudar_cotas(self, *_args) -> None:
        self._atualizar_referencia()
        self._recalcular_capital()
        # Percentual ainda em branco acompanha as cotas; um já informado (o do
        # contrato) só muda pelo botão.
        if not self.percentual.value() or self._percentual_automatico:
            self.calcular_percentual()
            self._percentual_automatico = True

    def _ao_mudar_valor_cota(self, *_args) -> None:
        self._recalcular_capital()

    def _ao_editar_percentual(self, *_args) -> None:
        # Quem digita o percentual assume o controle dele: as cotas param de
        # mexer no campo.
        if not self._calculando_percentual:
            self._percentual_automatico = False

    _calculando_percentual = False

    def calcular_percentual(self) -> None:
        estado = self._estado()
        if not estado or not estado["quantidade_cotas"]:
            return
        self._calculando_percentual = True
        try:
            self.percentual.setValue(100 * self.cotas.value() / estado["quantidade_cotas"])
        finally:
            self._calculando_percentual = False

    def gravar_valor_da_cota(self) -> None:
        """O valor da cota é da empresa: o que foi usado aqui fica gravado
        nela. Sem cotas, ele não entrou em conta nenhuma — e não é gravado."""
        empresa_id = self._empresa_id_atual()
        if empresa_id is not None and self.cotas.value() and self.valor_cota.value():
            repo.definir_valor_da_cota(self.conn, empresa_id, self.valor_cota.value())

    def montar_visual(self) -> QWidget:
        """A participação como conta: [cotas] × [valor da cota] = [capital], e
        o % embaixo, com o botão que o calcula pelas cotas."""
        for rotulo_dica in (self.total_cotas, self.dica_valor_cota, self.conta_capital):
            rotulo_dica.setProperty("role", "dicaCampo")
        caixa = form_ui.Caixa()
        coluna = QVBoxLayout(caixa)
        coluna.setContentsMargins(0, 0, 0, 0)
        coluna.setSpacing(12)
        coluna.addWidget(form_ui.equacao(
            form_ui.campo("Cotas do sócio", self.cotas, self.total_cotas),
            "×",
            form_ui.campo("Valor da cota", self.valor_cota, self.dica_valor_cota),
            "=",
            form_ui.campo("Capital do sócio", self.capital, self.conta_capital,
                          info="Cotas × valor da cota, calculado sozinho. Dá pra digitar outro "
                               "valor se o contrato disser diferente."),
        ))
        percentual = QHBoxLayout()
        percentual.setSpacing(10)
        percentual.addWidget(form_ui.campo(
            "% do capital", self.percentual,
            info="O percentual do contrato. Enquanto estiver em branco acompanha as cotas; "
                 "depois de digitado, só muda pelo botão."), 1)
        botao = QVBoxLayout()
        botao.addStretch()
        botao.addWidget(self.btn_percentual)
        percentual.addLayout(botao)
        percentual.addStretch(1)
        coluna.addLayout(percentual)
        return caixa

    def montar(self, form: QFormLayout) -> None:
        form.addRow("Cotas do sócio", self.cotas)
        form.addRow("", self.total_cotas)
        form.addRow("Valor da cota", self.valor_cota)
        form.addRow("", self.dica_valor_cota)
        form.addRow("Capital do sócio", self.capital)
        form.addRow("", self.conta_capital)
        form.addRow("% do capital", self.percentual)
        form.addRow("", self.btn_percentual)


class _DialogoAssociarEmpresa(QDialog):
    def __init__(self, conn, socio_id: int, parent=None):
        super().__init__(parent)
        self.conn = conn
        socio = next((s for s in repo.listar_socios(conn) if s.id == socio_id), None)
        self.setWindowTitle("Associar a uma empresa")
        self.setMinimumWidth(520)

        vinculadas_ativas = {
            v.empresa_id
            for v in repo.listar_vinculos_socio(conn, socio_id)
            if v.data_saida is None
        }

        self.empresa = SeletorEmpresa()
        self.empresa.definir_empresas([e for e in repo.listar_empresas(conn) if e.id not in vinculadas_ativas])

        self.campos = _CamposParticipacao(conn, self.empresa.currentData)
        self.empresa.currentIndexChanged.connect(lambda _i: self.campos.carregar_empresa())
        # Atalhos usados pelos testes e pela aba: os campos moram em
        # _CamposParticipacao, mas a tela continua expondo cada um.
        self.cotas = self.campos.cotas
        self.valor_cota = self.campos.valor_cota
        self.percentual = self.campos.percentual
        self.capital = self.campos.capital

        self.data_entrada = _campo_data()
        self.data_entrada.dateChanged.connect(self._atualizar_aviso_alteracao)
        self.descricao = QLineEdit("Inclusão de sócio (registrado pela aba de Sócios)")
        self.descricao.setCursorPosition(0)  # senão o começo do texto fica escondido
        self.aviso_alteracao = QLabel()
        self.aviso_alteracao.setProperty("role", "alerta")
        self.aviso_alteracao.setWordWrap(True)

        bloco_empresa, col = form_ui.secao("Empresa", "1")
        col.addWidget(form_ui.campo("Código e nome", self.empresa,
                                    info="Digite o código e Enter, ou F2 para buscar pelo nome."))
        bloco_participacao, col = form_ui.secao("Participação", "2")
        col.addWidget(self.campos.montar_visual())
        bloco_entrada, col = form_ui.secao("Entrada na sociedade", "3")
        col.addLayout(form_ui.linha(
            form_ui.campo("Data de entrada", self.data_entrada),
            form_ui.campo("Alteração contratual (descrição)", self.descricao,
                          info="Entrada no ano corrente gera uma alteração contratual com esta descrição."),
            esticar=(1, 2),
        ))
        col.addWidget(self.aviso_alteracao)

        btn_associar = QPushButton("Associar")
        btn_associar.setProperty("role", "primario")
        btn_associar.setDefault(True)
        btn_associar.clicked.connect(self.accept)
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.clicked.connect(self.reject)

        form_ui.montar_janela(
            self,
            form_ui.cabecalho(f"Associar {socio.nome if socio else 'o sócio'}",
                              "Em qual empresa ele entra, com quantas cotas e desde quando."),
            [bloco_empresa, bloco_participacao, bloco_entrada],
            form_ui.botoes_rodape(direita=(btn_cancelar, btn_associar)),
            largura=720,
        )
        self._atualizar_aviso_alteracao()

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
    """Todos os dados da participação numa tela só: cotas, valor da cota,
    capital, %, entrada, saída, alterações contratuais e observação — e o
    botão de excluir.

    Tudo aqui é correção do próprio registro: não abre participação nova nem
    cria alteração contratual. A alteração de entrada e de saída é escolhida
    entre as que a empresa já tem — é como se associa depois a alteração que
    a importação não criou."""

    EXCLUIDO = 2

    def __init__(self, conn, vinculo: VinculoSocietario, empresa_nome: str, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.vinculo = vinculo
        self.setWindowTitle(f"Editar participação — {empresa_nome}")
        self.setMinimumWidth(540)

        socio = next((s for s in repo.listar_socios(conn) if s.id == vinculo.socio_id), None)

        self.campos = _CamposParticipacao(conn, lambda: vinculo.empresa_id, vinculo)
        self.cotas = self.campos.cotas
        self.valor_cota = self.campos.valor_cota
        self.percentual = self.campos.percentual
        self.capital = self.campos.capital

        alteracoes = repo.listar_alteracoes(conn, vinculo.empresa_id)
        self.data_entrada = _campo_data(vinculo.data_entrada)
        self.alteracao_entrada = self._combo_alteracoes(alteracoes, vinculo.alteracao_entrada_id)

        self.saiu = QCheckBox("O sócio saiu desta empresa")
        self.saiu.setChecked(vinculo.data_saida is not None)
        self.data_saida = _campo_data(vinculo.data_saida)
        self.alteracao_saida = self._combo_alteracoes(alteracoes, vinculo.alteracao_saida_id)
        self.saiu.toggled.connect(self._ajustar_saida)

        self.observacao = QLineEdit(vinculo.observacao or "")
        self.observacao.setPlaceholderText("Opcional")

        bloco_participacao, col = form_ui.secao(
            "Participação",
            info="Corrige este registro como está — não cria alteração contratual. Para registrar uma "
                 "mudança com histórico, cadastre a alteração em Alterações contratuais e escolha-a abaixo.",
        )
        col.addWidget(self.campos.montar_visual())

        bloco_entrada, col = form_ui.secao("Entrada")
        col.addLayout(form_ui.linha(
            form_ui.campo("Data de entrada", self.data_entrada),
            form_ui.campo("Alteração contratual", self.alteracao_entrada),
            esticar=(1, 2),
        ))

        bloco_saida, col = form_ui.secao("Saída")
        col.addWidget(self.saiu)
        self.campos_saida = form_ui.Caixa()
        linha_saida = form_ui.linha(
            form_ui.campo("Data de saída", self.data_saida),
            form_ui.campo("Alteração contratual", self.alteracao_saida),
            esticar=(1, 2),
        )
        linha_saida.setContentsMargins(0, 0, 0, 0)
        self.campos_saida.setLayout(linha_saida)
        col.addWidget(self.campos_saida)

        bloco_obs, col = form_ui.secao("Observação")
        col.addWidget(self.observacao)

        self.btn_excluir = QPushButton("Excluir participação")
        self.btn_excluir.setProperty("role", "perigo")
        self.btn_excluir.clicked.connect(self._excluir)
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.clicked.connect(self.reject)
        btn_salvar = QPushButton("Salvar")
        btn_salvar.setProperty("role", "primario")
        btn_salvar.setDefault(True)
        btn_salvar.clicked.connect(self._salvar)

        form_ui.montar_janela(
            self,
            form_ui.cabecalho(empresa_nome, f"Participação de {socio.nome if socio else 'sócio'}"),
            [bloco_participacao, bloco_entrada, bloco_saida, bloco_obs],
            form_ui.botoes_rodape(self.btn_excluir, direita=(btn_cancelar, btn_salvar)),
            largura=720,
        )

        self._ajustar_saida()

    @staticmethod
    def _combo_alteracoes(alteracoes: list, atual_id: int | None) -> QComboBox:
        combo = QComboBox()
        combo.addItem("Nenhuma (associar depois)", None)
        for a in alteracoes:
            descricao = (a.descricao or "").strip()
            if len(descricao) > 40:
                descricao = descricao[:39] + "…"
            rotulo = f"Nº {a.numero} — {formatar_data_br(a.data)}" + (f" — {descricao}" if descricao else "")
            if a.fechada:
                rotulo += " (trancada)"
            combo.addItem(rotulo, a.id)
        indice = combo.findData(atual_id)
        combo.setCurrentIndex(indice if indice >= 0 else 0)
        return combo

    def _ajustar_saida(self, *_args) -> None:
        saiu = self.saiu.isChecked()
        self.data_saida.setEnabled(saiu)
        self.alteracao_saida.setEnabled(saiu)
        # Sem saída, os campos dela nem aparecem: menos coisa na tela.
        self.campos_saida.setVisible(saiu)

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
        self.campos.gravar_valor_da_cota()
        self.accept()

    def _excluir(self) -> None:
        resposta = QMessageBox.question(
            self,
            "Excluir participação",
            "Excluir de vez esta participação? O registro é apagado, sem deixar histórico.\n\n"
            "Se o sócio saiu da empresa, marque \"O sócio saiu desta empresa\" com a data em vez "
            "de excluir — assim os anos em que ele participou continuam aparecendo.",
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


class DialogoSocio(QDialog):
    """Cadastrar um sócio novo ou mudar os dados de um que já existe.

    Enquanto se digita o nome ou o documento, avisa se já existe alguém
    parecido: sócio repetido se espalha por todas as empresas dele e só
    costuma aparecer na hora de emitir informe, quando já é trabalhoso
    desfazer. No cadastro novo, "Abrir o cadastro existente" fecha esta
    janela e mostra o que já está lá.

    O cadastro novo termina com "Salvar e associar a uma empresa": o
    cadastro inicial de um sócio só fica completo com a participação dele —
    é lá que entram as cotas, o valor da cota e o capital."""

    ABRIR_EXISTENTE = 2
    EXCLUIDO = 3

    def __init__(self, conn, socio: Socio | None = None, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.socio = socio
        self.socio_id: int | None = socio.id if socio else None
        self.associar_em_seguida = False
        self.semelhante_id: int | None = None
        self.setWindowTitle("Editar sócio" if socio else "Novo sócio")
        self.setMinimumWidth(480)

        self.nome = QLineEdit(socio.nome if socio else "")
        self.nome.setPlaceholderText("Nome completo ou razão social")
        self.tipo_pessoa = form_ui.OpcoesLadoALado(list((label, tipo) for tipo, label in TIPOS_PESSOA_LABEL.items()))
        self.cpf = QLineEdit()
        self.cpf.setProperty("role", "mono")
        self._rotulo_documento = QLabel("CPF")
        self._rotulo_documento.setProperty("role", "rotuloCampo")

        documento = form_ui.Caixa()
        coluna_documento = QVBoxLayout(documento)
        coluna_documento.setContentsMargins(0, 0, 0, 0)
        coluna_documento.setSpacing(4)
        coluna_documento.addWidget(self._rotulo_documento)
        coluna_documento.addWidget(self.cpf)

        self.aviso_duplicado = QLabel()
        self.aviso_duplicado.setWordWrap(True)
        self.aviso_duplicado.setTextFormat(Qt.RichText)
        self.aviso_duplicado.hide()
        self.btn_abrir_semelhante = QPushButton("Abrir o cadastro existente")
        self.btn_abrir_semelhante.clicked.connect(self._abrir_semelhante)
        self.btn_abrir_semelhante.hide()

        bloco, col = form_ui.secao(
            "Dados do sócio",
            info="O sócio é cadastrado uma vez só e reaproveitado em todas as empresas de que participa."
                 if socio is None else "Muda os dados deste sócio em todas as empresas dele.",
        )
        col.addWidget(form_ui.campo("Tipo", self.tipo_pessoa))
        col.addLayout(form_ui.linha(form_ui.campo("Nome", self.nome), documento, esticar=(3, 2)))
        col.addWidget(self.aviso_duplicado)
        col.addWidget(self.btn_abrir_semelhante, 0, Qt.AlignLeft)

        esquerda = []
        if socio is not None:
            self.btn_excluir = QPushButton("Excluir sócio")
            self.btn_excluir.setProperty("role", "perigo")
            self.btn_excluir.clicked.connect(self._excluir)
            esquerda.append(self.btn_excluir)
        btn_cancelar = QPushButton("Cancelar")
        btn_cancelar.clicked.connect(self.reject)
        self.btn_salvar = QPushButton("Salvar")
        self.btn_salvar.clicked.connect(lambda: self._salvar(associar=False))
        direita = [btn_cancelar, self.btn_salvar]
        if socio is None:
            self.btn_salvar_associar = QPushButton("Salvar e associar a uma empresa  →")
            self.btn_salvar_associar.setProperty("role", "primario")
            self.btn_salvar_associar.setDefault(True)
            self.btn_salvar_associar.clicked.connect(lambda: self._salvar(associar=True))
            direita.append(self.btn_salvar_associar)
        else:
            self.btn_salvar.setProperty("role", "primario")
            self.btn_salvar.setDefault(True)

        form_ui.montar_janela(
            self,
            form_ui.cabecalho(socio.nome if socio else "Novo sócio",
                              "" if socio else "Depois de salvar, você já associa a uma empresa."),
            [bloco],
            form_ui.botoes_rodape(*esquerda, direita=tuple(direita)),
            largura=600,
        )

        indice = self.tipo_pessoa.findData(socio.tipo_pessoa if socio else "fisica")
        self.tipo_pessoa.setCurrentIndex(indice if indice >= 0 else 0)
        self._ajustar_mascara_documento()
        if socio is not None:
            self.cpf.setText(socio.cpf or "")
        self.tipo_pessoa.currentIndexChanged.connect(self._ajustar_mascara_documento)
        self.nome.textChanged.connect(self._procurar_semelhantes)
        self.cpf.textChanged.connect(self._procurar_semelhantes)
        self.nome.setFocus()

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
        achados = repo.socios_semelhantes(
            self.conn,
            self.nome.text(),
            documento_valido_ou_vazio(self.cpf) or self.cpf.text(),
            ignorar_id=self.socio_id,
        )
        if not achados:
            self.semelhante_id = None
            self.aviso_duplicado.hide()
            self.btn_abrir_semelhante.hide()
            return
        socio, motivo = achados[0]
        self.semelhante_id = socio.id
        extra = f" (e mais {len(achados) - 1})" if len(achados) > 1 else ""
        self.aviso_duplicado.setText(
            f"⚠ Já existe <b>{socio.nome}</b> — {motivo}{extra}. Confira antes de cadastrar outro."
        )
        self.aviso_duplicado.setStyleSheet(
            f"color: {SAIU_FG()}; background: {SAIU_BG()}; border-radius: 4px; "
            f"padding: 7px 10px; font-size: 11px;"
        )
        self.aviso_duplicado.show()
        # Só no cadastro novo: editando, abrir outro cadastro no meio da edição
        # descartaria o que está na tela.
        self.btn_abrir_semelhante.setVisible(self.socio is None)

    def _abrir_semelhante(self) -> None:
        if self.semelhante_id is not None:
            self.done(self.ABRIR_EXISTENTE)

    def _salvar(self, associar: bool) -> None:
        nome = self.nome.text().strip()
        if not nome:
            QMessageBox.warning(self, "Falta o nome", "Informe o nome do sócio.")
            return
        try:
            self.socio_id = repo.salvar_socio(
                self.conn,
                Socio(
                    id=self.socio_id,
                    nome=nome,
                    cpf=documento_valido_ou_vazio(self.cpf),
                    tipo_pessoa=self.tipo_pessoa.currentData(),
                ),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Não foi possível salvar", str(exc))
            return
        self.associar_em_seguida = associar
        self.accept()

    def _excluir(self) -> None:
        resposta = QMessageBox.question(
            self,
            "Excluir sócio",
            f"Excluir o cadastro de {self.socio.nome}?\n\nSó é possível excluir um sócio sem "
            "participações nem lançamentos — o histórico de quem participou de uma sociedade não "
            "pode sumir.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resposta != QMessageBox.Yes:
            return
        try:
            repo.excluir_socio(self.conn, self.socio.id)
        except ValueError as exc:
            QMessageBox.warning(self, "Não foi possível excluir", str(exc))
            return
        self.done(self.EXCLUIDO)


class SociosTab(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._socios: list[Socio] = []
        self._socio_atual_id: int | None = None
        self._vinculos_exibidos: list[VinculoSocietario] = []
        self.cartoes: list[CartaoParticipacao] = []
        self._empresas_das_abas: list[int] = []
        self._empresa_da_aba: int | None = None

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

    # ------------------------------------------------------------- painéis --
    def _montar_painel_lista(self) -> QWidget:
        painel = QWidget()
        col = QVBoxLayout(painel)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(10)

        # Sem título próprio: a janela já diz "Sócios" acima da tela.
        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Buscar por nome, CPF ou CNPJ…")
        self.busca.setClearButtonEnabled(True)
        self.busca.textChanged.connect(lambda _texto: self.atualizar())
        self.btn_novo = QPushButton("Novo sócio")
        self.btn_novo.setProperty("role", "primario")
        self.btn_novo.clicked.connect(self._novo_socio)
        cabecalho = QHBoxLayout()
        cabecalho.addWidget(self.busca, 1)
        cabecalho.addWidget(self.btn_novo)

        self.lista = ListaFichas("Nenhum sócio cadastrado ainda.\nClique em Novo sócio para começar.")
        # itemSelectionChanged, e não currentItemChanged: no clique do mouse o
        # Qt avisa que o item atual mudou ANTES de selecioná-lo, e a ficha
        # perguntava pelo selecionado cedo demais — e ficava vazia.
        self.lista.itemSelectionChanged.connect(self._ao_selecionar_socio)
        self.lista.itemDoubleClicked.connect(lambda _item: self._editar_socio())

        self.contagem = QLabel()
        self.contagem.setProperty("role", "subtitulo")

        col.addLayout(cabecalho)
        col.addWidget(self.lista, 1)
        col.addWidget(self.contagem)
        return painel

    def _montar_painel_ficha(self) -> QWidget:
        """O sócio selecionado e as empresas em que ele participa, uma ficha
        por empresa (ver CartaoParticipacao). Sem quadro branco em volta: o
        cabeçalho fica no papel da página e só as fichas são brancas."""
        painel = QWidget()
        col = QVBoxLayout(painel)
        col.setContentsMargins(20, 6, 6, 0)
        col.setSpacing(6)

        # ---- quem é o sócio
        self.titulo_socio = QLabel()
        self.titulo_socio.setProperty("role", "titulo")
        self.titulo_socio.setWordWrap(True)
        self.documento_socio = QLabel()
        self.documento_socio.setProperty("role", "subtitulo")
        self.documento_socio.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.btn_editar_socio = QPushButton("Editar dados")
        self.btn_editar_socio.setToolTip("Nome, tipo e documento do sócio. Também dá pra excluir por lá.")
        self.btn_editar_socio.clicked.connect(self._editar_socio)
        # O mapa e o informe olham pro sócio inteiro, não pra uma empresa: por
        # isso ficam no cabeçalho dele, e não em cada ficha.
        self.btn_mapa = QPushButton("Mapa de vínculos")
        self.btn_mapa.setToolTip(
            "Abre um diagrama com as empresas em que este sócio participa — dá pra exportar "
            "em PDF ou SVG para anexar a processo, contrato ou apresentação."
        )
        self.btn_mapa.clicked.connect(self._abrir_mapa_vinculos)
        self.btn_informe = QPushButton("Informe de rendimentos")
        self.btn_informe.setToolTip(
            "Comprovante de Rendimentos Pagos e de Imposto sobre a Renda Retido na Fonte "
            "(IN RFB nº 2.060/2021) — um por empresa em que o sócio recebeu."
        )
        self.btn_informe.clicked.connect(self._emitir_informe)

        self.btn_associar = QPushButton("+ Associar empresa")
        self.btn_associar.setProperty("role", "primario")
        self.btn_associar.clicked.connect(self._associar_empresa)
        self.resumo_socio = QLabel()
        self.resumo_socio.setProperty("role", "subtitulo")
        separador = QLabel("·")
        separador.setProperty("role", "subtitulo")
        linha_documento = QHBoxLayout()
        linha_documento.setSpacing(6)
        linha_documento.addWidget(self.documento_socio)
        linha_documento.addWidget(separador)
        linha_documento.addWidget(self.resumo_socio)
        linha_documento.addStretch()
        identificacao = QVBoxLayout()
        identificacao.setSpacing(2)
        identificacao.addWidget(self.titulo_socio)
        identificacao.addLayout(linha_documento)
        # As ações numa linha própria, abaixo do nome: ao lado dele, com nome
        # comprido e a janela no mínimo, o último botão saía cortado.
        acoes = QHBoxLayout()
        acoes.setSpacing(8)
        acoes.addWidget(self.btn_editar_socio)
        acoes.addWidget(self.btn_mapa)
        acoes.addWidget(self.btn_informe)
        acoes.addStretch()
        acoes.addWidget(self.btn_associar)
        cabecalho = QVBoxLayout()
        cabecalho.setSpacing(8)
        cabecalho.addLayout(identificacao)
        cabecalho.addLayout(acoes)

        # ---- participações, em abas: a visão geral e uma aba por empresa
        self.abas = BarraAbas()
        self.abas.escolhida.connect(self._mostrar_aba)
        linha_abas = QHBoxLayout()
        linha_abas.addWidget(self.abas, 1)

        self.paginas = QStackedWidget()
        self.rolagem_cartoes = QWidget()
        coluna_abas = QVBoxLayout(self.rolagem_cartoes)
        coluna_abas.setContentsMargins(0, 0, 0, 0)
        coluna_abas.setSpacing(10)
        coluna_abas.addLayout(linha_abas)
        coluna_abas.addWidget(self.paginas, 1)

        # ---- tela vazia: sem sócio ou sócio sem empresa
        self.vazio_titulo = QLabel()
        self.vazio_titulo.setProperty("role", "vazioTitulo")
        self.vazio_titulo.setAlignment(Qt.AlignCenter)
        self.vazio_titulo.setWordWrap(True)
        self.vazio_texto = QLabel()
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

        self.cabecalho_socio = QWidget()
        coluna_cabecalho = QVBoxLayout(self.cabecalho_socio)
        coluna_cabecalho.setContentsMargins(0, 0, 0, 0)
        coluna_cabecalho.setSpacing(6)
        coluna_cabecalho.addLayout(cabecalho)
        coluna_cabecalho.addSpacing(4)

        col.addWidget(self.cabecalho_socio)
        col.addWidget(self.rolagem_cartoes, 1)
        col.addWidget(self.painel_vazio, 1)
        return painel

    # -------------------------------------------------------------- sócios --
    def atualizar(self) -> None:
        todos = repo.listar_socios(self.conn)
        termo = self.busca.text().strip().lower()
        digitos = "".join(c for c in termo if c.isalnum())
        socios = [
            s for s in todos
            if not termo
            or termo in s.nome.lower()
            or (digitos and digitos in repo.normalizar_documento(s.cpf).lower())
        ]
        self._socios = socios
        ativas = repo.quantidade_empresas_ativas_por_socio(self.conn)

        self.lista.blockSignals(True)
        self.lista.clear()
        for s in socios:
            documento = "CNPJ" if s.tipo_pessoa == "juridica" else "CPF"
            quantidade = ativas.get(s.id, 0)
            empresas = (
                "sem empresa" if quantidade == 0
                else f"{quantidade} empresa" if quantidade == 1
                else f"{quantidade} empresas"
            )
            self.lista.adicionar(
                s.id,
                s.nome,
                f"{documento} {s.cpf}" if s.cpf else f"sem {documento} cadastrado",
                empresas,
                apagado=quantidade == 0,
            )
        self.lista.blockSignals(False)
        if not self.lista.selecionar_id(self._socio_atual_id):
            self._socio_atual_id = None

        if termo:
            self.contagem.setText(f"{len(socios)} de {len(todos)} sócios")
        else:
            self.contagem.setText(f"{len(todos)} sócio" + ("" if len(todos) == 1 else "s"))
        self._atualizar_painel_vinculos()

    def _ao_selecionar_socio(self) -> None:
        if self.lista.id_selecionado() != self._socio_atual_id:
            self._empresa_da_aba = None
        self._socio_atual_id = self.lista.id_selecionado()
        self._atualizar_painel_vinculos()

    def _selecionar_socio(self, socio_id: int) -> None:
        """Mostra o sócio, limpando a busca se ela o escondia."""
        if not self.lista.selecionar_id(socio_id):
            self.busca.clear()
            self.lista.selecionar_id(socio_id)

    def _novo_socio(self) -> None:
        dialogo = DialogoSocio(self.conn, parent=self)
        resultado = dialogo.exec()
        if resultado == DialogoSocio.ABRIR_EXISTENTE:
            self.atualizar()
            self._selecionar_socio(dialogo.semelhante_id)
            return
        if resultado != QDialog.Accepted:
            return
        self._socio_atual_id = dialogo.socio_id
        self.busca.clear()
        self.atualizar()
        self._selecionar_socio(dialogo.socio_id)
        if dialogo.associar_em_seguida:
            self._associar_empresa()

    def _editar_socio(self) -> None:
        socio = next((s for s in self._socios if s.id == self._socio_atual_id), None)
        if socio is None:
            return
        dialogo = DialogoSocio(self.conn, socio, self)
        resultado = dialogo.exec()
        if resultado == DialogoSocio.EXCLUIDO:
            self._socio_atual_id = None
        if resultado != QDialog.Rejected:
            self.atualizar()

    # ------------------------------------------------------------ vínculos --
    def _mostrar_vazio(self, titulo: str, texto: str, com_cabecalho: bool) -> None:
        self.vazio_titulo.setText(titulo)
        self.vazio_texto.setText(texto)
        self.cabecalho_socio.setVisible(com_cabecalho)
        self.rolagem_cartoes.hide()
        self.painel_vazio.show()

    def _limpar_cartoes(self) -> None:
        while self.paginas.count():
            pagina = self.paginas.widget(0)
            self.paginas.removeWidget(pagina)
            pagina.hide()  # o deleteLater só apaga depois; até lá ficaria à mostra
            pagina.deleteLater()
        self.cartoes = []
        self._empresas_das_abas = []

    def _atualizar_painel_vinculos(self) -> None:
        self._limpar_cartoes()
        socio = next((s for s in self._socios if s.id == self._socio_atual_id), None)
        if socio is None:
            self._vinculos_exibidos = []
            self._mostrar_vazio(
                "Nenhum sócio selecionado",
                "Escolha um sócio na lista para ver em quais empresas ele participa, "
                "ou clique em Novo sócio para cadastrar outro.",
                com_cabecalho=False,
            )
            self._atualizar_disponibilidade_botoes()
            return

        self.titulo_socio.setText(socio.nome)
        documento = "CNPJ" if socio.tipo_pessoa == "juridica" else "CPF"
        self.documento_socio.setText(
            f"{documento} {socio.cpf} · {TIPOS_PESSOA_LABEL.get(socio.tipo_pessoa, '')}"
            if socio.cpf
            else f"{TIPOS_PESSOA_LABEL.get(socio.tipo_pessoa, '')} · sem {documento} cadastrado"
        )

        vinculos = repo.listar_vinculos_socio(self.conn, socio.id)
        # Quem está na sociedade hoje vem primeiro, do maior para o menor;
        # quem já saiu vem depois, da saída mais recente para a mais antiga.
        ativos = sorted((v for v in vinculos if v.data_saida is None), key=lambda v: -v.percentual_capital)
        encerrados = sorted((v for v in vinculos if v.data_saida is not None), key=lambda v: v.data_saida, reverse=True)
        self._vinculos_exibidos = ativos + encerrados

        capital_informado = sum(v.valor_capital or 0 for v in ativos)
        # Contado por empresa, não por vínculo: participação refeita fecha um
        # vínculo e abre outro, mas o sócio não saiu de lugar nenhum.
        empresas_ativas = {v.empresa_id for v in ativos}
        empresas_que_saiu = {v.empresa_id for v in encerrados} - empresas_ativas
        partes = [_contar(len(empresas_ativas), "empresa ativa", "empresas ativas")]
        if empresas_que_saiu:
            partes.append(f"saiu de {_contar(len(empresas_que_saiu), 'empresa', 'empresas')}")
        if capital_informado:
            partes.append(f"R$ {formatar_valor_br(capital_informado)} de capital nas ativas")
        resumo = " · ".join(partes)
        self.resumo_socio.setText(resumo[:1].upper() + resumo[1:])

        if not vinculos:
            self._mostrar_vazio(
                f"{socio.nome} ainda não participa de nenhuma empresa",
                "Clique em + Associar empresa para informar a participação na sociedade: "
                "as cotas, o valor da cota, o capital e o percentual.",
                com_cabecalho=True,
            )
            self._atualizar_disponibilidade_botoes()
            return

        # Uma empresa por aba, na ordem: quem está na sociedade hoje primeiro
        # (maior fatia antes), depois de onde ele já saiu. Em cada empresa
        # vale a participação mais recente — as anteriores ficam nas
        # movimentações, como "foto" daquela época.
        empresas = {e.id: e for e in repo.listar_empresas(self.conn)}
        atuais: dict[int, VinculoSocietario] = {}
        for v in self._vinculos_exibidos:
            atuais.setdefault(v.empresa_id, v)
        ordem_empresas = list(atuais)
        movimentos = repo.movimentacoes_do_socio(self.conn, socio.id)
        uma_so = len(ordem_empresas) == 1

        for empresa_id in ordem_empresas:
            self.cartoes.append(self._criar_cartao(atuais[empresa_id], empresas))
        self.paginas.addWidget(self._pagina_visao_geral(
            self.cartoes, movimentos if uma_so else None
        ))

        abas = [("Visão geral", "Todas as empresas deste sócio, como estão hoje", False)]
        for empresa_id in ordem_empresas:
            empresa = empresas.get(empresa_id)
            nome = empresa.nome if empresa else "?"
            saiu = atuais[empresa_id].data_saida is not None
            abas.append((nome_curto(nome), f"{nome}" + (" — o sócio já saiu" if saiu else ""), saiu))
            self.paginas.addWidget(self._pagina_empresa(
                self._criar_cartao(atuais[empresa_id], empresas),
                [m for m in movimentos if m["empresa_id"] == empresa_id],
            ))
            self._empresas_das_abas.append(empresa_id)
        self.abas.definir(abas)
        # Com uma empresa só, a visão geral já é a da empresa: abas sobrando
        # só ocupariam a tela.
        self.abas.setVisible(not uma_so)

        alvo = self._empresa_da_aba
        indice = self._empresas_das_abas.index(alvo) + 1 if alvo in self._empresas_das_abas and not uma_so else 0
        self.abas.escolher(indice)
        self.paginas.setCurrentIndex(indice)

        self.cabecalho_socio.show()
        self.painel_vazio.hide()
        self.rolagem_cartoes.show()
        self._atualizar_disponibilidade_botoes()

    def _criar_cartao(self, v: VinculoSocietario, empresas: dict) -> CartaoParticipacao:
        empresa = empresas.get(v.empresa_id)
        estado = repo.estado_atual_empresa(self.conn, v.empresa_id)
        alteracoes = {a.id: a for a in repo.listar_alteracoes(self.conn, v.empresa_id)}
        calculado = repo.valor_participacao(self.conn, v) or None if v.data_saida is None and v.quantidade_cotas else None
        da_empresa = [o for o in repo.listar_vinculos_socio(self.conn, v.socio_id) if o.empresa_id == v.empresa_id]
        refeita = v.data_saida is not None and any(
            o.id != v.id and o.data_entrada == v.data_saida for o in da_empresa
        )
        # Volta pelas participações refeitas até a primeira entrada contínua.
        desde = v.data_entrada
        while True:
            anterior = next((o for o in da_empresa if o.data_saida == desde and o.id != v.id), None)
            if anterior is None or anterior.data_entrada == desde:
                break
            desde = anterior.data_entrada
        cartao = CartaoParticipacao(
            v, empresa, estado["quantidade_cotas"], calculado, alteracoes,
            valor_cota_informado=bool(empresa and empresa.valor_cota), refeita=refeita,
            na_empresa_desde=desde,
        )
        cartao.editar.connect(self._editar_vinculo)
        return cartao

    # ---------------------------------------------------------------- abas --
    def _mostrar_aba(self, indice: int) -> None:
        self.paginas.setCurrentIndex(indice)
        self._empresa_da_aba = self._empresas_das_abas[indice - 1] if indice > 0 else None

    def abrir_aba_da_empresa(self, empresa_id: int) -> None:
        if empresa_id in self._empresas_das_abas and self.abas.isVisibleTo(self):
            indice = self._empresas_das_abas.index(empresa_id) + 1
            self.abas.escolher(indice)
            self._mostrar_aba(indice)

    def _pagina_rolavel(self) -> tuple[QScrollArea, QVBoxLayout]:
        corpo = QWidget()
        coluna = QVBoxLayout(corpo)
        coluna.setContentsMargins(0, 4, 8, 12)
        coluna.setSpacing(14)
        rolagem = QScrollArea()
        rolagem.setProperty("role", "listaCartoes")
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.NoFrame)
        rolagem.setWidget(corpo)
        return rolagem, coluna

    def _pagina_visao_geral(self, cartoes: list, movimentos: list[dict] | None) -> QWidget:
        """O estado de hoje: o cartão de cada empresa, com Editar
        participação. Entradas e saídas ficam na aba de cada empresa — a
        não ser que ele só tenha uma, e aí ficam aqui mesmo."""
        pagina, coluna = self._pagina_rolavel()
        for cartao in cartoes:
            coluna.addWidget(cartao)
        if movimentos is not None:
            coluna.addWidget(self._bloco_movimentos(movimentos))
        coluna.addStretch()
        return pagina

    def _pagina_empresa(self, cartao: CartaoParticipacao, movimentos: list[dict]) -> QWidget:
        pagina, coluna = self._pagina_rolavel()
        coluna.addWidget(cartao)
        coluna.addWidget(self._bloco_movimentos(movimentos))
        coluna.addStretch()
        return pagina

    def _bloco_movimentos(self, movimentos: list[dict]) -> QFrame:
        quadro, dentro = bloco("Movimentações nesta empresa")
        dentro.setSpacing(4)
        dentro.addWidget(_dica("Clique numa movimentação para ver como era a participação naquela época."))
        montar_movimentos(dentro, movimentos, self._abrir_foto)
        return quadro

    def _abrir_foto(self, vinculo_id: int) -> None:
        """A participação como era naquela época — o cartão completo, com
        Editar participação, numa janela à parte."""
        vinculo = repo.buscar_vinculo(self.conn, vinculo_id)
        if vinculo is None:
            return
        empresas = {e.id: e for e in repo.listar_empresas(self.conn)}
        cartao = self._criar_cartao(vinculo, empresas)
        dialogo = QDialog(self)
        empresa = empresas.get(vinculo.empresa_id)
        dialogo.setWindowTitle(f"Participação em {empresa.nome if empresa else '?'}")
        dialogo.setMinimumWidth(640)
        periodo = (
            f"desde {formatar_data_br(vinculo.data_entrada)} (é a participação de hoje)"
            if vinculo.data_saida is None
            else f"de {formatar_data_br(vinculo.data_entrada)} a {formatar_data_br(vinculo.data_saida)}"
        )
        titulo = QLabel("Como era a participação")
        titulo.setProperty("role", "titulo")
        layout = QVBoxLayout(dialogo)
        layout.setSpacing(10)
        layout.addWidget(titulo)
        layout.addWidget(_dica(f"Período {periodo}."))
        layout.addSpacing(4)
        layout.addWidget(cartao)
        fechar = QPushButton("Fechar")
        fechar.clicked.connect(dialogo.reject)
        linha = QHBoxLayout()
        linha.addStretch()
        linha.addWidget(fechar)
        layout.addLayout(linha)
        # Editar daqui fecha a foto e abre a edição, que redesenha a ficha.
        cartao.editar.disconnect()
        cartao.editar.connect(lambda vid: (dialogo.accept(), self._editar_vinculo(vid)))
        dialogo.exec()

    def _atualizar_disponibilidade_botoes(self) -> None:
        tem_socio = self._socio_atual_id is not None
        for botao in (self.btn_associar, self.btn_mapa, self.btn_informe, self.btn_editar_socio):
            botao.setEnabled(tem_socio)

    def _associar_empresa(self) -> None:
        if self._socio_atual_id is None:
            return
        dialogo = _DialogoAssociarEmpresa(self.conn, self._socio_atual_id, self)
        if dialogo.empresa.count() == 0:
            QMessageBox.information(
                self, "Associar a uma empresa",
                "Não há empresas disponíveis: o sócio já está em todas, ou nenhuma empresa foi cadastrada.",
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
        dialogo.campos.gravar_valor_da_cota()
        self._empresa_da_aba = empresa_id
        self.atualizar()

    def _editar_vinculo(self, vinculo_id: int) -> None:
        vinculo = repo.buscar_vinculo(self.conn, vinculo_id)
        if vinculo is None:
            return
        empresa = repo.buscar_empresa(self.conn, vinculo.empresa_id)
        self._empresa_da_aba = vinculo.empresa_id
        dialogo = _DialogoEditarVinculo(self.conn, vinculo, empresa.nome if empresa else "?", self)
        # A tela grava (ou exclui) por conta própria e só fecha se deu certo;
        # aqui é só redesenhar quando algo mudou.
        if dialogo.exec() != QDialog.Rejected:
            self.atualizar()

    def _emitir_informe(self) -> None:
        """Abre a conferência e emissão do informe de rendimentos do sócio
        selecionado. A janela é por sócio (não por vínculo) porque um sócio de
        três empresas recebe três comprovantes e é bom conferir os três de uma
        vez, na mesma sessão."""
        socio = next((s for s in self._socios if s.id == self._socio_atual_id), None)
        if socio is None:
            return
        InformeRendimentosDialog(self.conn, socio, self).exec()

    def _abrir_mapa_vinculos(self) -> None:
        """Mostra num desenho o que as fichas mostram uma a uma — onde a
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
                # O percentual registrado no vínculo, o mesmo da ficha — não o
                # recalculado por cotas, que muda com o capital da empresa e
                # faria o desenho discordar do que está ao lado dele na tela.
                "percentual": v.percentual_capital,
                "data_entrada": v.data_entrada,
                "data_saida": v.data_saida,
                "capital": v.valor_capital,
            }
            for v in repo.listar_vinculos_socio(self.conn, socio.id)
        ]
        DialogoMapaVinculos(socio.nome, socio.cpf or "", vinculos, self).exec()
