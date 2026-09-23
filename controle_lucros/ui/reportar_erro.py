"""A tela de reportar problema, e a captura do que dá errado.

O caminho preferido é abrir o programa de e-mail já preenchido, mas ele não
pode ser o único: em máquina que usa webmail pelo navegador não há programa
de e-mail configurado, e o link simplesmente não faz nada. Por isso a tela
mostra o texto inteiro, com botão de copiar e de salvar em arquivo, e diz o
endereço por extenso. Assim o relatório chega mesmo quando o atalho falha.

A pessoa vê o texto antes de enviar de propósito: é o que garante que ela
saiba o que está mandando, e a chance de revisar se algum nome escapou na
mensagem de erro.
"""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from .. import db, relatorio_erro


class DialogoReportarProblema(QDialog):
    """Mostra o relatório, deixa descrever o que aconteceu e oferece os três
    caminhos de envio (e-mail, copiar, salvar)."""

    def __init__(self, relatorio: relatorio_erro.Relatorio, parent=None):
        super().__init__(parent)
        self._relatorio = relatorio
        self._origem = relatorio.contexto.get("origem", "erro")

        self.setWindowTitle("Reportar problema")
        self.setMinimumSize(640, 560)

        self.titulo = QLabel(self._titulo_da_origem())
        self.titulo.setProperty("role", "titulo")
        self.titulo.setWordWrap(True)

        explicacao = QLabel(
            "Descreva o que estava fazendo quando isso aconteceu. É a parte mais útil "
            "do relatório: a pilha do erro diz onde quebrou, mas só você sabe o que "
            "estava tentando fazer."
        )
        explicacao.setWordWrap(True)
        explicacao.setProperty("role", "subtitulo")

        self.o_que_fazia = QPlainTextEdit()
        self.o_que_fazia.setPlaceholderText(
            "Ex.: cliquei em Importar relatório de sócios, escolhi o PDF do mês e a tela fechou."
        )
        self.o_que_fazia.setFixedHeight(90)
        self.o_que_fazia.textChanged.connect(self._atualizar_texto)

        rotulo_mensagem = QLabel("Mensagem que será enviada:")
        rotulo_mensagem.setProperty("role", "secao")

        self.mensagem = QPlainTextEdit()
        self.mensagem.setReadOnly(True)
        self.mensagem.setProperty("role", "mono")

        self.instrucao = QLabel(
            f'Envie para <b>{relatorio_erro.DESTINO}</b>. O botão abaixo abre seu programa de '
            "e-mail já preenchido; se ele não abrir (comum em quem usa e-mail pelo navegador), "
            "use <b>Copiar mensagem</b> e cole num e-mail novo."
        )
        self.instrucao.setWordWrap(True)
        self.instrucao.setProperty("role", "subtitulo")

        self.btn_email = QPushButton("Abrir meu e-mail")
        self.btn_email.setProperty("role", "primario")
        self.btn_email.clicked.connect(self._abrir_email)

        self.btn_copiar = QPushButton("Copiar mensagem")
        self.btn_copiar.clicked.connect(self._copiar)

        self.btn_salvar = QPushButton("Salvar em arquivo…")
        self.btn_salvar.setToolTip(
            "Grava o relatório num arquivo de texto, pra anexar ao e-mail ou mandar por outro meio."
        )
        self.btn_salvar.clicked.connect(self._salvar)

        btn_fechar = QPushButton("Fechar")
        btn_fechar.clicked.connect(self.reject)

        self.aviso = QLabel()
        self.aviso.setProperty("role", "subtitulo")
        self.aviso.setWordWrap(True)

        acoes = QHBoxLayout()
        acoes.setSpacing(8)
        acoes.addWidget(self.btn_email)
        acoes.addWidget(self.btn_copiar)
        acoes.addWidget(self.btn_salvar)
        acoes.addStretch()
        acoes.addWidget(btn_fechar)

        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(16, 16, 16, 16)
        coluna.setSpacing(10)
        coluna.addWidget(self.titulo)
        coluna.addWidget(explicacao)
        coluna.addWidget(self.o_que_fazia)
        coluna.addWidget(rotulo_mensagem)
        coluna.addWidget(self.mensagem, 1)
        coluna.addWidget(self.instrucao)
        coluna.addWidget(self.aviso)
        coluna.addLayout(acoes)

        self._atualizar_texto()
        self.o_que_fazia.setFocus()

    def _titulo_da_origem(self) -> str:
        if self._origem == "fechamento":
            return "O programa fechou sozinho da última vez"
        if self._origem == "manual":
            return "Reportar um problema"
        return "Aconteceu um erro inesperado"

    # ------------------------------------------------------------ texto --
    def relatorio_atual(self) -> relatorio_erro.Relatorio:
        """Remonta com o que a pessoa escreveu — o texto na tela é sempre o
        que vai ser enviado, sem versão paralela escondida."""
        base = self._relatorio
        return relatorio_erro.montar(
            base.contexto.get("erro"),
            o_que_fazia=self.o_que_fazia.toPlainText(),
            tela=base.contexto.get("tela", ""),
            detalhes_extras=base.contexto.get("detalhes_extras", ""),
            origem=self._origem,
            quando=base.contexto.get("quando"),
        )

    def _atualizar_texto(self) -> None:
        self.mensagem.setPlainText(self.relatorio_atual().corpo)

    # ------------------------------------------------------------ ações --
    def _abrir_email(self) -> None:
        relatorio = self.relatorio_atual()
        abriu = QDesktopServices.openUrl(QUrl(relatorio_erro.url_mailto(relatorio)))
        if abriu:
            self.aviso.setText(
                "Seu programa de e-mail foi aberto. Confira a mensagem e clique em enviar."
            )
            return
        # Não abriu: dizer isso e apontar o caminho que funciona sempre, em vez
        # de deixar a pessoa achando que o relatório foi enviado.
        self.aviso.setText(
            "Não consegui abrir um programa de e-mail nesta máquina. Use \"Copiar mensagem\" "
            f"e cole num e-mail para {relatorio_erro.DESTINO}."
        )

    def _copiar(self) -> None:
        QGuiApplication.clipboard().setText(self.relatorio_atual().corpo)
        self.aviso.setText(
            f"Mensagem copiada. Cole num e-mail para {relatorio_erro.DESTINO} e envie."
        )

    def _salvar(self) -> None:
        relatorio = self.relatorio_atual()
        caminho, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar relatório do problema",
            relatorio_erro.nome_de_arquivo(relatorio),
            "Arquivo de texto (*.txt)",
        )
        if not caminho:
            return
        if not caminho.lower().endswith(".txt"):
            caminho += ".txt"
        try:
            Path(caminho).write_text(relatorio.corpo, encoding="utf-8")
        except OSError as erro:
            QMessageBox.warning(self, "Erro ao salvar", str(erro))
            return
        self.aviso.setText(f"Salvo em {caminho}")


