"""Conversão do informe de rendimentos (HTML) em PDF A4.

Fica na camada de interface de propósito: controle_lucros.informe_rendimentos
monta o HTML e continua testável sem GUI; aqui só acontece a conversão, que
depende do motor de texto do Qt.

Ao contrário do relatorio_pdf.py (que usa QPrinter, suficiente pra uma tabela
solta), aqui o caminho é o QPdfWriter em 300 DPI, porque o informe é um
documento com posicionamento fixo que precisa caber numa página A4 exata.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QMarginsF, QSizeF
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QPdfWriter, QTextDocument

RESOLUCAO_DPI = 300
MARGEM_MM = 10.0
# Segoe UI primeiro (é o que existe no Windows, onde o programa roda); DejaVu
# Sans é a alternativa no Linux. 7pt é o tamanho que faz os 8 quadros caberem
# numa página A4 só — o modelo oficial é de uma página.
FAMILIAS_FONTE = ["Segoe UI", "DejaVu Sans", "Arial"]
TAMANHO_FONTE_PT = 7.0


def gerar_pdf(html: str, caminho: Path) -> Path:
    caminho = Path(caminho)
    caminho.parent.mkdir(parents=True, exist_ok=True)

    escritor = QPdfWriter(str(caminho))
    escritor.setResolution(RESOLUCAO_DPI)
    escritor.setPageSize(QPageSize(QPageSize.A4))
    escritor.setPageMargins(QMarginsF(MARGEM_MM, MARGEM_MM, MARGEM_MM, MARGEM_MM), QPageLayout.Millimeter)

    documento = QTextDocument()
    # Amarrar o layout ao writer ANTES do setHtml. Sem isso o Qt converte
    # ponto em pixel a 96 DPI enquanto a página está a 300 DPI: o informe sai
    # com cerca de um terço do tamanho, espremido no topo da folha.
    documento.documentLayout().setPaintDevice(escritor)
    fonte = QFont()
    fonte.setFamilies(FAMILIAS_FONTE)
    fonte.setPointSizeF(TAMANHO_FONTE_PT)
    documento.setDefaultFont(fonte)
    documento.setHtml(html)
    documento.setPageSize(QSizeF(escritor.width(), escritor.height()))
    documento.print_(escritor)
    return caminho


def gerar_pdfs(paginas: list[tuple[str, str]], pasta: Path) -> list[Path]:
    """Um arquivo por informe — cada um é o documento de uma fonte pagadora
    específica, então não faz sentido emendar tudo num PDF só. `paginas` é uma
    lista de (nome_do_arquivo, html)."""
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    return [gerar_pdf(html, _caminho_livre(pasta, nome)) for nome, html in paginas]


def _caminho_livre(pasta: Path, nome: str) -> Path:
    """Nunca sobrescreve um informe já emitido: reemitir depois de corrigir um
    valor deve deixar os dois arquivos na pasta, pra dar pra ver qual é qual."""
    candidato = pasta / nome
    if not candidato.exists():
        return candidato
    base, extensao = candidato.stem, candidato.suffix
    contador = 1
    while candidato.exists():
        candidato = pasta / f"{base} ({contador}){extensao}"
        contador += 1
    return candidato
