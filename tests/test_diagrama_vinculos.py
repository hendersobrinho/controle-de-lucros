"""Desenho e exportação do mapa de vínculos.

Ninguém consegue afirmar por teste que um desenho ficou bonito, mas dá pra
garantir o que costuma quebrar: que o arquivo sai, que ele sai vetorial e com
o texto dentro (SVG que virou imagem rasterizada não serve pra nada), que o
PDF de um sócio com muitas empresas vira retrato, e que a tela oferece as duas
exportações.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import sqlite3

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from controle_lucros import db, repositories as repo
from controle_lucros.mapa_vinculos import montar_mapa
from controle_lucros.models import Empresa, Socio, VinculoSocietario
from controle_lucros.ui import diagrama_vinculos as diagrama
from controle_lucros.ui.diagrama_vinculos import DialogoMapaVinculos, exportar_pdf, exportar_svg
from controle_lucros.ui.socios_tab import SociosTab


@pytest.fixture(scope="module", autouse=True)
def app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture()
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    db.init_schema(connection)
    yield connection
    connection.close()


VINCULOS = [
    {"empresa_nome": "ENDOGASTRO CLINICA MEDICA LTDA", "percentual": 46.94,
     "data_entrada": "2007-03-23", "data_saida": None},
    {"empresa_nome": "PADARIA MODELO LTDA", "percentual": 30.0,
     "data_entrada": "2015-06-01", "data_saida": None},
    {"empresa_nome": "CLINICA ANTIGA LTDA", "percentual": 25.0,
     "data_entrada": "2010-01-05", "data_saida": "2023-12-31"},
]


def _mapa(vinculos=None):
    return montar_mapa("ANDRE FRANZOTTI", "076.925.727-55", vinculos or VINCULOS,
                       gerado_em="15/09/2026")


# ---------------------------------------------------------------- exportar --
def test_svg_sai_vetorial_com_o_texto_dentro(tmp_path):
    caminho = exportar_svg(tmp_path / "mapa.svg", _mapa())
    conteudo = caminho.read_text(encoding="utf-8")

    assert conteudo.lstrip().startswith("<?xml")
    assert "ENDOGASTRO CLINICA MEDICA LTDA" in conteudo
    assert "46,94%" in conteudo
    # Vetorial de verdade: nada de imagem embutida em base64.
    assert "base64" not in conteudo


def test_pdf_sai_com_conteudo(tmp_path):
    caminho = exportar_pdf(tmp_path / "mapa.pdf", _mapa())

    assert caminho.read_bytes().startswith(b"%PDF")
    assert caminho.stat().st_size > 2000


def test_orientacao_da_pagina_segue_a_forma_do_mapa():
    """Com o teto de 24 empresas o mapa nunca fica mais alto que largo, então
    na prática sai sempre em paisagem. A regra é testada com o teto solto para
    não virar código que ninguém sabe se funciona."""
    from PySide6.QtGui import QPageLayout

    largo = montar_mapa("FULANO", "", VINCULOS)
    assert diagrama.orientacao_da_pagina(largo) == QPageLayout.Landscape

    muitos = [dict(VINCULOS[0], empresa_nome=f"EMPRESA {i} LTDA") for i in range(40)]
    alto = montar_mapa("FULANO", "", muitos, maximo=40)
    assert alto.altura > alto.largura
    assert diagrama.orientacao_da_pagina(alto) == QPageLayout.Portrait


def test_mapa_sem_vinculos_ainda_exporta(tmp_path):
    caminho = exportar_pdf(tmp_path / "vazio.pdf", montar_mapa("SEM VINCULO", "", []))
    assert caminho.exists()


# ------------------------------------------------------------------- tela --
def test_dialogo_pode_esconder_os_encerrados():
    dialogo = DialogoMapaVinculos("ANDRE FRANZOTTI", "076.925.727-55", VINCULOS)
    assert dialogo.mapa().encerrados == 1

    dialogo.incluir_encerrados.setChecked(False)

    mapa = dialogo.mapa()
    assert mapa.encerrados == 0
    assert [e.nome for e in mapa.empresas] == ["ENDOGASTRO CLINICA MEDICA LTDA", "PADARIA MODELO LTDA"]


def test_dialogo_exporta_nos_dois_formatos(tmp_path, monkeypatch):
    dialogo = DialogoMapaVinculos("ANDRE FRANZOTTI", "076.925.727-55", VINCULOS)
    monkeypatch.setattr(diagrama.QMessageBox, "information", staticmethod(lambda *a, **k: None))

    for extensao, acao in (("pdf", dialogo._exportar_pdf), ("svg", dialogo._exportar_svg)):
        destino = tmp_path / f"mapa.{extensao}"
        monkeypatch.setattr(diagrama.QFileDialog, "getSaveFileName",
                            staticmethod(lambda *a, **k: (str(destino), "")))
        acao()
        assert destino.exists(), extensao
    assert "mapa." in dialogo.aviso.text()


def test_extensao_e_acrescentada_quando_a_pessoa_nao_digita(tmp_path, monkeypatch):
    dialogo = DialogoMapaVinculos("ANDRE FRANZOTTI", "076.925.727-55", VINCULOS)
    monkeypatch.setattr(diagrama.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(diagrama.QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "sem_extensao"), "")))

    dialogo._exportar_svg()

    assert (tmp_path / "sem_extensao.svg").exists()


def test_cancelar_a_escolha_do_arquivo_nao_grava_nada(tmp_path, monkeypatch):
    dialogo = DialogoMapaVinculos("ANDRE FRANZOTTI", "076.925.727-55", VINCULOS)
    monkeypatch.setattr(diagrama.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))

    dialogo._exportar_pdf()

    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------- integração com a aba --
def test_botao_da_aba_abre_o_mapa_do_socio_selecionado(conn, monkeypatch):
    empresa_id = repo.salvar_empresa(conn, Empresa(
        id=None, numero_chamada="91", nome="ENDOGASTRO LTDA", cnpj="",
        capital_social=1000, quantidade_cotas=1000))
    socio_id = repo.salvar_socio(conn, Socio(id=None, nome="ANDRE FRANZOTTI", cpf="076.925.727-55"))
    repo.salvar_vinculo(conn, VinculoSocietario(
        id=None, empresa_id=empresa_id, socio_id=socio_id, percentual_capital=46.94,
        quantidade_cotas=469, data_entrada="2007-03-23", data_saida=None))

    aba = SociosTab(conn)
    aba.tabela.selectRow(0)
    assert aba.btn_mapa.isEnabled()

    abertos = []
    monkeypatch.setattr(
        "controle_lucros.ui.socios_tab.DialogoMapaVinculos",
        lambda nome, documento, vinculos, parent=None: abertos.append((nome, documento, vinculos))
        or type("Falso", (), {"exec": lambda self: 0})(),
    )
    aba._abrir_mapa_vinculos()

    (nome, documento, vinculos) = abertos[0]
    assert nome == "ANDRE FRANZOTTI"
    assert documento == "076.925.727-55"
    assert vinculos == [{"empresa_nome": "ENDOGASTRO LTDA", "percentual": 46.94,
                         "data_entrada": "2007-03-23", "data_saida": None}]


def test_sem_socio_selecionado_o_botao_fica_travado(conn):
    aba = SociosTab(conn)
    assert not aba.btn_mapa.isEnabled()
