"""A tela de reportar problema e a captura automática de erros.

O ponto da captura: sem ela, uma exceção que ninguém tratou só aparece no
console — que num programa empacotado não existe. A pessoa vê o clique não
fazer nada e não tem o que contar depois.

O ponto da tela: o botão de e-mail é um atalho, não a garantia. Máquina que
usa webmail pelo navegador não tem programa de e-mail configurado e o link
não faz nada — por isso copiar e salvar precisam funcionar sozinhos.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from controle_lucros import relatorio_erro
from controle_lucros.ui import reportar_erro


@pytest.fixture(scope="module", autouse=True)
def app():
    yield QApplication.instance() or QApplication([])


def _erro(mensagem="deu ruim") -> Exception:
    try:
        raise ValueError(mensagem)
    except ValueError as erro:
        return erro


def _dialogo(origem="erro", erro=None, detalhes=""):
    relatorio = relatorio_erro.montar(erro, origem=origem, detalhes_extras=detalhes)
    relatorio.contexto.update({"erro": erro, "detalhes_extras": detalhes})
    return reportar_erro.DialogoReportarProblema(relatorio)


def test_a_tela_mostra_a_mensagem_que_sera_enviada():
    """O texto fica à vista de propósito: é o que permite conferir o que está
    sendo mandado antes de mandar."""
    dialogo = _dialogo(erro=_erro("coluna X não existe"))
    texto = dialogo.mensagem.toPlainText()

    assert "coluna X não existe" in texto
    assert "Traceback" in texto
    assert relatorio_erro.DESTINO in dialogo.instrucao.text()


def test_o_que_a_pessoa_digita_entra_na_mensagem_na_hora():
    dialogo = _dialogo(erro=_erro())
    assert "(não informado)" in dialogo.mensagem.toPlainText()

    dialogo.o_que_fazia.setPlainText("cliquei em Exportar PDF e travou")

    assert "cliquei em Exportar PDF e travou" in dialogo.mensagem.toPlainText()
    assert "(não informado)" not in dialogo.mensagem.toPlainText()


def test_copiar_leva_o_relatorio_inteiro_pra_area_de_transferencia(app):
    """O caminho que funciona mesmo sem programa de e-mail — e por isso não
    pode depender de nada além do próprio programa."""
    dialogo = _dialogo(erro=_erro("falha ao ler o PDF"))
    dialogo.o_que_fazia.setPlainText("importando o relatório de setembro")
    dialogo._copiar()

    copiado = app.clipboard().text()
    assert "falha ao ler o PDF" in copiado
    assert "importando o relatório de setembro" in copiado
    assert copiado == dialogo.relatorio_atual().corpo
    assert relatorio_erro.DESTINO in dialogo.aviso.text()


def test_quando_o_email_nao_abre_a_tela_diz_o_que_fazer(monkeypatch):
    """Silêncio aqui seria o pior desfecho: a pessoa fecharia a janela achando
    que o relatório foi enviado."""
    monkeypatch.setattr(reportar_erro.QDesktopServices, "openUrl", staticmethod(lambda url: False))
    dialogo = _dialogo(erro=_erro())
    dialogo._abrir_email()

    aviso = dialogo.aviso.text()
    assert "Copiar mensagem" in aviso
    assert relatorio_erro.DESTINO in aviso


def test_quando_o_email_abre_a_tela_confirma(monkeypatch):
    enviados = []
    monkeypatch.setattr(
        reportar_erro.QDesktopServices, "openUrl",
        staticmethod(lambda url: enviados.append(url.toString()) or True),
    )
    dialogo = _dialogo(erro=_erro())
    dialogo.o_que_fazia.setPlainText("estava salvando uma alteração")
    dialogo._abrir_email()

    (url,) = enviados
    assert url.startswith(f"mailto:{relatorio_erro.DESTINO}")
    assert "salvando" in dialogo.aviso.text() or "enviar" in dialogo.aviso.text()


def test_salvar_grava_o_arquivo(monkeypatch, tmp_path):
    destino = tmp_path / "problema.txt"
    monkeypatch.setattr(
        reportar_erro.QFileDialog, "getSaveFileName",
        staticmethod(lambda *a, **k: (str(destino), "")),
    )
    dialogo = _dialogo(erro=_erro("erro ao gerar informe"))
    dialogo._salvar()

    assert "erro ao gerar informe" in destino.read_text(encoding="utf-8")


def test_a_tela_de_fechamento_traz_o_registro_do_tombo():
    dialogo = _dialogo(origem="fechamento", detalhes="Fatal Python error: Segmentation fault")
    # O título diz de cara o que aconteceu — quem chega nesta tela depois de o
    # programa ter fechado sozinho precisa entender por que ela apareceu.
    assert "fechou sozinho" in dialogo.titulo.text().lower()
    assert "Segmentation fault" in dialogo.mensagem.toPlainText()


# ------------------------------------------------- captura automática --


def test_a_captura_transforma_erro_solto_em_relatorio(monkeypatch):
    abertos = []
    monkeypatch.setattr(
        reportar_erro, "abrir_para_erro",
        lambda erro, tela="", parent=None: abertos.append((erro, tela)),
    )
    captura = reportar_erro.CapturaDeErros()
    erro = _erro("estourei fora de qualquer try")
    captura._tratar(type(erro), erro, erro.__traceback__)

    assert len(abertos) == 1
    assert str(abertos[0][0]) == "estourei fora de qualquer try"


def test_o_mesmo_erro_repetido_abre_uma_janela_so(monkeypatch):
    """Erro em paintEvent se repete a cada redesenho: sem isto, arrastar a
    borda da janela empilharia dezenas de telas iguais, e fechá-las uma a uma
    seria pior do que o defeito original."""
    abertos = []
    monkeypatch.setattr(
        reportar_erro, "abrir_para_erro",
        lambda erro, tela="", parent=None: abertos.append(erro),
    )
    captura = reportar_erro.CapturaDeErros()
    for _ in range(20):
        erro = _erro("o mesmo de sempre")   # mesma linha, mesmo tipo
        captura._tratar(type(erro), erro, erro.__traceback__)

    assert len(abertos) == 1


def test_erros_diferentes_abrem_janelas_diferentes(monkeypatch):
    """O contrário também importa: agrupar demais esconderia um problema novo
    atrás de um já conhecido."""
    abertos = []
    monkeypatch.setattr(
        reportar_erro, "abrir_para_erro",
        lambda erro, tela="", parent=None: abertos.append(erro),
    )
    captura = reportar_erro.CapturaDeErros()

    primeiro = _erro("um")
    captura._tratar(type(primeiro), primeiro, primeiro.__traceback__)
    try:
        raise TypeError("outro problema, outro lugar")
    except TypeError as segundo:
        captura._tratar(type(segundo), segundo, segundo.__traceback__)

    assert len(abertos) == 2


def test_falha_ao_montar_o_relatorio_nao_vira_outro_erro(monkeypatch):
    """Relatar problema não pode ser mais uma fonte de problema: se a própria
    tela de relatório quebrar, o programa segue."""
    def explode(*_a, **_k):
        raise RuntimeError("a tela de relatório também quebrou")

    monkeypatch.setattr(reportar_erro, "abrir_para_erro", explode)
    captura = reportar_erro.CapturaDeErros()
    erro = _erro()

    captura._tratar(type(erro), erro, erro.__traceback__)  # não pode levantar


def test_a_captura_preserva_o_hook_anterior(monkeypatch):
    """O erro continua indo pro console de quem roda pelo código — a tela é
    um acréscimo, não uma troca."""
    import sys

    vistos = []
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: vistos.append(v))
    monkeypatch.setattr(reportar_erro, "abrir_para_erro", lambda *a, **k: None)

    captura = reportar_erro.CapturaDeErros()
    captura.instalar()
    try:
        erro = _erro("vai pros dois lugares")
        sys.excepthook(type(erro), erro, erro.__traceback__)
    finally:
        captura.desinstalar()

    assert [str(e) for e in vistos] == ["vai pros dois lugares"]


def test_erro_solto_no_meio_de_uma_gravacao_desfaz_a_gravacao(monkeypatch, conn):
    """Com o banco no servidor, a gravação pela metade seguraria trava nas
    linhas pros outros PCs, e o próximo commit a gravaria assim mesmo."""
    from types import SimpleNamespace

    from controle_lucros import db

    monkeypatch.setattr(reportar_erro, "abrir_para_erro", lambda *a, **k: None)
    captura = reportar_erro.CapturaDeErros()
    captura.janela_principal = SimpleNamespace(conn=conn)
    conn.execute("INSERT INTO empresa (numero_chamada, nome) VALUES ('001', 'PELA METADE LTDA')")

    erro = _erro("estourou entre duas gravações")
    captura._tratar(type(erro), erro, erro.__traceback__)

    assert not conn.em_transacao
    outro_pc = db.connect()
    try:
        assert outro_pc.execute("SELECT COUNT(*) FROM empresa").fetchone()[0] == 0
    finally:
        outro_pc.close()


def test_erro_de_programacao_no_sql_vira_relatorio_e_nao_aviso_de_rede(monkeypatch, conn):
    """Coluna que não existe é defeito do programa: tem que chegar como
    relatório, não como "confira a rede"."""
    import psycopg

    abertos = []
    monkeypatch.setattr(reportar_erro, "abrir_para_erro", lambda erro, **k: abertos.append(erro))
    try:
        conn.execute("SELECT coluna_que_nao_existe FROM empresa")
    except psycopg.Error as erro:
        reportar_erro.CapturaDeErros()._tratar(type(erro), erro, erro.__traceback__)

    assert len(abertos) == 1
