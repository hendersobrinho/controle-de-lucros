"""Dashboard — análise de uma empresa.

O painel azul responde "quanto e para quem"; as barras, como isso andou ano
a ano (cada sócio na sua cor); os pontos de atenção, o que pede
providência; e a comparação, para cada sócio, a fatia do capital × a fatia
do que ele de fato recebeu, com a diferença em reais — o número que se leva
para a conversa com o cliente.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
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
)

from .seletor_empresa import SeletorEmpresa
from .. import repositories as repo
from ..analise import desvio_por_socio, sem_pro_labore
from ..planilha import exportar_relatorio_excel
from . import formulario as form_ui
from .classificacao import CLASSE_PDF, LABEL
from .common import formatar_percentual, formatar_valor_br, preencher_combo
from .painel_distribuicao import cor_da_vez, divisor_hero, kpi
from .paineis_dashboard import CartaoAtencao, ComparacaoSocios, EvolucaoAnos, SeletorPeriodo, bloco, nomes_unicos
from .paineis_dashboard import reais as _reais
from .relatorio_pdf import exportar_relatorio_pdf

COLUNAS = [
    "Ano", "Sócio", "CPF", "% do capital", "% distribuído", "Valor distribuído",
    "Pró-labore", "IRRF", "Empréstimo", "Classificação",
]


class DashboardEmpresaView(form_ui.Caixa):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._linhas: list[dict] = []

        ano = repo.ultimo_ano_com_distribuicao(conn) or dt.date.today().year
        self.empresa = SeletorEmpresa()
        self.empresa.currentIndexChanged.connect(lambda _: self._carregar())
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

        linha1 = QHBoxLayout()
        linha1.setSpacing(14)
        linha1.addWidget(form_ui.campo("Empresa", self.empresa, info="Código e Enter, ou F2 para buscar."), 1)
        linha1.addWidget(form_ui.campo(
            "Tolerância", self.tolerancia,
            info="Quanto a fatia recebida pode se afastar da fatia do capital (em pontos percentuais) "
                 "e ainda contar como proporcional."))
        linha2 = QHBoxLayout()
        linha2.addWidget(form_ui.campo("Período", self.periodo,
                                       info="Clique num ano. Shift+clique escolhe de um ano até outro."), 1)
        exportar = QVBoxLayout()
        exportar.addStretch()
        botoes = QHBoxLayout()
        botoes.addWidget(self.btn_exportar_excel)
        botoes.addWidget(self.btn_exportar_pdf)
        exportar.addLayout(botoes)
        linha2.addLayout(exportar)

        # ---- painel azul
        self.selo = QLabel()
        self.selo.setProperty("role", "heroAno")
        self.resumo = QLabel()
        self.resumo.setProperty("role", "heroNota")
        self.resumo.setWordWrap(True)
        bloco_total, self.valor_total, self.nota_total = kpi("Lucro distribuído", grande=True)
        esquerda = QVBoxLayout()
        esquerda.setSpacing(8)
        esquerda.addWidget(self.selo, 0, Qt.AlignLeft)
        esquerda.addWidget(bloco_total)
        esquerda.addWidget(self.resumo)
        grade = QGridLayout()
        grade.setHorizontalSpacing(28)
        grade.setVerticalSpacing(14)
        self.kpis = {}
        for i, (chave, rotulo) in enumerate((
            ("media", "Média por ano"), ("socios", "Sócios que receberam"), ("proporcional", "Na proporção"),
            ("pro_labore", "Pró-labore"), ("irrf", "IRRF retido"), ("emprestado", "Emprestado a sócios"),
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

        # ---- barras por ano + atenção
        self.grafico = EvolucaoAnos()
        self.grafico.clicado.connect(lambda a: self.periodo.escolher(a, a))
        quadro_grafico, col = bloco("Distribuição por ano", "Cada sócio na sua cor. Clique numa barra para ver o ano.")
        col.addWidget(self.grafico, 1)
        self.atencao_fora = CartaoAtencao("Fora da proporção")
        self.atencao_pro_labore = CartaoAtencao("Lucro sem pró-labore")
        self.atencao_sem_receber = CartaoAtencao("Sócios que não receberam")
        quadro_atencao, col = bloco("Pontos de atenção")
        for cartao in (self.atencao_fora, self.atencao_pro_labore, self.atencao_sem_receber):
            col.addWidget(cartao)
        meio = QHBoxLayout()
        meio.setSpacing(14)
        meio.addWidget(quadro_grafico, 5)
        meio.addWidget(quadro_atencao, 3)

        # ---- capital × recebido
        self.grafico_desvio = ComparacaoSocios()
        quadro_comparacao, col = bloco(
            "Fatia do capital × fatia do que recebeu",
            "No período escolhido. À direita, quanto cada sócio recebeu acima ou abaixo da proporção dele.")
        col.addWidget(self.grafico_desvio)

        corpo = form_ui.Caixa()
        coluna = QVBoxLayout(corpo)
        coluna.setContentsMargins(0, 0, 8, 12)
        coluna.setSpacing(14)
        coluna.addLayout(linha1)
        coluna.addLayout(linha2)
        coluna.addWidget(self.hero)
        coluna.addLayout(meio)
        coluna.addWidget(quadro_comparacao)
        coluna.addStretch()
        rolagem = QScrollArea()
        rolagem.setProperty("role", "listaCartoes")
        rolagem.setWidgetResizable(True)
        rolagem.setFrameShape(QFrame.NoFrame)
        rolagem.setWidget(corpo)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(rolagem)

        # Troca de tema: a janela principal recarrega a página visível, e as
        # outras recarregam ao serem abertas — não precisa ouvir o tema aqui.
        self.atualizar()

    def atualizar(self) -> None:
        empresa_id_anterior = self.empresa.currentData()
        self.empresa.blockSignals(True)
        preencher_combo(self.empresa, repo.listar_empresas(self.conn))
        if empresa_id_anterior is not None:
            idx = self.empresa.findData(empresa_id_anterior)
            if idx >= 0:
                self.empresa.setCurrentIndex(idx)
        self.empresa.blockSignals(False)
        self.periodo.definir_anos(repo.anos_disponiveis(self.conn), self.ano_de.value(), self.ano_ate.value())
        self._carregar()

    def selecionar(self, empresa_id: int, ano_de: int, ano_ate: int, tolerancia: float,
                   carregar: bool = True) -> None:
        """Chega aqui vindo da Visão Geral, já com o período/tolerância usados
        lá. Com carregar=False só deixa tudo escolhido — quem chama vai abrir
        a página, e abrir já recarrega (uma vez só)."""
        for widget in (self.tolerancia, self.empresa, self.periodo):
            widget.blockSignals(True)
        self.ano_de.setValue(ano_de)
        self.ano_ate.setValue(ano_ate)
        self.periodo.escolher(ano_de, ano_ate, avisar=False)
        self.tolerancia.setValue(tolerancia)
        idx = self.empresa.findData(empresa_id)
        if idx >= 0:
            self.empresa.setCurrentIndex(idx)
        for widget in (self.tolerancia, self.empresa, self.periodo):
            widget.blockSignals(False)
        if carregar:
            self._carregar()

    def _ao_mudar_periodo(self, de: int, ate: int) -> None:
        self.ano_de.setValue(de)
        self.ano_ate.setValue(ate)
        self._carregar()

    def _carregar(self, *_args) -> None:
        de, ate = self.ano_de.value(), self.ano_ate.value()
        empresa_id = self.empresa.currentData()
        self.selo.setText(f"Período: {de if de == ate else f'{de} a {ate}'}")
        if empresa_id is None:
            self._linhas = []
            self.valor_total.setText("—")
            self.nota_total.setText("")
            self.resumo.setText("Cadastre uma empresa primeiro.")
            for valor, nota in self.kpis.values():
                valor.setText("—")
                nota.setText("")
            for cartao in (self.atencao_fora, self.atencao_pro_labore, self.atencao_sem_receber):
                cartao.definir("—", "", [], "info")
            self.grafico.definir([], de, ate)
            self.grafico_desvio.definir([])
            self._atualizar_botoes()
            return

        self._linhas = repo.analise_empresa_periodo(self.conn, empresa_id, de, ate, self.tolerancia.value())
        painel = repo.painel_empresa(self.conn, empresa_id)

        # Cor de cada sócio: quem mais recebeu no histórico todo primeiro.
        totais: dict[int, float] = {}
        for ano in painel["por_ano"]:
            for socio_id, (_nome, valor) in ano["socios"].items():
                totais[socio_id] = totais.get(socio_id, 0.0) + valor
        ordem = sorted(totais, key=lambda s: -totais[s])
        cores = {socio_id: cor_da_vez(i) for i, socio_id in enumerate(ordem)}
        colunas = []
        for ano in painel["por_ano"]:
            partes = [(valor, cores[sid], nome) for sid, (nome, valor) in
                      sorted(ano["socios"].items(), key=lambda x: ordem.index(x[0]))]
            colunas.append((ano["ano"], ano["total"], partes))
        self.grafico.definir(colunas, de, ate)

        # ---- números do período: o total é o das barras, pra o painel e o
        # gráfico dizerem o mesmo número.
        total = sum(a["total"] for a in painel["por_ano"] if de <= a["ano"] <= ate)
        anos_com = sorted({l["ano_base"] for l in self._linhas if l["valor_distribuido"]})
        proporcional = sum(l["valor_distribuido"] for l in self._linhas if l["classificacao"] == "proporcional")
        recebedores = {l["socio_id"] for l in self._linhas if l["valor_distribuido"]}
        todos = {l["socio_id"] for l in self._linhas}
        emprestado = sum(l["emprestimo_recebido"] for l in self._linhas)
        self.valor_total.setText(_reais(total))
        empresa = repo.buscar_empresa(self.conn, empresa_id)
        estado = repo.estado_atual_empresa(self.conn, empresa_id)
        self.nota_total.setText(f"{empresa.nome}")
        self.resumo.setText(
            f"Capital social {_reais(estado['capital_social'])} · "
            + (f"distribuiu em {len(anos_com)} de {ate - de + 1} ano(s)" if anos_com else "nada distribuído no período")
        )
        valores = {
            "media": (_reais(total / len(anos_com)) if anos_com else "—", "nos anos em que distribuiu"),
            "socios": (str(len(recebedores)), f"de {len(todos)} no período"),
            "proporcional": (f"{formatar_valor_br(100 * proporcional / total, 1)}%" if total else "—",
                             _reais(proporcional) if total else ""),
            "pro_labore": (_reais(sum(l["pro_labore"] for l in self._linhas)), ""),
            "irrf": (_reais(sum(l["irrf"] for l in self._linhas)), ""),
            "emprestado": (_reais(emprestado), ""),
        }
        for chave, (valor, nota) in valores.items():
            self.kpis[chave][0].setText(valor)
            self.kpis[chave][1].setText(nota)

        # ---- atenção
        fora = [l for l in self._linhas if l["classificacao"] == "desproporcional"]
        if fora:
            nomes = sorted({l["socio_nome"] for l in fora})
            self.atencao_fora.definir(
                _reais(sum(l["valor_distribuido"] for l in fora)),
                f"distribuídos fora da proporção do capital, para {len(nomes)} sócio(s).", nomes, "alerta")
        else:
            self.atencao_fora.definir("Tudo certo", "Toda a distribuição seguiu a proporção do capital.", [], "ok")
        sem = sem_pro_labore(self._linhas)
        if sem:
            self.atencao_pro_labore.definir(
                f"{len(sem)} sócio(s)",
                f"receberam {_reais(sum(i.valor_sem_pro_labore for i in sem))} nos anos em que não tiveram "
                "pró-labore.",
                nomes_unicos(i.socio_nome for i in sem), "aviso")
        else:
            self.atencao_pro_labore.definir("Nenhum", "Quem recebeu lucro teve pró-labore.", [], "ok")
        nao = sorted({l["socio_nome"] for l in self._linhas if l["classificacao"] == "socio_sem_distribuicao"})
        self.atencao_sem_receber.definir(
            str(len(nao)) if nao else "Nenhum",
            "sócio(s) ativos que não receberam nada em algum ano em que a empresa distribuiu." if nao
            else "Todos os sócios receberam nos anos com distribuição.",
            nao, "info" if nao else "ok")

        # ---- capital × recebido
        desvios = desvio_por_socio(self._linhas)
        desvios.sort(key=lambda d: -d.valor_distribuido)
        self.grafico_desvio.definir([
            (d.socio_nome, d.percentual_capital, d.percentual_distribuido, d.valor_distribuido, d.desvio,
             cores.get(d.socio_id, cor_da_vez(99)))
            for d in desvios[:25]
        ])
        self._atualizar_botoes()

    def _atualizar_botoes(self) -> None:
        tem_dados = bool(self._linhas)
        self.btn_exportar_excel.setEnabled(tem_dados)
        self.btn_exportar_pdf.setEnabled(tem_dados)

    def _linhas_relatorio(self) -> tuple[list[list], list[str | None]]:
        linhas_export = []
        classes = []
        for linha in self._linhas:
            linhas_export.append(
                [
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
