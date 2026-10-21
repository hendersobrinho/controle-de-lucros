"""Diálogos de entrada no sistema: criação do primeiro usuário (quando o
banco está vazio) e o login normal do dia a dia."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from .. import preferencias, repositories as repo
from ..models import Usuario
from . import theme
from .conectar_claude import DialogoConectarClaude
from .local_banco import DialogoConexao
from .marca import TelaDeEntrada, aviso_de_entrada, botao_link, campo_de_entrada, mostrar_aviso

# Login (só o nome de usuário) guardado nas preferências deste PC. A senha
# nunca é guardada.
CHAVE_LOGIN_LEMBRADO = "login_lembrado"
# "Entrar sem pedir a senha": uma chave aleatória deste PC, conferida no
# banco (repo.usuario_do_acesso_lembrado). Clicar em Sair a apaga.
CHAVE_ACESSO_LEMBRADO = "acesso_lembrado"


def entrar_sem_senha(conn) -> Usuario | None:
    """O usuário deste PC, se ele marcou "entrar sem pedir a senha" e a
    chave ainda vale (não trocou a senha nem foi desativado)."""
    chave = str(preferencias.obter(CHAVE_ACESSO_LEMBRADO) or "")
    usuario = repo.usuario_do_acesso_lembrado(conn, chave) if chave else None
    if chave and usuario is None:
        preferencias.salvar_chave(CHAVE_ACESSO_LEMBRADO, "")
    return usuario


def esquecer_acesso(conn) -> None:
    """Sair da conta: este PC volta a pedir a senha na próxima vez."""
    chave = str(preferencias.obter(CHAVE_ACESSO_LEMBRADO) or "")
    preferencias.salvar_chave(CHAVE_ACESSO_LEMBRADO, "")
    try:
        repo.esquecer_acesso_lembrado(conn, chave)
    except Exception:  # noqa: BLE001 — sem banco, a chave local já foi apagada
        pass


def _botao_claude(parent) -> QPushButton:
    """Logo na entrada, para dar para ligar o Claude antes mesmo de entrar —
    ele usa a conexão deste PC com o banco, não a conta de quem está aqui."""
    botao = botao_link("Conectar ao Claude")
    botao.setToolTip("Deixa o Claude consultar o sistema (só leitura).")
    botao.clicked.connect(lambda: DialogoConectarClaude(parent).exec())
    return botao


def _rodape(*botoes: QPushButton) -> QHBoxLayout:
    rodape = QHBoxLayout()
    rodape.setSpacing(4)
    for i, botao in enumerate(botoes):
        if i:
            ponto = QLabel("·")
            ponto.setProperty("role", "entradaSubtitulo")
            rodape.addWidget(ponto)
        rodape.addWidget(botao)
    rodape.addStretch()
    return rodape


class DialogoPrimeiroUsuario(TelaDeEntrada):
    """Só aparece quando ainda não existe nenhum usuário cadastrado — cria a
    primeira conta, que já nasce administradora.

    Num escritório que já usa o sistema, cair aqui quer dizer que este PC
    está conectado no banco errado (vazio): por isso oferece trocar a
    conexão, pro banco onde os usuários já existem. Trocada, o diálogo fecha
    com trocou_banco e quem chamou reconecta."""

    def __init__(self, conn, parent=None):
        super().__init__(
            "Primeiro acesso",
            "Tudo pronto para começar.",
            "O banco de dados está conectado e vazio. Crie a primeira conta — ela será a "
            "administradora e poderá cadastrar as outras pessoas do escritório.",
            parent,
            altura=640,
        )
        self.conn = conn
        self.trocou_banco = False

        self.cabecalho("Seja bem-vindo", "Crie sua conta para entrar no Controle de Lucros.")
        rotulo_nome, self.nome = campo_de_entrada("Seu nome", "nome completo")
        rotulo_login, self.login = campo_de_entrada("Login", "como você vai entrar")
        rotulo_senha, self.senha = campo_de_entrada("Senha", "pelo menos 4 caracteres", senha=True)
        rotulo_conf, self.confirmar = campo_de_entrada("Confirme a senha", "repita a senha", senha=True)
        self.confirmar.returnPressed.connect(self._criar)
        self.erro = aviso_de_entrada()

        for rotulo, campo in ((rotulo_nome, self.nome), (rotulo_login, self.login)):
            self.corpo.addWidget(rotulo)
            self.corpo.addWidget(campo)
            self.corpo.addSpacing(14)
        senhas = QHBoxLayout()
        senhas.setSpacing(12)
        for rotulo, campo in ((rotulo_senha, self.senha), (rotulo_conf, self.confirmar)):
            coluna = QVBoxLayout()
            coluna.setSpacing(0)
            coluna.addWidget(rotulo)
            coluna.addWidget(campo)
            senhas.addLayout(coluna)
        self.corpo.addLayout(senhas)
        self.corpo.addSpacing(16)
        self.corpo.addWidget(self.erro)
        self.corpo.addSpacing(10)

        criar = QPushButton("Criar conta e entrar")
        criar.setProperty("role", "entradaPrincipal")
        criar.setCursor(Qt.PointingHandCursor)
        criar.clicked.connect(self._criar)
        self.corpo.addWidget(criar)
        self.corpo.addStretch()

        usar_servidor = botao_link("Usar outro banco de dados")
        usar_servidor.setToolTip("Este PC deveria estar no banco do escritório, onde as contas já existem?")
        usar_servidor.clicked.connect(self._usar_banco_do_servidor)
        sair = botao_link("Sair")
        sair.clicked.connect(self.reject)
        self.corpo.addLayout(_rodape(usar_servidor, _botao_claude(self), sair))

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
        mostrar_aviso(self.erro, texto)


class DialogoLogin(TelaDeEntrada):
    def __init__(self, conn, parent=None):
        super().__init__(
            "Entrar",
            "Os lucros do escritório, em ordem.",
            "Quem é sócio de quê, quanto cada um recebeu e o que vai no informe — num lugar só, "
            "o mesmo para todos os computadores do escritório.",
            parent,
        )
        self.conn = conn
        self.usuario_autenticado: Usuario | None = None

        lembrado = str(preferencias.obter(CHAVE_LOGIN_LEMBRADO) or "")
        self.cabecalho("Seja bem-vindo",
                       "Bom te ver de novo. Digite sua senha para continuar." if lembrado
                       else "Entre com seu login e senha.")

        rotulo_login, self.login = campo_de_entrada("Login", "seu login")
        rotulo_senha, self.senha = campo_de_entrada("Senha", "sua senha", senha=True)
        self.login.returnPressed.connect(lambda: self.senha.setFocus())
        self.senha.returnPressed.connect(self._entrar)
        self.erro = aviso_de_entrada()

        self.lembrar = QCheckBox("Lembrar meu login neste computador")
        self.lembrar.setToolTip("Guarda só o login; a senha continua sendo pedida.")
        if lembrado:
            self.login.setText(lembrado)
            self.lembrar.setChecked(True)
        self.entrar_direto = QCheckBox("Entrar direto, sem pedir a senha")
        self.entrar_direto.setToolTip(
            "Nas próximas vezes o programa abre já na sua conta, neste computador.\n"
            "A senha não fica guardada. Para voltar a pedir a senha, use Sair dentro do programa.\n"
            "Não marque em computador que outras pessoas usam."
        )
        # Entrar direto implica lembrar o login; desmarcar lembrar desmarca o outro.
        self.entrar_direto.toggled.connect(lambda marcado: marcado and self.lembrar.setChecked(True))
        self.lembrar.toggled.connect(lambda marcado: marcado or self.entrar_direto.setChecked(False))

        entrar = QPushButton("Entrar")
        entrar.setProperty("role", "entradaPrincipal")
        entrar.setCursor(Qt.PointingHandCursor)
        entrar.clicked.connect(self._entrar)

        self.corpo.addWidget(rotulo_login)
        self.corpo.addWidget(self.login)
        self.corpo.addSpacing(16)
        self.corpo.addWidget(rotulo_senha)
        self.corpo.addWidget(self.senha)
        self.corpo.addSpacing(14)
        self.corpo.addWidget(self.lembrar)
        self.corpo.addSpacing(6)
        self.corpo.addWidget(self.entrar_direto)
        self.corpo.addSpacing(16)
        self.corpo.addWidget(self.erro)
        self.corpo.addSpacing(10)
        self.corpo.addWidget(entrar)
        self.corpo.addStretch()

        sair = botao_link("Sair")
        sair.clicked.connect(self.reject)
        self.corpo.addLayout(_rodape(_botao_claude(self), sair))

        # Com o login lembrado, quem abre o programa só digita a senha.
        (self.senha if lembrado else self.login).setFocus()

    def _entrar(self) -> None:
        usuario = repo.autenticar(self.conn, self.login.text(), self.senha.text())
        if usuario is None:
            mostrar_aviso(self.erro, repo.motivo_login_recusado(self.conn, self.login.text()))
            self.senha.clear()
            self.senha.setFocus()
            return
        # Só depois de entrar: lembrar um login digitado errado preencheria a
        # próxima abertura com algo que não funciona.
        preferencias.salvar_chave(CHAVE_LOGIN_LEMBRADO, usuario.login if self.lembrar.isChecked() else "")
        if self.entrar_direto.isChecked():
            preferencias.salvar_chave(CHAVE_ACESSO_LEMBRADO, repo.criar_acesso_lembrado(self.conn, usuario.id))
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
