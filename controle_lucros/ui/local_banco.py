"""Onde fica o banco: em que servidor PostgreSQL este PC se conecta.

Cada PC tem o programa instalado e conecta no mesmo PostgreSQL — é assim que
o escritório inteiro vê o mesmo cadastro, com os mesmos usuários. Os dados
da conexão ficam na configuração local de cada PC (ver db.definir_conexao).

Trocar a conexão só vale na próxima abertura, então quem chama cuida de
reconectar (tela de entrada) ou de fechar o programa (tela de Backup)."""
from __future__ import annotations

import psycopg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from .. import db
from . import theme
from .ocupado import ocupado


def descrever_conexao() -> str:
    parametros = db.conexao_configurada()
    return parametros.descricao() if parametros else "Nenhum servidor configurado neste computador."


def abrir_tutorial_do_servidor(parent=None) -> None:
    """O passo a passo de instalar e liberar o PostgreSQL no servidor, que
    fica no manual (tópico "Servidor PostgreSQL")."""
    from .manual import DialogoManual

    DialogoManual("sistema.servidor", parent).exec()


def botao_tutorial(parent=None) -> QPushButton:
    botao = QPushButton("Como preparar o servidor PostgreSQL?")
    botao.setFlat(True)
    botao.setCursor(Qt.PointingHandCursor)
    botao.setStyleSheet(
        f"QPushButton {{ border: none; background: transparent; color: {theme.BRASS_DARK()};"
        f" text-decoration: underline; padding: 2px 0; text-align: left; }}"
    )
    botao.clicked.connect(lambda: abrir_tutorial_do_servidor(parent))
    return botao


