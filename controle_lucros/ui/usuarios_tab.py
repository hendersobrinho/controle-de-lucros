"""Cadastro de usuários — só para administradores. Contas nunca são
excluídas de verdade, só desativadas, pra não perder o histórico de quem fez
o quê no log de atividade."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import repositories as repo
from .. import sessao
from . import theme


class _DialogoNovaSenha(QDialog):
    def __init__(self, nome_usuario: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Redefinir senha — {nome_usuario}")
        self.setMinimumWidth(340)

        self.senha = QLineEdit()
        self.senha.setEchoMode(QLineEdit.Password)
        self.confirmar = QLineEdit()
        self.confirmar.setEchoMode(QLineEdit.Password)

        form = QFormLayout()
        form.addRow("Nova senha", self.senha)
        form.addRow("Confirmar", self.confirmar)

        self.erro = QLabel("")
        self.erro.setStyleSheet(f"color: {theme.SEAL_RED()}; font-size: 11px;")
        self.erro.hide()

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.accepted.connect(self._validar)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.erro)
        layout.addWidget(botoes)

    def _validar(self) -> None:
        if len(self.senha.text()) < 4:
            self.erro.setText("A senha precisa ter pelo menos 4 caracteres.")
            self.erro.show()
            return
        if self.senha.text() != self.confirmar.text():
            self.erro.setText("As senhas não conferem.")
            self.erro.show()
            return
        self.accept()


class _DialogoCriarUsuario(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Novo usuário")
        self.setMinimumWidth(360)

        self.nome = QLineEdit()
        self.login = QLineEdit()
        self.senha = QLineEdit()
        self.senha.setEchoMode(QLineEdit.Password)
        self.confirmar = QLineEdit()
        self.confirmar.setEchoMode(QLineEdit.Password)
        self.admin = QCheckBox("Administrador")

        form = QFormLayout()
        form.addRow("Nome", self.nome)
        form.addRow("Login", self.login)
        form.addRow("Senha", self.senha)
        form.addRow("Confirmar senha", self.confirmar)
        form.addRow("", self.admin)

        self.erro = QLabel("")
        self.erro.setStyleSheet(f"color: {theme.SEAL_RED()}; font-size: 11px;")
        self.erro.setWordWrap(True)
        self.erro.hide()

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.button(QDialogButtonBox.Ok).setText("Criar")
        botoes.accepted.connect(self._validar)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.erro)
        layout.addWidget(botoes)

    def _validar(self) -> None:
        if not self.nome.text().strip() or not self.login.text().strip():
            self.erro.setText("Preencha nome e login.")
            self.erro.show()
            return
        if len(self.senha.text()) < 4:
            self.erro.setText("A senha precisa ter pelo menos 4 caracteres.")
            self.erro.show()
            return
        if self.senha.text() != self.confirmar.text():
            self.erro.setText("As senhas não conferem.")
            self.erro.show()
            return
        self.accept()


class UsuariosTab(QWidget):
    COLUNAS = ["Nome", "Login", "Nível", "Situação"]

    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._usuarios = []
        self._usuario_atual_id: int | None = None

        self.tabela = QTableWidget(0, len(self.COLUNAS))
        self.tabela.setHorizontalHeaderLabels(self.COLUNAS)
        self.tabela.setAlternatingRowColors(True)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela.verticalHeader().setVisible(False)
        self.tabela.itemSelectionChanged.connect(self._ao_selecionar)

        self.nome = QLineEdit()
        self.login_campo = QLineEdit()
        self.admin = QCheckBox("Administrador")

        form = QFormLayout()
        form.addRow("Nome", self.nome)
        form.addRow("Login", self.login_campo)
        form.addRow("", self.admin)

        self.btn_novo = QPushButton("Novo usuário")
        self.btn_novo.setProperty("role", "primario")
        self.btn_novo.clicked.connect(self._novo_usuario)

        self.btn_salvar = QPushButton("Salvar dados")
        self.btn_salvar.clicked.connect(self._salvar)

        self.btn_redefinir_senha = QPushButton("Redefinir senha")
        self.btn_redefinir_senha.clicked.connect(self._redefinir_senha)

        self.btn_alternar_ativo = QPushButton("Desativar")
        self.btn_alternar_ativo.setProperty("role", "perigo")
        self.btn_alternar_ativo.clicked.connect(self._alternar_ativo)

        botoes = QHBoxLayout()
        botoes.addWidget(self.btn_novo)
        botoes.addWidget(self.btn_salvar)
        botoes.addWidget(self.btn_redefinir_senha)
        botoes.addWidget(self.btn_alternar_ativo)
        botoes.addStretch()

        form_container = QVBoxLayout()
        form_container.addLayout(form)
        form_container.addLayout(botoes)
        form_container.addStretch()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)
        layout.addWidget(self.tabela, 2)
        layout.addLayout(form_container, 1)

        self._atualizar_disponibilidade()
        self.atualizar()

    def atualizar(self) -> None:
        self._usuarios = repo.listar_usuarios(self.conn)
        self.tabela.setRowCount(len(self._usuarios))
        for row, u in enumerate(self._usuarios):
            valores = [u.nome, u.login, "Administrador" if u.admin else "Usuário", "Ativo" if u.ativo else "Desativado"]
            for col, valor in enumerate(valores):
                self.tabela.setItem(row, col, QTableWidgetItem(valor))
        self.tabela.resizeColumnsToContents()

    def _ao_selecionar(self) -> None:
        linhas = self.tabela.selectionModel().selectedRows()
        if not linhas:
            return
        usuario = self._usuarios[linhas[0].row()]
        self._usuario_atual_id = usuario.id
        self.nome.setText(usuario.nome)
        self.login_campo.setText(usuario.login)
        self.admin.setChecked(usuario.admin)
        self.btn_alternar_ativo.setText("Desativar" if usuario.ativo else "Ativar")
        self._atualizar_disponibilidade()

    def _novo_usuario(self) -> None:
        dialogo = _DialogoCriarUsuario(self)
        if dialogo.exec() != QDialog.Accepted:
            return
        try:
            repo.criar_usuario(
                self.conn,
                dialogo.nome.text().strip(),
                dialogo.login.text().strip(),
                dialogo.senha.text(),
                admin=dialogo.admin.isChecked(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao criar usuário", str(exc))
            return
        self.atualizar()

    def _salvar(self) -> None:
        if self._usuario_atual_id is None:
            return
        nome = self.nome.text().strip()
        login = self.login_campo.text().strip()
        if not nome or not login:
            QMessageBox.warning(self, "Erro ao salvar", "Preencha nome e login.")
            return
        try:
            repo.atualizar_usuario(self.conn, self._usuario_atual_id, nome, login, self.admin.isChecked())
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao salvar", str(exc))
            return
        self.atualizar()

    def _redefinir_senha(self) -> None:
        if self._usuario_atual_id is None:
            return
        usuario = next(u for u in self._usuarios if u.id == self._usuario_atual_id)
        dialogo = _DialogoNovaSenha(usuario.nome, self)
        if dialogo.exec() != QDialog.Accepted:
            return
        repo.alterar_senha(self.conn, self._usuario_atual_id, dialogo.senha.text())
        QMessageBox.information(self, "Senha redefinida", f"Senha de {usuario.nome} atualizada.")

    def _alternar_ativo(self) -> None:
        if self._usuario_atual_id is None:
            return
        usuario = next(u for u in self._usuarios if u.id == self._usuario_atual_id)
        if usuario.id == (sessao.usuario_atual().id if sessao.usuario_atual() else None):
            QMessageBox.warning(self, "Não permitido", "Você não pode desativar a própria conta.")
            return
        repo.definir_ativo(self.conn, usuario.id, not usuario.ativo)
        self.atualizar()

    def _atualizar_disponibilidade(self) -> None:
        tem_selecao = self._usuario_atual_id is not None
        self.btn_salvar.setEnabled(tem_selecao)
        self.btn_redefinir_senha.setEnabled(tem_selecao)
        self.btn_alternar_ativo.setEnabled(tem_selecao)
