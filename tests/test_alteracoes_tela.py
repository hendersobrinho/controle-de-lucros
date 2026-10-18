"""Tela de Alterações contratuais: lista à esquerda, ficha à direita, e o
número da alteração livre.

O número é o do contrato de verdade. Quem começa a usar o sistema hoje não
lança o passado: a primeira alteração registrada pode ser a Nº 7, e o
sistema tem de aceitar isso — só não pode repetir número na mesma empresa."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox

from controle_lucros import repositories as repo
from controle_lucros.models import AlteracaoContratual, Empresa, Socio, VinculoSocietario
from controle_lucros.ui import alteracao_card as mod
from controle_lucros.ui import alteracoes_view as mod_view
from controle_lucros.ui.alteracao_card import AlteracaoCard, DialogoAlteracao
from controle_lucros.ui.alteracoes_view import AlteracoesView
from controle_lucros.ui.destino_alteracao import DialogoDestinoAlteracao


@pytest.fixture(scope="module", autouse=True)
def app():
    return QApplication.instance() or QApplication([])


def _alteracao(empresa_id, numero, data, capital=10000, cotas=1000, descricao=""):
    return AlteracaoContratual(None, empresa_id, numero, data, "ACME LTDA", capital, cotas, descricao)


@pytest.fixture()
def empresa(conn):
    return repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 10000, 1000))


# ------------------------------------------------------------ repositório --
def test_primeira_alteracao_pode_comecar_no_numero_do_contrato(conn, empresa):
    repo.salvar_alteracao(conn, _alteracao(empresa, 7, "2025-03-10"))
    (unica,) = repo.listar_alteracoes(conn, empresa)
    assert unica.numero == 7
    # A sugestão seguinte continua a partir dela.
    assert repo.proximo_numero_alteracao(conn, empresa) == 8


def test_numero_pode_ser_corrigido_depois(conn, empresa):
    alteracao_id = repo.salvar_alteracao(conn, _alteracao(empresa, 1, "2025-03-10"))
    corrigida = repo.buscar_alteracao(conn, alteracao_id)
    corrigida.numero = 12
    repo.salvar_alteracao(conn, corrigida)
    assert repo.buscar_alteracao(conn, alteracao_id).numero == 12


def test_numero_repetido_na_mesma_empresa_e_recusado_com_mensagem_clara(conn, empresa):
    repo.salvar_alteracao(conn, _alteracao(empresa, 7, "2025-03-10"))
    outra_id = repo.salvar_alteracao(conn, _alteracao(empresa, 8, "2025-06-10"))
    with pytest.raises(ValueError, match="já tem a alteração contratual Nº 7"):
        repo.salvar_alteracao(conn, _alteracao(empresa, 7, "2025-09-10"))
    outra = repo.buscar_alteracao(conn, outra_id)
    outra.numero = 7
    with pytest.raises(ValueError, match="Nº 7"):
        repo.salvar_alteracao(conn, outra)
    assert repo.buscar_alteracao(conn, outra_id).numero == 8


def test_salvar_sem_mudar_o_numero_nao_acusa_repeticao(conn, empresa):
    alteracao_id = repo.salvar_alteracao(conn, _alteracao(empresa, 7, "2025-03-10"))
    mesma = repo.buscar_alteracao(conn, alteracao_id)
    mesma.descricao = "corrigida"
    repo.salvar_alteracao(conn, mesma)
    assert repo.buscar_alteracao(conn, alteracao_id).descricao == "corrigida"


def test_mesmo_numero_em_empresas_diferentes_pode(conn, empresa):
    outra = repo.salvar_empresa(conn, Empresa(None, "002", "BETA LTDA", "", 0, 0))
    repo.salvar_alteracao(conn, _alteracao(empresa, 7, "2025-03-10"))
    repo.salvar_alteracao(conn, _alteracao(outra, 7, "2025-03-10"))


def test_numero_zero_e_recusado(conn, empresa):
    with pytest.raises(ValueError, match="1 ou maior"):
        repo.salvar_alteracao(conn, _alteracao(empresa, 0, "2025-03-10"))


def test_ficha_diz_quem_entrou_saiu_e_teve_a_participacao_refeita(conn, empresa):
    antiga = repo.salvar_alteracao(conn, _alteracao(empresa, 7, "2024-01-01"))
    nova = repo.salvar_alteracao(conn, _alteracao(empresa, 8, "2025-01-01", capital=20000, cotas=2000))
    ana = repo.salvar_socio(conn, Socio(None, "ANA", ""))
    bia = repo.salvar_socio(conn, Socio(None, "BIA", ""))
    caio = repo.salvar_socio(conn, Socio(None, "CAIO", ""))
    v_ana = repo.salvar_vinculo(conn, VinculoSocietario(None, empresa, ana, 50, 500, "2024-01-01", None, alteracao_entrada_id=antiga))
    v_bia = repo.salvar_vinculo(conn, VinculoSocietario(None, empresa, bia, 50, 500, "2024-01-01", None, alteracao_entrada_id=antiga))
    # Na Nº 8: BIA sai, CAIO entra, ANA tem a participação refeita.
    repo.encerrar_vinculo(conn, v_bia, "2025-01-01", nova)
    repo.encerrar_vinculo(conn, v_ana, "2025-01-01", nova)
    repo.salvar_vinculo(conn, VinculoSocietario(None, empresa, ana, 60, 1200, "2025-01-01", None, alteracao_entrada_id=nova))
    repo.salvar_vinculo(conn, VinculoSocietario(None, empresa, caio, 40, 800, "2025-01-01", None, alteracao_entrada_id=nova))

    ficha = repo.ficha_alteracao(conn, nova)
    assert ficha["entradas"] == ["CAIO"]
    assert [s["nome"] for s in ficha["saidas"]] == ["BIA"]
    assert ficha["mudancas"] == ["ANA"]
    assert {q["nome"]: q["movimento"] for q in ficha["quadro"]} == {"ANA": "mudou", "CAIO": "entrou"}
    assert ficha["capital_antes"] == 10000 and ficha["cotas_antes"] == 1000
    assert ficha["valor_cota"] == 10
    assert ficha["soma_percentual"] == 100

    primeira = repo.ficha_alteracao(conn, antiga)
    assert primeira["anterior"] is None
    assert sorted(primeira["entradas"]) == ["ANA", "BIA"]


# ---------------------------------------------------------------- janela --
def test_janela_sugere_o_proximo_e_explica_que_pode_comecar_no_real(conn, empresa):
    dialogo = DialogoAlteracao(conn, empresa)
    assert dialogo.numero.value() == 1
    assert "informe 7" in dialogo.dica_numero.text()

    repo.salvar_alteracao(conn, _alteracao(empresa, 7, "2025-03-10"))
    dialogo = DialogoAlteracao(conn, empresa)
    assert dialogo.numero.value() == 8


def test_janela_avisa_numero_repetido_e_trava_o_salvar(conn, empresa):
    repo.salvar_alteracao(conn, _alteracao(empresa, 7, "2025-03-10"))
    dialogo = DialogoAlteracao(conn, empresa)
    dialogo.numero.setValue(7)
    assert not dialogo.aviso_numero.isHidden()
    assert not dialogo.btn_salvar.isEnabled()
    dialogo.numero.setValue(9)
    assert dialogo.aviso_numero.isHidden()
    assert dialogo.btn_salvar.isEnabled()


def test_janela_cadastra_com_o_numero_escolhido(conn, empresa):
    dialogo = DialogoAlteracao(conn, empresa)
    dialogo.numero.setValue(7)
    dialogo.descricao.setPlainText("Situação de hoje")
    dialogo._salvar()
    assert dialogo.result() == QDialog.Accepted
    criada = repo.buscar_alteracao(conn, dialogo.alteracao_id)
    assert (criada.numero, criada.descricao) == (7, "Situação de hoje")


def test_janela_de_edicao_troca_o_numero(conn, empresa):
    alteracao_id = repo.salvar_alteracao(conn, _alteracao(empresa, 1, "2025-03-10"))
    dialogo = DialogoAlteracao(conn, empresa, repo.buscar_alteracao(conn, alteracao_id))
    assert dialogo.btn_salvar.isEnabled()  # o próprio número não conta como repetido
    dialogo.numero.setValue(7)
    dialogo._salvar()
    assert repo.buscar_alteracao(conn, alteracao_id).numero == 7


def test_excluir_de_dentro_da_janela_ja_vem_em_nao(conn, empresa, monkeypatch):
    alteracao_id = repo.salvar_alteracao(conn, _alteracao(empresa, 7, "2025-03-10"))
    padroes = []
    monkeypatch.setattr(mod.QMessageBox, "warning",
                        staticmethod(lambda p, t, x, b=None, padrao=None: padroes.append(padrao) or mod.QMessageBox.No))
    dialogo = DialogoAlteracao(conn, empresa, repo.buscar_alteracao(conn, alteracao_id))
    dialogo._excluir()
    assert padroes == [mod.QMessageBox.No]
    assert repo.buscar_alteracao(conn, alteracao_id) is not None


def test_importacao_cadastra_a_alteracao_com_o_numero_escolhido(conn, empresa):
    destino = DialogoDestinoAlteracao(conn, empresa, "Li 1 sócio.")
    assert destino.numero.value() == 1
    destino.numero.setValue(7)
    criada = repo.buscar_alteracao(conn, destino.resolver())
    assert criada.numero == 7


def test_importacao_trava_numero_repetido(conn, empresa):
    repo.salvar_alteracao(conn, _alteracao(empresa, 7, "2025-03-10"))
    destino = DialogoDestinoAlteracao(conn, empresa, "Li 1 sócio.")
    destino.opcao_nova.setChecked(True)
    destino.numero.setValue(7)
    assert not destino.botoes.button(QDialogButtonBox.Ok).isEnabled()


# ------------------------------------------------------------------ tela --
def test_linha_do_tempo_vai_da_mais_antiga_a_mais_recente_e_abre_na_de_hoje(conn, empresa):
    sete = repo.salvar_alteracao(conn, _alteracao(empresa, 7, "2024-03-10"))
    oito = repo.salvar_alteracao(conn, _alteracao(empresa, 8, "2025-03-10"))
    tela = AlteracoesView(conn)
    tela.selecionar_empresa(empresa)
    assert tela.linha.ids() == [sete, oito]
    assert "a partir da Nº 7" in tela.contagem.text()
    assert tela.ficha.alteracao.numero == 8


def test_clicar_num_selo_da_linha_abre_a_ficha_da_alteracao(conn, empresa):
    sete = repo.salvar_alteracao(conn, _alteracao(empresa, 7, "2024-03-10"))
    repo.salvar_alteracao(conn, _alteracao(empresa, 8, "2025-03-10"))
    tela = AlteracoesView(conn)
    tela.resize(1200, 700)
    tela.show()
    tela.selecionar_empresa(empresa)
    QApplication.processEvents()
    centro = tela.linha.posicao_do_marco(sete).toPoint()
    QTest.mouseClick(tela.linha, Qt.LeftButton, Qt.NoModifier, centro)
    QApplication.processEvents()
    assert tela.ficha.alteracao.numero == 7
    assert tela.ficha.titulo.text() == "Alteração contratual Nº 7"
    tela.close()


def test_setas_do_teclado_andam_pela_linha(conn, empresa):
    sete = repo.salvar_alteracao(conn, _alteracao(empresa, 7, "2024-03-10"))
    oito = repo.salvar_alteracao(conn, _alteracao(empresa, 8, "2025-03-10"))
    tela = AlteracoesView(conn)
    tela.selecionar_empresa(empresa)
    QTest.keyClick(tela.linha, Qt.Key_Left)
    assert tela.ficha.alteracao.id == sete
    QTest.keyClick(tela.linha, Qt.Key_Right)
    assert tela.ficha.alteracao.id == oito


def test_selo_mais_da_linha_cadastra_a_proxima(conn, empresa, monkeypatch):
    repo.salvar_alteracao(conn, _alteracao(empresa, 7, "2024-03-10"))
    abertas = []
    def aceitar(self):
        abertas.append(self.numero.value())
        self._salvar()
        return QDialog.Accepted
    monkeypatch.setattr(mod_view.DialogoAlteracao, "exec", aceitar)
    tela = AlteracoesView(conn)
    tela.resize(1200, 700)
    tela.show()
    tela.selecionar_empresa(empresa)
    QApplication.processEvents()
    centro = tela.linha.posicao_do_marco(None).toPoint()
    QTest.mouseClick(tela.linha, Qt.LeftButton, Qt.NoModifier, centro)
    assert abertas == [8]
    assert tela.ficha.alteracao.numero == 8
    tela.close()


def test_empresa_sem_alteracao_convida_a_cadastrar_a_primeira(conn, empresa):
    tela = AlteracoesView(conn)
    tela.selecionar_empresa(empresa)
    ficha = tela.ficha
    assert ficha.alteracao is None
    assert not ficha.painel_vazio.isHidden()
    assert ficha.btn_importar_relatorio.isEnabled()


def test_nova_alteracao_pela_tela_ja_fica_selecionada(conn, empresa, monkeypatch):
    def aceitar(self):
        self.numero.setValue(7)
        self._salvar()
        return QDialog.Accepted
    monkeypatch.setattr(mod_view.DialogoAlteracao, "exec", aceitar)
    tela = AlteracoesView(conn)
    tela.selecionar_empresa(empresa)
    tela._nova_alteracao()
    assert len(tela.linha.ids()) == 1
    assert tela.ficha.alteracao.numero == 7


def test_alteracao_trancada_nao_deixa_editar_nem_movimentar(conn, empresa):
    alteracao_id = repo.salvar_alteracao(conn, _alteracao(empresa, 7, "2025-03-10"))
    repo.fechar_alteracao(conn, alteracao_id)
    ficha = AlteracaoCard(conn, empresa, repo.buscar_alteracao(conn, alteracao_id), lambda _f: None)
    assert not ficha.btn_editar.isEnabled()
    assert not ficha.btn_incluir_socio.isEnabled()
    assert ficha.btn_trancar.text() == "Destrancar período"
