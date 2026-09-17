"""Desenho que falha não pode fechar o programa.

Exceção dentro de um paintEvent não se comporta como exceção no resto do
sistema: o PySide imprime o traceback e devolve o controle ao Qt com o
QPainter ainda ativo, o Qt bate em "QBackingStore::endPaint() called with
active painter" e o processo morre por falha de segmentação. Pra quem está
usando, o programa fecha sozinho no meio do trabalho, sem mensagem — e leva
junto o que estava aberto nas outras telas.

O mapa de vínculos é onde isso mais dói: ele é redesenhado a cada pixel
arrastado na borda da janela, o que dá muitas chances a um desenho que falha.

Os testes rodam em subprocesso de propósito: falha de segmentação não vira
exceção que o pytest capture — ela mata o processo inteiro, e a única forma
de afirmar que ela NÃO aconteceu é olhar o código de saída.
"""
import os
import pathlib
import subprocess
import sys
import textwrap

PROJETO = pathlib.Path(__file__).resolve().parent.parent


def _rodar(codigo: str) -> subprocess.CompletedProcess:
    programa = textwrap.dedent(
        f"""
        import os, sys
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.path.insert(0, {str(PROJETO)!r})
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        """
    ) + textwrap.dedent(codigo)
    return subprocess.run(
        [sys.executable, "-c", programa],
        capture_output=True, text=True, timeout=120,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )


def test_o_perigo_existe_mesmo_sem_a_protecao():
    """Prova o que está em jogo: um paintEvent que levanta exceção com o
    pintor aberto derruba o processo. É o que justifica proteger todo
    paintEvent do sistema — sem esta demonstração, o cuidado pareceria zelo
    exagerado."""
    concluido = _rodar(
        """
        from PySide6.QtWidgets import QWidget
        from PySide6.QtGui import QPainter

        class SemProtecao(QWidget):
            def paintEvent(self, evento):
                pintor = QPainter(self)          # aberto e nunca encerrado
                raise ValueError("falhei no meio do desenho")

        w = SemProtecao(); w.resize(300, 200); w.show()
        app.processEvents()
        w.repaint()
        app.processEvents()
        print("SOBREVIVEU")
        """
    )
    assert "SOBREVIVEU" not in concluido.stdout
    assert concluido.returncode != 0


def test_pintura_segura_encerra_o_pintor_quando_o_desenho_quebra():
    """O mesmo desenho que derrubava o processo, agora dentro do utilitário."""
    concluido = _rodar(
        """
        from PySide6.QtWidgets import QWidget
        from controle_lucros.ui.common import pintura_segura

        class Protegido(QWidget):
            def paintEvent(self, evento):
                try:
                    with pintura_segura(self) as pintor:
                        raise ValueError("falhei no meio do desenho")
                except ValueError:
                    pass

        w = Protegido(); w.resize(300, 200); w.show()
        app.processEvents()
        w.repaint()
        app.processEvents()
        print("SOBREVIVEU")
        """
    )
    assert concluido.returncode == 0, concluido.stderr
    assert "SOBREVIVEU" in concluido.stdout


def test_mapa_com_desenho_quebrado_avisa_em_vez_de_fechar():
    """O caso relatado: a janela do mapa sendo esticada. Com o desenho
    quebrado de propósito, o programa precisa continuar de pé e mostrar o
    motivo na tela — é essa mensagem que permite descobrir a causa quando
    acontecer numa máquina que não dá pra depurar."""
    concluido = _rodar(
        """
        from controle_lucros.ui import diagrama_vinculos as dv

        def desenho_que_quebra(painter, mapa, paleta):
            raise RuntimeError("defeito plantado no desenho")

        dv.desenhar = desenho_que_quebra

        vinculos = [
            {"empresa_nome": "ENDOGASTRO LTDA", "percentual": 46.94,
             "data_entrada": "2007-03-23", "data_saida": None},
        ]
        d = dv.DialogoMapaVinculos("ANDRE FRANZOTTI", "076.925.727-55", vinculos)
        d.show()
        app.processEvents()

        # Estica a janela em vários tamanhos, como quem arrasta a borda.
        for largura in range(600, 2200, 61):
            d.resize(largura, 700)
            app.processEvents()
            d.repaint()
        app.processEvents()
        print("SOBREVIVEU")
        """
    )
    assert concluido.returncode == 0, concluido.stderr
    assert "SOBREVIVEU" in concluido.stdout
    # O motivo tem que chegar a quem for investigar.
    assert "defeito plantado no desenho" in concluido.stderr


