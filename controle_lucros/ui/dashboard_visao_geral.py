"""Dashboard — visão geral de todas as empresas: quanto foi distribuído
proporcional/desproporcionalmente, quanto foi emprestado, e quais empresas
não distribuíram nada no período selecionado. Só cartões e gráficos — sem
tabela — pra ficar um raio-x rápido, não mais uma lista pra ler."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtWidgets import (
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
from .classificacao import CLASSE_PDF, LABEL
from . import theme
from ..analise import resumo_sem_pro_labore, sem_pro_labore
from .common import CartaoEstatistica, formatar_valor_br
from .graficos import (
    grafico_barras_emprestimos_por_empresa,
    grafico_barras_por_empresa,
    grafico_sem_pro_labore,
    nova_chart_view,
)
from .relatorio_pdf import exportar_relatorio_pdf

COLUNAS_RELATORIO = [
    "Empresa", "Ano", "Sócio", "CPF", "% Capital", "% Distribuído", "Valor Distribuído",
    "Pró-labore", "IRRF", "Empréstimo", "Classificação",
]


def _lista_curta(nomes: list[str], quantos: int = 2) -> str:
    """Os primeiros nomes e um "e mais N". O cartão tem uma linha para o
    contexto; despejar dez razões sociais ali esticava a caixa e desalinhava a
    fileira inteira."""
    if not nomes:
        return ""
    mostrados = ", ".join(nomes[:quantos])
    resto = len(nomes) - quantos
    return f"{mostrados} e mais {resto}" if resto > 0 else mostrados


class DashboardVisaoGeralView(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._resultado: dict | None = None

        ano_atual = dt.date.today().year

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

        btn_todo_periodo = QPushButton("Todo o período")
        btn_todo_periodo.clicked.connect(self._selecionar_todo_periodo)

        topo = QHBoxLayout()
        topo.addWidget(QLabel("De:"))
        topo.addWidget(self.ano_de)
        topo.addWidget(QLabel("até:"))
        topo.addWidget(self.ano_ate)
        topo.addWidget(btn_todo_periodo)
        topo.addSpacing(16)
        topo.addWidget(QLabel("Tolerância:"))
        topo.addWidget(self.tolerancia)
        topo.addStretch()

        self.cartao_empresas = CartaoEstatistica(
            "Empresas", descricao="Empresas com movimento no período filtrado acima")
        self.cartao_sem_distribuicao = CartaoEstatistica(
            "Sem distribuição", descricao="Empresas sem nenhuma distribuição no período")
        self.cartao_total = CartaoEstatistica(
            "Total distribuído", descricao="Soma de tudo o que foi distribuído no período")
        self.cartao_proporcional = CartaoEstatistica(
            "Proporcional", descricao="Distribuído na proporção do capital de cada sócio")
        self.cartao_desproporcional = CartaoEstatistica(
            "Desproporcional", descricao="Distribuído fora da proporção do capital")
        self.cartao_emprestimos = CartaoEstatistica(
            "Emprestado a sócios", descricao="Total emprestado a sócios no período")

        cartoes = QHBoxLayout()
        cartoes.setSpacing(12)
        for cartao in (
            self.cartao_empresas,
            self.cartao_sem_distribuicao,
            self.cartao_total,
            self.cartao_proporcional,
            self.cartao_desproporcional,
            self.cartao_emprestimos,
        ):
            cartoes.addWidget(cartao, 1)

        # A frase que resume o achado do período. Fica entre os cartões e os
        # gráficos porque é a única linha da tela que pede uma providência —
        # os números acima descrevem, esta aponta.
        self.aviso_pro_labore = QLabel("")
        self.aviso_pro_labore.setWordWrap(True)

        self.grafico_pizza = nova_chart_view()
        self.grafico_barras = nova_chart_view()
        self.grafico_emprestimos = nova_chart_view()
        graficos = QHBoxLayout()
        graficos.setSpacing(12)
        graficos.addWidget(self.grafico_pizza, 1)
        graficos.addWidget(self.grafico_barras, 1)
        graficos.addWidget(self.grafico_emprestimos, 1)

        self.btn_exportar_excel = QPushButton("Exportar Excel")
        self.btn_exportar_excel.clicked.connect(self._exportar_excel)

        self.btn_exportar_pdf = QPushButton("Exportar PDF")
        self.btn_exportar_pdf.clicked.connect(self._exportar_pdf)

        botoes = QHBoxLayout()
        botoes.addStretch()
        botoes.addWidget(self.btn_exportar_excel)
        botoes.addWidget(self.btn_exportar_pdf)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addLayout(topo)
        layout.addLayout(cartoes)
        layout.addWidget(self.aviso_pro_labore)
        layout.addLayout(graficos, 1)
        layout.addLayout(botoes)

        self._carregar()

    def _selecionar_todo_periodo(self) -> None:
        anos = repo.anos_disponiveis(self.conn)
        self.ano_de.blockSignals(True)
        self.ano_de.setValue(min(anos))
        self.ano_de.blockSignals(False)
        self.ano_ate.setValue(max(anos))

    def atualizar(self) -> None:
        self._carregar()

    def _carregar(self) -> None:
        if self.ano_de.value() > self.ano_ate.value():
            self.ano_de.blockSignals(True)
            self.ano_de.setValue(self.ano_ate.value())
            self.ano_de.blockSignals(False)

        self._resultado = repo.visao_geral(self.conn, self.ano_de.value(), self.ano_ate.value(), self.tolerancia.value())
        self._atualizar_cartoes()
        self._atualizar_graficos()
        self._atualizar_disponibilidade_botoes()

    def _atualizar_cartoes(self) -> None:
        r = self._resultado
        total = r["total_distribuido"]

        self.cartao_empresas.definir(str(r["total_empresas"]))

        sem_dist = r["empresas_sem_distribuicao"]
        self.cartao_sem_distribuicao.definir(
            str(len(sem_dist)),
            _lista_curta(sem_dist),
            # Empresa sem distribuição no período é o que se vai procurar, não
            # um número neutro: em vermelho ela se acha de longe.
            cor=theme.SEAL_RED() if sem_dist else None,
        )

        self.cartao_total.definir(f"R$ {formatar_valor_br(total)}")

        # Proporcional e desproporcional são o julgamento que esta tela existe
        # para dar. Em preto os dois são só dois números; com a cor do selo,
        # verde e vermelho, o olho separa antes de ler.
        pct_proporcional = (100 * r["total_proporcional"] / total) if total else 0
        self.cartao_proporcional.definir(
            f"R$ {formatar_valor_br(r['total_proporcional'])}",
            f"{formatar_valor_br(pct_proporcional, 1)}% do total",
            cor=theme.SEAL_GREEN() if r["total_proporcional"] else None,
        )

        pct_desproporcional = (100 * r["total_desproporcional"] / total) if total else 0
        self.cartao_desproporcional.definir(
            f"R$ {formatar_valor_br(r['total_desproporcional'])}",
            f"{formatar_valor_br(pct_desproporcional, 1)}% do total",
            cor=theme.SEAL_RED() if r["total_desproporcional"] else None,
        )

        pct_emprestimo = (100 * r["total_emprestimos"] / total) if total else 0
        contexto_emprestimo = f"{formatar_valor_br(pct_emprestimo, 1)}% do total distribuído"
        self.cartao_emprestimos.definir(f"R$ {formatar_valor_br(r['total_emprestimos'])}", contexto_emprestimo)

    def _atualizar_graficos(self) -> None:
        r = self._resultado
        # Quem recebeu lucro sem pró-labore, em vez da pizza proporcional x
        # desproporcional — que só repetia em desenho os dois cartões acima.
        self._sem_pro_labore = sem_pro_labore(r["linhas"])
        grafico_sem_pro_labore(self.grafico_pizza, self._sem_pro_labore)
        self.aviso_pro_labore.setText(resumo_sem_pro_labore(self._sem_pro_labore))
        self.aviso_pro_labore.setStyleSheet(
            f"color: {theme.SAIU_FG() if self._sem_pro_labore else theme.INK_MUTED()};"
            " font-size: 12px; font-weight: 600;"
        )
        grafico_barras_por_empresa(self.grafico_barras, r["resumo_empresas"])
        grafico_barras_emprestimos_por_empresa(self.grafico_emprestimos, r["resumo_empresas"])

    def _atualizar_disponibilidade_botoes(self) -> None:
        tem_dados = bool(self._resultado and self._resultado["linhas"])
        self.btn_exportar_excel.setEnabled(tem_dados)
        self.btn_exportar_pdf.setEnabled(tem_dados)

    def _linhas_relatorio(self) -> tuple[list[list], list[str | None]]:
        linhas_export = []
        classes = []
        for linha in self._resultado["linhas"]:
            linhas_export.append(
                [
                    linha["empresa_nome"],
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
        if not self._resultado or not self._resultado["linhas"]:
            QMessageBox.information(self, "Exportar", "Não há dados no período selecionado.")
            return
        sugestao = f"relatorio_distribuicao_{self.ano_de.value()}_{self.ano_ate.value()}.xlsx"
        caminho, _ = QFileDialog.getSaveFileName(self, "Exportar relatório", sugestao, "Planilha Excel (*.xlsx)")
        if not caminho:
            return
        if not caminho.lower().endswith(".xlsx"):
            caminho += ".xlsx"
        linhas, _ = self._linhas_relatorio()
        exportar_relatorio_excel(
            Path(caminho),
            titulo=f"Relatório de Distribuição de Lucros — {self._titulo_periodo()}",
            cabecalho=COLUNAS_RELATORIO,
            linhas=linhas,
        )
        QMessageBox.information(self, "Exportado", f"Relatório salvo em:\n{caminho}")

    def _exportar_pdf(self) -> None:
        if not self._resultado or not self._resultado["linhas"]:
            QMessageBox.information(self, "Exportar", "Não há dados no período selecionado.")
            return
        sugestao = f"relatorio_distribuicao_{self.ano_de.value()}_{self.ano_ate.value()}.pdf"
        caminho, _ = QFileDialog.getSaveFileName(self, "Exportar relatório", sugestao, "PDF (*.pdf)")
        if not caminho:
            return
        if not caminho.lower().endswith(".pdf"):
            caminho += ".pdf"
        linhas, classes = self._linhas_relatorio()
        exportar_relatorio_pdf(
            Path(caminho),
            titulo="Relatório de Distribuição de Lucros",
            subtitulo=f"{self._titulo_periodo()} · Tolerância: {formatar_valor_br(self.tolerancia.value(), 1)} p.p. · Todas as empresas",
            cabecalho=COLUNAS_RELATORIO,
            linhas=linhas,
            gerado_em=f"Gerado em {dt.date.today().strftime('%d/%m/%Y')}",
            classe_por_linha=classes,
        )
        QMessageBox.information(self, "Exportado", f"Relatório salvo em:\n{caminho}")
