"""Diálogos de entrada no sistema: criação do primeiro usuário (quando o
banco está vazio) e o login normal do dia a dia."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
)

from .. import preferencias, repositories as repo
from ..models import Usuario
from . import theme


class DialogoPrimeiroUsuario(QDialog):
    """Só aparece quando ainda não existe nenhum usuário cadastrado — cria a
    primeira conta, que já nasce administradora."""

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.setWindowTitle("Bem-vindo — crie o primeiro usuário")
        self.setMinimumWidth(380)
        self.setModal(True)

        titulo = QLabel("Nenhum usuário cadastrado ainda")
        titulo.setProperty("role", "titulo")
        subtitulo = QLabel("Crie a primeira conta — ela será a administradora do sistema.")
        subtitulo.setProperty("role", "subtitulo")
        subtitulo.setWordWrap(True)

        self.nome = QLineEdit()
        self.login = QLineEdit()
        self.senha = QLineEdit()
        self.senha.setEchoMode(QLineEdit.Password)
        self.confirmar = QLineEdit()
        self.confirmar.setEchoMode(QLineEdit.Password)

        form = QFormLayout()
        form.addRow("Nome", self.nome)
        form.addRow("Login", self.login)
        form.addRow("Senha", self.senha)
        form.addRow("Confirmar senha", self.confirmar)

        self.erro = QLabel("")
        self.erro.setStyleSheet(f"color: {theme.SEAL_RED()}; font-size: 11px;")
        self.erro.setWordWrap(True)
        self.erro.hide()

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.button(QDialogButtonBox.Ok).setText("Criar conta")
        botoes.accepted.connect(self._criar)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(titulo)
        layout.addWidget(subtitulo)
        layout.addSpacing(8)
        layout.addLayout(form)
        layout.addWidget(self.erro)
        layout.addWidget(botoes)

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
        self.setMinimumWidth(340)
        self.setModal(True)

        titulo = QLabel("Controle de Distribuição de Lucros")
        titulo.setProperty("role", "titulo")
        subtitulo = QLabel("Entre com seu usuário e senha.")
        subtitulo.setProperty("role", "subtitulo")

        self.login = QLineEdit()
        self.login.setPlaceholderText("login")
        self.senha = QLineEdit()
        self.senha.setPlaceholderText("senha")
        self.senha.setEchoMode(QLineEdit.Password)
        self.senha.returnPressed.connect(self._entrar)

        # Desmarcado por padrão de propósito: o log de atividades atribui cada
        # ação a quem está logado, e entrar direto num computador compartilhado
        # faria o trabalho de um sair no nome do outro. Quem marca está dizendo
        # que aquela máquina é dele.
        self.continuar_conectado = QCheckBox("Continuar conectado neste computador")
        self.continuar_conectado.setToolTip(
            f"Só marque se este computador for de uso pessoal. Vale por "
            f"{repo.DIAS_SESSAO_SALVA} dias, e sair do sistema encerra."
        )

        form = QFormLayout()
        form.addRow("Login", self.login)
        form.addRow("Senha", self.senha)
        form.addRow("", self.continuar_conectado)

        self.erro = QLabel("")
        self.erro.setStyleSheet(f"color: {theme.SEAL_RED()}; font-size: 11px;")
        self.erro.hide()

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.button(QDialogButtonBox.Ok).setText("Entrar")
        botoes.accepted.connect(self._entrar)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(titulo)
        layout.addWidget(subtitulo)
        layout.addSpacing(8)
        layout.addLayout(form)
        layout.addWidget(self.erro)
        layout.addWidget(botoes)

        # Com o login já preenchido, o cursor vai direto pra senha.
        self.login.setText(preferencias.ultimo_login())
        if self.login.text():
            self.senha.setFocus()
        else:
            self.login.setFocus()

    def _entrar(self) -> None:
        usuario = repo.autenticar(self.conn, self.login.text(), self.senha.text())
        if usuario is None:
            self.erro.setText("Login ou senha incorretos, ou usuário desativado.")
            self.erro.show()
            self.senha.clear()
            self.senha.setFocus()
            return

        preferencias.guardar_ultimo_login(usuario.login)
        if self.continuar_conectado.isChecked():
            preferencias.guardar_sessao(usuario.id, repo.salvar_sessao(self.conn, usuario.id))
        else:
            # Desmarcar e entrar tem que apagar uma sessão anterior, senão a
            # opção só ligaria e nunca desligaria.
            repo.esquecer_sessao(self.conn, usuario.id)
            preferencias.esquecer_sessao()

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
