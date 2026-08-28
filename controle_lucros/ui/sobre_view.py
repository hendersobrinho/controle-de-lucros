"""Tela "Sobre": crédito de autoria do sistema e link para o site de quem
desenvolveu. A logo fica sobre uma placa clara fixa (não segue o tema),
porque o traço preto do arquivo original só é legível em fundo claro."""
from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtSvgWidgets import QSvgWidget
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from .icones import pasta_assets
from .theme import BRASS

SITE_URL = "https://www.henderlab.com.br/"


class SobreView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        titulo = QLabel("Sobre o sistema")
        titulo.setProperty("role", "secao")

        card = QFrame()
        card.setProperty("role", "card")
        card.setMaximumWidth(560)

        placa_logo = QFrame()
        placa_logo.setFixedSize(96, 96)
        placa_logo.setStyleSheet("background: #FFFFFF; border-radius: 10px;")
        logo = QSvgWidget(str(pasta_assets() / "henderlab_logo.svg"), placa_logo)
        logo.setFixedSize(64, 64)
        logo.move(16, 16)

        nome = QLabel("Henderson Pereira")
        nome.setProperty("role", "titulo")

        assinatura = QLabel("Desenvolvido por HenderLab")
        assinatura.setProperty("role", "subtitulo")

        cabecalho = QHBoxLayout()
        cabecalho.setSpacing(16)
        cabecalho.addWidget(placa_logo)
        coluna_nome = QVBoxLayout()
        coluna_nome.setSpacing(2)
        coluna_nome.addWidget(nome)
        coluna_nome.addWidget(assinatura)
        cabecalho.addLayout(coluna_nome)
        cabecalho.addStretch()

        descricao = QLabel(
            "Este Controle de Distribuição de Lucros foi desenvolvido sob medida pra este "
            "escritório: histórico completo de sócios e alterações contratuais, distribuição "
            "anual, dashboards e backup — tudo num só lugar."
        )
        descricao.setWordWrap(True)

        link = QLabel(f'<a href="{SITE_URL}" style="color:{BRASS()};">{SITE_URL.rstrip("/")}</a>')
        link.setOpenExternalLinks(True)
        link.setTextInteractionFlags(Qt.TextBrowserInteraction)

        btn_site = QPushButton("Visitar site")
        btn_site.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(SITE_URL)))

        linha_link = QHBoxLayout()
        linha_link.addWidget(link)
        linha_link.addStretch()
        linha_link.addWidget(btn_site)

        conteudo_card = QVBoxLayout(card)
        conteudo_card.setContentsMargins(24, 24, 24, 24)
        conteudo_card.setSpacing(16)
        conteudo_card.addLayout(cabecalho)
        conteudo_card.addWidget(descricao)
        conteudo_card.addLayout(linha_link)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(titulo)
        layout.addWidget(card)
        layout.addStretch()
