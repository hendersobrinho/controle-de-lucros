"""Painel de distribuição trimestral: para uma empresa/ano/trimestre, lança o
que cada sócio recebeu naquele pedaço do ano.

Nem toda empresa distribui por trimestre — quem não usa esta tela continua
lançando só o valor anual na aba de Distribuição anual, e nada muda. Para
quem usa, cada gravação aqui reescreve a distribuição anual do sócio com a
soma dos trimestres lançados: o anual vai acumulando sozinho em vez de
alguém ter que somar à mão no fim do ano (e o informe de rendimentos, que lê
o anual, acompanha).
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
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
from ..models import TRIMESTRES, TRIMESTRES_LABEL
from ..planilha import exportar_modelo_distribuicao, importar_distribuicao
from .importacao_distribuicao import DialogoRevisaoImportacao, associar_linhas
from .common import (
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
    BarrasTrimestres,
    agrupar_fatias,
    DelegadoEtiqueta,
    DelegadoPercentual,
    DelegadoSocio,
    cor_da_vez,
    divisor_hero,
    kpi,
    navegador_ano,
    ordem_de_cores,
)
from .theme import ENTROU_BG, ENTROU_FG, SAIU_FG
from .theme import estado as tema_estado

COLUNAS = [
    "Sócio",
    "% do capital",
    "Valor do trimestre",
    "Pró-labore",
    "IRRF",
    "Acumulado no ano",
    "Situação",
]

COL_VALOR = COLUNAS.index("Valor do trimestre")
COL_PRO_LABORE = COLUNAS.index("Pró-labore")
COL_IRRF = COLUNAS.index("IRRF")
COLUNAS_EDITAVEIS = (COL_VALOR, COL_PRO_LABORE, COL_IRRF)


MESES_TRIMESTRE = {1: "janeiro a março", 2: "abril a junho", 3: "julho a setembro", 4: "outubro a dezembro"}


class DistribuicaoTrimestralView(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._linhas: list[dict] = []
        self._editando = False
        self._widgets_edicao: list[dict] = []
        self._periodo_fechado = False

        # ---- empresa e ano
        self.empresa = SeletorEmpresa()
        self.empresa.currentIndexChanged.connect(lambda _: self._carregar())
        self.empresa.setMinimumWidth(160)

        self.ano = QSpinBox()
        self.ano.setRange(2000, 2100)
        self.ano.setValue(dt.date.today().year)
        self.ano.setMinimumWidth(96)
        self.ano.valueChanged.connect(lambda _: self._carregar())

        # O trimestre escolhido mora aqui (os cartões só o mudam); fica fora
        # da tela, porque a faixa do ano já mostra os quatro.
        self.trimestre = QComboBox()
        for numero in TRIMESTRES:
            self.trimestre.addItem(TRIMESTRES_LABEL[numero], numero)
        self.trimestre.setCurrentIndex(self._trimestre_corrente() - 1)
        self.trimestre.currentIndexChanged.connect(lambda _: self._carregar())
        self.trimestre.hide()

        rotulo_empresa = QLabel("EMPRESA")
        rotulo_empresa.setProperty("role", "rotuloCampo")
        rotulo_ano = QLabel("ANO")
        rotulo_ano.setProperty("role", "rotuloCampo")
        coluna_empresa = QVBoxLayout()
        coluna_empresa.setSpacing(3)
        coluna_empresa.addWidget(rotulo_empresa)
        coluna_empresa.addWidget(self.empresa)
        self.btn_ano_anterior = QPushButton("‹")
        self.btn_ano_anterior.setProperty("role", "chevron")
        self.btn_ano_anterior.setToolTip("Ano anterior")
        self.btn_ano_anterior.clicked.connect(lambda: self.ano.setValue(self.ano.value() - 1))
        self.btn_ano_proximo = QPushButton("›")
        self.btn_ano_proximo.setProperty("role", "chevron")
        self.btn_ano_proximo.setToolTip("Próximo ano")
        self.btn_ano_proximo.clicked.connect(lambda: self.ano.setValue(self.ano.value() + 1))
        coluna_ano = QVBoxLayout()
        coluna_ano.setSpacing(3)
        coluna_ano.addWidget(rotulo_ano, 0, Qt.AlignHCenter)
        coluna_ano.addWidget(navegador_ano(self.ano, self.btn_ano_anterior, self.btn_ano_proximo))
        topo = QHBoxLayout()
        topo.setSpacing(16)
        topo.addLayout(coluna_empresa, 1)
        topo.addLayout(coluna_ano)

        # ---- painel de destaque: o ano em barras, um trimestre por coluna,
        # empilhado por sócio (na cor de cada um), e o total que vai pro anual.
        self.grafico = BarrasTrimestres()
        self.grafico.clicado.connect(self._escolher_trimestre)

        self.selo_ano = QLabel()
        self.selo_ano.setProperty("role", "heroAno")
        bloco_total, self.total_ano, self.nota_total = kpi("Total do ano", grande=True)
        self.nota_total.setText("vai sozinho para a distribuição anual")
        bloco_lancados, self.valor_lancados, self.nota_lancados = kpi("Trimestres lançados")
        bloco_media, self.valor_media, _ = kpi("Média por trimestre")
        self.progresso = QLabel()
        self.progresso.setProperty("role", "heroNota")
        self.progresso.setWordWrap(True)
        menores = QHBoxLayout()
        menores.setSpacing(24)
        menores.addWidget(bloco_lancados)
        menores.addWidget(bloco_media)
        menores.addStretch()
        numeros = QVBoxLayout()
        numeros.setSpacing(12)
        numeros.addWidget(self.selo_ano, 0, Qt.AlignLeft)
        numeros.addWidget(bloco_total)
        numeros.addLayout(menores)
        numeros.addWidget(self.progresso)
        numeros.addStretch()

        self.hero = QFrame()
        self.hero.setProperty("role", "hero")
        dentro_hero = QHBoxLayout(self.hero)
        dentro_hero.setContentsMargins(24, 18, 28, 18)
        dentro_hero.setSpacing(24)
        dentro_hero.addWidget(self.grafico, 3)
        dentro_hero.addWidget(divisor_hero())
        dentro_hero.addLayout(numeros, 2)
        self.hero.setMinimumHeight(250)

        # As setas andam um trimestre por vez e atravessam a virada do ano: o
        # anterior ao 1º de 2025 é o 4º de 2024.
        self.btn_anterior = QPushButton("‹")
        self.btn_anterior.setProperty("role", "chevron")
        self.btn_anterior.setToolTip("Trimestre anterior")
        self.btn_anterior.clicked.connect(lambda: self._navegar_trimestre(-1))
        self.btn_proximo = QPushButton("›")
        self.btn_proximo.setProperty("role", "chevron")
        self.btn_proximo.setToolTip("Próximo trimestre")
        self.btn_proximo.clicked.connect(lambda: self._navegar_trimestre(1))

        # ---- o trimestre escolhido, num bloco só
        self.resumo = QLabel()
        self.resumo.setProperty("role", "titulo")
        self.periodo = QLabel()
        self.periodo.setProperty("role", "subtitulo")
        titulo_bloco = QVBoxLayout()
        titulo_bloco.setSpacing(2)
        titulo_bloco.addWidget(self.resumo)
        titulo_bloco.addWidget(self.periodo)

        self.btn_editar = QPushButton("Lançar valores")
        self.btn_editar.setProperty("role", "primario")
        self.btn_editar.clicked.connect(self._iniciar_edicao)
        self.btn_salvar = QPushButton("Salvar trimestre")
        self.btn_salvar.setProperty("role", "primario")
        self.btn_salvar.clicked.connect(self._salvar_edicao)
        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.clicked.connect(self._cancelar_edicao)
        self.btn_limpar = QPushButton("Limpar trimestre")
        self.btn_limpar.setProperty("role", "perigo")
        self.btn_limpar.clicked.connect(self._limpar_trimestre)
        self.btn_exportar_modelo = QPushButton("Exportar modelo")
        self.btn_exportar_modelo.setToolTip("Planilha com os sócios deste trimestre, pra preencher fora e importar depois.")
        self.btn_exportar_modelo.clicked.connect(self._exportar_modelo)
        self.btn_importar = QPushButton("Importar planilha")
        self.btn_importar.setToolTip("Lança neste trimestre os valores de uma planilha no formato do modelo.")
        self.btn_importar.clicked.connect(self._importar_planilha)

        acoes = QHBoxLayout()
        acoes.setSpacing(8)
        acoes.addWidget(self.btn_anterior, 0, Qt.AlignVCenter)
        acoes.addLayout(titulo_bloco)
        acoes.addWidget(self.btn_proximo, 0, Qt.AlignVCenter)
        acoes.addStretch(1)
        for botao in (self.btn_exportar_modelo, self.btn_importar, self.btn_limpar,
                      self.btn_cancelar, self.btn_salvar, self.btn_editar):
            acoes.addWidget(botao, 0, Qt.AlignVCenter)

        self.aviso_trancado = QLabel()
        self.aviso_trancado.setWordWrap(True)
        self.aviso_trancado.hide()

        # ---- ajuda de lançamento: só aparece editando
        self.total_para_dividir = self._campo_dinheiro(0.0)
        self.total_para_dividir.setMinimumWidth(170)
        self.btn_dividir = QPushButton("Dividir pelo % do capital")
        self.btn_dividir.setToolTip(
            "Reparte o valor entre os sócios que estão na empresa, na proporção do % do capital de "
            "cada um. Os centavos que sobram do arredondamento vão pro sócio de maior fatia."
        )
        self.btn_dividir.clicked.connect(self._dividir_pelo_percentual)
        self.total_digitado = QLabel()
        self.total_digitado.setProperty("role", "valorCampo")
        rotulo_dividir = QLabel("Valor total do trimestre")
        rotulo_dividir.setProperty("role", "subtitulo")
        self.barra_ajuda = QWidget()
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

        self.tabela = TabelaLista(0, len(COLUNAS), coluna_flexivel=0,
                                  mensagem_vazia="Nenhum sócio na empresa neste trimestre.")
        self.tabela.setHorizontalHeaderLabels(COLUNAS)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela.verticalHeader().setDefaultSectionSize(56)
        self.tabela.horizontalHeaderItem(0).setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.tabela.setItemDelegateForColumn(0, DelegadoSocio(self.tabela))
        self.tabela.setItemDelegateForColumn(COLUNAS.index("% do capital"), DelegadoPercentual(self.tabela))
        self.tabela.setItemDelegateForColumn(COLUNAS.index("Situação"), DelegadoEtiqueta(self.tabela))
        # Dois cliques num sócio já abrem o lançamento.
        self.tabela.cellDoubleClicked.connect(lambda *_: self.btn_editar.isEnabled() and self._iniciar_edicao())

        self.rodape = QLabel()
        self.rodape.setProperty("role", "subtitulo")
        self._legenda_entrou = QLabel("●  Entrou neste trimestre")
        self._legenda_saiu = QLabel("●  Saiu neste trimestre")
        linha_rodape = QHBoxLayout()
        linha_rodape.addWidget(self.rodape, 1)
        linha_rodape.addWidget(self._legenda_entrou)
        linha_rodape.addWidget(self._legenda_saiu)

        self.bloco_trimestre = QFrame()
        self.bloco_trimestre.setProperty("role", "card")
        miolo = QVBoxLayout(self.bloco_trimestre)
        miolo.setContentsMargins(20, 16, 20, 14)
        miolo.setSpacing(12)
        miolo.addLayout(acoes)
        miolo.addWidget(self.aviso_trancado)
        miolo.addWidget(self.barra_ajuda)
        miolo.addWidget(self.tabela, 1)
        miolo.addLayout(linha_rodape)

        coluna = QWidget()
        coluna.setMaximumWidth(1320)
        conteudo = QVBoxLayout(coluna)
        conteudo.setContentsMargins(0, 0, 0, 0)
        conteudo.setSpacing(12)
        conteudo.addLayout(topo)
        conteudo.addWidget(self.hero)
        conteudo.addWidget(self.bloco_trimestre, 1)
        conteudo.addWidget(self.trimestre)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        layout.addWidget(coluna, 30)
        layout.addStretch(1)

        self._aplicar_cores()
        tema_estado().mudou.connect(self._aplicar_cores)
        # As cores dos sócios mudam com o tema: redesenha (fora da edição).
        tema_estado().mudou.connect(lambda: None if self._editando else self._carregar())
        self.atualizar()

    def _escolher_trimestre(self, trimestre: int) -> None:
        if not self._editando and trimestre != self.trimestre.currentData():
            self.trimestre.setCurrentIndex(trimestre - 1)

    @staticmethod
    def _trimestre_corrente() -> int:
        return (dt.date.today().month - 1) // 3 + 1

    def _posicao_na_linha_do_tempo(self) -> int:
        """Ano e trimestre viram um número só, pra andar de um em um sem
        tratar a virada de ano como caso especial."""
        return self.ano.value() * 4 + (self.trimestre.currentData() - 1)

    def _limites_da_linha_do_tempo(self) -> tuple[int, int]:
        return self.ano.minimum() * 4, self.ano.maximum() * 4 + 3

    def _navegar_trimestre(self, passo: int) -> None:
        primeiro, ultimo = self._limites_da_linha_do_tempo()
        destino = self._posicao_na_linha_do_tempo() + passo
        if not (primeiro <= destino <= ultimo):
            return

        ano, trimestre = divmod(destino, 4)
        # Um recarregamento só: sem bloquear os sinais, mudar ano e trimestre
        # dispararia _carregar duas vezes, e a tela piscaria o período errado
        # no meio do caminho.
        self.ano.blockSignals(True)
        self.trimestre.blockSignals(True)
        self.ano.setValue(ano)
        self.trimestre.setCurrentIndex(trimestre)
        self.ano.blockSignals(False)
        self.trimestre.blockSignals(False)
        self._carregar()

    def _aplicar_cores(self) -> None:
        self.barra_ajuda.setStyleSheet(f"QWidget[role=\"barraAjuda\"] {{ background: {ENTROU_BG()}; border-radius: 6px; }}")
        self.aviso_trancado.setProperty("role", "alerta")
        self._legenda_entrou.setStyleSheet(
            f"color: {ENTROU_FG()}; font-size: 11px; font-weight: 600; padding-left: 12px;"
        )
        self._legenda_saiu.setStyleSheet(
            f"color: {SAIU_FG()}; font-size: 11px; font-weight: 600; padding-left: 12px;"
        )

    # ----------------------------------------------------------- carregar --
    def atualizar(self) -> None:
        empresa_anterior = self.empresa.currentData()
        preencher_combo(self.empresa, repo.listar_empresas(self.conn))
        if empresa_anterior is not None:
            idx = self.empresa.findData(empresa_anterior)
            if idx >= 0:
                self.empresa.setCurrentIndex(idx)
        self._carregar()

    def selecionar_empresa(self, empresa_id: int) -> None:
        idx = self.empresa.findData(empresa_id)
        if idx >= 0 and idx != self.empresa.currentIndex():
            self.empresa.setCurrentIndex(idx)

    def _carregar(self) -> None:
        self._editando = False
        self._widgets_edicao = []
        for row in range(self.tabela.rowCount()):
            for col in COLUNAS_EDITAVEIS:
                # Esconde já: o campo só é apagado na volta ao laço de
                # eventos, e até lá ficava desenhado por cima da tabela.
                campo = self.tabela.cellWidget(row, col)
                if campo is not None:
                    campo.hide()
                self.tabela.removeCellWidget(row, col)

        empresa_id = self.empresa.currentData()
        if empresa_id is None:
            self._linhas = []
            self._periodo_fechado = False
            self.tabela.setRowCount(0)
            self.resumo.setText("Cadastre uma empresa primeiro.")
            self.progresso.setText("")
            self.aviso_trancado.hide()
            self._atualizar_disponibilidade_botoes()
            return

        ano_base = self.ano.value()
        trimestre = self.trimestre.currentData()
        self._periodo_fechado = repo.periodo_esta_fechado(self.conn, empresa_id, ano_base)
        if self._periodo_fechado:
            self.aviso_trancado.setText(
                f"🔒 O período de {ano_base} está trancado. Destranque-o na aba de Distribuição "
                "anual para lançar trimestres."
            )
            self.aviso_trancado.show()
        else:
            self.aviso_trancado.hide()

        self._linhas = repo.panorama_distribuicao_trimestral(self.conn, empresa_id, ano_base, trimestre)
        total = repo.total_distribuido_trimestre(self.conn, empresa_id, ano_base, trimestre)
        self.resumo.setText(f"{trimestre}º trimestre de {ano_base}")

        lancados = repo.trimestres_lancados(self.conn, empresa_id, ano_base)
        hoje = dt.date.today()
        atual = (hoje.year, (hoje.month - 1) // 3 + 1)
        # Cor de cada sócio pelo ano inteiro (não só por este trimestre): quem
        # saiu no 1º continua com a mesma cor na barra do 1º.
        do_ano = repo.panorama_distribuicao_anual(self.conn, empresa_id, ano_base)
        self._cores = ordem_de_cores(do_ano or self._linhas)
        nomes = {l["socio_id"]: l["socio_nome"] for l in do_ano + self._linhas}
        colunas = {}
        for t in TRIMESTRES:
            lancamentos = repo.listar_distribuicoes_trimestrais(self.conn, empresa_id, ano_base, t)
            colunas[t] = agrupar_fatias([
                (d.valor_distribuido, cor_da_vez(self._cores.get(d.socio_id, len(self._cores))), nomes.get(d.socio_id, "?"))
                for d in sorted(lancamentos, key=lambda d: self._cores.get(d.socio_id, 99))
                if d.valor_distribuido
            ], limite=8)
        futuros = {t for t in TRIMESTRES if (ano_base, t) > atual}
        chave = (empresa_id, ano_base)
        self.grafico.definir(colunas, trimestre, futuros, animar=chave != getattr(self, "_chave_grafico", None))
        self._chave_grafico = chave
        total_ano = sum(self.grafico.total(t) for t in TRIMESTRES)
        self.selo_ano.setText(f"Ano de {ano_base}")
        self.total_ano.setText(f"R$ {formatar_valor_br(total_ano)}")
        self.valor_lancados.setText(f"{len(lancados)} de 4")
        self.nota_lancados.setText(", ".join(f"{t}º" for t in lancados) if lancados else "nenhum ainda")
        self.valor_media.setText(f"R$ {formatar_valor_br(total_ano / len(lancados))}" if lancados else "—")
        situacao_trimestre = "lançado" if trimestre in lancados else "ainda sem lançamento"
        self.periodo.setText(f"{MESES_TRIMESTRE[trimestre]} · {situacao_trimestre}")
        # Somar as linhas da tela daria um total menor: um sócio que saiu no 1º
        # trimestre não aparece na lista do 4º, mas o que ele recebeu continua
        # fazendo parte do acumulado do ano.
        somas = repo.acumulado_trimestral(self.conn, empresa_id, ano_base, ate_trimestre=trimestre)
        acumulado_ano = sum(s["valor_distribuido"] for s in somas.values())
        if lancados:
            texto = (
                f"Trimestres lançados em {ano_base}: "
                + ", ".join(f"{t}º" for t in lancados)
                + f"  ·  acumulado até o {trimestre}º: R$ {formatar_valor_br(acumulado_ano)}"
            )
        else:
            texto = (
                f"Nenhum trimestre lançado em {ano_base}. Enquanto não houver lançamento aqui, "
                "a distribuição anual desta empresa continua sendo a digitada na aba anual."
            )
        self.progresso.setText(texto)

        self.tabela.setRowCount(len(self._linhas))
        for row, linha in enumerate(self._linhas):
            situacao = "Ativo"
            if linha["saiu_no_trimestre"]:
                situacao = f"Saiu em {formatar_data_br(linha['data_saida'])}"
            elif linha["entrou_no_trimestre"]:
                situacao = "Entrou neste trimestre"
            elif linha["data_saida"]:
                situacao = f"Saiu em {formatar_data_br(linha['data_saida'])}"

            tom = "saiu" if linha["saiu_no_trimestre"] else "entrou" if linha["entrou_no_trimestre"] else (
                "neutro" if linha["data_saida"] else "ativo")
            valores = [
                linha["socio_nome"],
                formatar_percentual(linha["percentual_capital"]),
                f"R$ {formatar_valor_br(linha['valor_distribuido'])}" if linha["registro_id"] else "—",
                f"R$ {formatar_valor_br(linha['pro_labore'])}" if linha["pro_labore"] else "—",
                f"R$ {formatar_valor_br(linha['irrf'])}" if linha["irrf"] else "—",
                f"R$ {formatar_valor_br(linha['acumulado_valor'])}",
                situacao,
            ]

            cor_socio = cor_da_vez(self._cores.get(linha["socio_id"], 0))
            for col, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                item.setData(Qt.UserRole, linha["socio_id"])
                item.setData(PAPEL_COR, cor_socio)
                if col == 0:
                    item.setData(PAPEL_DETALHE, f"CPF/CNPJ {linha['socio_cpf']}" if linha["socio_cpf"] else "sem documento")
                elif col == 1:
                    item.setData(PAPEL_PERCENTUAL, linha["percentual_capital"])
                elif col == len(valores) - 1:
                    item.setData(PAPEL_TOM, tom)
                if col == COL_VALOR:
                    fonte = item.font()
                    fonte.setBold(True)
                    item.setFont(fonte)
                if 1 <= col < len(valores) - 1:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabela.setItem(row, col, item)
        self.tabela.ajustar_colunas()
        pro_labore = sum(l["pro_labore"] for l in self._linhas)
        irrf = sum(l["irrf"] for l in self._linhas)
        self.rodape.setText(
            f"Distribuído no trimestre: R$ {formatar_valor_br(total)}"
            + (f"  ·  pró-labore R$ {formatar_valor_br(pro_labore)}" if pro_labore else "")
            + (f"  ·  IRRF R$ {formatar_valor_br(irrf)}" if irrf else "")
        )
        self._atualizar_disponibilidade_botoes()

    def _atualizar_disponibilidade_botoes(self) -> None:
        tem_empresa = self.empresa.currentData() is not None
        editavel = tem_empresa and not self._periodo_fechado and bool(self._linhas)
        algum_lancamento = any(l["registro_id"] is not None for l in self._linhas)

        self.btn_editar.setVisible(not self._editando)
        self.btn_salvar.setVisible(self._editando)
        self.btn_cancelar.setVisible(self._editando)
        self.btn_editar.setEnabled(editavel)
        self.btn_limpar.setVisible(not self._editando)
        self.btn_limpar.setEnabled(editavel and algum_lancamento)
        self.btn_exportar_modelo.setEnabled(tem_empresa and bool(self._linhas) and not self._editando)
        self.btn_importar.setEnabled(editavel and not self._editando)

        self.empresa.setEnabled(not self._editando)
        self.ano.setEnabled(not self._editando)
        self.btn_ano_anterior.setEnabled(not self._editando and self.ano.value() > self.ano.minimum())
        self.btn_ano_proximo.setEnabled(not self._editando and self.ano.value() < self.ano.maximum())
        self.trimestre.setEnabled(not self._editando)

        primeiro, ultimo = self._limites_da_linha_do_tempo()
        posicao = self._posicao_na_linha_do_tempo()
        self.btn_anterior.setEnabled(not self._editando and posicao > primeiro)
        self.btn_proximo.setEnabled(not self._editando and posicao < ultimo)
        self.grafico.setEnabled(not self._editando)
        self.barra_ajuda.setVisible(self._editando)
        self.btn_editar.setText(
            "Editar valores" if any(l["registro_id"] is not None for l in self._linhas) else "Lançar valores"
        )

    # ------------------------------------------------------ edição em linha --
    def _campo_dinheiro(self, valor: float) -> QDoubleSpinBox:
        campo = QDoubleSpinBox()
        campo.setMaximum(1_000_000_000)
        campo.setDecimals(2)
        campo.setPrefix("R$ ")
        formatar_numero(campo)
        campo.setValue(valor)
        return campo

    def _iniciar_edicao(self) -> None:
        if not self._linhas:
            return
        self._editando = True
        self._widgets_edicao = []

        for row, linha in enumerate(self._linhas):
            campos = {
                "valor": self._campo_dinheiro(linha["valor_distribuido"]),
                "pro_labore": self._campo_dinheiro(linha["pro_labore"]),
                "irrf": self._campo_dinheiro(linha["irrf"]),
            }
            self.tabela.setCellWidget(row, COL_VALOR, campos["valor"])
            self.tabela.setCellWidget(row, COL_PRO_LABORE, campos["pro_labore"])
            self.tabela.setCellWidget(row, COL_IRRF, campos["irrf"])
            for campo in campos.values():
                campo.valueChanged.connect(self._mostrar_total_digitado)
            self._widgets_edicao.append(campos)

        # Pela tabela, e não coluna a coluna: ela redistribui as larguras a
        # cada redimensionamento e desfaria um setColumnWidth solto.
        larguras = self.tabela._larguras_base()
        for col in COLUNAS_EDITAVEIS:
            larguras[col] = max(larguras[col], 150)
        self.tabela._larguras_do_conteudo = larguras
        self.tabela._distribuir_sobra()
        altura = QDoubleSpinBox().sizeHint().height() + 8
        for row in range(len(self._linhas)):
            if self.tabela.rowHeight(row) < altura:
                self.tabela.setRowHeight(row, altura)

        self.total_para_dividir.setValue(sum(l["valor_distribuido"] for l in self._linhas))
        self._mostrar_total_digitado()
        self._atualizar_disponibilidade_botoes()
        if self._widgets_edicao:
            self._widgets_edicao[0]["valor"].setFocus()
            self._widgets_edicao[0]["valor"].selectAll()

    def _mostrar_total_digitado(self, *_args) -> None:
        total = sum(c["valor"].value() for c in self._widgets_edicao)
        self.total_digitado.setText(f"Soma dos sócios: R$ {formatar_valor_br(total)}")

    def _dividir_pelo_percentual(self) -> None:
        """Reparte o total pelo % do capital de quem está na empresa no fim
        do trimestre. É o caso comum — distribuição proporcional — e poupa a
        conta de cabeça de cada sócio; quem recebe diferente ajusta depois."""
        total = round(self.total_para_dividir.value(), 2)
        participantes = [
            (row, linha) for row, linha in enumerate(self._linhas)
            if (linha["percentual_capital"] or 0) > 0 and not linha["saiu_no_trimestre"]
        ]
        soma_percentual = sum(l["percentual_capital"] for _, l in participantes)
        if not participantes or not soma_percentual:
            QMessageBox.information(self, "Dividir pelo % do capital", "Nenhum sócio com % do capital neste trimestre.")
            return
        partes = {row: round(total * l["percentual_capital"] / soma_percentual, 2) for row, l in participantes}
        # Os centavos do arredondamento ficam com a maior fatia, pra soma bater.
        maior = max(participantes, key=lambda p: p[1]["percentual_capital"])[0]
        partes[maior] = round(partes[maior] + total - sum(partes.values()), 2)
        for row, campos in enumerate(self._widgets_edicao):
            campos["valor"].setValue(partes.get(row, 0.0))
        self._mostrar_total_digitado()

    def _cancelar_edicao(self) -> None:
        self._carregar()

    @staticmethod
    def _mudou(novo: float, antigo: float, tolerancia: float = 1e-6) -> bool:
        return abs((novo or 0) - (antigo or 0)) > tolerancia

    def _salvar_edicao(self) -> None:
        empresa_id = self.empresa.currentData()
        ano_base = self.ano.value()
        trimestre = self.trimestre.currentData()

        mudancas = []
        for row, linha in enumerate(self._linhas):
            campos = self._widgets_edicao[row]
            valor = campos["valor"].value()
            pro_labore = campos["pro_labore"].value()
            irrf = campos["irrf"].value()
            if (
                self._mudou(valor, linha["valor_distribuido"])
                or self._mudou(pro_labore, linha["pro_labore"])
                or self._mudou(irrf, linha["irrf"])
            ):
                mudancas.append((linha, valor, pro_labore, irrf))

        if not mudancas:
            self._carregar()
            return

        try:
            for linha, valor, pro_labore, irrf in mudancas:
                repo.salvar_distribuicao_trimestral(
                    self.conn, empresa_id, ano_base, trimestre, linha["socio_id"], valor, pro_labore, irrf
                )
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao salvar", str(exc))
            self._carregar()
            return

        self._carregar()
        QMessageBox.information(
            self,
            "Trimestre lançado",
            f"{len(mudancas)} sócio(s) atualizado(s) no {trimestre}º trimestre de {ano_base}.\n\n"
            "A distribuição anual desses sócios passou a mostrar a soma dos trimestres lançados.",
        )

    def _limpar_trimestre(self) -> None:
        """Apaga os lançamentos deste trimestre. O anual volta a ser a soma dos
        trimestres que sobraram — não fica com o valor antigo pendurado."""
        ano_base = self.ano.value()
        trimestre = self.trimestre.currentData()
        registros = [l for l in self._linhas if l["registro_id"] is not None]
        if not registros:
            return

        resposta = QMessageBox.question(
            self,
            "Limpar trimestre",
            f"Apagar os {len(registros)} lançamento(s) do {trimestre}º trimestre de {ano_base}?\n\n"
            "A distribuição anual desses sócios será recalculada com os trimestres que sobrarem.",
        )
        if resposta != QMessageBox.Yes:
            return
        try:
            for linha in registros:
                repo.excluir_distribuicao_trimestral(self.conn, linha["registro_id"])
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao limpar", str(exc))
        self._carregar()

    # ------------------------------------------------------------ planilha --
    def _rotulo_periodo(self) -> str:
        return f"no {self.trimestre.currentData()}º trimestre de {self.ano.value()}"

    def _exportar_modelo(self) -> None:
        """Mesmo formato da distribuição anual (CPF, Sócio, Valor, Pró-labore,
        IRRF) — a planilha é a mesma; o que muda é onde os valores são
        gravados. Sai preenchida com os sócios do trimestre e o que já foi
        lançado, pra servir também de conferência."""
        empresa_id = self.empresa.currentData()
        if empresa_id is None:
            return
        ano_base = self.ano.value()
        trimestre = self.trimestre.currentData()

        linhas = [
            {
                "cpf": linha["socio_cpf"],
                "nome": linha["socio_nome"],
                "valor_distribuido": linha["valor_distribuido"],
                "pro_labore": linha["pro_labore"],
                "irrf": linha["irrf"],
            }
            for linha in self._linhas
            if linha["data_saida"] is None or linha["saiu_no_trimestre"]
        ]
        if not linhas:
            QMessageBox.information(
                self, "Exportar modelo", "Não há sócios nesta empresa neste trimestre pra exportar."
            )
            return

        sugestao = f"distribuicao_{self.empresa.currentText()}_{ano_base}_T{trimestre}.xlsx".replace(" ", "_")
        caminho, _ = QFileDialog.getSaveFileName(
            self, "Exportar modelo do trimestre", sugestao, "Planilha Excel (*.xlsx)"
        )
        if not caminho:
            return
        if not caminho.lower().endswith(".xlsx"):
            caminho += ".xlsx"
        try:
            exportar_modelo_distribuicao(Path(caminho), linhas)
        except OSError as exc:
            QMessageBox.warning(self, "Erro ao exportar", str(exc))
            return
        QMessageBox.information(
            self,
            "Modelo exportado",
            f"{len(linhas)} sócio(s) do {trimestre}º trimestre de {ano_base} em:\n{caminho}\n\n"
            'A aba "Exemplo" da planilha mostra o preenchimento com dados fictícios.',
        )

    def _importar_planilha(self) -> None:
        empresa_id = self.empresa.currentData()
        if empresa_id is None:
            return
        ano_base = self.ano.value()
        trimestre = self.trimestre.currentData()

        if repo.periodo_esta_fechado(self.conn, empresa_id, ano_base):
            QMessageBox.warning(
                self, "Importar planilha",
                f"O período de {ano_base} desta empresa está trancado. Destranque-o na aba de "
                "Distribuição anual antes de importar.",
            )
            return

        # O período vai no título da janela de arquivo: é onde a pessoa está
        # olhando no momento de importar, e diz em que trimestre os valores
        # vão entrar sem cobrar um clique a mais só pra confirmar o que já
        # está selecionado no topo da tela.
        caminho, _ = QFileDialog.getOpenFileName(
            self,
            f"Importar planilha — {trimestre}º trimestre de {ano_base} — {self.empresa.currentText()}",
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

        socios_do_trimestre = {l["socio_id"] for l in self._linhas}
        resolvidos, pendencias = associar_linhas(
            self.conn, linhas_importadas, socios_do_trimestre, self._rotulo_periodo()
        )

        if pendencias:
            dialogo = DialogoRevisaoImportacao(self.conn, pendencias, self)
            if dialogo.exec() == QDialog.Accepted:
                resolvidos.extend(dialogo.resolvidos())

        if not resolvidos:
            QMessageBox.information(self, "Importar planilha", "Nenhuma linha foi aplicada.")
            return

        # Pergunta só quando há o que perder. Trimestre em branco importa
        # direto; substituir valor já lançado é a única situação em que vale
        # interromper, porque o valor antigo não volta.
        ja_lancados = {
            l["socio_id"] for l in self._linhas if l["registro_id"] is not None
        } & {socio_id for _, socio_id in resolvidos}
        if ja_lancados:
            resposta = QMessageBox.question(
                self,
                "Substituir lançamentos",
                f"{len(ja_lancados)} sócio(s) já têm valor lançado no {trimestre}º trimestre de "
                f"{ano_base}. Importar substitui esses valores pelos da planilha. Continuar?",
            )
            if resposta != QMessageBox.Yes:
                return

        try:
            for linha, socio_id in resolvidos:
                repo.salvar_distribuicao_trimestral(
                    self.conn, empresa_id, ano_base, trimestre, socio_id,
                    linha["valor_distribuido"],
                    pro_labore=linha.get("pro_labore") or 0.0,
                    irrf=linha.get("irrf") or 0.0,
                )
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao importar", str(exc))
            self._carregar()
            return

        self._carregar()
        nao_aplicadas = len(linhas_importadas) - len(resolvidos)
        resumo = f"{len(resolvidos)} sócio(s) lançados no {trimestre}º trimestre de {ano_base}."
        if nao_aplicadas > 0:
            resumo += f"\n{nao_aplicadas} linha(s) não foram aplicadas."
        resumo += "\n\nA distribuição anual desses sócios passou a mostrar a soma dos trimestres lançados."
        QMessageBox.information(self, "Importação concluída", resumo)
