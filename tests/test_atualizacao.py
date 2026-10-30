"""Atualização automática: ler a release do GitHub, baixar e conferir o
instalador. A rede é sempre trocada por um dublê — nenhum teste fala com o GitHub."""
import hashlib
import io
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from controle_lucros import atualizacao as at
from controle_lucros.atualizacao import Atualizacao, ErroDeAtualizacao

CONTEUDO = b"instalador-de-mentira" * 1000
SHA = hashlib.sha256(CONTEUDO).hexdigest()
URL = "https://github.com/hendersobrinho/controle-de-lucros/releases/download/v9.0.0/ControleDeLucros_Setup_9.0.0.exe"


def _release(**mudancas):
    dados = {
        "tag_name": "v9.0.0", "body": "- Coisa nova", "draft": False, "prerelease": False,
        "assets": [{"name": "ControleDeLucros_Setup_9.0.0.exe", "size": len(CONTEUDO),
                    "browser_download_url": URL, "digest": f"sha256:{SHA}"}],
    }
    dados.update(mudancas)
    return dados


def _nova(**mudancas) -> Atualizacao:
    base = dict(versao="9.0.0", notas="", url=URL, nome="ControleDeLucros_Setup_9.0.0.exe",
                tamanho=len(CONTEUDO), sha256=SHA)
    base.update(mudancas)
    return Atualizacao(**base)


class _Resposta(io.BytesIO):
    def __init__(self, conteudo, url=URL):
        super().__init__(conteudo)
        self._url, self.headers = url, {}

    def geturl(self):
        return self._url


# ------------------------------------------------------------- a release --


def test_versoes_se_comparam_como_numeros():
    assert at.versao_como_tupla("v2.10.0") > at.versao_como_tupla("2.9.3")
    with pytest.raises(ValueError):
        at.versao_como_tupla("beta")


def test_release_mais_nova_vira_atualizacao():
    nova = at.interpretar_release(_release(), "2.1.0")
    assert (nova.versao, nova.notas, nova.sha256, nova.tamanho) == ("9.0.0", "- Coisa nova", SHA, len(CONTEUDO))


@pytest.mark.parametrize("release", [
    _release(tag_name="v2.1.0"),                      # igual
    _release(tag_name="v2.0.0"),                      # mais velha
    _release(prerelease=True),
    _release(draft=True),
    _release(assets=[]),                              # sem instalador anexo
    _release(assets=[{"name": "outro.zip", "browser_download_url": URL}]),
    _release(assets=[{"name": "ControleDeLucros_Setup_9.0.0.exe",
                      "browser_download_url": "https://exemplo.com/ControleDeLucros_Setup_9.0.0.exe"}]),
    _release(tag_name="sem-versao"),
])
def test_release_que_nao_serve_nao_atualiza(release):
    assert at.interpretar_release(release, "2.1.0") is None


def test_procurar_le_a_ultima_release(monkeypatch):
    pedidos = []
    monkeypatch.setattr(at, "_abrir", lambda url, espera, aceita="": pedidos.append(url) or
                        _Resposta(json.dumps(_release()).encode()))
    assert at.procurar("2.1.0").versao == "9.0.0"
    assert pedidos == [at.URL_ULTIMA_RELEASE]
    assert at.procurar("9.0.0") is None


def test_sem_internet_vira_erro_de_atualizacao(monkeypatch):
    import urllib.error

    def sem_rede(*_a, **_k):
        raise urllib.error.URLError("sem rede")

    monkeypatch.setattr(at.urllib.request, "urlopen", sem_rede)
    with pytest.raises(ErroDeAtualizacao, match="GitHub"):
        at.procurar("2.1.0")


def test_endereco_que_nao_e_do_github_e_recusado(monkeypatch):
    monkeypatch.setattr(at.urllib.request, "urlopen", lambda *_a, **_k: _Resposta(b"{}", "https://mal.example/x"))
    with pytest.raises(ErroDeAtualizacao, match="não é do GitHub"):
        at.procurar("2.1.0")


# ----------------------------------------------------------- o download --


@pytest.fixture()
def baixando(monkeypatch, tmp_path):
    monkeypatch.setattr(at, "pasta_de_downloads", lambda: tmp_path / "baixados")
    monkeypatch.setattr(at, "_abrir", lambda *_a, **_k: _Resposta(CONTEUDO))


def test_baixa_confere_e_entrega_o_instalador(baixando):
    andou = []
    caminho = at.baixar(_nova(), progresso=lambda b, t: andou.append((b, t)))
    assert caminho.read_bytes() == CONTEUDO and caminho.name == "ControleDeLucros_Setup_9.0.0.exe"
    assert andou[-1] == (len(CONTEUDO), len(CONTEUDO))
    assert not list(caminho.parent.glob("*.parte"))


def test_arquivo_que_nao_confere_com_o_sha_nao_e_entregue(baixando):
    with pytest.raises(ErroDeAtualizacao, match="não confere"):
        at.baixar(_nova(sha256="0" * 64))
    assert not list(at.pasta_de_downloads().glob("*"))


