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
    QValueAxis,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPainter

from .theme import BRASS, HAIRLINE, INK, INK_MUTED, PAPER_RAISED, SAIU_FG

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
    # Menos marcas no eixo: com o padrão, os rótulos de reais se encostam e
    # viram uma tira ilegível na base do gráfico.
    eixo_valores.setTickCount(4)
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
    # Menos marcas no eixo: com o padrão, os rótulos de reais se encostam e
    # viram uma tira ilegível na base do gráfico.
    eixo_valores.setTickCount(4)
    _estilizar_eixo(eixo_valores)
    chart.addAxis(eixo_valores, Qt.AlignBottom)
    serie.attachAxis(eixo_valores)

    chart.legend().setVisible(False)
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


def grafico_sem_pro_labore(view: QChartView, itens: list, limite: int = 8) -> None:
    """Quem recebeu lucro sem pró-labore, do maior para o menor.

    Entrou no lugar da pizza de proporcional × desproporcional, que só
    repetia em desenho o que os dois cartões acima já diziam em número. Este
    aponta nome e valor — dá para pegar o telefone depois de olhar."""
    chart = _novo_chart("Distribuição sem pró-labore")

    ordenado = [i for i in itens if i.valor_distribuido > 0][:limite]
    if not ordenado:
        chart.setTitle("Distribuição sem pró-labore — nenhum caso no período")
        view.setChart(chart)
        return

    conjunto = QBarSet("Lucro recebido")
    conjunto.setColor(QColor(SAIU_FG()))
    rotulos = []
    for item in ordenado:
        conjunto.append(item.valor_distribuido)
        anos = f" · {item.anos_sem_pro_labore} anos" if item.anos_sem_pro_labore > 1 else ""
        # Uma palavra de cada lado: o eixo é estreito, e "ANDRE · ENDOGASTRO"
        # identifica o caso melhor do que "ANDRE FRANZOTTI …" cortado.
        rotulos.append(
            f"{_primeiro_nome(item.socio_nome, 1)} · {_primeiro_nome(item.empresa_nome, 1)}{anos}"
        )
    categorias = _categorias_unicas(rotulos)

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
    # Menos marcas no eixo: com o padrão, os rótulos de reais se encostam e
    # viram uma tira ilegível na base do gráfico.
    eixo_valores.setTickCount(4)
    _estilizar_eixo(eixo_valores)
    chart.addAxis(eixo_valores, Qt.AlignBottom)
    serie.attachAxis(eixo_valores)

    chart.legend().setVisible(False)
    view.setChart(chart)


def grafico_desvio_por_socio(view: QChartView, itens: list, limite: int = 10) -> None:
    """Quanto cada sócio recebeu além (ou aquém) do que a participação daria.

    Duas barras em cores opostas a partir do zero: à direita quem recebeu a
    mais, à esquerda quem recebeu a menos. Substituiu a pizza de
    classificações, que dizia quantos sócios estavam fora do eixo sem dizer
    por quanto — e é o "por quanto" que vira conversa com o cliente."""
    chart = _novo_chart("Desvio em relação à participação")

    ordenado = [i for i in itens if abs(i.desvio) >= 0.01][:limite]
    if not ordenado:
        chart.setTitle("Desvio — distribuição proporcional no período")
        view.setChart(chart)
        return

    # Dois conjuntos no mesmo eixo, cada um com zero onde o outro tem valor:
    # é assim que o QtCharts desenha barra divergente mantendo uma cor para
    # cada lado.
    # Nenhum dos dois lados é "o certo": receber aquém da participação é tão
    # fora do eixo quanto receber além. Por isso não há verde aqui — verde
    # leria como "este está ok". O vermelho fica com quem recebeu a mais, que
    # é o lado que costuma vir acompanhado de pergunta da fiscalização; o
    # outro fica em tinta, sóbrio.
    a_mais = QBarSet("Recebeu a mais")
    a_mais.setColor(QColor(SAIU_FG()))
    a_menos = QBarSet("Recebeu a menos")
    a_menos.setColor(QColor(INK()))

    rotulos = []
    for item in ordenado:
        a_mais.append(item.desvio if item.desvio > 0 else 0)
        a_menos.append(item.desvio if item.desvio < 0 else 0)
        rotulos.append(_primeiro_nome(item.socio_nome))
    categorias = _categorias_unicas(rotulos)

    serie = QHorizontalBarSeries()
    serie.append(a_mais)
    serie.append(a_menos)
    chart.addSeries(serie)

    eixo_categorias = QBarCategoryAxis()
    eixo_categorias.append(categorias)
    eixo_categorias.setLabelsFont(FONTE_EIXO)
    _estilizar_eixo(eixo_categorias)
    chart.addAxis(eixo_categorias, Qt.AlignLeft)
    serie.attachAxis(eixo_categorias)

    maior = max(abs(i.desvio) for i in ordenado)
    eixo_valores = QValueAxis()
    # Simétrico em torno do zero: sem isso o lado com o maior desvio domina a
    # escala e o outro vira um risco, como se não houvesse desvio nenhum ali.
    eixo_valores.setRange(-maior * 1.1, maior * 1.1)
    eixo_valores.setLabelsFont(FONTE_EIXO)
    eixo_valores.setLabelFormat("R$ %.0f")
    _estilizar_eixo(eixo_valores)
    chart.addAxis(eixo_valores, Qt.AlignBottom)
    serie.attachAxis(eixo_valores)

    chart.legend().setVisible(True)
    chart.legend().setAlignment(Qt.AlignBottom)
    view.setChart(chart)


def _categorias_unicas(rotulos: list[str]) -> list[str]:
    """O eixo de categorias do QtCharts usa o texto como identidade: dois
    rótulos iguais viram uma barra só, e o mesmo sócio em duas empresas
    desaparecia do gráfico. Um espaço invisível no fim resolve sem sujar o
    rótulo."""
    vistos: dict[str, int] = {}
    unicos = []
    for rotulo in rotulos:
        repeticoes = vistos.get(rotulo, 0)
        vistos[rotulo] = repeticoes + 1
        unicos.append(rotulo + "\u2009" * repeticoes)
    return unicos


def _primeiro_nome(nome: str, palavras: int = 2) -> str:
    """Razão social e nome completo não cabem no eixo de um gráfico estreito;
    duas palavras bastam para reconhecer quem é."""
    partes = str(nome or "").split()
    return " ".join(partes[:palavras]) if partes else "?"
