"""Janela de conferência e emissão do informe: o que ela carrega, o que
guarda entre uma empresa e outra, e o que grava ao emitir."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox

from controle_lucros import db, repositories as repo
from controle_lucros.models import Empresa, Movimentacao, Socio
from controle_lucros.ui import informe_rendimentos_view as mod
from controle_lucros.ui.informe_rendimentos_view import InformeRendimentosDialog


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
    csi = repo.salvar_empresa(conn, Empresa(None, "001", "CSI LTDA", "36415149000189", 100000, 1000))
    clinirim = repo.salvar_empresa(conn, Empresa(None, "002", "CLINIRIM LTDA", "00317100000146", 50000, 500))
    socio_id = repo.salvar_socio(conn, Socio(None, "ROSELENE CARONE", "005.169.717-35"))
    repo.associar_socio_a_empresa(conn, csi, socio_id, 100.0, 1000, "2020-01-01")
    repo.associar_socio_a_empresa(conn, clinirim, socio_id, 50.0, 250, "2020-01-01")
    repo.salvar_distribuicao(conn, csi, 2025, socio_id, 560619.85, pro_labore=24500.00, irrf=562.51)
    repo.salvar_movimentacao(
        conn, Movimentacao(None, csi, socio_id, "emprestimo_empresa_para_socio", 785516.16, "2025-03-10")
    )
    return {"csi": csi, "clinirim": clinirim, "socio": repo.listar_socios(conn)[0]}


def _dialogo(conn, cenario, ano: int = 2025) -> InformeRendimentosDialog:
    dialogo = InformeRendimentosDialog(conn, cenario["socio"])
    dialogo.ano.setValue(ano)
    return dialogo


def test_lista_uma_linha_por_fonte_pagadora_marcada(conn, cenario):
    dialogo = _dialogo(conn, cenario)
    assert dialogo.lista.count() == 2
    assert all(dialogo.lista.item(i).checkState() == Qt.Checked for i in range(2))
    assert dialogo.exercicio.text() == "exercício 2026"


def test_carrega_os_valores_sugeridos_da_empresa_selecionada(conn, cenario):
    dialogo = _dialogo(conn, cenario)
    # A lista vem ordenada por nome: CLINIRIM antes de CSI.
    assert dialogo.lista.item(1).data(Qt.UserRole) == cenario["csi"]
    dialogo.lista.setCurrentRow(1)
    assert dialogo.campos["q3_total_rendimentos"].text() == "24.500,00"
    assert dialogo.campos["q3_irrf"].text() == "562,51"
    assert dialogo.campos["q4_lucros_dividendos"].text() == "560.619,85"
    assert dialogo.campos["emprestimo_saldo"].text() == "785.516,16"
    # A empresa sem lançamento no ano vem zerada, não com os valores da outra.
    dialogo.lista.setCurrentRow(0)
    assert dialogo.campos["q4_lucros_dividendos"].text() == "0,00"


def test_o_que_foi_digitado_sobrevive_a_troca_de_empresa(conn, cenario):
    dialogo = _dialogo(conn, cenario)
    dialogo.lista.setCurrentRow(1)
    dialogo.campos["q3_previdencia_oficial"].setText("2.695,00")
    dialogo.lista.setCurrentRow(0)
    dialogo.lista.setCurrentRow(1)
    assert dialogo.campos["q3_previdencia_oficial"].text() == "2.695,00"


def test_salvar_grava_os_valores_de_todas_as_empresas(conn, cenario):
    dialogo = _dialogo(conn, cenario)
    dialogo.lista.setCurrentRow(1)
    dialogo.campos["q3_previdencia_oficial"].setText("2.695,00")
    dialogo.campos_texto["responsavel_nome"].setText("ELLEN SCHNEIDER EWALD")
    assert dialogo._salvar() is True

    salvo = repo.buscar_informe(conn, cenario["csi"], 2025, cenario["socio"].id)
    assert salvo.q3_previdencia_oficial == 269500
    assert salvo.q4_lucros_dividendos == 56061985
    assert salvo.responsavel_nome == "ELLEN SCHNEIDER EWALD"
    assert repo.buscar_informe(conn, cenario["clinirim"], 2025, cenario["socio"].id) is not None


def test_valor_mal_digitado_barra_o_salvamento(conn, cenario, monkeypatch):
    """Um valor inválido não pode virar 0,00 calado num documento fiscal."""
    avisos = []
    monkeypatch.setattr(mod.QMessageBox, "warning", lambda *args, **kwargs: avisos.append(args[2]))
    dialogo = _dialogo(conn, cenario)
    dialogo.lista.setCurrentRow(1)
    dialogo.campos["q3_irrf"].setText("mil reais")
    assert dialogo._salvar() is False
    assert avisos and "não é um valor em reais válido" in avisos[0]
    assert repo.buscar_informe(conn, cenario["csi"], 2025, cenario["socio"].id) is None


def test_valores_salvos_tem_precedencia_sobre_a_sugestao(conn, cenario):
    """Depois de conferido, o informe é o que foi conferido: mudar um
    lançamento do ano não pode reescrever sozinho um documento já emitido."""
    dialogo = _dialogo(conn, cenario)
    dialogo.lista.setCurrentRow(1)
    dialogo.campos["q4_lucros_dividendos"].setText("1.000,00")
    dialogo._salvar()

    outro = _dialogo(conn, cenario)
    outro.lista.setCurrentRow(1)
    assert outro.campos["q4_lucros_dividendos"].text() == "1.000,00"
    assert "conferidos e salvos" in outro.origem_valores.text()


def test_trocar_de_ano_recarrega_as_fontes_pagadoras(conn, cenario):
    dialogo = _dialogo(conn, cenario)
    dialogo.lista.setCurrentRow(1)
    dialogo.ano.setValue(2024)
    assert dialogo.exercicio.text() == "exercício 2025"
    dialogo.lista.setCurrentRow(1)
    # 2024 não tem distribuição nem empréstimo lançado.
    assert dialogo.campos["q4_lucros_dividendos"].text() == "0,00"
    assert dialogo.campos["emprestimo_saldo"].text() == "0,00"


def test_trocar_de_ano_com_edicao_pendente_pergunta_antes_de_descartar(conn, cenario, monkeypatch):
    respostas = []

    def _pergunta(*args, **kwargs):
        respostas.append(args[2])
        return QMessageBox.No

    monkeypatch.setattr(mod.QMessageBox, "question", _pergunta)
    dialogo = _dialogo(conn, cenario)
    dialogo.lista.setCurrentRow(1)
    dialogo.campos["q3_irrf"].textEdited.emit("1,00")  # simula digitação do usuário
    dialogo.ano.setValue(2024)

    assert respostas and "não foram salvos" in respostas[0]
    assert dialogo.ano.value() == 2025  # a recusa mantém o ano carregado


def test_emitir_grava_um_pdf_por_empresa_marcada_e_registra_no_log(conn, cenario, monkeypatch, tmp_path):
    monkeypatch.setattr(mod.QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))
    monkeypatch.setattr(mod.QMessageBox, "information", lambda *a, **k: None)

    dialogo = _dialogo(conn, cenario)
    dialogo.lista.item(0).setCheckState(Qt.Unchecked)  # emite só a CSI
    dialogo._emitir()

    gerados = sorted(p.name for p in tmp_path.glob("*.pdf"))
    assert gerados == ["Informe 2025 - ROSELENE CARONE - CSI LTDA.pdf"]
    emissoes = [
        linha for linha in repo.listar_log_atividade(conn)
        if linha.entidade == "informe_rendimento" and linha.acao == "emitir"
    ]
    assert len(emissoes) == 1
    assert "CSI LTDA" in emissoes[0].detalhes


def test_emitir_avisa_quando_o_cpf_do_socio_e_invalido(conn, cenario, monkeypatch, tmp_path):
    """CPF errado impede o sócio de importar o informe na declaração e só
    aparece meses depois — melhor barrar na hora de emitir."""
    socio = cenario["socio"]
    socio.cpf = "111.111.111-11"
    repo.salvar_socio(conn, socio)

    perguntas = []
    monkeypatch.setattr(
        mod.QMessageBox, "question", lambda *a, **k: (perguntas.append(a[2]), QMessageBox.No)[1]
    )
    monkeypatch.setattr(mod.QFileDialog, "getExistingDirectory", lambda *a, **k: str(tmp_path))

    dialogo = _dialogo(conn, cenario)
    dialogo._emitir()

    assert perguntas and "não é válido" in perguntas[0]
    assert list(tmp_path.glob("*.pdf")) == []
    # E o aviso também fica visível no cabeçalho, antes de chegar a emitir.
    assert "CPF inválido" in dialogo.identificacao.text()


def test_socio_sem_fonte_pagadora_no_ano_nao_deixa_emitir(conn, cenario):
    dialogo = _dialogo(conn, cenario, ano=2015)
    assert dialogo.lista.count() == 0
    assert not dialogo.btn_emitir.isEnabled()
    assert not dialogo.btn_visualizar.isEnabled()
    assert "não foi fonte pagadora" in dialogo.origem_valores.text()
