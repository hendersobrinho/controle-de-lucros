"""Empresas · Alterações contratuais: escolhe a empresa, a linha do tempo
mostra as alterações dela de uma ponta à outra e a ficha da escolhida
aparece embaixo, deslizando para o lado da que foi clicada.

Antes cada alteração era uma página de um carrossel, com o formulário
sempre aberto: pra achar a Nº 3 era preciso passar uma por uma, e não dava
pra distinguir de relance o que era leitura e o que era edição. A linha do
tempo mantém o deslizar do carrossel, mas leva direto a qualquer alteração;
a ficha só mostra, e cadastrar ou editar abre uma janela própria."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QParallelAnimationGroup, QPoint, QPropertyAnimation, Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .seletor_empresa import SeletorEmpresa
from .. import repositories as repo
from .alteracao_card import AlteracaoCard, DialogoAlteracao
from .common import preencher_combo
from .linha_do_tempo import LinhaDoTempo

# A tela vive numa coluna só, que acompanha a janela (80% da largura) e para
# de crescer no teto: num monitor largo, ficha esticada até a borda não
# ajuda a ler nada.
PROPORCAO_COLUNA = 8
LARGURA_MAXIMA_COLUNA = 1240
DURACAO_MS = 260


class _Palco(QWidget):
    """Onde a ficha fica. Trocar de alteração desliza a ficha nova para
    dentro pelo lado de onde ela está na linha do tempo — a mais antiga
    entra pela esquerda, a mais nova pela direita."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.atual: QWidget | None = None
        self._grupo = None
        self._saindo: QWidget | None = None

    def mostrar(self, widget: QWidget, direcao: int = 0) -> None:
        anterior = self.atual
        if self._grupo is not None:
            # Troca no meio de um deslize: a que estava saindo some já, e a
            # que estava entrando passa a ser a que sai agora.
            self._grupo.stop()
            self._grupo = None
            self._descartar(self._saindo)
            if anterior is not None:
                anterior.move(0, 0)
        widget.setParent(self)
        self.atual = widget
        largura, altura = self.width(), self.height()
        if anterior is None or direcao == 0 or not self.isVisible() or largura <= 0:
            widget.setGeometry(0, 0, largura, altura)
            widget.show()
            self._descartar(anterior)
            return

        deslocamento = largura if direcao > 0 else -largura
        widget.setGeometry(deslocamento, 0, largura, altura)
        widget.show()
        widget.raise_()
        saida = QPropertyAnimation(anterior, b"pos")
        entrada = QPropertyAnimation(widget, b"pos")
        for animacao, de, ate in ((saida, QPoint(0, 0), QPoint(-deslocamento, 0)),
                                  (entrada, QPoint(deslocamento, 0), QPoint(0, 0))):
            animacao.setDuration(DURACAO_MS)
            animacao.setEasingCurve(QEasingCurve.OutCubic)
            animacao.setStartValue(de)
            animacao.setEndValue(ate)
        grupo = QParallelAnimationGroup(self)
        grupo.addAnimation(saida)
        grupo.addAnimation(entrada)

        def terminar() -> None:
            widget.move(0, 0)
            self._descartar(anterior)
            self._grupo = None
            self._saindo = None

        grupo.finished.connect(terminar)
        self._grupo = grupo
        self._saindo = anterior
        grupo.start()

    def _descartar(self, widget: QWidget | None) -> None:
        if widget is not None and widget is not self.atual:
            widget.hide()
            widget.deleteLater()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        if self.atual is not None:
            self.atual.setGeometry(0, 0, self.width(), self.height())