def abrir_para_erro(erro: BaseException, tela: str = "", parent=None) -> None:
    relatorio = relatorio_erro.montar(erro, tela=tela, origem="erro")
    relatorio.contexto.update({"erro": erro, "tela": tela, "quando": dt.datetime.now()})
    DialogoReportarProblema(relatorio, parent).exec()


def abrir_para_fechamento(detalhes: str, parent=None) -> None:
    relatorio = relatorio_erro.montar(origem="fechamento", detalhes_extras=detalhes)
    relatorio.contexto.update({"detalhes_extras": detalhes, "quando": dt.datetime.now()})
    DialogoReportarProblema(relatorio, parent).exec()


def abrir_para_relato(tela: str = "", parent=None) -> None:
    relatorio = relatorio_erro.montar(origem="manual", tela=tela)
    relatorio.contexto.update({"tela": tela, "quando": dt.datetime.now()})
    DialogoReportarProblema(relatorio, parent).exec()


class CapturaDeErros:
    """Substitui o sys.excepthook pra transformar erro solto em relatório.

    Sem isto, uma exceção que ninguém tratou só aparece no console — que num
    programa empacotado não existe. A pessoa vê a tela não responder ao clique
    e não tem o que contar depois.

    O mesmo erro pode se repetir a cada redesenho da tela, então cada tipo de
    problema abre uma janela só por execução: vinte janelas iguais empilhadas
    seriam pior que o erro."""

    def __init__(self, janela_principal=None):
        self.janela_principal = janela_principal
        self._ja_mostrados: set[str] = set()
        self._anterior = None
        self._dentro = False

    def instalar(self) -> None:
        import sys

        self._anterior = sys.excepthook
        sys.excepthook = self._tratar

    def desinstalar(self) -> None:
        import sys

        if self._anterior is not None:
            sys.excepthook = self._anterior

    def _tratar(self, tipo, valor, tb) -> None:
        if self._anterior is not None:
            self._anterior(tipo, valor, tb)  # segue imprimindo no console

        # Reentrância: um erro dentro da própria tela de relatório não pode
        # abrir outra tela de relatório em cima, sem fim.
        if self._dentro:
            return

        assinatura = self._assinatura(tipo, tb)
        if assinatura in self._ja_mostrados:
            return
        self._ja_mostrados.add(assinatura)

        self._desfazer_gravacao_pela_metade()

        self._dentro = True
        try:
            # Rede que caiu ou banco ocupado por outro PC não é defeito do
            # programa: pedir relatório disso só confunde. A pessoa precisa
            # é saber o que aconteceu e o que fazer.
            explicacao = db.explicar_erro(valor)
            if explicacao != str(valor):
                QMessageBox.warning(self.janela_principal, "Problema com o banco de dados", explicacao)
                return
            abrir_para_erro(valor, tela=self._tela_atual(), parent=self.janela_principal)
        except Exception:  # noqa: BLE001 — relatar não pode virar outro erro
            pass
        finally:
            self._dentro = False

    def _desfazer_gravacao_pela_metade(self) -> None:
        """Erro que escapou no meio de uma gravação deixa a transação aberta
        no servidor, segurando trava nas linhas que ela mexeu: os outros PCs
        que tocassem nelas ficariam recebendo "tente de novo", e o próximo
        commit, de outra ação qualquer, gravaria o trabalho pela metade."""
        conn = getattr(self.janela_principal, "conn", None)
        if conn is None:
            return
        try:
            conn.rollback()
        except Exception:  # noqa: BLE001 — conexão caída: não há o que desfazer
            pass

    @staticmethod
    def _assinatura(tipo, tb) -> str:
        """Tipo do erro mais o ponto do código onde estourou: é o que
        distingue "o mesmo problema de novo" de "outro problema"."""
        ultimo = tb
        while ultimo is not None and ultimo.tb_next is not None:
            ultimo = ultimo.tb_next
        if ultimo is None:
            return tipo.__name__
        quadro = ultimo.tb_frame
        return f"{tipo.__name__}@{quadro.f_code.co_filename}:{ultimo.tb_lineno}"

    def _tela_atual(self) -> str:
        janela = self.janela_principal
        if janela is None:
            return ""
        try:
            return janela.titulo_pagina.text()
        except Exception:  # noqa: BLE001 — nome da tela é enfeite, não pode falhar aqui
            return ""
