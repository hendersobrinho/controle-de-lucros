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
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import repositories as repo
from ..models import TRIMESTRES, TRIMESTRES_LABEL
from ..planilha import exportar_modelo_distribuicao, importar_distribuicao
from .importacao_distribuicao import DialogoRevisaoImportacao, associar_linhas
from .common import formatar_numero, formatar_valor_br, preencher_combo
from .theme import ENTROU_BG, ENTROU_FG, SAIU_BG, SAIU_FG
from .theme import estado as tema_estado

COLUNAS = [
    "Sócio",
    "CPF",
    "% capital",
    "Cotas",
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


class DistribuicaoTrimestralView(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._linhas: list[dict] = []
        self._editando = False
        self._widgets_edicao: list[dict] = []
        self._periodo_fechado = False

        self.empresa = QComboBox()
        self.empresa.currentIndexChanged.connect(lambda _: self._carregar())

        self.ano = QSpinBox()
        self.ano.setRange(2000, 2100)
        self.ano.setValue(dt.date.today().year)
        self.ano.valueChanged.connect(lambda _: self._carregar())

        self.trimestre = QComboBox()
        for numero in TRIMESTRES:
            self.trimestre.addItem(TRIMESTRES_LABEL[numero], numero)
        self.trimestre.setCurrentIndex(self._trimestre_corrente() - 1)
        self.trimestre.currentIndexChanged.connect(lambda _: self._carregar())

        # Setas pra andar na linha do tempo, no mesmo estilo do histórico de
        # alterações contratuais. Atravessam a virada de ano de propósito:
        # o trimestre anterior ao 1º de 2025 é o 4º de 2024, e parar na borda
        # do ano obrigaria a mexer em dois campos pra dar um passo só.
        self.btn_anterior = QPushButton("‹")
        self.btn_anterior.setProperty("role", "chevron")
        self.btn_anterior.setToolTip("Trimestre anterior")
        self.btn_anterior.clicked.connect(lambda: self._navegar_trimestre(-1))

        self.btn_proximo = QPushButton("›")
        self.btn_proximo.setProperty("role", "chevron")
        self.btn_proximo.setToolTip("Próximo trimestre")
        self.btn_proximo.clicked.connect(lambda: self._navegar_trimestre(1))

        # A empresa encolhe antes de tudo: é o único campo cujo conteúdo cabe
        # cortado sem atrapalhar (o nome inteiro fica na dica), enquanto ano,
        # trimestre e setas têm largura fixa e some tudo junto se apertar.
        self.empresa.setMinimumWidth(160)

        topo = QHBoxLayout()
        topo.addWidget(QLabel("Empresa:"))
        topo.addWidget(self.empresa, 1)
        topo.addSpacing(8)
        topo.addWidget(QLabel("Ano:"))
        topo.addWidget(self.ano)
        topo.addSpacing(8)
        topo.addWidget(self.btn_anterior)
        topo.addWidget(self.trimestre)
        topo.addWidget(self.btn_proximo)

        self.resumo = QLabel()
        self.resumo.setProperty("role", "secao")

        self.progresso = QLabel()
        self.progresso.setProperty("role", "subtitulo")
        self.progresso.setWordWrap(True)

        self.aviso_trancado = QLabel()
        self.aviso_trancado.setWordWrap(True)
        self.aviso_trancado.hide()

        self.tabela = QTableWidget(0, len(COLUNAS))
        self.tabela.setHorizontalHeaderLabels(COLUNAS)
        self.tabela.setAlternatingRowColors(True)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela.verticalHeader().setVisible(False)

        self.btn_editar = QPushButton("Lançar trimestre")
        self.btn_editar.setProperty("role", "primario")
        self.btn_editar.clicked.connect(self._iniciar_edicao)

        self.btn_salvar = QPushButton("Salvar")
        self.btn_salvar.setProperty("role", "primario")
        self.btn_salvar.clicked.connect(self._salvar_edicao)

        self.btn_cancelar = QPushButton("Cancelar")
        self.btn_cancelar.clicked.connect(self._cancelar_edicao)

        self.btn_limpar = QPushButton("Limpar trimestre")
        self.btn_limpar.setProperty("role", "perigo")
        self.btn_limpar.clicked.connect(self._limpar_trimestre)

        self.btn_exportar_modelo = QPushButton("Exportar modelo")
        self.btn_exportar_modelo.clicked.connect(self._exportar_modelo)

        self.btn_importar = QPushButton("Importar planilha")
        self.btn_importar.clicked.connect(self._importar_planilha)

        botoes = QHBoxLayout()
        botoes.addWidget(self.btn_editar)
        botoes.addWidget(self.btn_salvar)
        botoes.addWidget(self.btn_cancelar)
        botoes.addWidget(self.btn_limpar)
        botoes.addSpacing(8)
        botoes.addWidget(self.btn_exportar_modelo)
        botoes.addWidget(self.btn_importar)
        botoes.addStretch()
        self._legenda_entrou = QLabel("●  Entrou neste trimestre")
        self._legenda_saiu = QLabel("●  Saiu neste trimestre")
        botoes.addWidget(self._legenda_entrou)
        botoes.addWidget(self._legenda_saiu)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(topo)
        layout.addWidget(self.resumo)
        layout.addWidget(self.progresso)
        layout.addWidget(self.aviso_trancado)
        layout.addWidget(self.tabela, 1)
        layout.addLayout(botoes)

        self._aplicar_cores()
        tema_estado().mudou.connect(self._aplicar_cores)
        self.atualizar()

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
        self.aviso_trancado.setStyleSheet(
            f"background: {ENTROU_BG()}; color: {ENTROU_FG()}; border-radius: 4px; "
            f"padding: 8px 12px; font-weight: 600; font-size: 12px;"
        )
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
        self.resumo.setText(
            f"Distribuído no {trimestre}º trimestre de {ano_base}: R$ {formatar_valor_br(total)}"
        )

        lancados = repo.trimestres_lancados(self.conn, empresa_id, ano_base)
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
                + "  ·  a distribuição anual desta empresa está recebendo essa soma."
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
                situacao = f"Saiu em {linha['data_saida']}"
            elif linha["entrou_no_trimestre"]:
                situacao = "Entrou neste trimestre"
            elif linha["data_saida"]:
                situacao = f"Saiu em {linha['data_saida']}"

            valores = [
                linha["socio_nome"],
                linha["socio_cpf"] or "—",
                formatar_valor_br(linha["percentual_capital"], 4),
                formatar_valor_br(linha["quantidade_cotas"], 0),
                f"R$ {formatar_valor_br(linha['valor_distribuido'])}",
                f"R$ {formatar_valor_br(linha['pro_labore'])}" if linha["pro_labore"] else "—",
                f"R$ {formatar_valor_br(linha['irrf'])}" if linha["irrf"] else "—",
                f"R$ {formatar_valor_br(linha['acumulado_valor'])}",
                situacao,
            ]

            cor_fundo = cor_texto = None
            if linha["saiu_no_trimestre"]:
                cor_fundo, cor_texto = SAIU_BG(), SAIU_FG()
            elif linha["entrou_no_trimestre"]:
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
        self.trimestre.setEnabled(not self._editando)

        primeiro, ultimo = self._limites_da_linha_do_tempo()
        posicao = self._posicao_na_linha_do_tempo()
        self.btn_anterior.setEnabled(not self._editando and posicao > primeiro)
        self.btn_proximo.setEnabled(not self._editando and posicao < ultimo)

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
            self._widgets_edicao.append(campos)

        for col in COLUNAS_EDITAVEIS:
            if self.tabela.columnWidth(col) < 150:
                self.tabela.setColumnWidth(col, 150)
        altura = QDoubleSpinBox().sizeHint().height() + 8
        for row in range(len(self._linhas)):
            if self.tabela.rowHeight(row) < altura:
                self.tabela.setRowHeight(row, altura)

        self._atualizar_disponibilidade_botoes()

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
