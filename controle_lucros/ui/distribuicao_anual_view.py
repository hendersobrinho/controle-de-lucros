"""Painel de distribuição anual: para uma empresa/ano, o painel de destaque
com o lucro distribuído, pró-labore, IRRF e capital, a rosca da divisão entre
os sócios, e a tabela com cada sócio — na mesma cor da fatia dele.

Sócios que entraram ou saíram naquele ano ficam destacados. Colunas que não
têm o que mostrar (origem dos trimestres, empréstimo, data de saída) somem
até terem."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import QDate, Qt
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
    QSpinBox,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .seletor_empresa import SeletorEmpresa
from .. import repositories as repo
from ..models import TIPOS_MOVIMENTACAO, TIPOS_MOVIMENTACAO_LABEL, Movimentacao
from ..planilha import exportar_modelo_distribuicao, importar_distribuicao
from .importacao_distribuicao import DialogoRevisaoImportacao, associar_linhas
from .common import (
    campo_percentual,
    formatar_data_br,
    formatar_numero,
    formatar_percentual,
    formatar_valor_br,
    preencher_combo,
    TabelaLista,
)
from .painel_distribuicao import (
    PAPEL_COR,
    PAPEL_DETALHE,
    PAPEL_PERCENTUAL,
    PAPEL_TOM,
    DelegadoEtiqueta,
    DelegadoPercentual,
    DelegadoSocio,
    Rosca,
    _compacto,
    agrupar_fatias,
    cor_da_vez,
    divisor_hero,
    kpi,
    navegador_ano,
    ordem_de_cores,
)
from .theme import ENTROU_BG, ENTROU_FG, SAIU_FG, cor
from .theme import estado as tema_estado

COLUNAS = [
    "Sócio",
    "% do capital",
    "Cotas",
    "Valor distribuído",
    "Origem",
    "Pró-labore",
    "IRRF",
    "% distribuído",
    "Empréstimo ao sócio",
    "Adiantamento",
    "Empréstimo do sócio",
    "Devolução de capital",
    "Data de saída",
    "Situação",
]

# Os widgets da edição em linha são posicionados por índice de coluna;
# derivar do nome evita que inserir uma coluna no meio desloque tudo em
# silêncio (o widget iria parar na célula errada, sem erro nenhum).
COL_PERCENTUAL = COLUNAS.index("% do capital")
COL_COTAS = COLUNAS.index("Cotas")
COL_VALOR = COLUNAS.index("Valor distribuído")
COL_ORIGEM = COLUNAS.index("Origem")
COL_PRO_LABORE = COLUNAS.index("Pró-labore")
COL_IRRF = COLUNAS.index("IRRF")
COL_DATA_SAIDA = COLUNAS.index("Data de saída")
COL_PCT_DISTRIBUIDO = COLUNAS.index("% distribuído")
COL_EMPRESTIMO = COLUNAS.index("Empréstimo ao sócio")
COL_ADIANTAMENTO = COLUNAS.index("Adiantamento")
COL_EMPRESTIMO_FEITO = COLUNAS.index("Empréstimo do sócio")
COL_DEVOLUCAO = COLUNAS.index("Devolução de capital")
COL_SITUACAO = COLUNAS.index("Situação")
COLUNAS_EDITAVEIS = (COL_PERCENTUAL, COL_COTAS, COL_VALOR, COL_PRO_LABORE, COL_IRRF, COL_DATA_SAIDA)


class _DialogoDataVigencia(QDialog):
    """Uma data só, perguntada uma vez pra todo o lote de mudanças de %
    capital/cotas salvas junto na edição em linha — é a data efetiva da
    alteração contratual gerada por trás pra preservar o histórico."""

    def __init__(self, ano_base: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Data da alteração")
        self.setMinimumWidth(320)

        self.data = QDateEdit(calendarPopup=True)
        self.data.setDisplayFormat("dd/MM/yyyy")
        # sugere uma data dentro do ano que está sendo editado — "hoje" é
        # furada quando o ano em edição é passado: a mudança só passaria a
        # valer dali pra frente, e a tela desse ano continuaria mostrando o
        # valor antigo, parecendo que "não salvou nada".
        hoje = dt.date.today()
        data_padrao = hoje if ano_base == hoje.year else dt.date(ano_base, 12, 31)
        self.data.setDate(data_padrao)

        aviso = QLabel(
            f"Uma ou mais linhas mudaram % de capital ou cotas — isso gera uma alteração "
            f"contratual no histórico da empresa. A partir de quando essa mudança vale? Pra "
            f"aparecer na distribuição de {ano_base}, a data precisa cair dentro desse ano."
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

        self.tabela = TabelaLista(0, 3, coluna_flexivel=0)
        self.tabela.setHorizontalHeaderLabels(["Tipo", "Data", "Valor"])
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)

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
        self.tabela.ajustar_colunas()

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


class DistribuicaoAnualView(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._linhas: list[dict] = []
        self._cores: dict[int, int] = {}

        # ---- empresa e ano
        self.empresa = SeletorEmpresa()
        self.empresa.currentIndexChanged.connect(lambda _: self._carregar())

        self.ano = QSpinBox()
        self.ano.setRange(2000, 2100)
        # Abre no ano corrente — ou, se ele ainda não tem nada lançado, no
        # último ano com distribuição: abrir num ano vazio parecia que os
        # dados não estavam lá.
        hoje = dt.date.today().year
        ultimo = repo.ultimo_ano_com_distribuicao(conn)
        self.ano.setValue(ultimo if ultimo and ultimo < hoje else hoje)
        self.ano.setMinimumWidth(90)
        self.ano.valueChanged.connect(lambda _: self._carregar())
        self.btn_ano_anterior = QPushButton("‹")
        self.btn_ano_anterior.setProperty("role", "chevron")
        self.btn_ano_anterior.setToolTip("Ano anterior")
        self.btn_ano_anterior.clicked.connect(lambda: self.ano.setValue(self.ano.value() - 1))
        self.btn_ano_proximo = QPushButton("›")
        self.btn_ano_proximo.setProperty("role", "chevron")
        self.btn_ano_proximo.setToolTip("Próximo ano")
        self.btn_ano_proximo.clicked.connect(lambda: self.ano.setValue(self.ano.value() + 1))

        rotulo_empresa = QLabel("EMPRESA")
        rotulo_empresa.setProperty("role", "rotuloCampo")
        rotulo_ano = QLabel("ANO")
        rotulo_ano.setProperty("role", "rotuloCampo")
        coluna_empresa = QVBoxLayout()
        coluna_empresa.setSpacing(3)
        coluna_empresa.addWidget(rotulo_empresa)
        coluna_empresa.addWidget(self.empresa)
        coluna_ano = QVBoxLayout()
        coluna_ano.setSpacing(3)
        coluna_ano.addWidget(rotulo_ano, 0, Qt.AlignHCenter)
        coluna_ano.addWidget(navegador_ano(self.ano, self.btn_ano_anterior, self.btn_ano_proximo))
        topo = QHBoxLayout()
        topo.setSpacing(16)
        topo.addLayout(coluna_empresa, 1)
        topo.addLayout(coluna_ano)

        # ---- painel de destaque: os números do ano e a rosca
        self._periodo_fechado = False
        self.rotulo_trancamento = QLabel()
        self.rotulo_trancamento.setProperty("role", "heroNota")
        self.btn_trancar = QPushButton()
        self.btn_trancar.setCursor(Qt.PointingHandCursor)
        self.btn_trancar.clicked.connect(self._alternar_trancamento)

        self.selo_ano = QLabel()
        self.selo_ano.setProperty("role", "heroAno")
        bloco_total, self.valor_total, self.resumo = kpi("Lucro distribuído", grande=True)
        self.resumo.setMaximumWidth(460)
        bloco_pro, self.valor_pro_labore, _ = kpi("Pró-labore")
        bloco_irrf, self.valor_irrf, _ = kpi("IRRF retido")
        bloco_socios, self.valor_socios, self.nota_socios = kpi("Sócios no ano")
        bloco_capital, self.valor_capital, self.info_capital = kpi("Capital social")
        menores = QHBoxLayout()
        menores.setSpacing(26)
        for bloco in (bloco_pro, bloco_irrf, bloco_socios, bloco_capital):
            menores.addWidget(bloco)
        menores.addStretch()

        linha_tranca = QHBoxLayout()
        linha_tranca.addWidget(bloco_total, 1)
        coluna_tranca = QVBoxLayout()
        coluna_tranca.addWidget(self.btn_trancar, 0, Qt.AlignRight)
        coluna_tranca.addWidget(self.rotulo_trancamento, 0, Qt.AlignRight)
        coluna_tranca.addStretch()
        linha_tranca.addLayout(coluna_tranca)

        numeros = QVBoxLayout()
        numeros.setSpacing(14)
        numeros.addWidget(self.selo_ano, 0, Qt.AlignLeft)
        numeros.addLayout(linha_tranca)
        numeros.addLayout(menores)

        self.rosca = Rosca()
        self.legenda = QVBoxLayout()
        self.legenda.setSpacing(4)
        coluna_legenda = QVBoxLayout()
        coluna_legenda.addStretch()
        coluna_legenda.addLayout(self.legenda)
        coluna_legenda.addStretch()

        self.hero = QFrame()
        self.hero.setProperty("role", "hero")
        dentro_hero = QHBoxLayout(self.hero)
        dentro_hero.setContentsMargins(28, 22, 28, 22)
        dentro_hero.setSpacing(26)
        dentro_hero.addLayout(numeros, 3)
        dentro_hero.addWidget(divisor_hero())
        dentro_hero.addWidget(self.rosca, 0, Qt.AlignVCenter)
        dentro_hero.addLayout(coluna_legenda, 2)

        # ---- avisos
        self.aviso_cotas = QLabel()
        self.aviso_cotas.setProperty("role", "alerta")
        self.aviso_cotas.setWordWrap(True)
        self.aviso_cotas.hide()
        self.aviso_percentual = QLabel()
        self.aviso_percentual.setProperty("role", "alerta")
        self.aviso_percentual.setWordWrap(True)
        self.aviso_percentual.hide()

        # ---- tabela dos sócios
        self.titulo_tabela = QLabel()
        self.titulo_tabela.setProperty("role", "secao")

        self.tabela = TabelaLista(0, len(COLUNAS), coluna_flexivel=0,
                                  mensagem_vazia="Nenhum sócio nesta empresa neste ano.")
        self.tabela.setHorizontalHeaderLabels(COLUNAS)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela.verticalHeader().setDefaultSectionSize(56)
        self.tabela.horizontalHeaderItem(0).setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tabela.setItemDelegateForColumn(0, DelegadoSocio(self.tabela))
        self.tabela.setItemDelegateForColumn(COL_PERCENTUAL, DelegadoPercentual(self.tabela))
        self.tabela.setItemDelegateForColumn(COL_PCT_DISTRIBUIDO, DelegadoPercentual(self.tabela))
        self.tabela.setItemDelegateForColumn(COL_SITUACAO, DelegadoEtiqueta(self.tabela))
        self.tabela.itemSelectionChanged.connect(self._atualizar_disponibilidade_botoes)
        self.tabela.cellDoubleClicked.connect(lambda *_: self.btn_editar.isEnabled() and self._iniciar_edicao())

        self._editando = False
        self._widgets_edicao: list[dict] = []

        self.btn_editar = QPushButton("Editar valores")
        self.btn_editar.setProperty("role", "primario")
        self.btn_editar.clicked.connect(self._iniciar_edicao)
        self.btn_salvar_edicao = QPushButton("Salvar")
        self.btn_salvar_edicao.setProperty("role", "primario")
        self.btn_salvar_edicao.clicked.connect(self._salvar_edicao)
        self.btn_cancelar_edicao = QPushButton("Cancelar")
        self.btn_cancelar_edicao.clicked.connect(self._cancelar_edicao)
        self.btn_movimentacoes = QPushButton("Movimentações do sócio")
        self.btn_movimentacoes.setToolTip("Empréstimos, adiantamentos e devoluções entre a empresa e o sócio selecionado.")
        self.btn_movimentacoes.clicked.connect(self._gerenciar_movimentacoes)
        self.btn_exportar_modelo = QPushButton("Exportar modelo")
        self.btn_exportar_modelo.clicked.connect(self._exportar_modelo)
        self.btn_importar = QPushButton("Importar planilha")
        self.btn_importar.clicked.connect(self._importar_planilha)

        cabecalho_tabela = QHBoxLayout()
        cabecalho_tabela.setSpacing(8)
        cabecalho_tabela.addWidget(self.titulo_tabela, 1)
        for botao in (self.btn_movimentacoes, self.btn_exportar_modelo, self.btn_importar,
                      self.btn_cancelar_edicao, self.btn_salvar_edicao, self.btn_editar):
            cabecalho_tabela.addWidget(botao)

        # Ajuda da edição: dividir um total pelo % do capital.
        self.total_para_dividir = QDoubleSpinBox()
        self.total_para_dividir.setMaximum(1_000_000_000)
        self.total_para_dividir.setDecimals(2)
        self.total_para_dividir.setPrefix("R$ ")
        formatar_numero(self.total_para_dividir)
        self.total_para_dividir.setMinimumWidth(170)
        self.btn_dividir = QPushButton("Dividir pelo % do capital")
        self.btn_dividir.setToolTip(
            "Reparte o valor entre os sócios ativos, na proporção do % do capital de cada um. "
            "Os centavos do arredondamento vão pro sócio de maior fatia."
        )
        self.btn_dividir.clicked.connect(self._dividir_pelo_percentual)
        self.total_digitado = QLabel()
        self.total_digitado.setProperty("role", "valorCampo")
        rotulo_dividir = QLabel("Lucro do ano a distribuir")
        rotulo_dividir.setProperty("role", "subtitulo")
        self.barra_ajuda = QFrame()
        self.barra_ajuda.setProperty("role", "barraAjuda")
        linha_ajuda = QHBoxLayout(self.barra_ajuda)
        linha_ajuda.setContentsMargins(12, 8, 12, 8)
        linha_ajuda.setSpacing(10)
        linha_ajuda.addWidget(rotulo_dividir)
        linha_ajuda.addWidget(self.total_para_dividir)
        linha_ajuda.addWidget(self.btn_dividir)
        linha_ajuda.addStretch()
        linha_ajuda.addWidget(self.total_digitado)
        self.barra_ajuda.hide()

        self._legenda_entrou = self._legenda("Entrou neste ano")
        self._legenda_saiu = self._legenda("Saiu neste ano")
        dica_tabela = QLabel("Dois cliques num sócio para editar.")
        dica_tabela.setProperty("role", "subtitulo")
        rodape = QHBoxLayout()
        rodape.addWidget(dica_tabela, 1)
        rodape.addWidget(self._legenda_entrou)
        rodape.addWidget(self._legenda_saiu)

        self.bloco_tabela = QFrame()
        self.bloco_tabela.setProperty("role", "card")
        miolo = QVBoxLayout(self.bloco_tabela)
        miolo.setContentsMargins(20, 16, 20, 14)
        miolo.setSpacing(12)
        miolo.addLayout(cabecalho_tabela)
        miolo.addWidget(self.barra_ajuda)
        miolo.addWidget(self.tabela, 1)
        miolo.addLayout(rodape)

        coluna = QWidget()
        coluna.setMaximumWidth(1320)
        conteudo = QVBoxLayout(coluna)
        conteudo.setContentsMargins(0, 0, 0, 0)
        conteudo.setSpacing(14)
        conteudo.addLayout(topo)
        conteudo.addWidget(self.hero)
        conteudo.addWidget(self.aviso_cotas)
        conteudo.addWidget(self.aviso_percentual)
        conteudo.addWidget(self.bloco_tabela, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        layout.addWidget(coluna, 40)
        layout.addStretch(1)

        self._aplicar_cores()
        tema_estado().mudou.connect(self._aplicar_cores)
        tema_estado().mudou.connect(self._repintar_cores_dos_socios)
        self.atualizar()

    @staticmethod
    def _texto_origem(linha: dict) -> str:
        """De onde veio o valor distribuído da linha. Empresa que não lança
        por trimestre não tem essa distinção — fica com um traço, em vez de
        "manual", que sugeriria que existe uma alternativa automática."""
        if not linha["tem_trimestres"]:
            return "—"
        if linha["origem_valor"] == "trimestres":
            return "trimestres"
        return f"editado à mão (trimestres: R$ {formatar_valor_br(linha['acumulado_trimestral'])})"

    @staticmethod
    def _dica_origem(linha: dict) -> str:
        if not linha["tem_trimestres"]:
            return "Esta empresa não usa lançamento trimestral."
        if linha["origem_valor"] == "trimestres":
            return "Valor, pró-labore e IRRF são a soma dos trimestres lançados."
        return (
            "Algum dos três valores (distribuído, pró-labore ou IRRF) foi editado aqui e "
            "não bate mais com a soma dos trimestres. O próximo lançamento trimestral "
            "volta a sobrescrever."
        )

    def _legenda(self, texto: str) -> QLabel:
        rotulo = QLabel(f"●  {texto}")
        return rotulo

    def _aplicar_cores(self) -> None:
        self.barra_ajuda.setStyleSheet(f"QFrame[role=\"barraAjuda\"] {{ background: {ENTROU_BG()}; border-radius: 6px; border: none; }}")
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
        for row in range(self.tabela.rowCount()):
            for col in COLUNAS_EDITAVEIS:
                campo = self.tabela.cellWidget(row, col)
                if campo is not None:
                    campo.hide()
                self.tabela.removeCellWidget(row, col)
        empresa_id = self.empresa.currentData()
        ano_base = self.ano.value()
        self.titulo_tabela.setText(f"Sócios em {ano_base}")
        self.selo_ano.setText(f"Ano de {ano_base}")
        if empresa_id is None:
            self._linhas = []
            self._periodo_fechado = False
            self.tabela.setRowCount(0)
            self.valor_total.setText("—")
            self.resumo.setText("Cadastre uma empresa primeiro.")
            for rotulo in (self.valor_pro_labore, self.valor_irrf, self.valor_socios, self.valor_capital):
                rotulo.setText("—")
            self.info_capital.setText("")
            self.aviso_cotas.hide()
            self.aviso_percentual.hide()
            self.rotulo_trancamento.setText("")
            self.btn_trancar.setVisible(False)
            self.rosca.definir([], "", "")
            self._montar_legenda([])
            self._atualizar_disponibilidade_botoes()
            return

        self._periodo_fechado = repo.periodo_esta_fechado(self.conn, empresa_id, ano_base)
        self.btn_trancar.setVisible(True)
        self.btn_trancar.setProperty("trancado", "true" if self._periodo_fechado else "false")
        self.btn_trancar.style().unpolish(self.btn_trancar)
        self.btn_trancar.style().polish(self.btn_trancar)
        if self._periodo_fechado:
            self.btn_trancar.setText("🔒  Trancado · destrancar")
            self.rotulo_trancamento.setText(f"{ano_base} não aceita mudanças")
        else:
            self.btn_trancar.setText("🔓  Aberto · trancar período")
            self.rotulo_trancamento.setText("")

        self._linhas = repo.panorama_distribuicao_anual(self.conn, empresa_id, ano_base)
        self._cores = ordem_de_cores(self._linhas)
        total = repo.total_distribuido_empresa_ano(self.conn, empresa_id, ano_base)
        self.valor_total.setText(f"R$ {formatar_valor_br(total)}")
        self.valor_pro_labore.setText(f"R$ {formatar_valor_br(sum(l['pro_labore'] for l in self._linhas))}")
        self.valor_irrf.setText(f"R$ {formatar_valor_br(sum(l['irrf'] for l in self._linhas))}")
        ativos = sum(1 for l in self._linhas if l["data_saida"] is None)
        self.valor_socios.setText(str(ativos))
        mudancas = sum(1 for l in self._linhas if l["entrou_no_ano"] or l["saiu_no_ano"])
        self.nota_socios.setText(f"{mudancas} entrada(s)/saída(s) no ano" if mudancas else "sem mudança no ano")

        # Empresa que lança por trimestre tem o valor anual alimentado por lá;
        # dizer isso aqui evita a pergunta "de onde saiu esse número?" e avisa
        # que editar à mão vale só até o próximo lançamento trimestral.
        lancados = repo.trimestres_lancados(self.conn, empresa_id, ano_base)
        if lancados:
            trimestres = ", ".join(f"{t}º" for t in lancados)
            resumo = (
                f"em {ano_base} · acumulado dos trimestres lançados ({trimestres}) — "
                "editar aqui vale até o próximo lançamento na aba trimestral"
            )
        else:
            resumo = f"em {ano_base} · lançado direto nesta tela"
        self.resumo.setText(resumo)

        estado = repo.estado_empresa_no_periodo(self.conn, empresa_id, ano_base)
        self.valor_capital.setText(f"R$ {formatar_valor_br(estado['capital_fim'])}")
        if estado["variacao_capital"] > 0:
            self.info_capital.setText(f"▲ aumento de R$ {formatar_valor_br(estado['variacao_capital'])} no ano")
        elif estado["variacao_capital"] < 0:
            self.info_capital.setText(f"▼ redução de R$ {formatar_valor_br(abs(estado['variacao_capital']))} no ano")
        else:
            self.info_capital.setText("sem mudança no ano")

        fatias = [
            (l["valor_distribuido"], cor_da_vez(self._cores[l["socio_id"]]), l["socio_nome"])
            for l in sorted(self._linhas, key=lambda l: self._cores[l["socio_id"]])
        ]
        # Anima só ao trocar de empresa ou de ano: recarregar o mesmo (depois
        # de salvar, por exemplo) não precisa refazer o gráfico do zero.
        chave = (empresa_id, ano_base)
        fatias = agrupar_fatias(fatias)
        self.rosca.definir(fatias, f"R$ {_compacto(total)}" if total else "—",
                           f"distribuídos em {ano_base}" if total else "nada lançado",
                           animar=chave != getattr(self, "_chave_grafico", None))
        self._chave_grafico = chave
        self._montar_legenda(fatias)

        consistencia = repo.consistencia_cotas_socios(self.conn, empresa_id, ano_base)
        if consistencia["diferenca"] != 0:
            self.aviso_cotas.setText(
                f"⚠  As cotas totais da empresa ({formatar_valor_br(consistencia['cotas_totais_empresa'], 0)}) não conferem com a "
                f"soma das cotas dos sócios ({formatar_valor_br(consistencia['soma_cotas_socios'], 0)}). O capital ou as cotas da "
                f"empresa mudaram numa alteração contratual, mas não foram redistribuídas entre os sócios — "
                f"use Editar valores e corrija as cotas de cada um."
            )
            self.aviso_cotas.show()
        else:
            self.aviso_cotas.hide()

        consistencia_pct = repo.consistencia_percentual_socios(self.conn, empresa_id, ano_base)
        if round(consistencia_pct["diferenca"], 4) != 0:
            sinal = "falta" if consistencia_pct["diferenca"] > 0 else "sobra"
            self.aviso_percentual.setText(
                f"⚠  Os percentuais de capital dos sócios ativos somam {formatar_percentual(consistencia_pct['soma_percentual'])}, "
                f"não 100% ({sinal} {formatar_percentual(abs(consistencia_pct['diferenca']))[:-1]} p.p.). "
                f"Confira o cadastro societário desta empresa na aba Empresas."
            )
            self.aviso_percentual.show()
        else:
            self.aviso_percentual.hide()

        self.tabela.setRowCount(len(self._linhas))
        for row, linha in enumerate(self._linhas):
            situacao, tom = "Ativo", "ativo"
            if linha["reentrou_no_ano"]:
                situacao, tom = f"Reentrou em {formatar_data_br(linha['data_entrada'])}", "entrou"
            elif linha["saiu_no_ano"]:
                situacao, tom = "Saiu este ano", "saiu"
            elif linha["entrou_no_ano"]:
                situacao, tom = "Entrou este ano", "entrou"
            elif linha["data_saida"]:
                situacao, tom = f"Saiu em {formatar_data_br(linha['data_saida'])}", "neutro"

            valores = [
                linha["socio_nome"],
                formatar_percentual(linha["percentual_capital"]),
                formatar_valor_br(linha["quantidade_cotas"], 0),
                f"R$ {formatar_valor_br(linha['valor_distribuido'])}",
                self._texto_origem(linha),
                f"R$ {formatar_valor_br(linha['pro_labore'])}" if linha["pro_labore"] else "—",
                f"R$ {formatar_valor_br(linha['irrf'])}" if linha["irrf"] else "—",
                formatar_percentual(linha["percentual_distribuido"]),
                f"R$ {formatar_valor_br(linha['emprestimo_recebido'])}" if linha["emprestimo_recebido"] else "—",
                f"R$ {formatar_valor_br(linha['adiantamento'])}" if linha["adiantamento"] else "—",
                f"R$ {formatar_valor_br(linha['emprestimo_feito'])}" if linha["emprestimo_feito"] else "—",
                f"R$ {formatar_valor_br(linha['devolucao_capital'])}" if linha["devolucao_capital"] else "—",
                formatar_data_br(linha["data_saida"]),
                situacao,
            ]

            cor_socio = cor_da_vez(self._cores[linha["socio_id"]])
            for col, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                item.setData(Qt.UserRole, linha["socio_id"])
                item.setData(PAPEL_COR, cor_socio)
                if col == 0:
                    tipo = "CNPJ" if linha.get("socio_tipo_pessoa") == "juridica" else "CPF"
                    item.setData(PAPEL_DETALHE, f"{tipo} {linha['socio_cpf']}" if linha["socio_cpf"] else f"sem {tipo}")
                elif col == COL_PERCENTUAL:
                    item.setData(PAPEL_PERCENTUAL, linha["percentual_capital"])
                elif col == COL_PCT_DISTRIBUIDO:
                    item.setData(PAPEL_PERCENTUAL, linha["percentual_distribuido"])
                elif col == COL_SITUACAO:
                    item.setData(PAPEL_TOM, tom)
                if col == COL_ORIGEM:
                    item.setToolTip(self._dica_origem(linha))
                if col == COL_VALOR:
                    fonte = item.font()
                    fonte.setBold(True)
                    item.setFont(fonte)
                if col not in (0, COL_ORIGEM, COL_SITUACAO):
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabela.setItem(row, col, item)

        # Coluna sem o que mostrar some: menos colunas, mais fácil de ler.
        self.tabela.setColumnHidden(COL_ORIGEM, not any(l["tem_trimestres"] for l in self._linhas))
        self.tabela.setColumnHidden(COL_EMPRESTIMO, not any(l["emprestimo_recebido"] for l in self._linhas))
        self.tabela.setColumnHidden(COL_ADIANTAMENTO, not any(l["adiantamento"] for l in self._linhas))
        self.tabela.setColumnHidden(COL_EMPRESTIMO_FEITO, not any(l["emprestimo_feito"] for l in self._linhas))
        self.tabela.setColumnHidden(COL_DEVOLUCAO, not any(l["devolucao_capital"] for l in self._linhas))
        self.tabela.setColumnHidden(COL_DATA_SAIDA, not any(l["data_saida"] for l in self._linhas))
        self.tabela.ajustar_colunas()
        self._atualizar_disponibilidade_botoes()

    def _montar_legenda(self, fatias: list) -> None:
        while self.legenda.count():
            item = self.legenda.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()
                item.widget().deleteLater()
        total = sum(v for v, _c, _n in fatias)
        if not total:
            vazio = QLabel("Nenhum valor distribuído neste ano ainda.\nUse Editar valores para lançar.")
            vazio.setProperty("role", "heroNota")
            self.legenda.addWidget(vazio)
            return
        # Uma linha por fatia, compacta: com muitos sócios a legenda não pode
        # empurrar a tabela pra fora da tela.
        for valor, cor_fatia, nome in fatias:
            curto = nome if len(nome) <= 30 else nome[:29].rstrip() + "…"
            linha = QLabel(
                f'<span style="color:{cor_fatia.name()}; font-size:15px;">●</span>&nbsp; '
                f"<b>{curto}</b>&nbsp;&nbsp;"
                f'<span style="color:{cor("HERO_MUTED")};">R$ {formatar_valor_br(valor)}'
                f" · {formatar_percentual(100 * valor / total)}</span>"
            )
            linha.setTextFormat(Qt.RichText)
            linha.setToolTip(nome)
            self.legenda.addWidget(linha)

    def _repintar_cores_dos_socios(self) -> None:
        if not self._editando:
            self._carregar()

    def _dividir_pelo_percentual(self) -> None:
        total = round(self.total_para_dividir.value(), 2)
        participantes = [
            (row, l) for row, l in enumerate(self._linhas)
            if (l["percentual_capital"] or 0) > 0 and l["data_saida"] is None
        ]
        soma = sum(l["percentual_capital"] for _r, l in participantes)
        if not participantes or not soma:
            QMessageBox.information(self, "Dividir pelo % do capital", "Nenhum sócio ativo com % do capital.")
            return
        partes = {row: round(total * l["percentual_capital"] / soma, 2) for row, l in participantes}
        maior = max(participantes, key=lambda p: p[1]["percentual_capital"])[0]
        partes[maior] = round(partes[maior] + total - sum(partes.values()), 2)
        for row, campos in enumerate(self._widgets_edicao):
            if row in partes:
                campos["valor"].setValue(partes[row])
        self._mostrar_total_digitado()

    def _mostrar_total_digitado(self, *_args) -> None:
        total = sum(c["valor"].value() for c in self._widgets_edicao)
        self.total_digitado.setText(f"Soma dos sócios: R$ {formatar_valor_br(total)}")

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
        self.btn_ano_anterior.setEnabled(not self._editando and self.ano.value() > self.ano.minimum())
        self.btn_ano_proximo.setEnabled(not self._editando and self.ano.value() < self.ano.maximum())
        self.btn_trancar.setEnabled(not self._editando)
        self.barra_ajuda.setVisible(self._editando)

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

            pct = campo_percentual()
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

            self.tabela.setCellWidget(row, COL_PERCENTUAL, pct)
            self.tabela.setCellWidget(row, COL_COTAS, cotas)
            self.tabela.setCellWidget(row, COL_VALOR, valor)
            self.tabela.setCellWidget(row, COL_PRO_LABORE, pro_labore)
            self.tabela.setCellWidget(row, COL_IRRF, irrf)
            self.tabela.setCellWidget(row, COL_DATA_SAIDA, saida)

            self._widgets_edicao.append(
                {"percentual": pct, "cotas": cotas, "valor": valor, "pro_labore": pro_labore, "irrf": irrf, "data_saida": saida}
            )

        # A data de saída aparece na edição mesmo se ninguém saiu: é por ela
        # que se registra uma saída.
        self.tabela.setColumnHidden(COL_DATA_SAIDA, False)
        larguras = self.tabela._larguras_base()
        for col, largura in ((COL_PERCENTUAL, 120), (COL_COTAS, 110), (COL_VALOR, 150),
                             (COL_PRO_LABORE, 140), (COL_IRRF, 140), (COL_DATA_SAIDA, 130)):
            larguras[col] = max(larguras[col], largura)
        self.tabela._larguras_do_conteudo = larguras
        self.tabela._distribuir_sobra()

        for campos in self._widgets_edicao:
            campos["valor"].valueChanged.connect(self._mostrar_total_digitado)
        self.total_para_dividir.setValue(sum(l["valor_distribuido"] for l in self._linhas))
        self._mostrar_total_digitado()
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
            dialogo_data = _DialogoDataVigencia(ano_base, self)
            if dialogo_data.exec() != QDialog.Accepted:
                return
            data_vigencia = dialogo_data.data.date().toString("yyyy-MM-dd")
            if not (f"{ano_base}-01-01" <= data_vigencia <= f"{ano_base}-12-31"):
                resposta = QMessageBox.question(
                    self, "Data fora do ano",
                    f"A data escolhida ({dialogo_data.data.date().toString('dd/MM/yyyy')}) não está dentro de "
                    f"{ano_base} — o novo percentual/cotas vai valer a partir dela, mas essa tela continuará "
                    f"mostrando os valores de {ano_base} até essa data chegar (ou já ter passado, se for antes "
                    f"do ano). Quer continuar mesmo assim?",
                )
                if resposta != QMessageBox.Yes:
                    return

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
        # Mesmo motivo da aba trimestral: o período vai no título da janela
        # de arquivo, que é onde a pessoa está olhando na hora de importar.
        caminho, _ = QFileDialog.getOpenFileName(
            self,
            f"Importar planilha — {self.ano.value()} — {self.empresa.currentText()}",
            "",
            "Planilhas (*.xlsx *.csv)",
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
        ativos = {l["socio_id"] for l in self._linhas if l["data_saida"] is None}
        resolvidos, pendencias = associar_linhas(self.conn, linhas_importadas, ativos, f"em {ano_base}")

        if pendencias:
            dialogo = DialogoRevisaoImportacao(self.conn, pendencias, self)
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
