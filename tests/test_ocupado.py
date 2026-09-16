"""O aviso de "estou trabalhando".

Importação grande leva segundos com a janela parada, e sem sinal nenhum a
leitura é de programa travado — a reação natural é clicar de novo. O que se
testa aqui é que o sinal aparece, conta certo e some no fim, inclusive quando o
trabalho estoura no meio.
"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication

from controle_lucros.ui.ocupado import JanelaDeEspera, Progresso, ocupado


@pytest.fixture(scope="module", autouse=True)
def app():
    yield QApplication.instance() or QApplication([])


def test_espera_indeterminada_aparece_e_some():
    with ocupado(None, "Lendo", "Lendo o arquivo…") as janela:
        assert janela.isVisible()
        # Máximo zero é como o Qt desenha a barra que vai e volta sozinha.
        assert janela.barra.maximum() == 0
        assert "Lendo o arquivo" in janela.mensagem.text()
    assert not janela.isVisible()


def test_a_espera_some_mesmo_se_o_trabalho_falhar():
    """Janela de "aguarde" que fica na tela depois de um erro é pior do que
    não ter janela nenhuma."""
    with pytest.raises(ValueError):
        with ocupado(None, "Lendo", "Lendo…") as janela:
            raise ValueError("arquivo ilegível")
    assert not janela.isVisible()


def test_o_cursor_de_espera_e_devolvido():
    with ocupado(None, "Lendo", "Lendo…"):
        assert QApplication.overrideCursor() is not None
    assert QApplication.overrideCursor() is None


def test_progresso_conta_os_passos():
    with Progresso(None, "Importando", 5) as barra:
        for i in range(5):
            barra.passo(mensagem=f"linha {i + 1}")
        assert barra.feitos == 5
        assert barra._janela.barra.value() == 5
        assert "linha 5" in barra._janela.mensagem.text()


def test_progresso_aceita_o_total_de_quem_faz_o_laco():
    """A contagem vem de baixo (o repositório sabe quantas linhas são), e a
    tela só repassa — por isso `passo` recebe (feitos, total)."""
    with Progresso(None, "Importando", 0) as barra:
        barra.passo(1, 3)
        barra.passo(2, 3)
        assert barra._janela.barra.maximum() == 3
        assert barra._janela.barra.value() == 2


def test_janela_de_espera_nao_tem_como_ser_fechada_no_meio():
    """O que ela acompanha é gravação no banco: interromper deixaria cadastro
    pela metade."""
    from PySide6.QtCore import Qt

    janela = JanelaDeEspera("Importando", "Gravando…", total=10)
    assert not janela.windowFlags() & Qt.WindowCloseButtonHint
    assert janela.isModal()
