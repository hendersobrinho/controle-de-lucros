"""Janela "Conectar ao Claude": liga o Claude Desktop e o Claude Code ao
servidor MCP deste PC com um clique (ver conexao_claude.py)."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .. import conexao_claude as claude
from . import theme


class DialogoConectarClaude(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Conectar ao Claude")
        self.setFixedWidth(600)

        titulo = QLabel("Consultar o sistema pelo Claude")
        titulo.setProperty("role", "secao")
        explicacao = QLabel(
            "Liga o Claude a este programa: dá para perguntar, em português, coisas como "
            "<i>“quanto a 275 distribuiu em 2024 e para quem?”</i> ou <i>“quem recebeu lucro sem "
            "pró-labore no ano passado?”</i>. O Claude só <b>lê</b> — não grava, não altera e não "
            "apaga nada — e usa a mesma conexão com o banco deste computador."
        )
        explicacao.setWordWrap(True)
        explicacao.setProperty("role", "subtitulo")

        aviso = QLabel(
            "As respostas que o Claude consulta saem do escritório e vão para a Anthropic, "
            "empresa do Claude: nomes de empresas e sócios e os valores. O CPF dos sócios vai "
            "mascarado (***.456.789-**), a menos que você marque a opção abaixo."
        )
        aviso.setWordWrap(True)
        aviso.setProperty("role", "info")

        self.cpf_completo = QCheckBox("Enviar o CPF completo dos sócios")

        self.desktop = self._linha(
            "Claude Desktop", "o aplicativo do Claude para Windows",
            self._conectar_desktop, self._desconectar_desktop,
        )
        self.code = self._linha(
            "Claude Code", "o Claude no terminal ou no VS Code",
            self._conectar_code, self._desconectar_code,
        )

        self.sem_servidor = QLabel(
            "Não achei o servidor do Claude ao lado deste programa (ControleDeLucrosMCP.exe). "
            "Reinstale o programa com a versão mais nova."
        )
        self.sem_servidor.setWordWrap(True)
        self.sem_servidor.setProperty("role", "alerta")

        botoes = QDialogButtonBox(QDialogButtonBox.Close)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(10)
        layout.addWidget(titulo)
        layout.addWidget(explicacao)
        layout.addWidget(aviso)
        layout.addWidget(self.cpf_completo)
        layout.addSpacing(4)
        layout.addWidget(self.desktop["quadro"])
        layout.addWidget(self.code["quadro"])
        layout.addWidget(self.sem_servidor)
        layout.addWidget(botoes)

        self.atualizar()

    def _linha(self, nome: str, descricao: str, conectar, desconectar) -> dict:
        quadro = QFrame()
        quadro.setProperty("role", "cartaoFormato")
        rotulo = QLabel(f"<b>{nome}</b> <span style='color:{theme.INK_MUTED()}'>— {descricao}</span>")
        rotulo.setWordWrap(True)
        situacao = QLabel()
        situacao.setProperty("role", "dicaCampo")
        textos = QVBoxLayout()
        textos.setSpacing(2)
        textos.addWidget(rotulo)
        textos.addWidget(situacao)
        botao_conectar = QPushButton("Conectar")
        botao_conectar.setProperty("role", "primario")
        botao_conectar.clicked.connect(conectar)
        botao_desconectar = QPushButton("Desconectar")
        botao_desconectar.clicked.connect(desconectar)
        linha = QHBoxLayout(quadro)
        linha.setContentsMargins(14, 10, 14, 10)
        linha.addLayout(textos, 1)
        linha.addWidget(botao_conectar)
        linha.addWidget(botao_desconectar)
        return {"quadro": quadro, "situacao": situacao, "conectar": botao_conectar, "desconectar": botao_desconectar}

    def atualizar(self) -> None:
        disponivel = claude.servidor_disponivel()
        self.sem_servidor.setVisible(not disponivel)

        estado = claude.situacao_claude_desktop()
        textos = {"conectado": "✓ conectado", "outro": "aponta para outra pasta", "desconectado": "não conectado"}
        self.desktop["situacao"].setText(textos[estado])
        self.desktop["conectar"].setText("Conectar de novo" if estado != "desconectado" else "Conectar")
        self.desktop["conectar"].setEnabled(disponivel)
        self.desktop["desconectar"].setEnabled(estado != "desconectado")

        tem_code = claude.comando_claude_code() is not None
        self.code["situacao"].setText("instalado neste computador" if tem_code else "não instalado")
        self.code["conectar"].setEnabled(disponivel and tem_code)
        self.code["desconectar"].setEnabled(tem_code)

    def _executar(self, acao, sucesso: str) -> None:
        try:
            acao()
        except (OSError, ValueError) as erro:
            QMessageBox.warning(self, "Conectar ao Claude", f"Não deu certo:\n\n{erro}")
        else:
            QMessageBox.information(self, "Conectar ao Claude", sucesso)
        self.atualizar()

    def _conectar_desktop(self) -> None:
        self._executar(
            lambda: claude.conectar_claude_desktop(self.cpf_completo.isChecked()),
            "Pronto. Feche o Claude Desktop por completo (também pelo ícone perto do relógio) e "
            "abra de novo: o “controle-de-lucros” aparece nas ferramentas, e é só perguntar.",
        )

    def _desconectar_desktop(self) -> None:
        self._executar(claude.desconectar_claude_desktop,
                       "Desconectado. Feche e abra o Claude Desktop para valer.")

    def _conectar_code(self) -> None:
        self._executar(
            lambda: claude.conectar_claude_code(self.cpf_completo.isChecked()),
            "Pronto. Na próxima vez que abrir o Claude Code, o “controle-de-lucros” já estará disponível.",
        )

    def _desconectar_code(self) -> None:
        self._executar(claude.desconectar_claude_code, "Desconectado do Claude Code.")
