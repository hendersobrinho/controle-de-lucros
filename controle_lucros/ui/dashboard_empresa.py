"""Dashboard — análise de uma empresa específica: quais sócios tiveram
distribuição proporcional, desproporcional, ou não receberam nada, ano a ano
num período selecionável. Só gráficos — sem tabela."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import repositories as repo
from ..planilha import exportar_relatorio_excel
from .classificacao import CLASSE_PDF, LABEL, cor_classificacao
from .common import formatar_valor_br, preencher_combo
from .graficos import grafico_capital_vs_distribuido, grafico_pizza_classificacoes, nova_chart_view
from .relatorio_pdf import exportar_relatorio_pdf
from .theme import estado as tema_estado

COLUNAS = [
    "Ano", "Sócio", "CPF", "% capital", "% distribuído", "Valor distribuído",
    "Pró-labore", "IRRF", "Empréstimo", "Classificação",
]


class DashboardEmpresaView(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._linhas: list[dict] = []

        ano_atual = dt.date.today().year

        self.empresa = QComboBox()
        self.empresa.currentIndexChanged.connect(lambda _: self._carregar())

        self.ano_de = QSpinBox()
        self.ano_de.setRange(2000, 2100)
        self.ano_de.setValue(ano_atual)
        self.ano_de.valueChanged.connect(lambda _: self._carregar())

        self.ano_ate = QSpinBox()
        self.ano_ate.setRange(2000, 2100)
        self.ano_ate.setValue(ano_atual)
        self.ano_ate.valueChanged.connect(lambda _: self._carregar())

        self.tolerancia = QDoubleSpinBox()
        self.tolerancia.setRange(0, 100)
        self.tolerancia.setValue(0)
        self.tolerancia.setSuffix(" p.p.")
        self.tolerancia.valueChanged.connect(lambda _: self._carregar())

        topo = QHBoxLayout()
        topo.addWidget(QLabel("Empresa:"))
        topo.addWidget(self.empresa, 1)
        topo.addWidget(QLabel("De:"))
        topo.addWidget(self.ano_de)
        topo.addWidget(QLabel("até:"))
        topo.addWidget(self.ano_ate)
        topo.addSpacing(16)
        topo.addWidget(QLabel("Tolerância:"))
        topo.addWidget(self.tolerancia)

        self.resumo = QLabel()
        self.resumo.setProperty("role", "secao")

        self.grafico = nova_chart_view()
        self.grafico_classificacoes = nova_chart_view()
        graficos = QHBoxLayout()
        graficos.setSpacing(12)
        graficos.addWidget(self.grafico, 2)
        graficos.addWidget(self.grafico_classificacoes, 1)

        legenda = QHBoxLayout()
        self._legenda_labels: list[tuple[str, QLabel]] = []
        for chave in ("proporcional", "desproporcional", "socio_sem_distribuicao", "empresa_sem_distribuicao"):
            rotulo = QLabel(f"●  {LABEL[chave]}")
            self._legenda_labels.append((chave, rotulo))
            legenda.addWidget(rotulo)
        legenda.addStretch()
        self._aplicar_cores_legenda()
        tema_estado().mudou.connect(self._aplicar_cores_legenda)

        self.btn_exportar_excel = QPushButton("Exportar Excel")
        self.btn_exportar_excel.clicked.connect(self._exportar_excel)

        self.btn_exportar_pdf = QPushButton("Exportar PDF")
        self.btn_exportar_pdf.clicked.connect(self._exportar_pdf)

        botoes = QHBoxLayout()
        botoes.addLayout(legenda, 1)
        botoes.addWidget(self.btn_exportar_excel)
        botoes.addWidget(self.btn_exportar_pdf)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(topo)
        layout.addWidget(self.resumo)
        layout.addLayout(graficos, 1)
        layout.addLayout(botoes)

        self.atualizar()

    def atualizar(self) -> None:
        empresa_id_anterior = self.empresa.currentData()
        preencher_combo(self.empresa, repo.listar_empresas(self.conn))
        if empresa_id_anterior is not None:
            idx = self.empresa.findData(empresa_id_anterior)
            if idx >= 0:
                self.empresa.setCurrentIndex(idx)
        self._carregar()

    def selecionar(self, empresa_id: int, ano_de: int, ano_ate: int, tolerancia: float) -> None:
        """Chega aqui vindo da Visão Geral, já com o período/tolerância usados lá."""
        # bloqueia tudo e recarrega uma vez só no fim — se a empresa já
        # estivesse selecionada, setCurrentIndex não dispara sinal nenhum e
        # o período novo nunca seria aplicado
        self.ano_de.blockSignals(True)
        self.ano_ate.blockSignals(True)
        self.tolerancia.blockSignals(True)
        self.empresa.blockSignals(True)

        self.ano_de.setValue(ano_de)
        self.ano_ate.setValue(ano_ate)
        self.tolerancia.setValue(tolerancia)
        idx = self.empresa.findData(empresa_id)
        if idx >= 0:
            self.empresa.setCurrentIndex(idx)

        self.ano_de.blockSignals(False)
        self.ano_ate.blockSignals(False)
        self.tolerancia.blockSignals(False)
        self.empresa.blockSignals(False)

        self._carregar()

    def _carregar(self) -> None:
        if self.ano_de.value() > self.ano_ate.value():
            self.ano_de.blockSignals(True)
            self.ano_de.setValue(self.ano_ate.value())
            self.ano_de.blockSignals(False)

        empresa_id = self.empresa.currentData()
        if empresa_id is None:
            self._linhas = []
            self.resumo.setText("Cadastre uma empresa primeiro.")
            grafico_capital_vs_distribuido(self.grafico, [])
            grafico_pizza_classificacoes(self.grafico_classificacoes, [])
            self._atualizar_botoes()
            return

        self._linhas = repo.analise_empresa_periodo(
            self.conn, empresa_id, self.ano_de.value(), self.ano_ate.value(), self.tolerancia.value()
        )
        grafico_capital_vs_distribuido(self.grafico, self._linhas)
        grafico_pizza_classificacoes(self.grafico_classificacoes, self._linhas)

        total = sum(l["valor_distribuido"] for l in self._linhas)
        proporcional = sum(l["valor_distribuido"] for l in self._linhas if l["classificacao"] == "proporcional")
        desproporcional = sum(l["valor_distribuido"] for l in self._linhas if l["classificacao"] == "desproporcional")
        sem_receber = sum(1 for l in self._linhas if l["classificacao"] == "socio_sem_distribuicao")
        self.resumo.setText(
            f"Total distribuído no período: R$ {formatar_valor_br(total)}  ·  "
            f"Proporcional: R$ {formatar_valor_br(proporcional)}  ·  "
            f"Desproporcional: R$ {formatar_valor_br(desproporcional)}  ·  "
            f"Sócios que não receberam: {sem_receber}"
        )
        self._atualizar_botoes()

    def _atualizar_botoes(self) -> None:
        tem_dados = bool(self._linhas)
        self.btn_exportar_excel.setEnabled(tem_dados)
        self.btn_exportar_pdf.setEnabled(tem_dados)

    def _aplicar_cores_legenda(self) -> None:
        for chave, rotulo in self._legenda_labels:
            rotulo.setStyleSheet(
                f"color: {cor_classificacao(chave)}; font-size: 11px; font-weight: 600; padding-right: 14px;"
            )

    def _linhas_relatorio(self) -> tuple[list[list], list[str | None]]:
        linhas_export = []
        classes = []
        for linha in self._linhas:
            linhas_export.append(
                [
                    linha["ano_base"],
                    linha["socio_nome"],
                    linha["socio_cpf"] or "—",
                    formatar_valor_br(linha["percentual_capital"], 4),
                    formatar_valor_br(linha["percentual_distribuido"], 3),
                    f"R$ {formatar_valor_br(linha['valor_distribuido'])}",
                    f"R$ {formatar_valor_br(linha['pro_labore'])}" if linha["pro_labore"] else "—",
                    f"R$ {formatar_valor_br(linha['irrf'])}" if linha["irrf"] else "—",
                    f"R$ {formatar_valor_br(linha['emprestimo_recebido'])}" if linha["emprestimo_recebido"] else "—",
                    LABEL[linha["classificacao"]],
                ]
            )
            classes.append(CLASSE_PDF[linha["classificacao"]])
        return linhas_export, classes

    def _titulo_periodo(self) -> str:
        if self.ano_de.value() == self.ano_ate.value():
            return f"Ano de {self.ano_de.value()}"
        return f"Período de {self.ano_de.value()} a {self.ano_ate.value()}"

    def _exportar_excel(self) -> None:
        if not self._linhas:
            QMessageBox.information(self, "Exportar", "Não há dados no período selecionado.")
            return
        nome_empresa = self.empresa.currentText()
        sugestao = f"distribuicao_{nome_empresa}_{self.ano_de.value()}_{self.ano_ate.value()}.xlsx".replace(" ", "_")
        caminho, _ = QFileDialog.getSaveFileName(self, "Exportar relatório", sugestao, "Planilha Excel (*.xlsx)")
        if not caminho:
            return
        if not caminho.lower().endswith(".xlsx"):
            caminho += ".xlsx"
        linhas, _ = self._linhas_relatorio()
        exportar_relatorio_excel(
            Path(caminho),
            titulo=f"Distribuição de Lucros — {nome_empresa} — {self._titulo_periodo()}",
            cabecalho=COLUNAS,
            linhas=linhas,
        )
        QMessageBox.information(self, "Exportado", f"Relatório salvo em:\n{caminho}")

    def _exportar_pdf(self) -> None:
        if not self._linhas:
            QMessageBox.information(self, "Exportar", "Não há dados no período selecionado.")
            return
        nome_empresa = self.empresa.currentText()
        sugestao = f"distribuicao_{nome_empresa}_{self.ano_de.value()}_{self.ano_ate.value()}.pdf".replace(" ", "_")
        caminho, _ = QFileDialog.getSaveFileName(self, "Exportar relatório", sugestao, "PDF (*.pdf)")
        if not caminho:
            return
        if not caminho.lower().endswith(".pdf"):
            caminho += ".pdf"
        linhas, classes = self._linhas_relatorio()
        exportar_relatorio_pdf(
            Path(caminho),
            titulo=f"Distribuição de Lucros — {nome_empresa}",
            subtitulo=f"{self._titulo_periodo()} · Tolerância: {formatar_valor_br(self.tolerancia.value(), 1)} p.p.",
            cabecalho=COLUNAS,
            linhas=linhas,
            gerado_em=f"Gerado em {dt.date.today().strftime('%d/%m/%Y')}",
            classe_por_linha=classes,
        )
        QMessageBox.information(self, "Exportado", f"Relatório salvo em:\n{caminho}")
