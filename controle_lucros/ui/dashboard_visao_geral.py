"""Dashboard — visão geral do escritório no período escolhido.

De cima para baixo, na ordem em que se pergunta:

1. Quanto foi distribuído, se cresceu ou caiu em relação ao período
   anterior, e o tamanho da carteira (empresas, sócios, pró-labore, IRRF,
   empréstimos) — o painel azul.
2. Como isso evoluiu ano a ano — clicar num ano escolhe aquele ano.
3. Pontos de atenção — o que pede providência: distribuição fora da
   proporção do capital, lucro sem pró-labore, empresa sem distribuição,
   empréstimo a sócio.
4. Quem mais distribuiu e quem mais recebeu — clicar abre o detalhe.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import repositories as repo
from ..analise import sem_pro_labore
from ..planilha import exportar_relatorio_excel
from . import formulario as form_ui
from .classificacao import CLASSE_PDF, LABEL
from .common import formatar_percentual, formatar_valor_br
from .painel_distribuicao import divisor_hero, kpi
from .paineis_dashboard import CartaoAtencao, EvolucaoAnos, Ranking, SeletorPeriodo, bloco, nomes_unicos
from .paineis_dashboard import reais as _reais
from .relatorio_pdf import exportar_relatorio_pdf

COLUNAS_RELATORIO = [
    "Empresa", "Ano", "Sócio", "CPF", "% do Capital", "% Distribuído", "Valor Distribuído",
    "Pró-labore", "IRRF", "Empréstimo", "Classificação",
]


def _rotulo_periodo(de: int, ate: int) -> str:
    return str(de) if de == ate else f"{de} a {ate}"


class DashboardVisaoGeralView(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._resultado: dict | None = None
        self._painel: dict | None = None
        # A classificação (proporcional, sem pró-labore…) é a consulta cara:
        # guardada por período e tolerância, e esquecida em atualizar(), que é
        # quando os dados podem ter mudado.
        self._cache_classificacao: dict[tuple, dict] = {}
        # A janela principal liga: abrir a análise de uma empresa e a ficha de um sócio.
        self.ao_abrir_empresa = None
        self.ao_abrir_socio = None

        # O período fica nestes dois (as exportações leem deles); as fichas de
        # ano os mudam. Não entram no layout.
        ano = repo.ultimo_ano_com_distribuicao(conn) or dt.date.today().year
        self.ano_de = QSpinBox()
        self.ano_de.setRange(2000, 2100)
        self.ano_de.setValue(ano)
        self.ano_ate = QSpinBox()
        self.ano_ate.setRange(2000, 2100)
        self.ano_ate.setValue(ano)
        for spin in (self.ano_de, self.ano_ate):
            spin.hide()

        self.periodo = SeletorPeriodo()
        self.periodo.mudou.connect(self._ao_mudar_periodo)

        self.tolerancia = QDoubleSpinBox()
        self.tolerancia.setRange(0, 100)
        self.tolerancia.setValue(0)
        self.tolerancia.setSuffix(" p.p.")
        self.tolerancia.setFixedWidth(100)
        self.tolerancia.valueChanged.connect(lambda _: self._carregar())

        self.btn_exportar_excel = QPushButton("Exportar Excel")
        self.btn_exportar_excel.clicked.connect(self._exportar_excel)
        self.btn_exportar_pdf = QPushButton("Exportar PDF")
        self.btn_exportar_pdf.clicked.connect(self._exportar_pdf)

        topo = QHBoxLayout()
        topo.setSpacing(14)
        topo.addWidget(form_ui.campo("Período", self.periodo,
                                     info="Clique num ano. Shift+clique escolhe de um ano até outro."), 1)
        topo.addWidget(form_ui.campo(
            "Tolerância", self.tolerancia,
            info="Quanto a fatia recebida pode se afastar da fatia do capital (em pontos "
                 "percentuais) e ainda contar como proporcional."))
        botoes = QVBoxLayout()
        botoes.addStretch()
        linha_botoes = QHBoxLayout()
        linha_botoes.addWidget(self.btn_exportar_excel)
        linha_botoes.addWidget(self.btn_exportar_pdf)
        botoes.addLayout(linha_botoes)
        topo.addLayout(botoes)

        # ---- painel azul
        self.selo = QLabel()
        self.selo.setProperty("role", "heroAno")
        bloco_total, self.valor_total, self.nota_total = kpi("Lucro distribuído", grande=True)
        self.variacao = QLabel()
        self.variacao.setProperty("role", "variacao")
        linha_total = QHBoxLayout()
        linha_total.addWidget(bloco_total)
        linha_total.addWidget(self.variacao, 0, Qt.AlignTop)
        linha_total.addStretch()
        esquerda = QVBoxLayout()
        esquerda.setSpacing(8)
        esquerda.addWidget(self.selo, 0, Qt.AlignLeft)
        esquerda.addLayout(linha_total)

        grade = QGridLayout()
        grade.setHorizontalSpacing(28)
        grade.setVerticalSpacing(14)
        self.kpis = {}
        for i, (chave, rotulo) in enumerate((
            ("empresas", "Empresas que distribuíram"), ("socios", "Sócios que receberam"),
            ("pro_labore", "Pró-labore"), ("irrf", "IRRF retido"),
            ("emprestado", "Emprestado a sócios"), ("adiantado", "Adiantamento de lucro"),
        )):
            caixa, valor, nota = kpi(rotulo)
            self.kpis[chave] = (valor, nota)
            grade.addWidget(caixa, i // 3, i % 3)

        self.hero = QFrame()
        self.hero.setProperty("role", "hero")
        dentro = QHBoxLayout(self.hero)
        dentro.setContentsMargins(28, 22, 28, 22)
        dentro.setSpacing(26)
        dentro.addLayout(esquerda, 2)
        dentro.addWidget(divisor_hero())
        dentro.addLayout(grade, 3)

        # ---- evolução + pontos de atenção
        self.evolucao = EvolucaoAnos()
        self.evolucao.clicado.connect(lambda ano: self.periodo.escolher(ano, ano))
        quadro_evolucao, col = bloco("Evolução ano a ano", "Lucro distribuído em cada ano. Clique numa barra para ver o ano.")
        col.addWidget(self.evolucao, 1)

        self.atencao_desproporcional = CartaoAtencao("Fora da proporção")
        self.atencao_pro_labore = CartaoAtencao("Lucro sem pró-labore")
        self.atencao_sem_distribuicao = CartaoAtencao("Empresas sem distribuição")
        self.atencao_emprestimos = CartaoAtencao("Empréstimos a sócios")
        quadro_atencao, col = bloco("Pontos de atenção", "O que vale olhar antes de fechar o período.")
        grade_atencao = QGridLayout()
        grade_atencao.setSpacing(10)
        for i, cartao in enumerate((self.atencao_desproporcional, self.atencao_pro_labore,
                                    self.atencao_sem_distribuicao, self.atencao_emprestimos)):
            grade_atencao.addWidget(cartao, i // 2, i % 2)
        col.addLayout(grade_atencao)

        meio = QHBoxLayout()
        meio.setSpacing(14)
        meio.addWidget(quadro_evolucao, 5)
        meio.addWidget(quadro_atencao, 4)

        # ---- rankings
        self.ranking_empresas = Ranking()
        self.ranking_empresas.clicado.connect(self._abrir_empresa)
        self.ranking_socios = Ranking()
        self.ranking_socios.clicado.connect(self._abrir_socio)
        self.quadro_empresas, col = bloco("Empresas que mais distribuíram", "Clique para ver a análise da empresa.")
        col.addWidget(self.ranking_empresas)
        col.addStretch()
        self.quadro_socios, col = bloco("Sócios que mais receberam", "Somando todas as empresas. Clique para abrir o sócio.")
        col.addWidget(self.ranking_socios)
        col.addStretch()
        rankings = QHBoxLayout()
        rankings.setSpacing(14)
        rankings.addWidget(self.quadro_empresas, 1)
        rankings.addWidget(self.quadro_socios, 1)

        corpo = form_ui.Caixa()
        coluna = QVBoxLayout(corpo)
        coluna.setContentsMargins(0, 0, 8, 12)
        coluna.setSpacing(14)
        coluna.addLayout(topo)
        coluna.addWidget(self.hero)
        coluna.addLayout(meio)
        coluna.addLayout(rankings)
        coluna.addStretch()
        rolagem = QScrollArea()
        rolagem.setProperty("role", "listaCartoes")
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.NoFrame)
        rolagem.setWidget(corpo)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(rolagem)

        self.periodo.definir_anos(repo.anos_disponiveis(conn), ano, ano)
        self._carregar()

    # ------------------------------------------------------------ período --
    def _ao_mudar_periodo(self, de: int, ate: int) -> None:
        self.ano_de.setValue(de)
        self.ano_ate.setValue(ate)
        self._carregar()

    def atualizar(self) -> None:
        self._cache_classificacao.clear()
        self.periodo.definir_anos(repo.anos_disponiveis(self.conn), self.ano_de.value(), self.ano_ate.value())
        self._carregar()

    def _abrir_empresa(self, empresa_id: int) -> None:
        if self.ao_abrir_empresa is not None:
            self.ao_abrir_empresa(empresa_id, self.ano_de.value(), self.ano_ate.value(), self.tolerancia.value())

    def _abrir_socio(self, socio_id: int) -> None:
        if self.ao_abrir_socio is not None:
            self.ao_abrir_socio(socio_id)

    # -------------------------------------------------------------- dados --
    def _carregar(self) -> None:
        de, ate = self.ano_de.value(), self.ano_ate.value()
        chave = (de, ate, self.tolerancia.value())
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self._painel = repo.painel_geral(self.conn, de, ate)
            if chave not in self._cache_classificacao:
                self._cache_classificacao[chave] = repo.visao_geral(self.conn, de, ate, self.tolerancia.value())
            self._resultado = self._cache_classificacao[chave]
        finally:
            QApplication.restoreOverrideCursor()
        self._mostrar_painel(de, ate)
        self._mostrar_atencao()
        self._atualizar_disponibilidade_botoes()

    def _mostrar_painel(self, de: int, ate: int) -> None:
        painel = self._painel
        periodo = _rotulo_periodo(de, ate)
        self.selo.setText(f"Período: {periodo}")
        self.valor_total.setText(_reais(painel["total"]))
        anterior = painel["total_anterior"]
        if anterior:
            variacao = 100 * (painel["total"] - anterior) / anterior
            self.variacao.setText(f"{'▲' if variacao >= 0 else '▼'} {formatar_valor_br(abs(variacao), 1)}%")
            self.variacao.setProperty("tom", "sobe" if variacao >= 0 else "desce")
            tamanho = ate - de + 1
            self.nota_total.setText(
                f"em {periodo} · {_reais(anterior)} em {_rotulo_periodo(de - tamanho, de - 1)}"
            )
        else:
            self.variacao.setText("")
            self.nota_total.setText(f"em {periodo}")
        self.variacao.setVisible(bool(anterior))
        self.variacao.style().unpolish(self.variacao)
        self.variacao.style().polish(self.variacao)

        movimentos = painel["movimentos"]
        valores = {
            "empresas": (str(painel["empresas_que_distribuiram"]), f"de {painel['empresas_ativas']} ativas no fim do período"),
            "socios": (str(painel["socios_que_receberam"]), f"de {painel['socios_ativos']} sócios ativos"),
            "pro_labore": (_reais(painel["pro_labore"]), ""),
            "irrf": (_reais(painel["irrf"]), ""),
            "emprestado": (_reais(movimentos.get("emprestimo_empresa_para_socio", 0)),
                           f"sócios emprestaram {_reais(movimentos.get('emprestimo_socio_para_empresa', 0))}"),
            "adiantado": (_reais(movimentos.get("adiantamento_lucro", 0)),
                          f"devolução de capital {_reais(movimentos.get('devolucao_capital', 0))}"),
        }
        for chave, (valor, nota) in valores.items():
            rotulo_valor, rotulo_nota = self.kpis[chave]
            rotulo_valor.setText(valor)
            rotulo_nota.setText(nota)

        colunas = [(a["ano"], a["total"], []) for a in painel["por_ano"]]
        self.evolucao.definir(colunas, de, ate)

        total = painel["total"]
        self.ranking_empresas.definir(
            [(e["empresa_id"], e["nome"], f"nº {e['numero']} · {e['socios']} sócio(s) receberam", e["total"])
             for e in painel["top_empresas"]], total, "Nenhuma empresa distribuiu no período.")
        self.ranking_socios.definir(
            [(s["socio_id"], s["nome"],
              (s["documento"] or "sem CPF") + f" · {s['empresas']} empresa(s)", s["total"])
             for s in painel["top_socios"]], total, "Ninguém recebeu no período.")

    def _mostrar_atencao(self) -> None:
        r = self._resultado
        # A mesma base do painel azul, pra porcentagem do cartão bater com o
        # total que está logo acima dele.
        total = self._painel["total"]
        empresas_fora = [e for e in r["resumo_empresas"] if e["socios_desproporcionais"]]
        empresas_fora.sort(key=lambda e: -e["socios_desproporcionais"])
        if r["total_desproporcional"]:
            pct = 100 * r["total_desproporcional"] / total if total else 0
            self.atencao_desproporcional.definir(
                _reais(r["total_desproporcional"]),
                f"{formatar_valor_br(pct, 1)}% do distribuído saiu fora da proporção do capital, em "
                f"{len(empresas_fora)} empresa(s).",
                nomes_unicos(e["empresa_nome"] for e in empresas_fora), "alerta",
            )
        else:
            self.atencao_desproporcional.definir("Tudo certo", "Toda a distribuição seguiu a proporção do capital.", [], "ok")

        sem = sem_pro_labore(r["linhas"])
        if sem:
            pessoas = len({i.socio_id for i in sem})
            self.atencao_pro_labore.definir(
                f"{pessoas} sócio(s)",
                f"receberam {_reais(sum(i.valor_sem_pro_labore for i in sem))} de lucro nos anos em que "
                "não tiveram pró-labore.",
                nomes_unicos(i.socio_nome for i in sem), "aviso",
            )
        else:
            self.atencao_pro_labore.definir("Nenhum", "Todo sócio que recebeu lucro teve pró-labore.", [], "ok")

        sem_dist = r["empresas_sem_distribuicao"]
        self.atencao_sem_distribuicao.definir(
            str(len(sem_dist)) if sem_dist else "Nenhuma",
            "empresa(s) cadastradas sem nenhum lucro distribuído no período." if sem_dist
            else "Todas as empresas distribuíram no período.",
            sem_dist, "info" if sem_dist else "ok",
        )

        com_emprestimo = sorted((e for e in r["resumo_empresas"] if e["total_emprestimos"]),
                                key=lambda e: -e["total_emprestimos"])
        if r["total_emprestimos"]:
            pct = 100 * r["total_emprestimos"] / total if total else 0
            self.atencao_emprestimos.definir(
                _reais(r["total_emprestimos"]),
                f"emprestados pela empresa aos sócios — {formatar_valor_br(pct, 1)}% do lucro distribuído.",
                [e["empresa_nome"] for e in com_emprestimo], "info",
            )
        else:
            self.atencao_emprestimos.definir("Nenhum", "Nenhuma empresa emprestou a sócios no período.", [], "ok")

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
                    formatar_percentual(linha["percentual_capital"]),
                    formatar_percentual(linha["percentual_distribuido"]),
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
