"""Telas da atualização automática (a lógica está em atualizacao.py).

Ao abrir o sistema, uma consulta rápida ao GitHub roda em segundo plano — sem
travar nada e sem barulho se não houver internet. Havendo versão nova, abre a
janela com as notas da release; com o "Atualizar agora" o instalador é baixado
(com barra de progresso), conferido e executado, e o programa fecha para ele
trocar os arquivos e abrir de novo."""
from __future__ import annotations

import threading

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from .. import __version__, atualizacao as nucleo
from ..atualizacao import Atualizacao, ErroDeAtualizacao


def _em_segundo_plano(funcao) -> dict:
    """Roda funcao numa thread; o dicionário devolvido ganha "pronto",
    "resultado" ou "erro" (lido por quem consulta de tempos em tempos)."""
    estado: dict = {"pronto": False, "resultado": None, "erro": None}

    def rodar() -> None:
        try:
            estado["resultado"] = funcao()
        except Exception as erro:  # noqa: BLE001 - qualquer falha vira mensagem, não derruba o programa
            estado["erro"] = erro
        estado["pronto"] = True

    threading.Thread(target=rodar, daemon=True).start()
    return estado


class DialogoAtualizacao(QDialog):
    """Mostra a versão nova e, com o "sim", baixa e executa o instalador."""

    def __init__(self, nova: Atualizacao, parent=None, versao_instalada: str = __version__):
        super().__init__(parent)
        self.nova = nova
        self._baixando: dict | None = None
        self._cancelar = False
        self.setWindowTitle("Nova versão disponível")
        self.setMinimumWidth(520)

        titulo = QLabel("Há uma versão nova do sistema")
        titulo.setProperty("role", "secao")
        versoes = QLabel(f"Versão {nova.versao}  ·  você está na {versao_instalada}")
        versoes.setProperty("role", "subtitulo")

        self.notas = QTextBrowser()
        self.notas.setOpenExternalLinks(True)
        self.notas.setMarkdown(nova.notas)
        self.notas.setMinimumHeight(150)
        self.notas.setVisible(bool(nova.notas))

        aviso = QLabel(
            "Ao atualizar, o sistema fecha e abre sozinho em seguida. O Windows vai pedir permissão: "
            "clique em <b>Sim</b>. Seus dados ficam no servidor e não são alterados."
        )
        aviso.setWordWrap(True)
        aviso.setProperty("role", "info")

        self.andamento = QLabel("")
        self.andamento.setProperty("role", "subtitulo")
        self.andamento.hide()
        self.barra = QProgressBar()
        self.barra.setTextVisible(True)
        self.barra.hide()

        self.btn_depois = QPushButton("Depois")
        self.btn_depois.clicked.connect(self._depois)
        self.btn_atualizar = QPushButton("Atualizar agora")
        self.btn_atualizar.setProperty("role", "primario")
        self.btn_atualizar.setDefault(True)
        self.btn_atualizar.clicked.connect(self._atualizar)

        botoes = QHBoxLayout()
        botoes.addStretch()
        botoes.addWidget(self.btn_depois)
        botoes.addWidget(self.btn_atualizar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(titulo)
        layout.addWidget(versoes)
        layout.addWidget(self.notas)
        layout.addWidget(aviso)
        layout.addWidget(self.andamento)
        layout.addWidget(self.barra)
        layout.addLayout(botoes)

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._acompanhar)

    def _depois(self) -> None:
        if self._baixando is not None:
            self._cancelar = True  # a thread para no próximo pedaço; a janela espera ela voltar
            self.btn_depois.setEnabled(False)
            self.andamento.setText("Cancelando…")
            return
        self.reject()

    def _atualizar(self) -> None:
        self.btn_atualizar.setEnabled(False)
        self.btn_depois.setText("Cancelar")
        self.andamento.setText("Baixando a atualização…")
        self.andamento.show()
        self.barra.setRange(0, 0)  # indefinida até saber o tamanho
        self.barra.show()
        self._cancelar = False
        progresso = {"baixado": 0, "total": self.nova.tamanho}

        def ao_baixar(baixado: int, total: int) -> None:
            progresso["baixado"], progresso["total"] = baixado, total

        self._baixando = _em_segundo_plano(
            lambda: nucleo.baixar(self.nova, progresso=ao_baixar, cancelado=lambda: self._cancelar)
        )
        self._baixando["progresso"] = progresso
        self._timer.start()

    def _acompanhar(self) -> None:
        tarefa = self._baixando
        if tarefa is None:
            return
        baixado, total = tarefa["progresso"]["baixado"], tarefa["progresso"]["total"]
        if total:
            self.barra.setRange(0, 1000)
            self.barra.setValue(int(1000 * min(baixado, total) / total))
            self.andamento.setText(f"Baixando a atualização…  {baixado / 1_048_576:.0f} de {total / 1_048_576:.0f} MB")
        if not tarefa["pronto"]:
            return
        self._timer.stop()
        self._baixando = None
        if tarefa["erro"] is not None:
            self._falhou(tarefa["erro"])
            return
        self.andamento.setText("Abrindo o instalador…")
        try:
            nucleo.executar_instalador(tarefa["resultado"])
        except ErroDeAtualizacao as erro:
            self._falhou(erro)
            return
        # O instalador assume daqui: fecha o sistema por inteiro para trocar os arquivos.
        self.accept()
        QApplication.quit()

    def _falhou(self, erro: Exception) -> None:
        cancelou = self._cancelar
        self._cancelar = False
        self.barra.hide()
        self.andamento.hide()
        self.btn_atualizar.setEnabled(True)
        self.btn_depois.setEnabled(True)
        self.btn_depois.setText("Depois")
        if cancelou:
            return
        QMessageBox.warning(
            self, "Não foi possível atualizar",
            f"{erro}\n\nO sistema continua como estava. Tente de novo mais tarde, ou baixe o instalador em "
            f"{nucleo.URL_RELEASES}.",
        )

    def reject(self) -> None:
        if self._baixando is not None:
            self._depois()
            return
        super().reject()


class VerificadorDeAtualizacao(QObject):
    """Consulta o GitHub sem travar a tela e abre a janela se houver versão
    nova. verificar(manual=True) é o botão da pessoa: ela quer resposta
    também quando não há nada novo ou quando não deu para consultar."""

    def __init__(self, janela: QWidget):
        super().__init__(janela)
        self._janela = janela
        self._consulta: dict | None = None
        self._manual = False
        self._timer = QTimer(self)
        self._timer.setInterval(150)
        self._timer.timeout.connect(self._acompanhar)

    def verificar(self, manual: bool = False) -> None:
        if self._consulta is not None:
            return
        self._manual = manual
        self._consulta = _em_segundo_plano(nucleo.procurar)
        self._timer.start()

    def _acompanhar(self) -> None:
        consulta = self._consulta
        if consulta is None or not consulta["pronto"]:
            return
        self._timer.stop()
        self._consulta = None
        if consulta["erro"] is not None:
            if self._manual:
                QMessageBox.information(
                    self._janela, "Atualização",
                    f"Não consegui verificar agora: {consulta['erro']}\nConfira a internet e tente de novo.",
                )
            return
        nova = consulta["resultado"]
        if nova is not None:
            DialogoAtualizacao(nova, self._janela).exec()
        elif self._manual:
            QMessageBox.information(
                self._janela, "Atualização", f"Você já está na versão mais nova ({__version__})."
            )
