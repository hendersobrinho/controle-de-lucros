"""Janela "Conectar ao Claude": liga o Claude Desktop e o Claude Code ao
servidor MCP deste PC com um clique (ver conexao_claude.py)."""
from __future__ import annotations

import subprocess

from PySide6.QtCore import Qt
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

from .. import conexao_claude as claude, preferencias
from . import theme
from .marca import TelaDeEntrada


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


# ---------------------------------------------------------- escolha inicial --

CHAVE_ESCOLHA = "claude_escolha"


def precisa_escolher() -> bool:
    """A pergunta "com ou sem o Claude?" aparece uma vez por computador; a
    resposta fica nas preferências dele. Mudar de ideia é pelo menu."""
    return preferencias.obter(CHAVE_ESCOLHA) not in ("com", "sem")


class _Opcao(QFrame):
    """Cartão clicável inteiro, em vez de um botão pequeno: são as duas
    únicas coisas da tela, e a escolha tem que ser óbvia."""

    def __init__(self, titulo: str, texto: str, ao_clicar, cores: tuple[str, ...], principal: bool = False):
        super().__init__()
        self.setProperty("role", "entradaOpcao")
        self.setCursor(Qt.PointingHandCursor)
        self._ao_clicar = ao_clicar
        pontos = "".join(f"<span style='color:{c}; font-size:18px'>●</span> " for c in cores)
        nome = QLabel(f"{pontos}&nbsp;<b style='font-size:15px'>{titulo}</b>")
        descricao = QLabel(texto)
        descricao.setWordWrap(True)
        descricao.setProperty("role", "entradaSubtitulo")
        self.botao = QPushButton(titulo)
        self.botao.setProperty("role", "entradaPrincipal" if principal else "entradaSecundario")
        self.botao.setCursor(Qt.PointingHandCursor)
        self.botao.clicked.connect(ao_clicar)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(8)
        layout.addWidget(nome)
        layout.addWidget(descricao)
        layout.addSpacing(4)
        layout.addWidget(self.botao)

    def mouseReleaseEvent(self, evento):
        # Só conta se soltou dentro do cartão: apertar, mudar de ideia e
        # arrastar para fora não pode virar escolha.
        if evento.button() == Qt.LeftButton and self.rect().contains(evento.position().toPoint()):
            self._ao_clicar()
        super().mouseReleaseEvent(evento)


class DialogoEscolhaClaude(TelaDeEntrada):
    """Na primeira abertura neste computador: usar só o programa, ou já ligar
    o Claude. Fechar a janela conta como "só o programa" — ninguém fica
    preso aqui, e a pergunta não volta."""

    def __init__(self, parent=None):
        super().__init__(
            "Como usar o programa",
            "Do seu jeito.",
            "O Controle de Lucros funciona completo sozinho. Se quiser, dá para ligar também o "
            "Claude, para fazer perguntas sobre os dados em português.",
            parent,
        )
        self.cabecalho("Como você quer usar o programa?",
                       "Dá para mudar depois, pelo item <b>Conectar ao Claude</b>, no rodapé do menu do programa.")
        self.sem = _Opcao(
            "Usar só o programa",
            "Entrar e usar normalmente. Nada é enviado para fora do escritório.",
            self._sem_claude, ("#203461",), principal=True,
        )
        self.com = _Opcao(
            "Usar com o Claude",
            "Ligar o Claude Desktop ou o Claude Code a este computador. Ele só consulta — não "
            "grava nada — e o que consulta vai para a Anthropic, empresa do Claude.",
            self._com_claude, ("#4BBDCD", "#F9B259"),
        )
        self.corpo.addWidget(self.sem)
        self.corpo.addSpacing(14)
        self.corpo.addWidget(self.com)
        self.corpo.addStretch()

    def _sem_claude(self) -> None:
        """"Nada é enviado" tem que ser verdade: se este PC já estava ligado ao
        Claude (por uma versão anterior, ou pelo link da entrada), desliga."""
        if claude.situacao_claude_desktop() != "desconectado":
            try:
                claude.desconectar_claude_desktop()
            except (OSError, ValueError):
                pass
        if claude.claude_code_registrado():
            try:
                claude.desconectar_claude_code()
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        preferencias.salvar_chave(CHAVE_ESCOLHA, "sem")
        self.accept()

    def _com_claude(self) -> None:
        """Só vale como escolha se conectou de fato; fechando a janela de
        conexão sem conectar, volta para cá para escolher de novo."""
        DialogoConectarClaude(self).exec()
        if claude.algum_conectado():
            preferencias.salvar_chave(CHAVE_ESCOLHA, "com")
            self.accept()

    def reject(self) -> None:
        self._sem_claude()


def texto_do_menu() -> str:
    """O item do menu diz a situação, para ninguém precisar abrir a janela
    só para saber se está ligado. Não pode derrubar a janela principal: sem
    conseguir ler a configuração do Claude, só oferece conectar."""
    try:
        return "Claude: conectado ✓" if claude.algum_conectado() else "Conectar ao Claude"
    except (OSError, ValueError):
        return "Conectar ao Claude"