def test_esticar_o_mapa_de_verdade_nao_derruba_nem_erra_o_desenho():
    """Sem defeito plantado: esticar a janela em muitos tamanhos, incluindo
    maximizar, não pode levantar nada nem fechar o programa."""
    concluido = _rodar(
        """
        from controle_lucros.ui import diagrama_vinculos as dv

        falhas = []
        original = dv.desenhar
        def espiao(painter, mapa, paleta):
            try:
                original(painter, mapa, paleta)
            except Exception as erro:
                falhas.append(repr(erro))
        dv.desenhar = espiao

        vinculos = [
            {"empresa_nome": f"EMPRESA {i} LTDA", "percentual": 5.0 + i,
             "data_entrada": "2020-01-01",
             "data_saida": None if i % 3 else "2025-06-01"}
            for i in range(14)
        ]
        d = dv.DialogoMapaVinculos("ANDRE FRANZOTTI", "076.925.727-55", vinculos)
        d.show()
        app.processEvents()

        for largura in range(400, 2600, 43):
            d.resize(largura, 300 + largura // 4)
            app.processEvents()
            d.repaint()
        d.showMaximized(); app.processEvents(); d.repaint()
        d.showNormal(); app.processEvents(); d.repaint()

        print("FALHAS:", falhas)
        print("SOBREVIVEU")
        """
    )
    assert concluido.returncode == 0, concluido.stderr
    assert "SOBREVIVEU" in concluido.stdout
    assert "FALHAS: []" in concluido.stdout


def test_os_dois_mapas_pintam_do_jeito_que_as_abas_os_abrem():
    """O defeito que chegou ao usuário: a aba de Sócios abria o diálogo com o
    widget no lugar do papel, e o desenho estourava ao tentar escrever um
    SociosTab dentro do hub — "o mapa do sócio ficou todo bugado".

    Os testes das abas não pegaram porque trocavam a classe inteira por um
    lambda: o construtor de verdade nunca rodava. Este aqui abre os dois
    mapas exatamente como as abas abrem, e PINTA — que é onde o erro
    aparecia."""
    concluido = _rodar(
        """
        import sqlite3
        from controle_lucros import db, repositories as repo
        from controle_lucros.models import Empresa, Socio, VinculoSocietario
        from controle_lucros.ui import diagrama_vinculos as dv
        from controle_lucros.ui.empresas_tab import EmpresasTab
        from controle_lucros.ui.socios_tab import SociosTab

        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        db.init_schema(conn)
        empresa_id = repo.salvar_empresa(conn, Empresa(
            None, "91", "ENDOGASTRO LTDA", "", 1000, 1000))
        socio_id = repo.salvar_socio(conn, Socio(None, "ANDRE FRANZOTTI", "076.925.727-55"))
        repo.salvar_vinculo(conn, VinculoSocietario(
            id=None, empresa_id=empresa_id, socio_id=socio_id, percentual_capital=46.94,
            quantidade_cotas=469, data_entrada="2007-03-23", data_saida=None))

        falhas = []
        original = dv.desenhar
        def espiao(painter, mapa, paleta):
            try:
                original(painter, mapa, paleta)
            except Exception as erro:
                falhas.append(f"{mapa.centro_papel}: {erro!r}")
        dv.desenhar = espiao

        abertos = []
        dv.DialogoMapaVinculos.exec = lambda self: abertos.append(self) or 0

        socios = SociosTab(conn)
        socios.tabela.selectRow(0)
        socios._abrir_mapa_vinculos()

        empresas = EmpresasTab(conn)
        empresas.tabela.selectRow(0)
        empresas._abrir_quadro_societario()

        papeis = []
        for dialogo in abertos:
            dialogo.show()
            app.processEvents()
            for largura in (700, 1400, 2100):
                dialogo.resize(largura, 700)
                app.processEvents()
                dialogo.repaint()
            papeis.append(dialogo.mapa().centro_papel)

        print("PAPEIS:", papeis)
        print("FALHAS:", falhas)
        print("SOBREVIVEU")
        """
    )
    assert concluido.returncode == 0, concluido.stderr
    assert "SOBREVIVEU" in concluido.stdout
    assert "FALHAS: []" in concluido.stdout
    # Cada aba abre o mapa do seu lado: sócio na de Sócios, empresa na de Cadastro.
    assert "PAPEIS: ['sócio', 'empresa']" in concluido.stdout
