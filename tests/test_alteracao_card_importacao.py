"""Importar relatório de sócios de dentro de um card da aba Alterações
contratuais: a movimentação trazida pelo relatório precisa cair dentro de uma
alteração contratual — escolhida na tela de destino, nova ou já aberta.

O relatório pode trazer várias empresas no mesmo arquivo, mas o card é de uma
empresa só: só a seção dela entra."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from controle_lucros import db, repositories as repo
from controle_lucros.models import AlteracaoContratual, Empresa, Socio
from controle_lucros.ui import alteracao_card as mod
from controle_lucros.ui import importacao_cadastro_view as vista_importacao
from controle_lucros.ui.alteracao_card import AlteracaoCard


@pytest.fixture(scope="module", autouse=True)
def app():
    aplicativo = QApplication.instance() or QApplication([])
    yield aplicativo


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON;")
    db.init_schema(connection)
    yield connection
    connection.close()


TEXTO_DUAS_EMPRESAS = (
    "Empresa: 91 - ENDOGASTRO CLINICA MEDICA LTDA Data do quadro societário: 20/05/2026\n"
    "75 ANDRE FRANZOTTI CARDOSO 076.925.727-55 23/03/2007 46,94\n"
    "Empresa: 92 - OUTRA EMPRESA LTDA\n"
    "1041 CAIO GUIMARAES ARAUJO 142.575.367-13 16/02/2024 100\n"
)


def _cenario(conn):
    empresa_a = repo.salvar_empresa(conn, Empresa(None, "91", "ENDOGASTRO CLINICA MEDICA LTDA", "", 10000, 1000))
    empresa_b = repo.salvar_empresa(conn, Empresa(None, "92", "OUTRA EMPRESA LTDA", "", 5000, 500))
    # Pré-cadastrados para o casamento de sócio ser direto — sem pendência,
    # o diálogo de revisão nem chega a abrir (blocking modal em teste).
    repo.salvar_socio(conn, Socio(None, "ANDRE FRANZOTTI CARDOSO", "076.925.727-55"))
    repo.salvar_socio(conn, Socio(None, "CAIO GUIMARAES ARAUJO", "142.575.367-13"))
    alteracao_id = repo.salvar_alteracao(
        conn,
        AlteracaoContratual(
            id=None, empresa_id=empresa_a, numero=1, data="2025-01-01",
            nome_empresa="ENDOGASTRO CLINICA MEDICA LTDA", capital_social=10000,
            quantidade_cotas=1000, descricao="",
        ),
    )
    alteracao = repo.buscar_alteracao(conn, alteracao_id)
    return {"empresa_a": empresa_a, "empresa_b": empresa_b, "alteracao": alteracao}


def _preparar_mocks(
    monkeypatch, tmp_path, texto=TEXTO_DUAS_EMPRESAS,
    resposta=QMessageBox.Yes, destino=QDialog.Accepted,
):
    """Mocka o que é modal. Devolve (perguntas, telas_de_destino): as caixas
    de pergunta e os diálogos de destino que o fluxo abriu."""
    arquivo = tmp_path / "relatorio.pdf"
    arquivo.write_bytes(b"%PDF-falso")
    monkeypatch.setattr(vista_importacao, "extrair_texto", lambda caminho: texto)
    monkeypatch.setattr(mod.QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(arquivo), "")))

    perguntas = []
    monkeypatch.setattr(
        mod.QMessageBox, "question",
        staticmethod(lambda parent, titulo, texto, *a, **k: perguntas.append(texto) or resposta),
    )
    monkeypatch.setattr(mod.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(mod.QMessageBox, "warning", staticmethod(lambda *a, **k: None))

    telas = []
    def abrir_destino(self):
        telas.append(self)
        return destino
    monkeypatch.setattr(mod.DialogoDestinoAlteracao, "exec", abrir_destino)
    return perguntas, telas


def test_importa_so_a_empresa_do_card_e_amarra_a_alteracao(conn, monkeypatch, tmp_path):
    cenario = _cenario(conn)
    _preparar_mocks(monkeypatch, tmp_path)

    card = AlteracaoCard(conn, cenario["empresa_a"], cenario["alteracao"], lambda _c: None)
    card._importar_relatorio_socios()

    vinculos_a = repo.listar_vinculos_empresa(conn, cenario["empresa_a"])
    assert len(vinculos_a) == 1
    assert vinculos_a[0].alteracao_entrada_id == cenario["alteracao"].id

    # A empresa 92 também aparece no arquivo, mas não é a deste card.
    assert repo.listar_vinculos_empresa(conn, cenario["empresa_b"]) == []
    assert repo.listar_alteracoes(conn, cenario["empresa_b"]) == []
    # Nenhuma empresa nova: o casamento é forçado na empresa do card.
    assert len(repo.listar_empresas(conn)) == 2


def test_tela_de_destino_ja_vem_na_alteracao_aberta_no_card(conn, monkeypatch, tmp_path):
    """Chamado de dentro de uma alteração, o destino não pode obrigar a
    reescolher o que já está na tela."""
    cenario = _cenario(conn)
    _perguntas, telas = _preparar_mocks(monkeypatch, tmp_path)

    card = AlteracaoCard(conn, cenario["empresa_a"], cenario["alteracao"], lambda _c: None)
    card._importar_relatorio_socios()

    (destino,) = telas
    assert destino.opcao_existente.isChecked()
    assert destino.existentes.currentData() == cenario["alteracao"].id
    # E diz o que foi lido, incluindo o que ficou de fora do arquivo.
    assert "1 outra(s) empresa(s)" in destino.resumo_leitura


def test_importar_de_um_rascunho_cadastra_a_alteracao_nova(conn, monkeypatch, tmp_path):
    """O caso que travava: quem clica em "Nova alteração contratual" pra
    importar o quadro societário dentro dela encontrava o botão desabilitado,
    porque a alteração ainda não existia. Agora a tela de destino cadastra a
    alteração e a importação entra nela."""
    cenario = _cenario(conn)
    _perguntas, telas = _preparar_mocks(monkeypatch, tmp_path)

    rascunho = AlteracaoCard(conn, cenario["empresa_a"], None, lambda _c: None)
    assert rascunho.btn_importar_relatorio.isEnabled()

    rascunho._importar_relatorio_socios()

    (destino,) = telas
    assert destino.opcao_nova.isChecked()
    # A data sugerida é a do quadro societário do relatório, não a de hoje.
    assert destino.data.date().toString("yyyy-MM-dd") == "2026-05-20"

    alteracoes = repo.listar_alteracoes(conn, cenario["empresa_a"])
    assert len(alteracoes) == 2  # a do cenário + a criada agora
    nova = alteracoes[-1]
    assert nova.data == "2026-05-20"

    (vinculo,) = repo.listar_vinculos_empresa(conn, cenario["empresa_a"])
    assert vinculo.alteracao_entrada_id == nova.id
    # E o card passa a ser o da alteração que recebeu a importação.
    assert rascunho.alteracao.id == nova.id


def test_cancelar_a_tela_de_destino_nao_grava_nada(conn, monkeypatch, tmp_path):
    cenario = _cenario(conn)
    _preparar_mocks(monkeypatch, tmp_path, destino=QDialog.Rejected)

    card = AlteracaoCard(conn, cenario["empresa_a"], cenario["alteracao"], lambda _c: None)
    card._importar_relatorio_socios()

    assert repo.listar_vinculos_empresa(conn, cenario["empresa_a"]) == []


def test_relatorio_de_empresa_que_nao_bate_pergunta_em_vez_de_recusar(conn, monkeypatch, tmp_path):
    """Nome e nº no relatório do outro sistema quase nunca são iguais aos do
    cadastro daqui. Com uma empresa só no arquivo não há ambiguidade: vale
    perguntar, em vez de deixar a pessoa sem saída."""
    so_outra_empresa = (
        "Empresa: 92 - OUTRA EMPRESA LTDA\n"
        "1041 CAIO GUIMARAES ARAUJO 142.575.367-13 16/02/2024 100\n"
    )
    cenario = _cenario(conn)
    perguntas, _telas = _preparar_mocks(monkeypatch, tmp_path, texto=so_outra_empresa)

    card = AlteracaoCard(conn, cenario["empresa_a"], cenario["alteracao"], lambda _c: None)
    card._importar_relatorio_socios()

    assert perguntas and "não bate com o cadastro" in perguntas[0]
    # Respondido Sim, entra na empresa do card.
    assert len(repo.listar_vinculos_empresa(conn, cenario["empresa_a"])) == 1


def test_relatorio_de_outra_empresa_recusado_nao_grava(conn, monkeypatch, tmp_path):
    so_outra_empresa = (
        "Empresa: 92 - OUTRA EMPRESA LTDA\n"
        "1041 CAIO GUIMARAES ARAUJO 142.575.367-13 16/02/2024 100\n"
    )
    cenario = _cenario(conn)
    _preparar_mocks(monkeypatch, tmp_path, texto=so_outra_empresa, resposta=QMessageBox.No)

    card = AlteracaoCard(conn, cenario["empresa_a"], cenario["alteracao"], lambda _c: None)
    card._importar_relatorio_socios()

    assert repo.listar_vinculos_empresa(conn, cenario["empresa_a"]) == []


def test_botao_fica_desabilitado_so_com_a_alteracao_fechada(conn):
    cenario = _cenario(conn)

    rascunho = AlteracaoCard(conn, cenario["empresa_a"], None, lambda _c: None)
    assert rascunho.btn_importar_relatorio.isEnabled()

    aberta = AlteracaoCard(conn, cenario["empresa_a"], cenario["alteracao"], lambda _c: None)
    assert aberta.btn_importar_relatorio.isEnabled()

    repo.fechar_alteracao(conn, cenario["alteracao"].id)
    fechada = AlteracaoCard(
        conn, cenario["empresa_a"], repo.buscar_alteracao(conn, cenario["alteracao"].id), lambda _c: None
    )
    assert not fechada.btn_importar_relatorio.isEnabled()
