"""Extração do texto de um PDF, para a importação do relatório de sócios.

Fica na camada de interface pelo mesmo motivo do informe_pdf.py: quem sabe
ler PDF aqui é o Qt, e deixar isso separado mantém o
controle_lucros.relatorio_socios — que é onde mora a parte difícil, o
casamento do layout — testável sem Qt e sem arquivo no disco.

Usa o QtPdf, que já vem no PySide6: nenhuma biblioteca de PDF a mais no
pacote. O módulo é carregado sob demanda porque só a importação de
relatório precisa dele.
"""
from __future__ import annotations

from pathlib import Path


class PdfIlegivel(ValueError):
    """O arquivo não abriu como PDF, ou abriu vazio."""


def extrair_texto(caminho: Path) -> str:
    """Todo o texto do PDF, com as páginas separadas por quebra de linha.

    PDF de relatório vem com o texto em camada de texto mesmo (foi gerado
    por um sistema, não escaneado), então não há OCR envolvido — se o
    arquivo for um scan, o texto sai vazio e o erro explica isso."""
    from PySide6.QtPdf import QPdfDocument

    caminho = Path(caminho)
    documento = QPdfDocument()
    erro = documento.load(str(caminho))
    if erro != QPdfDocument.Error.None_:
        raise PdfIlegivel(
            f'Não consegui abrir "{caminho.name}" como PDF. Confira se o arquivo '
            "não está corrompido ou protegido por senha."
        )

    paginas = [documento.getAllText(i).text() for i in range(documento.pageCount())]
    texto = "\n".join(paginas)
    if not texto.strip():
        raise PdfIlegivel(
            f'"{caminho.name}" não tem texto — parece ser um PDF digitalizado '
            "(imagem). Só dá para importar o relatório gerado pelo outro sistema, "
            "que vem com o texto dentro do arquivo."
        )
    return texto