def test_arquivo_incompleto_nao_e_entregue(baixando):
    with pytest.raises(ErroDeAtualizacao, match="incompleto"):
        at.baixar(_nova(tamanho=len(CONTEUDO) + 1, sha256=None))


def test_download_pode_ser_cancelado(baixando):
    with pytest.raises(ErroDeAtualizacao, match="cancelado"):
        at.baixar(_nova(), cancelado=lambda: True)
    assert not list(at.pasta_de_downloads().glob("*"))


def test_so_o_programa_instalado_se_atualiza_sozinho(monkeypatch):
    assert not at.verificacao_automatica_ligada()  # rodando do código
    monkeypatch.setattr(at.sys, "frozen", True, raising=False)
    monkeypatch.delenv("CONTROLE_LUCROS_SEM_ATUALIZACAO", raising=False)
    assert at.verificacao_automatica_ligada()
    monkeypatch.setenv("CONTROLE_LUCROS_SEM_ATUALIZACAO", "1")
    assert not at.verificacao_automatica_ligada()


# --------------------------------------------------------------- a tela --


@pytest.fixture()
def app():
    return QApplication.instance() or QApplication([])


def _esperar(condicao, ms=5000):
    for _ in range(ms // 20):
        if condicao():
            return True
        QTest.qWait(20)
    return condicao()


def test_atualizar_agora_baixa_executa_o_instalador_e_fecha_o_programa(app, monkeypatch, tmp_path):
    from controle_lucros.ui import atualizacao as tela

    instalador = tmp_path / "ControleDeLucros_Setup_9.0.0.exe"
    chamadas = []
    monkeypatch.setattr(tela.nucleo, "baixar", lambda nova, progresso=None, cancelado=None:
                        (progresso(5, 10), instalador)[1])
    monkeypatch.setattr(tela.nucleo, "executar_instalador", lambda caminho: chamadas.append(("rodou", caminho)))
    monkeypatch.setattr(tela.QApplication, "quit", staticmethod(lambda: chamadas.append(("fechou",))))

    dialogo = tela.DialogoAtualizacao(_nova(notas="# Novidades\n- algo"), versao_instalada="2.1.0")
    assert dialogo.notas.isVisibleTo(dialogo) and "Novidades" in dialogo.notas.toPlainText()
    dialogo.btn_atualizar.click()
    assert _esperar(lambda: ("fechou",) in chamadas)
    assert chamadas == [("rodou", instalador), ("fechou",)]


def test_instalador_recusado_pelo_windows_nao_fecha_o_programa(app, monkeypatch, tmp_path):
    from controle_lucros.ui import atualizacao as tela

    avisos, fechou = [], []
    monkeypatch.setattr(tela.nucleo, "baixar", lambda *_a, **_k: tmp_path / "x.exe")

    def recusa(_caminho):
        raise ErroDeAtualizacao("Não consegui abrir o instalador (permissão negada).")

    monkeypatch.setattr(tela.nucleo, "executar_instalador", recusa)
    monkeypatch.setattr(tela.QApplication, "quit", staticmethod(lambda: fechou.append(1)))
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: avisos.append(a[2]))

    dialogo = tela.DialogoAtualizacao(_nova(notas=""), versao_instalada="2.1.0")
    assert not dialogo.notas.isVisibleTo(dialogo)  # sem notas, sem caixa vazia
    dialogo.btn_atualizar.click()
    assert _esperar(lambda: avisos)
    assert "permissão negada" in avisos[0] and not fechou
    assert dialogo.btn_atualizar.isEnabled()


def test_verificador_avisa_quando_ja_esta_atualizado_so_se_foi_a_pessoa_que_pediu(app, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from controle_lucros.ui import atualizacao as tela

    mensagens = []
    monkeypatch.setattr(tela.nucleo, "procurar", lambda: None)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: mensagens.append(a[2]))
    janela = QWidget()
    verificador = tela.VerificadorDeAtualizacao(janela)

    verificador.verificar()  # automática: silêncio
    assert _esperar(lambda: verificador._consulta is None)
    assert mensagens == []
    verificador.verificar(manual=True)
    assert _esperar(lambda: mensagens)
    assert "já está na versão mais nova" in mensagens[0]


def test_falha_na_consulta_e_silenciosa_na_automatica(app, monkeypatch):
    from PySide6.QtWidgets import QWidget
    from controle_lucros.ui import atualizacao as tela

    def cai():
        raise ErroDeAtualizacao("Não consegui falar com o GitHub.")

    mensagens = []
    monkeypatch.setattr(tela.nucleo, "procurar", cai)
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: mensagens.append(a[2]))
    verificador = tela.VerificadorDeAtualizacao(QWidget())
    verificador.verificar()
    assert _esperar(lambda: verificador._consulta is None)
    assert mensagens == []
    verificador.verificar(manual=True)
    assert _esperar(lambda: mensagens)
    assert "Não consegui verificar" in mensagens[0]
