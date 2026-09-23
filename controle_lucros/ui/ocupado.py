"""Sinal de que o programa está trabalhando.

Importar uma planilha de cento e sessenta empresas leva alguns segundos, e
durante esses segundos a janela simplesmente não responde — o trabalho acontece
na mesma linha de execução que desenha a tela. Sem nada dizendo o contrário, a
impressão é de programa travado, e a reação natural é clicar de novo.

Duas formas, conforme dê ou não para contar os passos:

- `ocupado(...)`: uma leitura de arquivo, que é uma chamada só e não tem
  passos. Mostra a janelinha com o que está acontecendo e troca o cursor.
- `Progresso(...)`: um laço que a gente controla (gravar linha por linha,
  emitir um informe por empresa). Aí dá para mostrar a barra andando de
  verdade, com "12 de 160" — e é ela que prova que o programa não travou.

A barra anda porque o laço devolve o controle ao Qt de tempos em tempos
(processEvents). Não é thread: a conexão com o banco é ligada a esta linha de
execução, e mover a gravação para outra abriria um problema bem maior do que o
que resolveria.
"""
from __future__ import annotations

from contextlib import contextmanager

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QLabel,
    QProgressBar,
    QVBoxLayout,
)

# De quantos em quantos passos a tela é redesenhada. Redesenhar a cada passo
# custa mais tempo do que o próprio trabalho numa importação grande; a cada
# vinte, a barra ainda anda de forma contínua aos olhos.
PASSOS_ENTRE_REDESENHOS = 20


class JanelaDeEspera(QDialog):
    """A janelinha de "aguarde". Sem botão de fechar e sem cancelar: o que ela
    acompanha (gravar no banco) não pode ser interrompido no meio sem deixar
    cadastro pela metade."""

    def __init__(self, titulo: str, mensagem: str, total: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        self.setModal(True)
        self.setFixedWidth(430)

        self.titulo = QLabel(titulo)
        self.titulo.setProperty("role", "secao")
        self.mensagem = QLabel(mensagem)
        self.mensagem.setProperty("role", "subtitulo")
        self.mensagem.setWordWrap(True)

        self.barra = QProgressBar()
        # Sem o "52%" por cima da barra: a mensagem logo acima já diz "84 de
        # 160", que informa mais e não briga com a cor do preenchimento.
        self.barra.setTextVisible(False)
        # Mínimo igual ao máximo em zero é como o Qt desenha a barra
        # indeterminada, aquela que vai e volta sozinha.
        self.barra.setRange(0, total)
        self.barra.setValue(0)
        self.barra.setFixedHeight(10)

        miolo = QVBoxLayout()
        miolo.setContentsMargins(24, 20, 24, 22)
        miolo.setSpacing(10)
        miolo.addWidget(self.titulo)
        miolo.addWidget(self.mensagem)
        miolo.addSpacing(4)
        miolo.addWidget(self.barra)

        cartao = QFrame()
        cartao.setProperty("role", "card")
        cartao.setLayout(miolo)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.addWidget(cartao)

    def dizer(self, mensagem: str) -> None:
        self.mensagem.setText(mensagem)

    def avancar(self, quanto: int = 1) -> None:
        self.barra.setValue(self.barra.value() + quanto)


@contextmanager
def ocupado(parent, titulo: str, mensagem: str):
    """Para o que é uma chamada só — ler um PDF, gravar uma planilha.

    A barra fica indeterminada porque não há passo nenhum para contar, e o
    cursor de espera cobre o instante entre a janela aparecer e o trabalho
    começar."""
    janela = JanelaDeEspera(titulo, mensagem, total=0, parent=parent)
    QGuiApplication.setOverrideCursor(Qt.WaitCursor)
    janela.show()
    QApplication.processEvents()
    try:
        yield janela
    finally:
        QGuiApplication.restoreOverrideCursor()
        janela.close()
        janela.deleteLater()
        QApplication.processEvents()


class Progresso:
    """Para laços que a gente controla, com a contagem aparecendo na barra.

    Use como gerenciador de contexto e chame `passo()` a cada item — ou passe
    `.passo` direto como callback para quem faz o laço."""

    def __init__(self, parent, titulo: str, total: int, mensagem: str = ""):
        self.total = max(0, total)
        self.feitos = 0
        self._janela = JanelaDeEspera(titulo, mensagem or "Só um instante…", self.total, parent)

    def __enter__(self) -> "Progresso":
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        self._janela.show()
        QApplication.processEvents()
        return self

    def __exit__(self, *_erro) -> None:
        QGuiApplication.restoreOverrideCursor()
        self._janela.close()
        self._janela.deleteLater()
        QApplication.processEvents()

    def passo(self, feitos: int | None = None, total: int | None = None,
              mensagem: str = "") -> None:
        """Avança um passo (ou salta para `feitos`, quando quem chama conta).

        A assinatura aceita (feitos, total) para poder ser passada como
        callback a quem faz o laço lá embaixo, sem a camada de baixo precisar
        saber que existe uma janela."""
        if total is not None and total != self.total:
            self.total = total
            self._janela.barra.setRange(0, total)
        self.feitos = feitos if feitos is not None else self.feitos + 1
        self._janela.barra.setValue(self.feitos)
        if mensagem:
            self._janela.dizer(mensagem)
        if self.feitos % PASSOS_ENTRE_REDESENHOS == 0 or self.feitos >= self.total:
            QApplication.processEvents()

    def dizer(self, mensagem: str) -> None:
        self._janela.dizer(mensagem)
        QApplication.processEvents()
