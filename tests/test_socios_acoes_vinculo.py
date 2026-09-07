"""Menu de ações do vínculo na aba de Sócios.

As quatro ações que dependem do vínculo selecionado (editar datas, atualizar
cotas, encerrar, excluir) ficam num menu só. O que estes testes prendem é que
juntar não afrouxou nenhuma das regras de quando cada uma vale.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3

import pytest
from PySide6.QtWidgets import QApplication

from controle_lucros import db, repositories as repo
from controle_lucros.models import Empresa, Socio
from controle_lucros.ui.socios_tab import SociosTab


@pytest.fixture(scope="module", autouse=True)
def app():
    aplicativo = QApplication.instance() or QApplication([])
    yield aplicativo


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    db.init_schema(connection)
    yield connection
    connection.close()


@pytest.fixture()
def cenario(conn):
    empresa_id = repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 100000, 1000))
    socio_id = repo.salvar_socio(conn, Socio(None, "Fulano de Tal", "005.169.717-35"))
    repo.associar_socio_a_empresa(conn, empresa_id, socio_id, 100.0, 1000, "2020-01-01")
    return {"empresa": empresa_id, "socio": socio_id}


def _aba(conn) -> SociosTab:
    aba = SociosTab(conn)
    aba.tabela.selectRow(0)
    return aba


def _acoes(aba) -> dict:
    return {
        "editar": aba.acao_editar,
        "cotas": aba.acao_atualizar_cotas,
        "encerrar": aba.acao_encerrar,
        "excluir": aba.acao_excluir,
    }


def test_menu_tem_as_quatro_acoes_na_ordem(conn, cenario):
    aba = _aba(conn)
    rotulos = [a.text() for a in aba.btn_acoes_vinculo.menu().actions() if not a.isSeparator()]
    assert rotulos == ["Editar datas", "Atualizar cotas", "Encerrar vínculo", "Excluir vínculo"]


def test_as_destrutivas_ficam_separadas_das_outras(conn, cenario):
    """A linha separadora é o aviso visual que o vermelho dos botões dava."""
    acoes = _aba(conn).btn_acoes_vinculo.menu().actions()
    posicao_separador = next(i for i, a in enumerate(acoes) if a.isSeparator())
    antes = [a.text() for a in acoes[:posicao_separador]]
    depois = [a.text() for a in acoes[posicao_separador + 1:]]
    assert antes == ["Editar datas", "Atualizar cotas"]
    assert depois == ["Encerrar vínculo", "Excluir vínculo"]


def test_sem_vinculo_selecionado_o_botao_inteiro_trava(conn, cenario):
    """Abrir um menu com tudo apagado não ajuda ninguém."""
    aba = SociosTab(conn)
    aba.tabela.selectRow(0)  # seleciona o sócio, não o vínculo
    assert aba.tabela_vinculos.rowCount() == 1
    assert not aba.btn_acoes_vinculo.isEnabled()
    # "Associar" fica de fora do menu porque não depende de vínculo selecionado.
    assert aba.btn_associar.isEnabled()


def test_com_vinculo_ativo_todas_as_acoes_valem(conn, cenario):
    aba = _aba(conn)
    aba.tabela_vinculos.selectRow(0)
    assert aba.btn_acoes_vinculo.isEnabled()
    assert all(acao.isEnabled() for acao in _acoes(aba).values())


def test_vinculo_encerrado_so_permite_editar_datas_e_excluir(conn, cenario):
    """Encerrar de novo ou mexer nas cotas de quem já saiu não faz sentido —
    era o que os botões desabilitados diziam antes."""
    vinculo = repo.listar_vinculos_socio(conn, cenario["socio"])[0]
    repo.encerrar_vinculo_registrando_alteracao(conn, vinculo, "2024-06-30", "Saída")

    aba = _aba(conn)
    aba.tabela_vinculos.selectRow(0)
    acoes = _acoes(aba)
    assert acoes["editar"].isEnabled()
    assert acoes["excluir"].isEnabled()
    assert not acoes["cotas"].isEnabled()
    assert not acoes["encerrar"].isEnabled()


def test_acoes_do_menu_continuam_ligadas_aos_mesmos_metodos(conn, cenario, monkeypatch):
    """Juntar num menu não pode ter trocado o que cada item dispara. Os dublês
    entram na classe antes de montar a aba, porque é na construção do menu que
    cada ação se liga ao método."""
    chamadas = []
    nomes = ("_editar_vinculo", "_atualizar_cotas", "_encerrar_vinculo", "_excluir_vinculo")
    for nome in nomes:
        # *args engole o "checked" que o triggered do Qt manda junto.
        monkeypatch.setattr(SociosTab, nome, lambda self, *args, n=nome: chamadas.append(n))

    aba = _aba(conn)
    aba.tabela_vinculos.selectRow(0)
    for acao in (aba.acao_editar, aba.acao_atualizar_cotas, aba.acao_encerrar, aba.acao_excluir):
        acao.trigger()

    assert chamadas == list(nomes)


def test_tudo_cabe_numa_linha_na_largura_padrao(conn, cenario):
    """Foi o problema que motivou juntar: seis botões soltos truncavam os
    rótulos em 1180px."""
    aba = _aba(conn)
    aba.resize(760, 600)
    aba.layout().activate()
    for botao in (aba.btn_associar, aba.btn_acoes_vinculo, aba.btn_informe):
        assert botao.sizeHint().width() > 0
    largura_necessaria = sum(
        b.sizeHint().width() for b in (aba.btn_associar, aba.btn_acoes_vinculo, aba.btn_informe)
    )
    assert largura_necessaria < 620


def test_nenhum_botao_trunca_na_largura_minima_da_janela(conn, cenario):
    """A régua é a janela no seu tamanho mínimo: se couber ali, cabe em
    qualquer uso real. Foi assim que "Cancelar" virou "ancel" antes."""
    from controle_lucros.ui.main_window import MainWindow

    repo.criar_usuario(conn, "Admin", "admin", "senha123", True)
    janela = MainWindow(conn, repo.listar_usuarios(conn)[0])
    janela.resize(janela.minimumSizeHint().width(), 720)
    janela._ir_para("socios")
    janela.show()

    aba = janela.socios_tab
    aba.tabela.selectRow(0)
    aba.tabela_vinculos.selectRow(0)
    janela.layout().activate()

    botoes = {
        "Novo": aba.btn_novo, "Salvar": aba.btn_salvar, "Cancelar": aba.btn_cancelar,
        "Excluir": aba.btn_excluir, "Associar": aba.btn_associar,
        "Ações do vínculo": aba.btn_acoes_vinculo, "Informe": aba.btn_informe,
    }
    truncados = [nome for nome, b in botoes.items() if b.width() < b.sizeHint().width()]
    assert truncados == [], f"rótulos cortados: {truncados}"
