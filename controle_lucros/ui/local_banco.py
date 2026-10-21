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
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .. import db
from . import theme
from .marca import TelaDeEntrada, aviso_de_entrada, botao_link, campo_de_entrada, mostrar_aviso
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


def _coluna(rotulo: QLabel, campo: QWidget) -> QVBoxLayout:
    coluna = QVBoxLayout()
    coluna.setSpacing(0)
    coluna.addWidget(rotulo)
    coluna.addWidget(campo)
    return coluna


class DialogoConexao(TelaDeEntrada):
    """Os dados de acesso ao PostgreSQL do escritório. Aparece na primeira
    abertura do programa neste PC, e depois sempre que alguém quiser trocar
    (servidor novo, senha trocada).

    Roda como o usuário do Windows, não como administrador — é por isso que
    a configuração não fica no instalador."""

    def __init__(self, parent=None, primeira_vez: bool = False):
        super().__init__(
            "Conexão com o banco de dados",
            "Vamos conectar ao banco do escritório." if primeira_vez else "Onde está o banco de dados.",
            "Todos os computadores usam o mesmo banco, num servidor PostgreSQL — é assim que o "
            "escritório inteiro vê o mesmo cadastro."
            + (" Isto só é perguntado uma vez neste computador." if primeira_vez else ""),
            parent,
            altura=640,
        )
        atual = db.conexao_configurada() or db.ParametrosConexao(servidor="")
        self.cabecalho("Conexão com o banco",
                       "Peça estes dados a quem instalou o PostgreSQL no servidor.")

        rotulo_servidor, self.servidor = campo_de_entrada("Servidor", "nome ou IP, ex.: 192.168.0.10")
        self.servidor.setText(atual.servidor)
        rotulo_porta = QLabel("Porta")
        rotulo_porta.setProperty("role", "entradaRotulo")
        self.porta = QSpinBox()
        self.porta.setProperty("role", "entrada")
        self.porta.setRange(1, 65535)
        self.porta.setValue(atual.porta)
        self.porta.setButtonSymbols(QSpinBox.NoButtons)
        self.porta.setFixedWidth(96)
        rotulo_banco, self.banco = campo_de_entrada("Banco", "nome do banco")
        self.banco.setText(atual.banco)
        rotulo_usuario, self.usuario = campo_de_entrada("Usuário", "usuário do PostgreSQL")
        self.usuario.setText(atual.usuario)
        rotulo_senha, self.senha = campo_de_entrada("Senha", "senha do PostgreSQL", senha=True)
        self.senha.setText(atual.senha)
        self.senha.returnPressed.connect(self._salvar)
        self.resultado = aviso_de_entrada()

        linha = QHBoxLayout()
        linha.setSpacing(12)
        linha.addLayout(_coluna(rotulo_servidor, self.servidor), 1)
        linha.addLayout(_coluna(rotulo_porta, self.porta))
        self.corpo.addLayout(linha)
        self.corpo.addSpacing(14)
        self.corpo.addLayout(_coluna(rotulo_banco, self.banco))
        self.corpo.addSpacing(14)
        linha = QHBoxLayout()
        linha.setSpacing(12)
        linha.addLayout(_coluna(rotulo_usuario, self.usuario), 1)
        linha.addLayout(_coluna(rotulo_senha, self.senha), 1)
        self.corpo.addLayout(linha)
        self.corpo.addSpacing(16)
        self.corpo.addWidget(self.resultado)
        self.corpo.addSpacing(10)

        testar = QPushButton("Testar conexão")
        testar.setProperty("role", "entradaSecundario")
        testar.setCursor(Qt.PointingHandCursor)
        testar.clicked.connect(self._testar)
        salvar = QPushButton("Salvar e continuar" if primeira_vez else "Salvar")
        salvar.setProperty("role", "entradaPrincipal")
        salvar.setCursor(Qt.PointingHandCursor)
        salvar.setDefault(True)
        salvar.clicked.connect(self._salvar)
        botoes = QHBoxLayout()
        botoes.setSpacing(10)
        botoes.addWidget(testar)
        botoes.addWidget(salvar, 1)
        self.corpo.addLayout(botoes)
        self.corpo.addStretch()

        tutorial = botao_link("Como preparar o servidor PostgreSQL?")
        tutorial.clicked.connect(lambda: abrir_tutorial_do_servidor(self))
        cancelar = botao_link("Sair" if primeira_vez else "Cancelar")
        cancelar.clicked.connect(self.reject)
        rodape = QHBoxLayout()
        rodape.addWidget(tutorial)
        rodape.addStretch()
        rodape.addWidget(cancelar)
        self.corpo.addLayout(rodape)

        for campo in (self.servidor, self.banco, self.usuario, self.senha):
            campo.textEdited.connect(lambda _texto: self.resultado.hide())
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
        """O resultado do teste fica escrito no próprio formulário, em vez de
        numa janela que some: dá para corrigir o campo olhando o erro."""
        erro = self._tentar()
        if erro:
            mostrar_aviso(self.resultado, erro, "erro")
        else:
            mostrar_aviso(self.resultado, f"✓  Conexão funcionando — PostgreSQL {self._versao} no servidor.", "ok")

    def _salvar(self) -> None:
        erro = self._tentar()
        if erro:
            if self._faltando():
                QMessageBox.warning(self, "Faltam dados", erro)
                return
            mostrar_aviso(self.resultado, erro, "erro")
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


