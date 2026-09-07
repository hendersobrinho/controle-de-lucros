"""Manual do sistema (F1).

Além de conferir a janela, estes testes prendem o manual ao código: tópico
que aponta pra tela inexistente, ou tela sem tópico, viram falha aqui — é o
que evita o manual envelhecer em silêncio e passar a ensinar errado.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3

import pytest
from PySide6.QtWidgets import QApplication

from controle_lucros import db, repositories as repo
from controle_lucros.ui.main_window import MainWindow
from controle_lucros.ui.manual import (
    TOPICO_POR_PAGINA,
    TOPICOS,
    DialogoManual,
    buscar_topicos,
    topico_da_pagina,
)


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
def janela(conn):
    repo.criar_usuario(conn, "Admin", "admin", "senha123", True)
    return MainWindow(conn, repo.listar_usuarios(conn)[0])


# ------------------------------------------------ manual x telas de verdade --


def test_todo_topico_tem_id_unico_e_corpo():
    ids = [t.id for t in TOPICOS]
    assert len(ids) == len(set(ids))
    for topico in TOPICOS:
        assert topico.titulo.strip()
        assert len(topico.corpo.strip()) > 200, topico.id


def test_toda_tela_do_sistema_tem_um_topico(janela):
    """Tela nova sem entrada aqui cairia no tópico genérico sem ninguém
    perceber — o F1 dela responderia a pergunta errada."""
    assert set(TOPICO_POR_PAGINA) == set(janela._paginas)


def test_todo_topico_apontado_por_uma_tela_existe():
    ids = {t.id for t in TOPICOS}
    assert set(TOPICO_POR_PAGINA.values()) <= ids


def test_topico_da_pagina_cai_no_inicio_quando_nao_conhece():
    assert topico_da_pagina("distribuicao") == "distribuicao"
    assert topico_da_pagina("tela.que.nao.existe") == "inicio"
    assert topico_da_pagina(None) == "inicio"


# ---------------------------------------------------------------- conteúdo --


@pytest.mark.parametrize(
    "topico_id,trechos",
    [
        # Regras que, se mudarem no código, têm que mudar no texto junto.
        ("informe", ["exercício", "Quadro 7", "fonte pagadora"]),
        ("distribuicao.trimestral", ["soma dos trimestres", "Origem", "editado à mão"]),
        ("distribuicao", ["Trancar o período", "Importar planilha", "Movimentações"]),
        ("dashboard", ["proporcional", "tolerância"]),
        ("sistema.importar", ["CPF", "CNPJ", "nº da empresa"]),
        ("socios", ["Encerrar vínculo", "Excluir vínculo"]),
        ("sistema", ["backup", "log"]),
    ],
)
def test_topicos_cobrem_as_regras_principais(topico_id, trechos):
    corpo = next(t for t in TOPICOS if t.id == topico_id).corpo.lower()
    for trecho in trechos:
        assert trecho.lower() in corpo, f"{topico_id} não menciona {trecho!r}"


def test_manual_explica_que_a_soma_dos_trimestres_pode_ser_sobrescrita():
    corpo = next(t for t in TOPICOS if t.id == "distribuicao.trimestral").corpo
    assert "até o próximo lançamento trimestral" in corpo


def test_manual_avisa_que_o_saldo_de_emprestimo_e_sugestao():
    corpo = next(t for t in TOPICOS if t.id == "informe").corpo
    assert "sugestão" in corpo
    assert "amortização" in corpo


# ------------------------------------------------------------------ janela --


def test_abre_no_topico_pedido():
    dialogo = DialogoManual("informe")
    assert dialogo._visiveis[dialogo.lista.currentRow()].id == "informe"
    assert "Comprovante de Rendimentos" in dialogo.conteudo.toPlainText()


def test_topico_desconhecido_abre_no_primeiro():
    dialogo = DialogoManual("nao-existe")
    assert dialogo.lista.currentRow() == 0


def test_busca_filtra_a_lista_e_mantem_o_topico_aberto_quando_possivel():
    dialogo = DialogoManual("informe")
    dialogo.busca.setText("empréstimo")
    ids = [t.id for t in dialogo._visiveis]
    assert ids == ["distribuicao", "informe"]
    assert dialogo._visiveis[dialogo.lista.currentRow()].id == "informe"


def test_busca_sem_resultado_avisa_em_vez_de_mostrar_lista_vazia():
    dialogo = DialogoManual()
    dialogo.busca.setText("xyzabc")
    assert dialogo._visiveis == []
    assert dialogo.vazio.isVisibleTo(dialogo)
    assert dialogo.conteudo.toPlainText().strip() == ""


def test_limpar_a_busca_traz_todos_os_topicos_de_volta():
    dialogo = DialogoManual()
    dialogo.busca.setText("xyzabc")
    dialogo.busca.setText("")
    assert len(dialogo._visiveis) == len(TOPICOS)
    assert dialogo.lista.currentRow() == 0


def test_buscar_topicos_acha_no_titulo_e_no_corpo():
    assert [t.id for t in buscar_topicos("trimestral")] != []
    assert "informe" in [t.id for t in buscar_topicos("2.060")]
    assert buscar_topicos("") == list(TOPICOS)


# --------------------------------------------------------------------- F1 --


def test_f1_abre_o_manual_no_topico_da_tela_aberta(janela, monkeypatch):
    abertos = []
    monkeypatch.setattr(
        "controle_lucros.ui.main_window.DialogoManual",
        lambda topico, parent=None: type("Falso", (), {"exec": lambda self: abertos.append(topico)})(),
    )
    janela._ir_para("distribuicao.trimestral")
    janela.abrir_manual()
    assert abertos == ["distribuicao.trimestral"]

    janela._ir_para("socios")
    janela.abrir_manual()
    assert abertos[-1] == "socios"


# ------------------------------------------------------------- tradução --


def test_botoes_padrao_do_qt_saem_em_portugues(app):
    """Os textos de "Fechar", "Cancelar" e "Sim/Não" vêm do próprio Qt, não
    do código daqui — sem a tradução instalada o programa fica em português
    com os botões em inglês."""
    from PySide6.QtWidgets import QDialogButtonBox, QMessageBox

    from controle_lucros import traducao

    assert traducao.instalar(app) is True

    caixa = QDialogButtonBox(QDialogButtonBox.Close | QDialogButtonBox.Cancel)
    assert caixa.button(QDialogButtonBox.Close).text() == "Fechar"
    assert caixa.button(QDialogButtonBox.Cancel).text() == "Cancelar"

    mensagem = QMessageBox()
    mensagem.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
    assert mensagem.button(QMessageBox.Yes).text().replace("&", "") == "Sim"
    assert mensagem.button(QMessageBox.No).text().replace("&", "") == "Não"
