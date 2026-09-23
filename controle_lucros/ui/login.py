"""Diálogos de entrada no sistema: criação do primeiro usuário (quando o
banco está vazio) e o login normal do dia a dia."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .. import repositories as repo
from ..models import Usuario
from . import theme
from .icones import pasta_assets
from .local_banco import DialogoConexao

LARGURA_ENTRADA = 420


def _marca(tamanho: int = 72) -> QLabel:
    """A marca do programa no topo da tela de entrada. Se o arquivo não estiver
    lá (execução a partir do código sem os ícones gerados), o rótulo fica vazio
    e o resto da tela continua de pé."""
    rotulo = QLabel()
    rotulo.setAlignment(Qt.AlignCenter)
    caminho = pasta_assets() / "logo.png"
    if caminho.exists():
        imagem = QPixmap(str(caminho)).scaled(
            tamanho, tamanho, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        rotulo.setPixmap(imagem)
    return rotulo


def _centralizado(texto: str, papel: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setProperty("role", papel)
    rotulo.setAlignment(Qt.AlignCenter)
    rotulo.setWordWrap(True)
    return rotulo


def _campo(texto_de_apoio: str, senha: bool = False) -> QLineEdit:
    campo = QLineEdit()
    campo.setPlaceholderText(texto_de_apoio)
    campo.setMinimumHeight(38)
    campo.setAlignment(Qt.AlignCenter)
    if senha:
        campo.setEchoMode(QLineEdit.Password)
    return campo


def _botao_discreto(texto: str) -> QPushButton:
    """Ação secundária da tela de entrada. Sem moldura, porque ela compete com
    o "Entrar" — que é o que a pessoa vem fazer aqui todo dia."""
    botao = QPushButton(texto)
    botao.setFlat(True)
    botao.setCursor(Qt.PointingHandCursor)
    botao.setStyleSheet(
        f"QPushButton {{ border: none; background: transparent; color: {theme.INK_MUTED()};"
        f" font-size: 13px; padding: 6px 10px; }}"
        f"QPushButton:hover {{ color: {theme.INK()}; text-decoration: underline; }}"
    )
    return botao


def _cartao(layout_interno: QVBoxLayout) -> QFrame:
    """O mesmo cartão das outras telas, aqui segurando a coluna de entrada —
    a tela fica com um centro, em vez de campos soltos sobre o fundo."""
    cartao = QFrame()
    cartao.setProperty("role", "card")
    cartao.setLayout(layout_interno)
    return cartao


def _rotulo_de_erro() -> QLabel:
    erro = QLabel("")
    erro.setAlignment(Qt.AlignCenter)
    erro.setWordWrap(True)
    erro.setStyleSheet(f"color: {theme.SEAL_RED()}; font-size: 12px;")
    erro.hide()
    return erro


class DialogoPrimeiroUsuario(QDialog):
    """Só aparece quando ainda não existe nenhum usuário cadastrado — cria a
    primeira conta, que já nasce administradora.

    Num escritório que já usa o sistema, cair aqui quer dizer que este PC
    está conectado no banco errado (vazio): por isso oferece trocar a
    conexão, pro banco onde os usuários já existem. Trocada, o diálogo fecha
    com trocou_banco e quem chamou reconecta."""

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.trocou_banco = False
        self.setWindowTitle("Bem-vindo")
        self.setFixedWidth(LARGURA_ENTRADA)
        self.setModal(True)

        self.nome = _campo("seu nome completo")
        self.login = _campo("um login para entrar")
        self.senha = _campo("uma senha", senha=True)
        self.confirmar = _campo("repita a senha", senha=True)
        self.confirmar.returnPressed.connect(self._criar)
        self.erro = _rotulo_de_erro()

        criar = QPushButton("Criar conta e entrar")
        criar.setProperty("role", "primario")
        criar.setMinimumHeight(40)
        criar.clicked.connect(self._criar)

        sair = _botao_discreto("Sair")
        sair.clicked.connect(self.reject)

        usar_servidor = _botao_discreto("Alterar a conexão…")
        usar_servidor.clicked.connect(self._usar_banco_do_servidor)

        miolo = QVBoxLayout()
        miolo.setContentsMargins(38, 32, 38, 30)
        miolo.setSpacing(0)
        miolo.addWidget(_marca())
        miolo.addSpacing(16)
        miolo.addWidget(_centralizado("Seja bem-vindo", "titulo"))
        miolo.addSpacing(4)
        miolo.addWidget(_centralizado(
            "Este é o primeiro acesso ao <b>Controle de Distribuição de Lucros</b>. "
            "Crie sua conta — ela será a administradora do sistema.", "subtitulo"))
        miolo.addSpacing(22)
        for campo in (self.nome, self.login, self.senha, self.confirmar):
            miolo.addWidget(campo)
            miolo.addSpacing(10)
        miolo.addWidget(self.erro)
        miolo.addSpacing(6)
        miolo.addWidget(criar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 26, 26, 18)
        layout.setSpacing(0)
        layout.addWidget(_cartao(miolo))
        layout.addSpacing(6)

        rodape = QHBoxLayout()
        rodape.addStretch()
        rodape.addWidget(usar_servidor)
        rodape.addWidget(sair)
        rodape.addStretch()
        layout.addLayout(rodape)

        self.nome.setFocus()

    def _usar_banco_do_servidor(self) -> None:
        if DialogoConexao(self).exec() == QDialog.Accepted:
            self.trocou_banco = True
            self.reject()

    def _criar(self) -> None:
        nome = self.nome.text().strip()
        login = self.login.text().strip()
        senha = self.senha.text()

        if not nome or not login:
            self._mostrar_erro("Preencha nome e login.")
            return
        if len(senha) < 4:
            self._mostrar_erro("A senha precisa ter pelo menos 4 caracteres.")
            return
        if senha != self.confirmar.text():
            self._mostrar_erro("As senhas não conferem.")
            return

        repo.criar_usuario(self.conn, nome, login, senha, admin=True)
        self.usuario_autenticado = repo.autenticar(self.conn, login, senha)
        self.accept()

    def _mostrar_erro(self, texto: str) -> None:
        self.erro.setText(texto)
        self.erro.show()


class DialogoLogin(QDialog):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.usuario_autenticado: Usuario | None = None
        self.setWindowTitle("Entrar")
        self.setFixedWidth(LARGURA_ENTRADA)
        self.setModal(True)

        self.login = _campo("login")
        self.login.returnPressed.connect(lambda: self.senha.setFocus())
        self.senha = _campo("senha", senha=True)
        self.senha.returnPressed.connect(self._entrar)
        self.erro = _rotulo_de_erro()

        entrar = QPushButton("Entrar")
        entrar.setProperty("role", "primario")
        entrar.setMinimumHeight(40)
        entrar.clicked.connect(self._entrar)

        sair = _botao_discreto("Sair")
        sair.clicked.connect(self.reject)

        # Tudo numa coluna centrada, em vez do formulário com rótulo à
        # esquerda: são dois campos, e a tela de entrada é a primeira coisa
        # que se vê do programa todo dia.
        miolo = QVBoxLayout()
        miolo.setContentsMargins(38, 34, 38, 30)
        miolo.setSpacing(0)
        miolo.addWidget(_marca())
        miolo.addSpacing(16)
        miolo.addWidget(_centralizado("Seja bem-vindo", "titulo"))
        miolo.addSpacing(4)
        miolo.addWidget(_centralizado("Controle de Distribuição de Lucros", "subtitulo"))
        miolo.addSpacing(26)
        miolo.addWidget(self.login)
        miolo.addSpacing(10)
        miolo.addWidget(self.senha)
        miolo.addSpacing(10)
        miolo.addWidget(self.erro)
        miolo.addSpacing(6)
        miolo.addWidget(entrar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 26, 26, 18)
        layout.setSpacing(0)
        layout.addWidget(_cartao(miolo))
        layout.addSpacing(6)

        rodape = QHBoxLayout()
        rodape.addStretch()
        rodape.addWidget(sair)
        rodape.addStretch()
        layout.addLayout(rodape)

        self.login.setFocus()

    def _entrar(self) -> None:
        usuario = repo.autenticar(self.conn, self.login.text(), self.senha.text())
        if usuario is None:
            self.erro.setText("Login ou senha incorretos, ou usuário desativado.")
            self.erro.show()
            self.senha.clear()
            self.senha.setFocus()
            return
        self.usuario_autenticado = usuario
        self.accept()


class DialogoTrocarMinhaSenha(QDialog):
    """Autoatendimento: exige a senha atual, ao contrário da redefinição
    feita por um administrador na tela de Usuários."""

    def __init__(self, conn, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.usuario = usuario
        self.setWindowTitle("Trocar minha senha")
        self.setMinimumWidth(340)

        self.senha_atual = QLineEdit()
        self.senha_atual.setEchoMode(QLineEdit.Password)
        self.senha_nova = QLineEdit()
        self.senha_nova.setEchoMode(QLineEdit.Password)
        self.confirmar = QLineEdit()
        self.confirmar.setEchoMode(QLineEdit.Password)

        form = QFormLayout()
        form.addRow("Senha atual", self.senha_atual)
        form.addRow("Nova senha", self.senha_nova)
        form.addRow("Confirmar nova senha", self.confirmar)

        self.erro = QLabel("")
        self.erro.setStyleSheet(f"color: {theme.SEAL_RED()}; font-size: 11px;")
        self.erro.hide()

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.button(QDialogButtonBox.Ok).setText("Trocar senha")
        botoes.accepted.connect(self._validar)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.erro)
        layout.addWidget(botoes)

    def _validar(self) -> None:
        if repo.autenticar(self.conn, self.usuario.login, self.senha_atual.text()) is None:
            self._mostrar_erro("Senha atual incorreta.")
            return
        if len(self.senha_nova.text()) < 4:
            self._mostrar_erro("A nova senha precisa ter pelo menos 4 caracteres.")
            return
        if self.senha_nova.text() != self.confirmar.text():
            self._mostrar_erro("As senhas não conferem.")
            return
        repo.alterar_senha(self.conn, self.usuario.id, self.senha_nova.text())
        self.accept()

    def _mostrar_erro(self, texto: str) -> None:
        self.erro.setText(texto)
        self.erro.show()
