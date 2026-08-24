"""Carrossel horizontal deslizante — navega para os lados entre páginas
(usado para percorrer o histórico de alterações contratuais)."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

DURACAO_MS = 260


class CarrosselDeslizante(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._paginas: list[QWidget] = []
        self._animando = False

        self.pilha = QStackedWidget()

        self.btn_anterior = QPushButton("‹")
        self.btn_anterior.setProperty("role", "chevron")
        self.btn_anterior.clicked.connect(self.ir_para_anterior)

        self.btn_proxima = QPushButton("›")
        self.btn_proxima.setProperty("role", "chevron")
        self.btn_proxima.clicked.connect(self.ir_para_proxima)

        self.rotulo_posicao = QLabel("")
        self.rotulo_posicao.setProperty("role", "subtitulo")

        navegacao = QHBoxLayout()
        navegacao.addWidget(self.btn_anterior)
        navegacao.addStretch()
        navegacao.addWidget(self.rotulo_posicao)
        navegacao.addStretch()
        navegacao.addWidget(self.btn_proxima)

        layout = QVBoxLayout(self)
        layout.addWidget(self.pilha, 1)
        layout.addLayout(navegacao)

        self._atualizar_controles()

    def definir_paginas(self, paginas: list[QWidget], indice_atual: int | None = None) -> None:
        while self.pilha.count():
            widget = self.pilha.widget(0)
            self.pilha.removeWidget(widget)
            widget.deleteLater()

        self._paginas = paginas
        for pagina in paginas:
            self.pilha.addWidget(pagina)

        if paginas:
            alvo = len(paginas) - 1 if indice_atual is None else indice_atual
            self.pilha.setCurrentIndex(max(0, min(alvo, len(paginas) - 1)))
        self._atualizar_controles()

    def indice_atual(self) -> int:
        return self.pilha.currentIndex()

    def ir_para_anterior(self) -> None:
        self._deslizar_para(self.pilha.currentIndex() - 1, direita_para_esquerda=False)

    def ir_para_proxima(self) -> None:
        self._deslizar_para(self.pilha.currentIndex() + 1, direita_para_esquerda=True)

    def _atualizar_controles(self) -> None:
        total = len(self._paginas)
        atual = self.pilha.currentIndex() if total else -1
        self.btn_anterior.setEnabled(atual > 0)
        self.btn_proxima.setEnabled(0 <= atual < total - 1)
        self.rotulo_posicao.setText(f"{atual + 1} de {total}" if total else "Nenhuma alteração ainda")

    def _deslizar_para(self, indice: int, direita_para_esquerda: bool) -> None:
        if self._animando or indice < 0 or indice >= len(self._paginas):
            return

        largura = self.pilha.width()
        if largura <= 0:
            self.pilha.setCurrentIndex(indice)
            self._atualizar_controles()
            return

        pagina_atual = self.pilha.currentWidget()
        pagina_nova = self.pilha.widget(indice)
        deslocamento = largura if direita_para_esquerda else -largura

        pagina_nova.setGeometry(deslocamento, 0, largura, self.pilha.height())
        pagina_nova.show()
        pagina_nova.raise_()

        anim_saida = QPropertyAnimation(pagina_atual, b"pos")
        anim_saida.setDuration(DURACAO_MS)
        anim_saida.setEasingCurve(QEasingCurve.OutCubic)
        anim_saida.setStartValue(QPoint(0, 0))
        anim_saida.setEndValue(QPoint(-deslocamento, 0))

        anim_entrada = QPropertyAnimation(pagina_nova, b"pos")
        anim_entrada.setDuration(DURACAO_MS)
        anim_entrada.setEasingCurve(QEasingCurve.OutCubic)
        anim_entrada.setStartValue(QPoint(deslocamento, 0))
        anim_entrada.setEndValue(QPoint(0, 0))

        self._grupo = QParallelAnimationGroup()
        self._grupo.addAnimation(anim_saida)
        self._grupo.addAnimation(anim_entrada)

        self._animando = True

        def finalizar() -> None:
            self.pilha.setCurrentIndex(indice)
            pagina_atual.move(0, 0)
            self._animando = False
            self._atualizar_controles()

        self._grupo.finished.connect(finalizar)
        self._grupo.start()
