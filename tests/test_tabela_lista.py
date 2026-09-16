"""A regra de largura das colunas e o comportamento da tabela.

É o que decide se a grade vai parecer inteira ou cortada no meio da tela, e é
fácil de errar nas pontas: ora sobra um vão morto à direita, ora aparece uma
barra de rolagem por causa de seis pixels, ora a coluna encolhe para nada
adiantar. Cada um desses casos tem o seu teste.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QTableWidgetItem

from controle_lucros.ui.common import (
    LARGURA_MINIMA_COLUNA_FLEXIVEL,
    TabelaLista,
    larguras_ajustadas,
)


@pytest.fixture(scope="module", autouse=True)
def app():
    yield QApplication.instance() or QApplication([])


# ------------------------------------------------------------- sobrando --
def test_o_que_sobra_vai_para_a_coluna_flexivel():
    """Sem isto fica um vão morto à direita da última coluna, que é metade da
    sensação de tabela quebrada."""
    assert larguras_ajustadas([100, 80, 60], disponivel=300, flexivel=0) == [160, 80, 60]


def test_a_coluna_flexivel_pode_ser_qualquer_uma():
    # Na tela de empresas quem cresce é o nome, não o número da empresa.
    assert larguras_ajustadas([60, 120, 80], disponivel=400, flexivel=1) == [60, 260, 80]


def test_indice_fora_da_faixa_cai_na_primeira():
    assert larguras_ajustadas([100, 50], disponivel=200, flexivel=9) == [150, 50]


def test_largura_exata_nao_mexe_em_nada():
    assert larguras_ajustadas([100, 80], disponivel=180, flexivel=0) == [100, 80]


# -------------------------------------------------------------- faltando --
def test_a_flexivel_cede_o_pouco_que_falta():
    """Barra de rolagem por causa de vinte pixels, com a tabela vazia embaixo,
    é exatamente o que incomoda."""
    larguras = larguras_ajustadas([200, 100, 100], disponivel=380, flexivel=0)

    assert larguras == [180, 100, 100]
    assert sum(larguras) == 380


def test_nao_encolhe_alem_do_minimo_util():
    larguras = larguras_ajustadas([200, 100, 100], disponivel=260, flexivel=0)

    # Encolher até 60 não faria caber (precisaria de 40 a mais), então nem
    # começa: fica a largura cheia e a barra de rolagem aparece.
    assert larguras == [200, 100, 100]


def test_encolhe_exatamente_ate_o_minimo_quando_isso_resolve():
    conteudo = [LARGURA_MINIMA_COLUNA_FLEXIVEL + 40, 100]
    disponivel = LARGURA_MINIMA_COLUNA_FLEXIVEL + 100

    larguras = larguras_ajustadas(conteudo, disponivel, flexivel=0)

    assert larguras[0] == LARGURA_MINIMA_COLUNA_FLEXIVEL
    assert sum(larguras) == disponivel


def test_tabela_larga_demais_nao_espreme_ninguem_a_toa():
    """Onze colunas não cabem de jeito nenhum; espremer o nome do sócio junto
    seria perder de graça, porque a barra vai aparecer igual."""
    conteudo = [150] + [90] * 10

    larguras = larguras_ajustadas(conteudo, disponivel=700, flexivel=0)

    assert larguras == conteudo


def test_nenhuma_coluna_nao_quebra():
    assert larguras_ajustadas([], disponivel=500) == []


# ---------------------------------------------------------------- tabela --
def _tabela_preenchida(nomes, largura=400):
    """A tabela precisa estar visível: enquanto não é exibida, o Qt não
    repassa o tamanho ao viewport, e é a largura do viewport que a regra usa."""
    tabela = TabelaLista(0, 2, coluna_flexivel=0, mensagem_vazia="Nada aqui.")
    tabela.setHorizontalHeaderLabels(["Nome", "CPF"])
    tabela.setRowCount(len(nomes))
    for linha, nome in enumerate(nomes):
        tabela.setItem(linha, 0, QTableWidgetItem(nome))
        tabela.setItem(linha, 1, QTableWidgetItem("111.111.111-11"))
    tabela.resize(largura, 200)
    tabela.show()
    QApplication.processEvents()
    tabela.ajustar_colunas()
    return tabela


def test_tabela_nasce_sem_a_grade_quadriculada():
    """São os trilhos verticais parando no ar depois do último registro que
    fazem a tela parecer cortada no meio."""
    tabela = TabelaLista(0, 2)

    assert not tabela.showGrid()
    assert tabela.alternatingRowColors()
    assert not tabela.verticalHeader().isVisible()


def test_colunas_ocupam_a_largura_toda_da_tabela():
    tabela = _tabela_preenchida(["ANA", "BRUNO"])

    soma = sum(tabela.columnWidth(i) for i in range(tabela.columnCount()))
    assert soma == tabela.viewport().width()


def test_o_cabecalho_serve_de_piso_mesmo_sem_linhas():
    """Tabela vazia com as colunas de 100px do Qt somava mais que a tela e
    trazia barra de rolagem para não mostrar nada."""
    tabela = TabelaLista(0, 2, coluna_flexivel=0)
    tabela.setHorizontalHeaderLabels(["Valor da participação", "IRRF"])
    tabela.resize(600, 200)
    tabela.show()
    QApplication.processEvents()
    tabela.ajustar_colunas()

    assert tabela.columnWidth(0) >= tabela.horizontalHeader().sectionSizeHint(0)
    assert tabela.columnWidth(1) >= tabela.horizontalHeader().sectionSizeHint(1)


def test_texto_cortado_ganha_o_conteudo_como_dica():
    """A flexível é a que encolhe, então é nela que aparece reticência — e sem
    jeito de ver o resto seria trocar um incômodo por outro."""
    tabela = _tabela_preenchida(["ANA", "B" * 200])

    assert tabela.item(0, 0).toolTip() == ""
    assert tabela.item(1, 0).toolTip() == "B" * 200


def test_redimensionar_a_janela_redistribui_a_sobra():
    """Sem redistribuir no resize, a coluna flexível guardaria a largura de
    quando a tabela foi preenchida e o vão morto voltaria ao arrastar a borda
    da janela."""
    tabela = _tabela_preenchida(["ANA", "BRUNO"], largura=400)
    antes = tabela.columnWidth(0)

    tabela.resize(700, 200)
    QApplication.processEvents()

    assert tabela.columnWidth(0) > antes
    assert sum(tabela.columnWidth(i) for i in range(2)) == tabela.viewport().width()
