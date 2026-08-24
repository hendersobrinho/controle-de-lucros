import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from controle_lucros.ui.relatorio_pdf import exportar_relatorio_pdf


@pytest.fixture(scope="module", autouse=True)
def app():
    aplicativo = QApplication.instance() or QApplication([])
    yield aplicativo


def test_exportar_relatorio_pdf_gera_arquivo(tmp_path):
    caminho = tmp_path / "relatorio.pdf"
    exportar_relatorio_pdf(
        caminho,
        titulo="Relatório de Distribuição de Lucros",
        subtitulo="Período: 2024 · Tolerância: 5 p.p.",
        cabecalho=["Empresa", "Sócio", "CPF", "Classificação"],
        linhas=[
            ["ACME LTDA", "Fulano", "111.111.111-11", "Proporcional"],
            ["ACME LTDA", "Beltrano", "222.222.222-22", "Desproporcional"],
        ],
        gerado_em="Gerado em 21/08/2026",
        classe_por_linha=["badge-proporcional", "badge-desproporcional"],
    )
    assert caminho.exists()
    assert caminho.stat().st_size > 1000


def test_exportar_relatorio_pdf_sem_linhas_nao_quebra(tmp_path):
    caminho = tmp_path / "vazio.pdf"
    exportar_relatorio_pdf(caminho, titulo="Vazio", subtitulo="", cabecalho=["A", "B"], linhas=[])
    assert caminho.exists()