class DialogoConexao(QDialog):
    """Os dados de acesso ao PostgreSQL do escritório. Aparece na primeira
    abertura do programa neste PC, e depois sempre que alguém quiser trocar
    (servidor novo, senha trocada).

    Roda como o usuário do Windows, não como administrador — é por isso que
    a configuração não fica no instalador."""

    def __init__(self, parent=None, primeira_vez: bool = False):
        super().__init__(parent)
        self.setWindowTitle("Conexão com o banco de dados")
        self.setMinimumWidth(480)

        atual = db.conexao_configurada() or db.ParametrosConexao(servidor="")

        titulo = QLabel("Em que servidor está o banco de dados?")
        titulo.setProperty("role", "secao")

        explicacao = QLabel(
            "O banco do escritório fica num servidor PostgreSQL, e todos os computadores se "
            "conectam nele. Peça estes dados a quem instalou o PostgreSQL."
            + (" Isto só é perguntado uma vez neste computador." if primeira_vez else "")
        )
        explicacao.setWordWrap(True)
        explicacao.setProperty("role", "subtitulo")

        self.servidor = QLineEdit(atual.servidor)
        self.servidor.setPlaceholderText("nome ou IP, ex.: 192.168.0.10")
        self.porta = QSpinBox()
        self.porta.setRange(1, 65535)
        self.porta.setValue(atual.porta)
        self.banco = QLineEdit(atual.banco)
        self.usuario = QLineEdit(atual.usuario)
        self.senha = QLineEdit(atual.senha)
        self.senha.setEchoMode(QLineEdit.Password)

        formulario = QFormLayout()
        formulario.addRow("Servidor:", self.servidor)
        formulario.addRow("Porta:", self.porta)
        formulario.addRow("Banco:", self.banco)
        formulario.addRow("Usuário:", self.usuario)
        formulario.addRow("Senha:", self.senha)

        testar = QPushButton("Testar conexão")
        testar.clicked.connect(self._testar)

        salvar = QPushButton("Salvar")
        salvar.setProperty("role", "primario")
        salvar.setDefault(True)
        salvar.clicked.connect(self._salvar)

        cancelar = QPushButton("Sair" if primeira_vez else "Cancelar")
        cancelar.clicked.connect(self.reject)

        botoes = QHBoxLayout()
        botoes.addWidget(testar)
        botoes.addStretch()
        botoes.addWidget(cancelar)
        botoes.addWidget(salvar)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(titulo)
        layout.addWidget(explicacao)
        layout.addLayout(formulario)
        layout.addWidget(botao_tutorial(self))
        layout.addSpacing(6)
        layout.addLayout(botoes)

        (self.servidor if not atual.servidor else self.senha).setFocus()

    def parametros(self) -> db.ParametrosConexao:
        return db.ParametrosConexao(
            servidor=self.servidor.text().strip(),
            porta=self.porta.value(),
            banco=self.banco.text().strip(),
            usuario=self.usuario.text().strip(),
            senha=self.senha.text(),
        )

    def _faltando(self) -> str | None:
        parametros = self.parametros()
        for nome, valor in (("o servidor", parametros.servidor), ("o banco", parametros.banco),
                            ("o usuário", parametros.usuario)):
            if not valor:
                return nome
        return None

    def _tentar(self) -> str | None:
        """Testa a conexão; devolve o erro explicado, ou None se conectou."""
        faltando = self._faltando()
        if faltando:
            return f"Preencha {faltando}."
        try:
            with ocupado(self, "Banco de dados", "Conectando ao servidor…"):
                self._versao = db.testar_conexao(self.parametros())
        except psycopg.Error as erro:
            return db.explicar_erro(erro)
        return None

    def _testar(self) -> None:
        erro = self._tentar()
        if erro:
            QMessageBox.warning(self, "Não conectou", erro)
        else:
            QMessageBox.information(
                self, "Conectou", f"Conexão funcionando. PostgreSQL {self._versao} no servidor."
            )

    def _salvar(self) -> None:
        erro = self._tentar()
        if erro:
            if self._faltando():
                QMessageBox.warning(self, "Faltam dados", erro)
                return
            resposta = QMessageBox.question(
                self,
                "Não conectou",
                f"{erro}\n\nSalvar esses dados assim mesmo?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if resposta != QMessageBox.Yes:
                return
        db.definir_conexao(self.parametros())
        self.accept()


class DialogoBancoInacessivel(QDialog):
    """Aparece antes do login quando o banco não abre — no dia a dia, é o
    servidor fora do ar ou este PC fora da rede. Sem isto o programa fecharia
    com um erro técnico, e a única saída seria chamar alguém."""

    TENTAR_DE_NOVO = 1
    OUTRA_CONEXAO = 2

    def __init__(self, erro: BaseException, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Banco de dados indisponível")
        self.setMinimumWidth(460)

        titulo = QLabel("Não consegui conectar no banco de dados")
        titulo.setProperty("role", "secao")

        explicacao = QLabel(db.explicar_erro(erro))
        explicacao.setWordWrap(True)
        explicacao.setTextInteractionFlags(Qt.TextSelectableByMouse)

        conexao = QLabel(descrever_conexao())
        conexao.setProperty("role", "mono")
        conexao.setWordWrap(True)
        conexao.setTextInteractionFlags(Qt.TextSelectableByMouse)

        tentar = QPushButton("Tentar de novo")
        tentar.setProperty("role", "primario")
        tentar.setDefault(True)
        tentar.clicked.connect(lambda: self.done(self.TENTAR_DE_NOVO))

        outra = QPushButton("Alterar a conexão…")
        outra.clicked.connect(self._alterar_conexao)

        sair = QPushButton("Sair")
        sair.clicked.connect(self.reject)

        botoes = QHBoxLayout()
        botoes.addWidget(outra)
        botoes.addStretch()
        botoes.addWidget(sair)
        botoes.addWidget(tentar)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(titulo)
        layout.addWidget(explicacao)
        layout.addWidget(conexao)
        layout.addWidget(botao_tutorial(self))
        layout.addSpacing(6)
        layout.addLayout(botoes)

    def _alterar_conexao(self) -> None:
        if DialogoConexao(self).exec() == QDialog.Accepted:
            self.done(self.OUTRA_CONEXAO)