class DialogoBancoInacessivel(TelaDeEntrada):
    """Aparece antes do login quando o banco não abre — no dia a dia, é o
    servidor fora do ar ou este PC fora da rede. Sem isto o programa fecharia
    com um erro técnico, e a única saída seria chamar alguém."""

    TENTAR_DE_NOVO = 1
    OUTRA_CONEXAO = 2

    def __init__(self, erro: BaseException, parent=None):
        super().__init__(
            "Banco de dados indisponível",
            "O servidor não respondeu.",
            "Quase sempre é o servidor reiniciando ou este computador fora da rede. Os dados "
            "estão seguros no servidor — é só a conexão que não abriu agora.",
            parent,
        )
        self.cabecalho("Não consegui conectar", "O que o servidor respondeu:")

        explicacao = aviso_de_entrada()
        mostrar_aviso(explicacao, db.explicar_erro(erro), "erro")
        explicacao.setTextInteractionFlags(Qt.TextSelectableByMouse)

        rotulo = QLabel("Conexão deste computador")
        rotulo.setProperty("role", "entradaRotulo")
        conexao = QLabel(descrever_conexao())
        conexao.setProperty("role", "entradaAviso")
        conexao.setProperty("tom", "info")
        conexao.setWordWrap(True)
        conexao.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.corpo.addWidget(explicacao)
        self.corpo.addSpacing(18)
        self.corpo.addWidget(rotulo)
        self.corpo.addWidget(conexao)
        self.corpo.addSpacing(22)

        outra = QPushButton("Alterar a conexão…")
        outra.setProperty("role", "entradaSecundario")
        outra.setCursor(Qt.PointingHandCursor)
        outra.clicked.connect(self._alterar_conexao)
        tentar = QPushButton("Tentar de novo")
        tentar.setProperty("role", "entradaPrincipal")
        tentar.setCursor(Qt.PointingHandCursor)
        tentar.setDefault(True)
        tentar.clicked.connect(lambda: self.done(self.TENTAR_DE_NOVO))
        botoes = QHBoxLayout()
        botoes.setSpacing(10)
        botoes.addWidget(outra)
        botoes.addWidget(tentar, 1)
        self.corpo.addLayout(botoes)
        self.corpo.addStretch()

        tutorial = botao_link("Como preparar o servidor PostgreSQL?")
        tutorial.clicked.connect(lambda: abrir_tutorial_do_servidor(self))
        sair = botao_link("Sair")
        sair.clicked.connect(self.reject)
        rodape = QHBoxLayout()
        rodape.addWidget(tutorial)
        rodape.addStretch()
        rodape.addWidget(sair)
        self.corpo.addLayout(rodape)
        tentar.setFocus()

    def _alterar_conexao(self) -> None:
        if DialogoConexao(self).exec() == QDialog.Accepted:
            self.done(self.OUTRA_CONEXAO)
