"""Exportação de relatórios em PDF usando o motor de impressão nativo do Qt
(QTextDocument + QPrinter) — sem depender de nenhuma lib externa de PDF."""
from __future__ import annotations

import html
from pathlib import Path

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter

_ESTILO = """
<style>
    body { font-family: "Segoe UI", Arial, sans-serif; color: #1B2A41; }
    h1 { font-family: Cambria, Georgia, serif; font-size: 20px; margin: 0 0 2px 0; }
    .subtitulo { color: #5B6472; font-size: 11px; margin-bottom: 6px; }
    .gerado_em { color: #8A93A0; font-size: 9px; margin-bottom: 16px; }
    table { border-collapse: collapse; width: 100%; font-size: 9.5px; }
    th { background: #1B2A41; color: #FFFFFF; text-align: left; padding: 6px 8px; }
    td { padding: 5px 8px; border-bottom: 1px solid #D9D3C2; }
    tr.par td { background: #FBF9F3; }
    .badge-proporcional { color: #2F5233; font-weight: 600; }
    .badge-desproporcional { color: #7A2E2E; font-weight: 600; }
    .badge-neutro { color: #5B6472; }
</style>
"""


def _linha_html(celulas: list[str], par: bool, classe_ultima_celula: str | None) -> str:
    tds = [f"<td>{html.escape(str(c))}</td>" for c in celulas[:-1]]
    ultima_classe = f' class="{classe_ultima_celula}"' if classe_ultima_celula else ""
    tds.append(f"<td{ultima_classe}>{html.escape(str(celulas[-1]))}</td>")
    classe_linha = ' class="par"' if par else ""
    return f"<tr{classe_linha}>{''.join(tds)}</tr>"


def exportar_relatorio_pdf(
    caminho: Path,
    titulo: str,
    subtitulo: str,
    cabecalho: list[str],
    linhas: list[list],
    gerado_em: str = "",
    classe_por_linha: list[str | None] | None = None,
) -> None:
    """linhas: lista de listas de valores (na mesma ordem do cabeçalho).
    classe_por_linha: classe CSS opcional pra colorir a última coluna de cada
    linha (ex.: "badge-proporcional" / "badge-desproporcional")."""
    cabecalho_html = "".join(f"<th>{html.escape(c)}</th>" for c in cabecalho)
    linhas_html = []
    for i, linha in enumerate(linhas):
        classe = classe_por_linha[i] if classe_por_linha else None
        linhas_html.append(_linha_html(linha, par=(i % 2 == 1), classe_ultima_celula=classe))

    corpo = f"""
    <html><head>{_ESTILO}</head><body>
        <h1>{html.escape(titulo)}</h1>
        <div class="subtitulo">{html.escape(subtitulo)}</div>
        <div class="gerado_em">{html.escape(gerado_em)}</div>
        <table>
            <thead><tr>{cabecalho_html}</tr></thead>
            <tbody>{''.join(linhas_html)}</tbody>
        </table>
    </body></html>
    """

    documento = QTextDocument()
    documento.setHtml(corpo)

    impressora = QPrinter(QPrinter.HighResolution)
    impressora.setOutputFormat(QPrinter.PdfFormat)
    impressora.setOutputFileName(str(caminho))
    layout = QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Landscape, QMarginsF(12, 12, 12, 12), QPageLayout.Millimeter)
    impressora.setPageLayout(layout)

    documento.setPageSize(impressora.pageRect(QPrinter.Point).size())
    documento.print_(impressora)
