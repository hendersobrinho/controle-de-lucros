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
    assert [e.nome for e in mapa.nos] == ["ENDOGASTRO CLINICA MEDICA LTDA", "PADARIA MODELO LTDA"]


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


# ------------------------------------------------- o mapa visto da empresa --


def test_com_a_empresa_no_centro_as_caixas_sao_os_socios(conn):
    """A mesma relação lida da outra ponta: o nome de cada caixa passa a vir
    de socio_nome, e o rótulo do hub muda junto."""
    from controle_lucros.mapa_vinculos import PAPEL_EMPRESA

    mapa = montar_mapa(
        "ENDOGASTRO LTDA", "02.294.442/0001-13",
        [
            {"socio_nome": "ANDRE FRANZOTTI", "percentual": 46.94,
             "data_entrada": "2007-03-23", "data_saida": None},
            {"socio_nome": "LUIZA DIAS TORRES", "percentual": 0.0,
             "data_entrada": "2023-03-02", "data_saida": "2026-05-20"},
        ],
        papel=PAPEL_EMPRESA,
    )

    assert [n.nome for n in mapa.nos] == ["ANDRE FRANZOTTI", "LUIZA DIAS TORRES"]
    assert mapa.centro_nome == "ENDOGASTRO LTDA"
    assert mapa.centro_papel == PAPEL_EMPRESA
    assert not mapa.centro_e_socio
    assert mapa.ativos == 1 and mapa.encerrados == 1


def test_a_geometria_nao_muda_com_o_papel_do_centro(conn):
    """Só troca de onde sai o nome da caixa: o desenho é o mesmo, e é o que
    permite uma função de pintura só para os dois sentidos."""
    from controle_lucros.mapa_vinculos import PAPEL_EMPRESA

    do_socio = montar_mapa("X", "", [
        {"empresa_nome": "A LTDA", "percentual": 60.0, "data_entrada": "2020-01-01", "data_saida": None},
        {"empresa_nome": "B LTDA", "percentual": 40.0, "data_entrada": "2020-01-01", "data_saida": None},
    ])
    da_empresa = montar_mapa("X", "", [
        {"socio_nome": "A LTDA", "percentual": 60.0, "data_entrada": "2020-01-01", "data_saida": None},
        {"socio_nome": "B LTDA", "percentual": 40.0, "data_entrada": "2020-01-01", "data_saida": None},
    ], papel=PAPEL_EMPRESA)

    assert (do_socio.largura, do_socio.altura) == (da_empresa.largura, da_empresa.altura)
    assert [n.caixa for n in do_socio.nos] == [n.caixa for n in da_empresa.nos]


def test_botao_da_aba_empresas_abre_o_quadro_societario(conn, monkeypatch):
    from controle_lucros.mapa_vinculos import PAPEL_EMPRESA
    from controle_lucros.ui.empresas_tab import EmpresasTab

    empresa_id = repo.salvar_empresa(conn, Empresa(
        id=None, numero_chamada="91", nome="ENDOGASTRO LTDA", cnpj="02.294.442/0001-13",
        capital_social=1000, quantidade_cotas=1000))
    socio_id = repo.salvar_socio(conn, Socio(id=None, nome="ANDRE FRANZOTTI", cpf="076.925.727-55"))
    repo.salvar_vinculo(conn, VinculoSocietario(
        id=None, empresa_id=empresa_id, socio_id=socio_id, percentual_capital=46.94,
        quantidade_cotas=469, data_entrada="2007-03-23", data_saida=None))

    aba = EmpresasTab(conn)
    assert not aba.btn_quadro.isEnabled()  # sem empresa escolhida não há quadro

    aba.tabela.selectRow(0)
    assert aba.btn_quadro.isEnabled()

    abertos = []
    monkeypatch.setattr(
        "controle_lucros.ui.empresas_tab.DialogoMapaVinculos",
        lambda nome, documento, vinculos, papel, parent=None: abertos.append(
            (nome, documento, vinculos, papel)
        ) or type("Falso", (), {"exec": lambda self: 0})(),
    )
    aba._abrir_quadro_societario()

    (nome, documento, vinculos, papel) = abertos[0]
    assert nome == "ENDOGASTRO LTDA"
    assert documento == "02.294.442/0001-13"
    assert papel == PAPEL_EMPRESA
    assert vinculos == [{"socio_nome": "ANDRE FRANZOTTI", "percentual": 46.94,
                         "data_entrada": "2007-03-23", "data_saida": None}]


def test_a_janela_do_mapa_abre_do_tamanho_do_desenho(conn):
    """Abria no mínimo e obrigava a arrastar a borda pra ver o que já estava
    pronto. O teto é a tela — o desenho de quem tem muitos vínculos é mais
    alto que qualquer monitor."""
    dialogo = DialogoMapaVinculos("ANDRE FRANZOTTI", "076.925.727-55", VINCULOS)
    mapa = dialogo.mapa()
    tela = dialogo.screen().availableGeometry()

    largura_desejada = min(mapa.largura + 28, tela.width() * 0.95)
    assert dialogo.width() >= min(int(largura_desejada), dialogo.minimumWidth())
    assert dialogo.width() <= tela.width()
    assert dialogo.height() <= tela.height()
