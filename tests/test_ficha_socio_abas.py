"""Ficha do sócio em abas: "Visão geral" com todas as empresas e todas as
movimentações, e uma aba por empresa com o que é só dela."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QLabel

from controle_lucros import repositories as repo
from controle_lucros.models import AlteracaoContratual, Empresa, Socio, VinculoSocietario
from controle_lucros.ui.cartao_participacao import CartaoParticipacao
from controle_lucros.ui.ficha_socio import LinhaMovimento
from controle_lucros.ui.socios_tab import SociosTab


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture()
def cenario(conn):
    acme = repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 1000, 1000))
    beta = repo.salvar_empresa(conn, Empresa(None, "002", "BETA LTDA", "", 1000, 1000))
    socio = repo.salvar_socio(conn, Socio(None, "Fulano de Tal", ""))
    a1 = repo.salvar_alteracao(conn, AlteracaoContratual(None, acme, 1, "2020-01-01", "ACME LTDA", 1000, 1000, ""))
    a2 = repo.salvar_alteracao(conn, AlteracaoContratual(None, acme, 2, "2022-01-01", "ACME LTDA", 1000, 1000, ""))
    antigo = repo.salvar_vinculo(conn, VinculoSocietario(None, acme, socio, 30, 300, "2020-01-01", None,
                                                          alteracao_entrada_id=a1))
    # Participação refeita na Nº 2: 30% -> 40%.
    repo.encerrar_vinculo(conn, antigo, "2022-01-01", a2)
    repo.salvar_vinculo(conn, VinculoSocietario(None, acme, socio, 40, 400, "2022-01-01", None,
                                                alteracao_entrada_id=a2))
    repo.salvar_vinculo(conn, VinculoSocietario(None, beta, socio, 10, 100, "2019-05-01", "2021-03-01"))
    return {"acme": acme, "beta": beta, "socio": socio}


def _aba(conn):
    aba = SociosTab(conn)
    aba.lista.selectRow(0)
    return aba


def _textos(widget) -> str:
    return " | ".join(r.text() for r in widget.findChildren(QLabel))


def test_movimentacoes_juntam_a_participacao_refeita_num_evento_so(conn, cenario):
    eventos = repo.movimentacoes_do_socio(conn, cenario["socio"])
    resumo = [(e["data"], e["empresa_nome"], e["tipo"]) for e in eventos]
    assert resumo == [
        ("2022-01-01", "ACME LTDA", "mudou"),
        ("2022-01-01", "ACME LTDA", "saiu"),
        ("2021-03-01", "BETA LTDA", "saiu"),
        ("2020-01-01", "ACME LTDA", "entrou"),
        ("2019-05-01", "BETA LTDA", "entrou"),
    ]
    mudou = eventos[0]
    assert (mudou["percentual_antes"], mudou["percentual"], mudou["alteracao_numero"]) == (30, 40, 2)
    # O encerramento da participação antiga aparece, marcado como refeita.
    assert eventos[1]["refeita"] and not eventos[2]["refeita"]


def test_cartao_diz_desde_quando_esta_na_empresa_e_nao_desde_a_refeita(conn, cenario):
    aba = _aba(conn)
    textos = _textos(aba.cartoes[0])
    assert "desde 01/01/2020" in textos
    assert "Participação refeita pela alteração Nº 2" in textos


def test_abas_sao_visao_geral_e_uma_por_empresa_so_com_o_nome(conn, cenario):
    aba = _aba(conn)
    textos = [b.text() for b in aba.abas.botoes]
    assert textos == ["Visão geral", "ACME", "BETA"]
    assert aba.abas.botoes[2].property("apagada") == "true"
    assert aba.paginas.currentIndex() == 0


def test_visao_geral_tem_o_cartao_de_cada_empresa_e_nao_as_movimentacoes(conn, cenario):
    aba = _aba(conn)
    geral = _textos(aba.paginas.widget(0))
    assert "ACME LTDA" in geral and "BETA LTDA" in geral
    assert [c.vinculo.empresa_id for c in aba.cartoes] == [cenario["acme"], cenario["beta"]]
    # Cada cartão é o da participação de hoje, com o botão de editar.
    assert aba.cartoes[0].vinculo.percentual_capital == 40
    assert "Movimentações" not in geral


def test_aba_da_empresa_mostra_so_ela(conn, cenario):
    aba = _aba(conn)
    aba.resize(1200, 800)
    aba.show()
    QApplication.processEvents()
    QTest.mouseClick(aba.abas.botoes[2], Qt.LeftButton)
    assert aba.paginas.currentIndex() == 2
    pagina = _textos(aba.paginas.widget(2))
    assert "BETA LTDA" in pagina and "ACME LTDA" not in pagina
    # A saída está nas movimentações da empresa.
    assert "Saiu" in pagina
    aba.close()


def test_participacao_antiga_fica_nas_movimentacoes_e_nao_em_cartao(conn, cenario):
    aba = _aba(conn)
    pagina = aba.paginas.widget(1)
    cartoes = pagina.findChildren(CartaoParticipacao)
    assert len(cartoes) == 1 and cartoes[0].vinculo.percentual_capital == 40
    assert "30,0000% → 40,0000%" in _textos(pagina)


def test_clicar_na_movimentacao_abre_a_foto_daquela_epoca(conn, cenario, monkeypatch):
    aba = _aba(conn)
    fotos = []
    monkeypatch.setattr(QDialog, "exec", lambda self: fotos.append(self) or QDialog.Rejected)
    linhas = aba.paginas.widget(1).findChildren(LinhaMovimento)
    saida = next(l for l in linhas if l.etiqueta.text() == "Saída (refeita)")
    saida.abrir.emit(saida._vinculo_id)
    (foto,) = fotos
    (cartao,) = foto.findChildren(CartaoParticipacao)
    # A foto da saída é a participação antiga: 30%.
    assert cartao.vinculo.percentual_capital == 30
    assert "01/01/2020 a 01/01/2022" in _textos(foto)


def test_socio_de_uma_empresa_so_nao_tem_abas(conn):
    acme = repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 1000, 1000))
    socio = repo.salvar_socio(conn, Socio(None, "Ciclano", ""))
    repo.salvar_vinculo(conn, VinculoSocietario(None, acme, socio, 100, 1000, "2020-01-01", None))
    aba = _aba(conn)
    assert aba.abas.isHidden()
    assert "Movimentações nesta empresa" in _textos(aba.paginas.widget(0))


def test_clicar_na_empresa_da_visao_geral_abre_a_aba(conn, cenario):
    aba = _aba(conn)
    aba.abrir_aba_da_empresa(cenario["beta"])
    assert aba.paginas.currentIndex() == 2
    assert aba.abas.botoes[2].isChecked()


def test_depois_de_atualizar_continua_na_mesma_aba(conn, cenario):
    aba = _aba(conn)
    aba.abrir_aba_da_empresa(cenario["beta"])
    aba.atualizar()
    assert aba.paginas.currentIndex() == 2


def test_resumo_conta_empresas_e_nao_vinculos(conn, cenario):
    aba = _aba(conn)
    # Participação refeita fecha um vínculo, mas ele continua na ACME.
    assert aba.resumo_socio.text().startswith("1 empresa ativa · saiu de 1 empresa")
