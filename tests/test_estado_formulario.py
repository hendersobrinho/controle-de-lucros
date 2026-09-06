"""Estados visíveis do formulário nas telas de cadastro.

O problema que isto cobre: a tela abria com os campos aparentemente
editáveis e nada indicando que digitar por cima de um registro selecionado
ALTERA aquele registro em vez de criar um novo.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from controle_lucros import db, repositories as repo
from controle_lucros.models import Empresa, Socio
from controle_lucros.ui import socios_tab as socios_mod
from controle_lucros.ui.common import MODO_EDICAO, MODO_NOVO, MODO_SALVO, MODO_VAZIO
from controle_lucros.ui.empresas_tab import EmpresasTab
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


@pytest.fixture(autouse=True)
def avisos(monkeypatch):
    """QMessageBox.warning é modal: sem interceptar, um erro de validação
    dentro do teste trava a suíte inteira esperando um clique."""
    capturados = []
    monkeypatch.setattr(
        QMessageBox, "warning", lambda *args, **kwargs: capturados.append(args[2])
    )
    monkeypatch.setattr(QMessageBox, "information", lambda *args, **kwargs: None)
    return capturados


def _e_primario(botao) -> bool:
    return botao.property("role") == "primario"


# =========================================================== Empresas ======


@pytest.fixture()
def empresas(conn):
    repo.salvar_empresa(conn, Empresa(None, "001", "ACME LTDA", "", 100000, 1000))
    repo.salvar_empresa(conn, Empresa(None, "002", "BETA LTDA", "", 50000, 500))
    return EmpresasTab(conn)


def test_abre_com_formulario_bloqueado_e_destaque_no_novo(empresas):
    assert empresas._modo == MODO_VAZIO
    assert not empresas.painel_campos.isEnabled()
    assert not empresas.btn_salvar.isEnabled()
    assert not empresas.btn_excluir.isEnabled()
    # O destaque de primário fica no botão que a tela espera que seja apertado.
    assert _e_primario(empresas.btn_novo)
    assert not _e_primario(empresas.btn_salvar)
    assert "Clique em <b>Novo</b>" in empresas.aviso_form.text()


def test_novo_destrava_o_formulario_e_move_o_destaque(empresas):
    empresas.novo()
    assert empresas._modo == MODO_NOVO
    assert empresas.painel_campos.isEnabled()
    assert empresas.btn_salvar.isEnabled()
    assert _e_primario(empresas.btn_salvar)
    assert not _e_primario(empresas.btn_novo)
    # Excluir não faz sentido num registro que ainda não existe.
    assert not empresas.btn_excluir.isEnabled()
    assert "Novo registro" in empresas.aviso_form.text()


def test_novo_ja_deixa_o_cursor_no_primeiro_campo(empresas):
    """hasFocus() exigiria a janela ativa (não existe com a plataforma
    offscreen); focusWidget() diz quem receberia o foco, que é o que importa."""
    empresas.novo()
    assert empresas.focusWidget() is empresas.numero_chamada


def test_selecionar_linha_entra_em_edicao_e_diz_quem_esta_sendo_editado(empresas):
    empresas.tabela.selectRow(0)
    assert empresas._modo == MODO_EDICAO
    assert empresas.painel_campos.isEnabled()
    assert empresas.btn_excluir.isEnabled()
    texto = empresas.aviso_form.text()
    assert "ACME LTDA" in texto
    assert "substitui esse registro" in texto
    assert "clique em <b>Novo</b>" in texto


def test_salvar_volta_pro_estado_bloqueado_com_aviso_de_salvo(empresas):
    empresas.novo()
    empresas.numero_chamada.setText("003")
    empresas.nome.setText("GAMA LTDA")
    empresas.salvar()

    assert empresas._modo == MODO_SALVO
    assert not empresas.painel_campos.isEnabled()
    assert _e_primario(empresas.btn_novo)
    assert "Registro salvo" in empresas.aviso_form.text()
    assert any(e.nome == "GAMA LTDA" for e in repo.listar_empresas(empresas.conn))


def test_erro_ao_salvar_mantem_o_formulario_aberto(empresas, avisos):
    """Se o salvamento falhou, travar o formulário faria perder o que foi
    digitado — o estado tem que continuar sendo o de edição."""
    empresas.novo()
    empresas.nome.setText("SEM NUMERO DE CHAMADA")
    empresas.salvar()

    assert avisos and "número da empresa" in avisos[0]
    assert empresas._modo == MODO_NOVO
    assert empresas.painel_campos.isEnabled()
    assert empresas.nome.text() == "SEM NUMERO DE CHAMADA"


def test_excluir_volta_pro_estado_bloqueado(empresas, monkeypatch):
    from controle_lucros.ui import common as common_mod

    monkeypatch.setattr(common_mod.QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    empresas.tabela.selectRow(0)
    empresas.excluir()

    assert empresas._modo == MODO_VAZIO
    assert not empresas.painel_campos.isEnabled()
    assert _e_primario(empresas.btn_novo)


def test_trocar_de_tema_nao_perde_o_estado(empresas, tmp_path, monkeypatch):
    """O aviso tem cor calculada na mão (não vem do QSS global), então ele é
    reaplicado ao trocar de tema — e o modo não pode se perder nisso.

    O tema é persistido em preferencias.json ao lado do banco; sem apontar o
    CONTROLE_LUCROS_DB pra um lugar temporário, o teste escreveria na
    preferência de verdade de quem estiver rodando a suíte."""
    from controle_lucros.ui import theme

    monkeypatch.setenv("CONTROLE_LUCROS_DB", str(tmp_path / "teste.db"))
    modo_inicial = theme.estado().modo

    empresas.tabela.selectRow(0)
    theme.estado().alternar()
    try:
        assert theme.estado().modo != modo_inicial
        assert empresas._modo == MODO_EDICAO
        assert "ACME LTDA" in empresas.aviso_form.text()
        assert empresas.painel_campos.isEnabled()
    finally:
        theme.estado().alternar()
    assert theme.estado().modo == modo_inicial


# ============================================================= Sócios ======


@pytest.fixture()
def socios(conn):
    repo.salvar_socio(conn, Socio(None, "Fulano de Tal", "005.169.717-35"))
    return SociosTab(conn)


def test_socios_abre_bloqueado_com_destaque_no_novo(socios):
    assert socios._modo == MODO_VAZIO
    assert not socios.painel_campos.isEnabled()
    assert not socios.btn_salvar.isEnabled()
    assert _e_primario(socios.btn_novo)
    assert "Clique em <b>Novo</b>" in socios.aviso_form.text()


def test_socios_novo_destrava_e_foca_o_nome(socios):
    socios._novo_socio()
    assert socios._modo == MODO_NOVO
    assert socios.painel_campos.isEnabled()
    assert socios.focusWidget() is socios.nome
    assert _e_primario(socios.btn_salvar)


def test_socios_selecionar_entra_em_edicao(socios):
    socios.tabela.selectRow(0)
    assert socios._modo == MODO_EDICAO
    assert socios.painel_campos.isEnabled()
    assert socios.btn_excluir.isEnabled()
    assert "Fulano de Tal" in socios.aviso_form.text()


def test_socios_salvar_novo_segue_em_edicao_do_recem_cadastrado(socios):
    """Aqui o sócio salvo continua selecionado de propósito: o painel de
    vínculos à direita é dele, e é pra lá que a pessoa vai em seguida."""
    socios._novo_socio()
    socios.nome.setText("Beltrano da Silva")
    socios._salvar_socio()

    assert socios._modo == MODO_EDICAO
    assert "Beltrano da Silva" in socios.aviso_form.text()
    assert socios.painel_campos.isEnabled()


def test_socios_salvar_com_busca_filtrando_o_registro_avisa_que_salvou(socios):
    """Se a busca esconde o registro recém-salvo, ele não fica selecionado —
    e aí o estado certo é o de "salvo", não o de edição de coisa nenhuma."""
    socios.busca.setText("Fulano")
    socios._novo_socio()
    socios.nome.setText("Zeca Pagodinho")
    socios._salvar_socio()

    assert socios._modo == MODO_SALVO
    assert "Registro salvo" in socios.aviso_form.text()
    assert any(s.nome == "Zeca Pagodinho" for s in repo.listar_socios(socios.conn))


def test_socios_erro_ao_salvar_mantem_o_formulario_aberto(socios, avisos):
    socios._novo_socio()
    socios._salvar_socio()  # sem nome

    assert avisos
    assert socios._modo == MODO_NOVO
    assert socios.painel_campos.isEnabled()


def test_socios_excluir_volta_pro_estado_bloqueado(socios, monkeypatch):
    monkeypatch.setattr(socios_mod.QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    socios.tabela.selectRow(0)
    socios._excluir_socio()

    assert socios._modo == MODO_VAZIO
    assert not socios.painel_campos.isEnabled()
    assert _e_primario(socios.btn_novo)
