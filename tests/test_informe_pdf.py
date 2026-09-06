"""Geração do PDF do informe. Separado dos testes do conteúdo porque estes
precisam do motor de texto do Qt (e, portanto, de uma QApplication)."""
import os
import re

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from controle_lucros.informe_rendimentos import (
    BRASAO_ALTURA,
    BRASAO_ARQUIVO,
    BRASAO_LARGURA,
    caminho_brasao,
    montar_html,
)
from controle_lucros.models import InformeRendimento
from controle_lucros.ui.icones import pasta_assets
from controle_lucros.ui.informe_pdf import gerar_pdf, gerar_pdfs


@pytest.fixture(scope="module", autouse=True)
def app():
    aplicativo = QApplication.instance() or QApplication([])
    yield aplicativo


def _html() -> str:
    informe = InformeRendimento(
        id=None,
        empresa_id=1,
        socio_id=1,
        ano_base=2025,
        codigo_beneficiario="000001",
        q3_total_rendimentos=2450000,
        q3_previdencia_oficial=269500,
        q3_irrf=56251,
        q4_lucros_dividendos=38764946,
        emprestimo_saldo=78551616,
        responsavel_nome="ELLEN SCHNEIDER EWALD",
    )
    return montar_html(
        informe,
        empresa_nome="CLINIRIM - CLINICA DO RIM LTDA",
        empresa_cnpj="00317100000146",
        socio_nome="RENATA MARIA BOURGUIGNON TORRES",
        socio_cpf="07252543781",
        data_emissao="15/04/2026",
    )


def _paginas(pdf: bytes) -> int:
    return int(re.search(rb"/Count\s+(\d+)", pdf).group(1))


def test_o_brasao_esta_empacotado_junto_com_o_resto_dos_assets():
    """O brasão vai no cabeçalho de todo informe; se sumir do pacote, o
    documento sai sem ele e ninguém percebe até imprimir."""
    assert (pasta_assets() / BRASAO_ARQUIVO).exists()
    assert caminho_brasao() is not None


def test_brasao_tem_fundo_transparente():
    """Sem canal alfa o fundo transparente vira um quadrado preto em volta do
    brasão no informe impresso — foi assim que quebrou uma vez."""
    from PySide6.QtGui import QImage

    imagem = QImage(str(pasta_assets() / BRASAO_ARQUIVO))
    assert imagem.hasAlphaChannel()
    assert imagem.pixelColor(0, 0).alpha() == 0


def test_dimensoes_do_brasao_no_html_batem_com_o_arquivo():
    """Se a proporção declarada não for a do PNG, o Qt estica a imagem pra
    caber e o brasão sai deformado — sem erro nenhum."""
    from PySide6.QtGui import QImage

    imagem = QImage(str(pasta_assets() / BRASAO_ARQUIVO))
    proporcao_arquivo = imagem.width() / imagem.height()
    proporcao_html = BRASAO_LARGURA / BRASAO_ALTURA
    assert abs(proporcao_arquivo - proporcao_html) < 0.02, (
        f"O brasão é {imagem.width()}x{imagem.height()} mas o informe declara "
        f"{BRASAO_LARGURA}x{BRASAO_ALTURA}. Ajuste BRASAO_LARGURA/BRASAO_ALTURA."
    )


def test_brasao_nao_tem_margem_transparente_sobrando():
    """Margem vazia em volta encolhe o desenho dentro do espaço reservado no
    cabeçalho — a imagem tem que estar recortada no conteúdo."""
    from PySide6.QtGui import QImage

    imagem = QImage(str(pasta_assets() / BRASAO_ARQUIVO))
    # Alguma coisa opaca tem que encostar em cada uma das quatro bordas.
    topo = any(imagem.pixelColor(x, 0).alpha() > 0 for x in range(imagem.width()))
    base = any(imagem.pixelColor(x, imagem.height() - 1).alpha() > 0 for x in range(imagem.width()))
    esquerda = any(imagem.pixelColor(0, y).alpha() > 0 for y in range(imagem.height()))
    direita = any(imagem.pixelColor(imagem.width() - 1, y).alpha() > 0 for y in range(imagem.height()))
    assert (topo, base, esquerda, direita) == (True, True, True, True)


def test_gerar_pdf_produz_uma_unica_pagina_a4(tmp_path):
    """O modelo oficial é de uma página. Se o layout escapar pra duas, é
    sinal de que a fonte ou as margens saíram do lugar."""
    caminho = gerar_pdf(_html(), tmp_path / "informe.pdf")
    conteudo = caminho.read_bytes()
    assert conteudo.startswith(b"%PDF")
    assert _paginas(conteudo) == 1
    # Com o brasão embutido e a escala certa, o arquivo fica na casa das
    # dezenas de KB; um PDF de poucos KB seria sinal de página em branco.
    assert 20_000 < len(conteudo) < 400_000


def test_gerar_pdfs_grava_um_arquivo_por_fonte_pagadora(tmp_path):
    gerados = gerar_pdfs([("CSI.pdf", _html()), ("CLINIRIM.pdf", _html())], tmp_path / "saida")
    assert [c.name for c in gerados] == ["CSI.pdf", "CLINIRIM.pdf"]
    assert all(c.exists() for c in gerados)


def test_reemitir_nao_sobrescreve_o_informe_anterior(tmp_path):
    """Corrigir um valor e emitir de novo deve deixar os dois arquivos na
    pasta — apagar o anterior esconderia o que já foi entregue ao sócio."""
    primeiro = gerar_pdfs([("Informe.pdf", _html())], tmp_path)[0]
    segundo = gerar_pdfs([("Informe.pdf", _html())], tmp_path)[0]
    terceiro = gerar_pdfs([("Informe.pdf", _html())], tmp_path)[0]
    assert [primeiro.name, segundo.name, terceiro.name] == [
        "Informe.pdf",
        "Informe (1).pdf",
        "Informe (2).pdf",
    ]
