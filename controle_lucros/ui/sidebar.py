"""Navegação lateral: seções e itens clicáveis, sóbria — sem cores fortes,
só a indicação da seção ativa por peso de fonte e uma barra fina de destaque.
O rodapé mostra quem está logado e dá acesso a trocar senha / sair."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from . import theme


class Sidebar(QFrame):
    navegar = Signal(str)
    trocar_senha = Signal()
    sair = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setFixedWidth(230)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 18, 0, 12)
        layout.setSpacing(2)

        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self._botoes: dict[str, QPushButton] = {}

        layout.addWidget(self._secao("EMPRESAS"))
        layout.addWidget(self._item("Cadastro", "empresas.cadastro", sub=True, marcado=True))
        layout.addWidget(self._item("Alterações contratuais", "empresas.alteracoes", sub=True))
        layout.addWidget(self._item("Importação em massa", "empresas.importar", sub=True))

        layout.addWidget(self._espacador())
        layout.addWidget(self._secao("SÓCIOS"))
        layout.addWidget(self._item("Cadastro de sócios", "socios", sub=True))

        layout.addWidget(self._espacador())
        layout.addWidget(self._secao("DISTRIBUIÇÃO"))
        layout.addWidget(self._item("Distribuição anual", "distribuicao", sub=True))

        layout.addWidget(self._espacador())
        layout.addWidget(self._secao("DASHBOARD"))
        layout.addWidget(self._item("Visão geral", "dashboard.geral", sub=True))
        layout.addWidget(self._item("Análise por empresa", "dashboard.empresa", sub=True))

        layout.addWidget(self._espacador())
        layout.addWidget(self._secao("SISTEMA"))
        layout.addWidget(self._item("Log de atividades", "sistema.log", sub=True))
        self._botao_usuarios = self._item("Usuários", "sistema.usuarios", sub=True)
        layout.addWidget(self._botao_usuarios)
        self._botao_backup = self._item("Backup", "sistema.backup", sub=True)
        layout.addWidget(self._botao_backup)
        layout.addWidget(self._item("Sobre", "sistema.sobre", sub=True))

        layout.addStretch()

        layout.addWidget(self._hairline())
        self._rotulo_usuario = QLabel("")
        self._rotulo_usuario.setProperty("role", "subtitulo")
        self._rotulo_usuario.setStyleSheet("padding: 10px 22px 4px 22px; font-weight: 600;")

        self.btn_tema = QPushButton()
        self.btn_tema.setProperty("role", "navSub")
        self.btn_tema.setCursor(Qt.PointingHandCursor)
        self.btn_tema.clicked.connect(theme.estado().alternar)
        self._atualizar_texto_tema()
        theme.estado().mudou.connect(self._atualizar_texto_tema)

        self.btn_trocar_senha = QPushButton("Trocar senha")
        self.btn_trocar_senha.setProperty("role", "navSub")
        self.btn_trocar_senha.setCursor(Qt.PointingHandCursor)
        self.btn_trocar_senha.clicked.connect(self.trocar_senha.emit)

        self.btn_sair = QPushButton("Sair")
        self.btn_sair.setProperty("role", "navSub")
        self.btn_sair.setCursor(Qt.PointingHandCursor)
        self.btn_sair.clicked.connect(self.sair.emit)

        layout.addWidget(self._rotulo_usuario)
        layout.addWidget(self.btn_tema)
        layout.addWidget(self.btn_trocar_senha)
        layout.addWidget(self.btn_sair)

    def definir_usuario(self, nome: str, admin: bool) -> None:
        rotulo = f"{nome}" + ("  ·  admin" if admin else "")
        self._rotulo_usuario.setText(rotulo)
        self._botao_usuarios.setVisible(admin)
        self._botao_backup.setVisible(admin)

    def _secao(self, texto: str) -> QLabel:
        rotulo = QLabel(texto)
        rotulo.setProperty("role", "navSecao")
        return rotulo

    def _espacador(self) -> QWidget:
        espacador = QWidget()
        espacador.setFixedHeight(16)
        return espacador

    def _hairline(self) -> QFrame:
        linha = QFrame()
        linha.setProperty("role", "hairline")
        return linha

    def _item(self, texto: str, chave: str, sub: bool = False, marcado: bool = False) -> QPushButton:
        botao = QPushButton(texto)
        botao.setProperty("role", "navSub" if sub else "navItem")
        botao.setCheckable(True)
        botao.setChecked(marcado)
        botao.setCursor(Qt.PointingHandCursor)
        botao.clicked.connect(lambda: self.navegar.emit(chave))
        self._grupo.addButton(botao)
        self._botoes[chave] = botao
        return botao

    def marcar(self, chave: str) -> None:
        botao = self._botoes.get(chave)
        if botao is not None:
            botao.setChecked(True)

    def _atualizar_texto_tema(self) -> None:
        escuro = theme.estado().modo == "escuro"
        self.btn_tema.setText("☀  Modo claro" if escuro else "☾  Modo escuro")
