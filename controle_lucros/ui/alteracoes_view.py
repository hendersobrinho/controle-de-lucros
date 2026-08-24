"""Tela de histórico de alterações contratuais: escolhe a empresa e navega
pelo carrossel deslizante, do rascunho mais recente até a fundação."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from .. import repositories as repo
from .alteracao_card import AlteracaoCard
from .carrossel import CarrosselDeslizante
from .common import preencher_combo


class AlteracoesView(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn

        self.empresa = QComboBox()
        self.empresa.currentIndexChanged.connect(lambda _: self._carregar_empresa())

        self.btn_nova = QPushButton("+ Nova alteração contratual")
        self.btn_nova.setProperty("role", "primario")
        self.btn_nova.clicked.connect(self._nova_alteracao)

        topo = QHBoxLayout()
        topo.addWidget(QLabel("Empresa:"))
        topo.addWidget(self.empresa, 1)
        topo.addWidget(self.btn_nova)

        self.carrossel = CarrosselDeslizante()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(topo)
        layout.addWidget(self.carrossel, 1)

        self.atualizar()

    def atualizar(self) -> None:
        empresa_id_anterior = self.empresa.currentData()
        preencher_combo(self.empresa, repo.listar_empresas(self.conn))
        if empresa_id_anterior is not None:
            idx = self.empresa.findData(empresa_id_anterior)
            if idx >= 0:
                self.empresa.setCurrentIndex(idx)
        self._carregar_empresa()

    def selecionar_empresa(self, empresa_id: int) -> None:
        idx = self.empresa.findData(empresa_id)
        if idx >= 0 and idx != self.empresa.currentIndex():
            self.empresa.setCurrentIndex(idx)
        elif idx >= 0:
            self._carregar_empresa()

    def _carregar_empresa(self, preservar_numero: int | None = None) -> None:
        empresa_id = self.empresa.currentData()
        if empresa_id is None:
            self.carrossel.definir_paginas([])
            return

        alteracoes = repo.listar_alteracoes(self.conn, empresa_id)
        paginas = [
            AlteracaoCard(self.conn, empresa_id, alteracao, self._ao_card_mudar)
            for alteracao in alteracoes
        ]

        indice = None
        if preservar_numero is not None:
            for i, a in enumerate(alteracoes):
                if a.numero == preservar_numero:
                    indice = i
                    break

        self.carrossel.definir_paginas(paginas, indice_atual=indice)

    def _ao_card_mudar(self, card: AlteracaoCard) -> None:
        numero = card.alteracao.numero if card.alteracao else None
        self._carregar_empresa(preservar_numero=numero)

    def _nova_alteracao(self) -> None:
        empresa_id = self.empresa.currentData()
        if empresa_id is None:
            QMessageBox.information(self, "Nova alteração", "Cadastre e selecione uma empresa primeiro.")
            return

        alteracoes = repo.listar_alteracoes(self.conn, empresa_id)
        paginas = [
            AlteracaoCard(self.conn, empresa_id, alteracao, self._ao_card_mudar)
            for alteracao in alteracoes
        ]
        rascunho = AlteracaoCard(self.conn, empresa_id, None, self._ao_card_mudar)
        paginas.append(rascunho)
        self.carrossel.definir_paginas(paginas, indice_atual=len(paginas) - 1)