class AlteracoesView(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._alteracao_atual_id: int | None = None
        self.ficha: AlteracaoCard | None = None

        rotulo_empresa = QLabel("EMPRESA")
        rotulo_empresa.setProperty("role", "rotuloCampo")
        self.empresa = SeletorEmpresa()
        self.empresa.setMinimumWidth(320)
        self.empresa.currentIndexChanged.connect(lambda _: self._carregar_empresa())
        escolha_empresa = QVBoxLayout()
        escolha_empresa.setSpacing(3)
        escolha_empresa.addWidget(rotulo_empresa)
        escolha_empresa.addWidget(self.empresa)

        self.contagem = QLabel()
        self.contagem.setProperty("role", "subtitulo")

        self.btn_nova = QPushButton("Nova alteração")
        self.btn_nova.setProperty("role", "primario")
        self.btn_nova.setToolTip("Cadastra uma alteração contratual desta empresa, com o número que está no contrato.")
        self.btn_nova.clicked.connect(self._nova_alteracao)

        topo = QHBoxLayout()
        topo.setSpacing(14)
        topo.addLayout(escolha_empresa, 1)
        topo.addWidget(self.contagem, 0, Qt.AlignBottom)
        topo.addWidget(self.btn_nova, 0, Qt.AlignBottom)

        # A linha do tempo num bloco branco próprio, com rolagem lateral
        # pra empresa com muitas alterações.
        self.linha = LinhaDoTempo()
        self.linha.escolhida.connect(self._ao_escolher)
        self.linha.nova.connect(self._nova_alteracao)
        rolagem_linha = QScrollArea()
        rolagem_linha.setProperty("role", "listaCartoes")
        rolagem_linha.setWidgetResizable(True)
        rolagem_linha.setFrameShape(QFrame.NoFrame)
        rolagem_linha.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rolagem_linha.setWidget(self.linha)
        rolagem_linha.setFixedHeight(self.linha.minimumHeight() + 14)
        self.faixa_linha = QFrame()
        self.faixa_linha.setProperty("role", "card")
        coluna_faixa = QVBoxLayout(self.faixa_linha)
        coluna_faixa.setContentsMargins(6, 6, 6, 0)
        coluna_faixa.addWidget(rolagem_linha)

        self.palco = _Palco()

        coluna = QWidget()
        coluna.setMaximumWidth(LARGURA_MAXIMA_COLUNA)
        conteudo = QVBoxLayout(coluna)
        conteudo.setContentsMargins(0, 0, 0, 0)
        conteudo.setSpacing(14)
        conteudo.addLayout(topo)
        conteudo.addWidget(self.faixa_linha)
        conteudo.addWidget(self.palco, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addStretch(1)
        layout.addWidget(coluna, PROPORCAO_COLUNA)
        layout.addStretch(1)

        self.atualizar()

    # ------------------------------------------------------------- dados --
    def atualizar(self) -> None:
        empresa_id_anterior = self.empresa.currentData()
        self.empresa.blockSignals(True)
        preencher_combo(self.empresa, repo.listar_empresas(self.conn))
        if empresa_id_anterior is not None:
            idx = self.empresa.findData(empresa_id_anterior)
            if idx >= 0:
                self.empresa.setCurrentIndex(idx)
        self.empresa.blockSignals(False)
        self._carregar_empresa(self._alteracao_atual_id)

    def selecionar_empresa(self, empresa_id: int) -> None:
        idx = self.empresa.findData(empresa_id)
        if idx >= 0 and idx != self.empresa.currentIndex():
            self.empresa.setCurrentIndex(idx)
        elif idx >= 0:
            self._carregar_empresa(self._alteracao_atual_id)

    def _carregar_empresa(self, selecionar_id: int | None = None) -> None:
        empresa_id = self.empresa.currentData()
        self.btn_nova.setEnabled(empresa_id is not None)
        alteracoes = repo.listar_alteracoes(self.conn, empresa_id) if empresa_id is not None else []

        if empresa_id is None:
            self.contagem.setText("Cadastre uma empresa para registrar as alterações dela.")
        elif not alteracoes:
            self.contagem.setText("")
        else:
            primeira = min(a.numero for a in alteracoes)
            texto = f"{len(alteracoes)} alteraç{'ão' if len(alteracoes) == 1 else 'ões'}"
            if primeira > 1:
                texto += f" · registradas a partir da Nº {primeira}"
            self.contagem.setText(texto)

        # Sem escolha, abre na que vale hoje: a mais recente.
        if any(a.id == selecionar_id for a in alteracoes):
            alvo = selecionar_id
        else:
            alvo = max(alteracoes, key=lambda a: (a.data, a.numero)).id if alteracoes else None
        self._alteracao_atual_id = alvo
        self.faixa_linha.setVisible(bool(alteracoes))
        self.linha.definir(alteracoes, alvo, pode_criar=empresa_id is not None)
        self._mostrar_ficha()

    def _ao_escolher(self, alteracao_id: int) -> None:
        ids = self.linha.ids()
        anterior = self._alteracao_atual_id
        direcao = 0
        if anterior in ids and alteracao_id in ids:
            direcao = 1 if ids.index(alteracao_id) > ids.index(anterior) else -1
        self._alteracao_atual_id = alteracao_id
        self.linha.escolher(alteracao_id)
        self._mostrar_ficha(direcao)

    def _mostrar_ficha(self, direcao: int = 0) -> None:
        empresa_id = self.empresa.currentData()
        if empresa_id is None:
            if self.ficha is not None:
                self.ficha.hide()
            return
        alteracao = repo.buscar_alteracao(self.conn, self._alteracao_atual_id) if self._alteracao_atual_id else None
        self.ficha = AlteracaoCard(self.conn, empresa_id, alteracao, self._ao_ficha_mudar)
        self.palco.mostrar(self.ficha, direcao)

    def _ao_ficha_mudar(self, ficha: AlteracaoCard) -> None:
        self._alteracao_atual_id = ficha.alteracao.id if ficha.alteracao else None
        self._carregar_empresa(self._alteracao_atual_id)

    # ------------------------------------------------------------- ações --
    def _nova_alteracao(self) -> None:
        empresa_id = self.empresa.currentData()
        if empresa_id is None:
            QMessageBox.information(self, "Nova alteração", "Cadastre e selecione uma empresa primeiro.")
            return
        dialogo = DialogoAlteracao(self.conn, empresa_id, None, self)
        if dialogo.exec() != QDialog.Accepted:
            return
        self._carregar_empresa(dialogo.alteracao_id)
