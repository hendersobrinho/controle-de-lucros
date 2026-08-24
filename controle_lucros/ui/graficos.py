"""Gráficos do dashboard — QtCharts nativo do Qt, estilizado pra combinar com
o resto do app (paleta e tipografia do tema) em vez do visual padrão."""
from __future__ import annotations

from PySide6.QtCharts import (
    QBarCategoryAxis,
    QBarSeries,
    QBarSet,
    QChart,
    QChartView,
    QHorizontalBarSeries,
    QPieSeries,
    QValueAxis,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter

from .classificacao import LABEL, cor_classificacao
from .theme import BRASS, HAIRLINE, INK, INK_MUTED, PAPER_RAISED, SAIU_FG, SEAL_GREEN

FONTE_TITULO = QFont("Constantia", 12, QFont.Bold)
FONTE_LEGENDA = QFont("Segoe UI", 9)
FONTE_EIXO = QFont("Segoe UI", 8)


def nova_chart_view() -> QChartView:
    view = QChartView()
    view.setRenderHint(QPainter.Antialiasing)
    view.setMinimumHeight(260)
    return view


def _estilizar_eixo(eixo) -> None:
    eixo.setLabelsColor(QColor(INK_MUTED()))
    eixo.setLinePenColor(QColor(HAIRLINE()))
    if hasattr(eixo, "setGridLineColor"):
        eixo.setGridLineColor(QColor(HAIRLINE()))


def _novo_chart(titulo: str) -> QChart:
    chart = QChart()
    chart.setTitle(titulo)
    chart.setTitleFont(FONTE_TITULO)
    chart.setTitleBrush(QColor(INK()))
    chart.setBackgroundBrush(QColor(PAPER_RAISED()))
    chart.setBackgroundRoundness(6)
    chart.legend().setFont(FONTE_LEGENDA)
    chart.legend().setLabelColor(QColor(INK()))
    return chart


def grafico_pizza_proporcionalidade(view: QChartView, proporcional: float, desproporcional: float) -> None:
    chart = _novo_chart("Proporcional vs desproporcional")

    if proporcional <= 0 and desproporcional <= 0:
        chart.setTitle("Proporcional vs desproporcional — sem dados no período")
        view.setChart(chart)
        return

    serie = QPieSeries()
    serie.setHoleSize(0.45)
    if proporcional > 0:
        serie.append("Proporcional", proporcional)
    if desproporcional > 0:
        serie.append("Desproporcional", desproporcional)

    for fatia in serie.slices():
        cor = SEAL_GREEN() if fatia.label() == "Proporcional" else SAIU_FG()
        fatia.setBrush(QColor(cor))
        fatia.setPen(QColor(PAPER_RAISED()))
        fatia.setBorderWidth(2)
        fatia.setLabelVisible(False)
        fatia.setLabelColor(QColor(INK()))
        fatia.setLabelFont(FONTE_EIXO)
        fatia.setLabel(f"{fatia.label()} — {fatia.percentage() * 100:.0f}%")

    chart.addSeries(serie)
    chart.legend().setVisible(True)
    chart.legend().setAlignment(Qt.AlignBottom)
    view.setChart(chart)


def grafico_barras_por_empresa(view: QChartView, resumo_empresas: list[dict], limite: int = 8) -> None:
    chart = _novo_chart("Total distribuído por empresa")

    ordenado = sorted(resumo_empresas, key=lambda r: r["total_distribuido"], reverse=True)
    ordenado = [r for r in ordenado if r["total_distribuido"] > 0][:limite]
    if not ordenado:
        chart.setTitle("Total distribuído por empresa — sem dados no período")
        view.setChart(chart)
        return

    conjunto = QBarSet("Total distribuído")
    conjunto.setColor(QColor(BRASS()))
    categorias = []
    for item in ordenado:
        conjunto.append(item["total_distribuido"])
        categorias.append(item["empresa_nome"])

    serie = QHorizontalBarSeries()
    serie.append(conjunto)
    chart.addSeries(serie)

    eixo_categorias = QBarCategoryAxis()
    eixo_categorias.append(categorias)
    eixo_categorias.setLabelsFont(FONTE_EIXO)
    _estilizar_eixo(eixo_categorias)
    chart.addAxis(eixo_categorias, Qt.AlignLeft)
    serie.attachAxis(eixo_categorias)

    eixo_valores = QValueAxis()
    eixo_valores.setLabelsFont(FONTE_EIXO)
    eixo_valores.setLabelFormat("R$ %.0f")
    _estilizar_eixo(eixo_valores)
    chart.addAxis(eixo_valores, Qt.AlignBottom)
    serie.attachAxis(eixo_valores)

    chart.legend().setVisible(False)
    view.setChart(chart)


def grafico_barras_emprestimos_por_empresa(view: QChartView, resumo_empresas: list[dict], limite: int = 8) -> None:
    chart = _novo_chart("Empréstimos a sócios por empresa")

    ordenado = sorted(resumo_empresas, key=lambda r: r["total_emprestimos"], reverse=True)
    ordenado = [r for r in ordenado if r["total_emprestimos"] > 0][:limite]
    if not ordenado:
        chart.setTitle("Empréstimos a sócios por empresa — nenhum no período")
        view.setChart(chart)
        return

    conjunto = QBarSet("Empréstimos")
    conjunto.setColor(QColor(INK()))
    categorias = []
    for item in ordenado:
        conjunto.append(item["total_emprestimos"])
        categorias.append(item["empresa_nome"])

    serie = QHorizontalBarSeries()
    serie.append(conjunto)
    chart.addSeries(serie)

    eixo_categorias = QBarCategoryAxis()
    eixo_categorias.append(categorias)
    eixo_categorias.setLabelsFont(FONTE_EIXO)
    _estilizar_eixo(eixo_categorias)
    chart.addAxis(eixo_categorias, Qt.AlignLeft)
    serie.attachAxis(eixo_categorias)

    eixo_valores = QValueAxis()
    eixo_valores.setLabelsFont(FONTE_EIXO)
    eixo_valores.setLabelFormat("R$ %.0f")
    _estilizar_eixo(eixo_valores)
    chart.addAxis(eixo_valores, Qt.AlignBottom)
    serie.attachAxis(eixo_valores)

    chart.legend().setVisible(False)
    view.setChart(chart)


def grafico_pizza_classificacoes(view: QChartView, linhas: list[dict]) -> None:
    chart = _novo_chart("Sócios por classificação")

    if not linhas:
        chart.setTitle("Sócios por classificação — sem dados no período")
        view.setChart(chart)
        return

    contagem: dict[str, int] = {}
    for linha in linhas:
        contagem[linha["classificacao"]] = contagem.get(linha["classificacao"], 0) + 1

    serie = QPieSeries()
    serie.setHoleSize(0.45)
    for chave in ("proporcional", "desproporcional", "socio_sem_distribuicao", "empresa_sem_distribuicao"):
        if contagem.get(chave):
            serie.append(LABEL[chave], contagem[chave])

    for fatia in serie.slices():
        chave = next(k for k, v in LABEL.items() if v == fatia.label())
        fatia.setBrush(QColor(cor_classificacao(chave)))
        fatia.setPen(QColor(PAPER_RAISED()))
        fatia.setBorderWidth(2)
        fatia.setLabelVisible(False)
        fatia.setLabelColor(QColor(INK()))
        fatia.setLabelFont(FONTE_EIXO)
        fatia.setLabel(f"{fatia.label()} — {fatia.value():.0f}")

    chart.addSeries(serie)
    chart.legend().setVisible(True)
    chart.legend().setAlignment(Qt.AlignBottom)
    view.setChart(chart)


def grafico_capital_vs_distribuido(view: QChartView, linhas: list[dict]) -> None:
    chart = _novo_chart("% de capital vs % efetivamente distribuído")

    if not linhas:
        chart.setTitle("% de capital vs % efetivamente distribuído — sem dados no período")
        view.setChart(chart)
        return

    capital = QBarSet("% capital")
    capital.setColor(QColor(BRASS()))
    distribuido = QBarSet("% distribuído")
    distribuido.setColor(QColor(INK()))

    categorias = []
    for linha in linhas:
        capital.append(linha["percentual_capital"])
        distribuido.append(linha["percentual_distribuido"])
        categorias.append(f"{linha['ano_base']} · {linha['socio_nome']}")

    serie = QBarSeries()
    serie.append(capital)
    serie.append(distribuido)
    chart.addSeries(serie)

    eixo_x = QBarCategoryAxis()
    eixo_x.append(categorias)
    eixo_x.setLabelsFont(FONTE_EIXO)
    if len(categorias) > 4:
        eixo_x.setLabelsAngle(-45)
    _estilizar_eixo(eixo_x)
    chart.addAxis(eixo_x, Qt.AlignBottom)
    serie.attachAxis(eixo_x)

    eixo_y = QValueAxis()
    eixo_y.setLabelsFont(FONTE_EIXO)
    eixo_y.setLabelFormat("%.0f%%")
    _estilizar_eixo(eixo_y)
    chart.addAxis(eixo_y, Qt.AlignLeft)
    serie.attachAxis(eixo_y)

    chart.legend().setVisible(True)
    chart.legend().setAlignment(Qt.AlignBottom)
    view.setChart(chart)
