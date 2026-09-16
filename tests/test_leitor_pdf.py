"""Extração do texto de um PDF de verdade.

O teste gera o PDF com o mesmo QPdfWriter usado no informe e lê de volta com
o QtPdf: é o percurso completo que a importação de relatório faz, sem
precisar de um arquivo de exemplo versionado no repositório.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from controle_lucros.relatorio_socios import ler_relatorio_socios
from controle_lucros.ui.informe_pdf import gerar_pdf
from controle_lucros.ui.leitor_pdf import PdfIlegivel, extrair_texto


@pytest.fixture(scope="module", autouse=True)
def app():
    aplicativo = QApplication.instance() or QApplication([])
    yield aplicativo


HTML_RELATORIO = """
<html><body>
<p>Empresa: 91 - ENDOGASTRO CLINICA MEDICA LTDA Data do quadro societário: 20/05/2026</p>
<p>75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 23/03/2007 46,94</p>
<p>707 LUIZA DIAS TORRES 103.285.827-35 02/03/2023 20/05/2026 0</p>
</body></html>
"""


def test_le_o_texto_do_pdf_e_o_relatorio_sai_inteiro(tmp_path):
    caminho = gerar_pdf(HTML_RELATORIO, tmp_path / "relatorio.pdf")

    texto = extrair_texto(caminho)
    (empresa,) = ler_relatorio_socios(texto).empresas

    assert empresa.numero == "91"
    assert [s.nome for s in empresa.socios] == ["ANDRE FRANZOTTI CARDOSO", "LUIZA DIAS TORRES"]
    assert empresa.socios[1].data_saida == "2026-05-20"


def test_arquivo_que_nao_e_pdf_reclama(tmp_path):
    caminho = tmp_path / "planilha.pdf"
    caminho.write_bytes(b"isto aqui nao e um PDF")

    with pytest.raises(PdfIlegivel):
        extrair_texto(caminho)


def test_arquivo_inexistente_reclama(tmp_path):
    with pytest.raises(PdfIlegivel):
        extrair_texto(tmp_path / "nao_existe.pdf")
