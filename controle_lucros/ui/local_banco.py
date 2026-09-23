"""Onde fica o banco: neste computador ou numa pasta do servidor.

Com o banco no servidor, cada PC tem o programa instalado e aponta pro
mesmo arquivo lá — é assim que o escritório inteiro vê o mesmo cadastro, com
os mesmos usuários, sem o programa rodar no servidor. O caminho escolhido é
guardado na configuração local de cada PC (ver db.definir_banco).

Trocar de banco só vale na próxima conexão, então quem chama cuida de
reconectar (tela de entrada) ou de fechar o programa (tela de Backup)."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .. import db
from . import theme
from .ocupado import ocupado


def descrever_local(caminho: Path) -> str:
    if db.banco_em_rede(caminho):
        return "Na rede — compartilhado com os outros computadores que apontam para este arquivo."
    return "Neste computador — só quem usa esta máquina enxerga estes dados."


def abrir_tutorial_do_caminho(parent=None) -> None:
    """O passo a passo de compartilhar a pasta e montar o \\\\SERVIDOR\\pasta,
    que fica no manual (tópico "Caminho do servidor")."""
    from .manual import DialogoManual

    DialogoManual("sistema.servidor", parent).exec()


def botao_tutorial(parent=None) -> QPushButton:
    botao = QPushButton("Como configurar o caminho do servidor?")
    botao.setFlat(True)
    botao.setCursor(Qt.PointingHandCursor)
    botao.setStyleSheet(
        f"QPushButton {{ border: none; background: transparent; color: {theme.BRASS_DARK()};"
        f" text-decoration: underline; padding: 2px 0; text-align: left; }}"
    )
    botao.clicked.connect(lambda: abrir_tutorial_do_caminho(parent))
    return botao


def _perguntar_pasta(parent, titulo: str) -> Path | None:
    pasta = QFileDialog.getExistingDirectory(
        parent, f"{titulo} — cole o caminho (\\\\SERVIDOR\\pasta) na barra de endereço",
        str(db.get_db_path().parent),
    )
    return db.caminho_de_rede(Path(pasta)) if pasta else None


def _usar_se_for_banco(caminho: Path, parent) -> Path | None:
    if not db.e_banco_do_sistema(caminho):
        QMessageBox.warning(
            parent,
            "Arquivo não reconhecido",
            f"{caminho} não é um banco do Controle de Distribuição de Lucros.",
        )
        return None
    db.definir_banco(caminho)
    return caminho


def escolher_banco_existente(parent: QWidget | None = None) -> Path | None:
    """Pergunta a pasta onde o banco já está e aponta este PC pra ele — o
    caso de todo PC depois do primeiro. Devolve o arquivo, ou None se a
    pessoa desistiu ou a pasta não tem banco."""
    pasta = _perguntar_pasta(parent, "Escolher a pasta onde o banco já está")
    if pasta is None:
        return None
    caminho = db.banco_na_pasta(pasta)
    if not caminho.exists():
        QMessageBox.warning(
            parent,
            "Não há banco nesta pasta",
            f"Não encontrei o {db.NOME_DO_ARQUIVO} em:\n{pasta}\n\n"
            "Confira se é a mesma pasta escolhida no primeiro computador. Se ainda não existe "
            "banco nenhum, use \"Criar um banco novo\".",
        )
        return None
    return _usar_se_for_banco(caminho, parent)


def criar_banco_novo(parent: QWidget | None = None) -> Path | None:
    """Pergunta a pasta e cria o banco lá — o caso do primeiro PC. Se já
    houver um banco na pasta (outro PC chegou antes), oferece usar esse em
    vez de criar outro: dois bancos seriam dois cadastros separados, e
    sobrescrever apagaria o trabalho de quem já usa."""
    pasta = _perguntar_pasta(parent, "Escolher a pasta onde o banco vai ficar")
    if pasta is None:
        return None
    caminho = db.banco_na_pasta(pasta)
    if caminho.exists():
        resposta = QMessageBox.question(
            parent,
            "Já existe um banco nesta pasta",
            f"Esta pasta já tem um banco:\n{caminho}\n\n"
            "Provavelmente foi criado por outro computador. Usar este banco? "
            "(Nada nele é apagado.)",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if resposta != QMessageBox.Yes:
            return None
        return _usar_se_for_banco(caminho, parent)
    if not db.banco_em_rede(pasta):
        resposta = QMessageBox.question(
            parent,
            "Pasta deste computador",
            f"{pasta} fica neste computador, não no servidor — os outros computadores não "
            "vão conseguir usar o banco aí.\n\nCriar nessa pasta assim mesmo?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resposta != QMessageBox.Yes:
            return None
    try:
        caminho = db.criar_banco_em(pasta)
    except (OSError, sqlite3.Error) as exc:
        QMessageBox.warning(parent, "Não foi possível criar o banco", db.explicar_erro(exc))
        return None
    db.definir_banco(caminho)
    return caminho


def levar_banco_para_rede(conn, parent: QWidget | None = None) -> Path | None:
    """Copia o banco deste PC pra uma pasta do servidor e passa a usar a
    cópia. Devolve o arquivo novo, ou None se não houve troca."""
    pasta = QFileDialog.getExistingDirectory(
        parent, "Escolher a pasta compartilhada do servidor", str(db.get_db_path().parent)
    )
    if not pasta:
        return None
    pasta = Path(pasta)
    if not db.banco_em_rede(pasta):
        resposta = QMessageBox.question(
            parent,
            "Pasta deste computador",
            f"{pasta} fica neste computador, não no servidor — os outros PCs não vão "
            "conseguir abrir o banco aí.\n\nLevar para essa pasta assim mesmo?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resposta != QMessageBox.Yes:
            return None
    try:
        with ocupado(parent, "Banco de dados", "Copiando o banco para o servidor…"):
            destino = db.levar_banco_para(conn, pasta)
    except FileExistsError as exc:
        QMessageBox.warning(parent, "Já existe um banco nessa pasta", str(exc))
        return None
    except (OSError, sqlite3.Error) as exc:
        QMessageBox.warning(parent, "Não foi possível copiar o banco", db.explicar_erro(exc))
        return None
    db.definir_banco(destino)
    return destino


class DialogoBancoInacessivel(QDialog):
    """Aparece antes do login quando o banco não abre — no dia a dia, é o
    servidor fora do ar ou este PC fora da rede. Sem isto o programa fecharia
    com um erro técnico, e a única saída seria chamar alguém."""

    TENTAR_DE_NOVO = 1
    OUTRO_BANCO = 2

    def __init__(self, erro: BaseException, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Banco de dados indisponível")
        self.setMinimumWidth(460)

        titulo = QLabel("Não consegui abrir o banco de dados")
        titulo.setProperty("role", "secao")

        texto = db.explicar_erro(erro)
        if isinstance(erro, OSError):
            # Pasta que não abre (servidor desligado, sem permissão): a
            # mensagem crua do Windows não diz o que fazer.
            texto = (
                f"Não consegui acessar a pasta do banco de dados ({erro.strerror or erro}).\n\n"
                "Se ela fica no servidor, confira se este computador está na rede, se a pasta "
                "abre no Explorador de Arquivos e se você tem permissão de gravar nela."
            )
        explicacao = QLabel(texto)
        explicacao.setWordWrap(True)
        explicacao.setTextInteractionFlags(Qt.TextSelectableByMouse)

        caminho = QLabel(str(db.get_db_path()))
        caminho.setProperty("role", "mono")
        caminho.setWordWrap(True)
        caminho.setTextInteractionFlags(Qt.TextSelectableByMouse)

        tentar = QPushButton("Tentar de novo")
        tentar.setProperty("role", "primario")
        tentar.setDefault(True)
        tentar.clicked.connect(lambda: self.done(self.TENTAR_DE_NOVO))

        outro = QPushButton("Escolher outro banco…")
        outro.clicked.connect(self._escolher_outro)

        sair = QPushButton("Sair")
        sair.clicked.connect(self.reject)

        botoes = QHBoxLayout()
        botoes.addWidget(outro)
        botoes.addStretch()
        botoes.addWidget(sair)
        botoes.addWidget(tentar)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(titulo)
        layout.addWidget(explicacao)
        if str(db.get_db_path()) not in texto:
            layout.addWidget(caminho)
        layout.addWidget(botao_tutorial(self))
        layout.addSpacing(6)
        layout.addLayout(botoes)

    def _escolher_outro(self) -> None:
        if escolher_banco_existente(self) is not None:
            self.done(self.OUTRO_BANCO)


class DialogoConfigurarBanco(QDialog):
    """Primeira abertura depois de instalar: onde fica o banco.

    O primeiro PC do escritório cria o banco na pasta do servidor; os outros
    usam esse mesmo. Cada PC escolhe uma vez só — fica guardado."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configurar o banco de dados")
        self.setMinimumWidth(500)

        titulo = QLabel("Onde fica o banco de dados?")
        titulo.setProperty("role", "secao")

        explicacao = QLabel(
            "Para o escritório usar o mesmo cadastro, o banco fica numa pasta compartilhada do "
            "servidor e todos os computadores apontam para ela, pelo caminho de rede — por "
            "exemplo <b>\\\\SRV-ESCRITORIO\\ControleDeLucros</b>. Isto só é perguntado uma "
            "vez neste computador."
        )
        explicacao.setWordWrap(True)
        explicacao.setProperty("role", "subtitulo")

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.addWidget(titulo)
        layout.addWidget(explicacao)
        layout.addWidget(botao_tutorial(self))
        layout.addSpacing(4)
        opcoes = (
            ("Usar o banco que já está no servidor",
             "Outro computador já criou o banco. Escolha a mesma pasta que ele escolheu.",
             self._usar_existente, True),
            ("Criar um banco novo no servidor",
             "Este é o primeiro computador do escritório a usar o sistema.",
             self._criar_novo, False),
            ("Usar só neste computador",
             "Sem servidor: o banco fica nesta máquina e os outros computadores não o veem.",
             self._so_neste, False),
        )
        for texto, detalhe, acao, principal in opcoes:
            botao = QPushButton(texto)
            if principal:
                botao.setProperty("role", "primario")
            botao.setMinimumHeight(38)
            botao.clicked.connect(acao)
            rotulo = QLabel(detalhe)
            rotulo.setWordWrap(True)
            rotulo.setProperty("role", "subtitulo")
            layout.addWidget(botao)
            layout.addWidget(rotulo)
            layout.addSpacing(4)

        sair = QPushButton("Sair")
        sair.clicked.connect(self.reject)
        rodape = QHBoxLayout()
        rodape.addStretch()
        rodape.addWidget(sair)
        layout.addLayout(rodape)

    def _usar_existente(self) -> None:
        if escolher_banco_existente(self) is not None:
            self.accept()

    def _criar_novo(self) -> None:
        if criar_banco_novo(self) is not None:
            self.accept()

    def _so_neste(self) -> None:
        db.definir_banco(None)
        self.accept()
