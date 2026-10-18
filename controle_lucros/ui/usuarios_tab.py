"""Cadastro de usuários — só para administradores.

Mesmo arranjo das telas de Empresas e Sócios: a lista à esquerda e, à
direita, a ficha do usuário escolhido — quem é, que nível tem, como anda o
acesso dele (desde quando existe, quando mexeu por último, em quantos
computadores entra sem senha) e o que fez por último. Cadastrar e editar
abrem uma janela própria.

Contas nunca são excluídas de verdade, só desativadas, pra não perder o
histórico de quem fez o quê no log de atividade."""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import repositories as repo
from .. import sessao
from .common import formatar_data_br, pintura_segura
from .lista_fichas import ListaFichas
from .log_atividades_view import ACAO_LABEL, ENTIDADE_LABEL
from .painel_distribuicao import iniciais
from . import theme

MINIMO_SENHA = 4


def _rotulo(texto: str) -> QLabel:
    rotulo = QLabel(texto.upper())
    rotulo.setProperty("role", "rotuloCampo")
    return rotulo


def _dica(texto: str = "") -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setProperty("role", "subtitulo")
    rotulo.setWordWrap(True)
    return rotulo


def _secao(texto: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setProperty("role", "secao")
    return rotulo


def _bloco(titulo: str = "") -> tuple[QFrame, QVBoxLayout]:
    quadro = QFrame()
    quadro.setProperty("role", "card")
    coluna = QVBoxLayout(quadro)
    coluna.setContentsMargins(20, 16, 20, 16)
    coluna.setSpacing(10)
    if titulo:
        coluna.addWidget(_secao(titulo))
    return quadro, coluna


def _etiqueta(texto: str, tom: str) -> QLabel:
    rotulo = QLabel(texto)
    rotulo.setProperty("role", "etiquetaSituacao")
    rotulo.setProperty("tom", tom)
    return rotulo


def _limpar(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget() is not None:
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout() is not None:
            _limpar(item.layout())


def _data_hora_br(texto: str) -> str:
    """'2026-10-18T14:03:22' -> '18/10/2026 às 14:03'."""
    if not texto:
        return "—"
    data, _, hora = texto.replace(" ", "T").partition("T")
    return f"{formatar_data_br(data)} às {hora[:5]}" if hora else formatar_data_br(data)


class Avatar(QWidget):
    """O círculo com as iniciais. Apagado quando a conta está desativada."""

    def __init__(self, nome: str = "", diametro: int = 56, parent=None):
        super().__init__(parent)
        self._nome = nome
        self._apagado = False
        self.setFixedSize(diametro, diametro)
        theme.estado().mudou.connect(self.update)

    def definir(self, nome: str, apagado: bool = False) -> None:
        self._nome, self._apagado = nome, apagado
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        with pintura_segura(self) as p:
            p.setRenderHint(QPainter.Antialiasing)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(theme.INK_MUTED() if self._apagado else theme.cor("HERO_BG")))
            p.drawEllipse(QRectF(1, 1, self.width() - 2, self.height() - 2))
            fonte = QFont(self.font())
            fonte.setPixelSize(int(self.height() * 0.36))
            fonte.setBold(True)
            p.setFont(fonte)
            p.setPen(QColor("#FFFFFF"))
            p.drawText(self.rect(), Qt.AlignCenter, iniciais(self._nome) if self._nome else "?")


class CampoSenha(QWidget):
    """Senha com o botão de mostrar/esconder: digitar duas vezes às cegas é
    onde mais se erra."""

    def __init__(self, texto_de_apoio: str = "", parent=None):
        super().__init__(parent)
        self.campo = QLineEdit()
        self.campo.setEchoMode(QLineEdit.Password)
        self.campo.setPlaceholderText(texto_de_apoio)
        self.btn_ver = QPushButton("Mostrar")
        self.btn_ver.setCheckable(True)
        self.btn_ver.setFocusPolicy(Qt.NoFocus)
        self.btn_ver.setProperty("role", "atalho")
        self.btn_ver.toggled.connect(self._alternar)
        linha = QHBoxLayout(self)
        linha.setContentsMargins(0, 0, 0, 0)
        linha.setSpacing(6)
        linha.addWidget(self.campo, 1)
        linha.addWidget(self.btn_ver)

    def _alternar(self, ver: bool) -> None:
        self.campo.setEchoMode(QLineEdit.Normal if ver else QLineEdit.Password)
        self.btn_ver.setText("Esconder" if ver else "Mostrar")

    def text(self) -> str:
        return self.campo.text()

    def setText(self, texto: str) -> None:  # noqa: N802
        self.campo.setText(texto)


class CartaoNivel(QFrame):
    """Usuário ou Administrador, escolhido num cartão grande que diz o que
    cada um pode fazer — em vez de uma caixinha "Administrador" solta."""

    escolhido = Signal(bool)

    def __init__(self, admin: bool, parent=None):
        super().__init__(parent)
        self.admin = admin
        self.setProperty("role", "cartaoFormato")
        self.setProperty("escolhido", "false")
        self.setCursor(Qt.PointingHandCursor)
        titulo = QLabel("Administrador" if admin else "Usuário")
        titulo.setProperty("role", "valorCampo")
        fonte = titulo.font()
        fonte.setBold(True)
        titulo.setFont(fonte)
        self.marca = QLabel("✓")
        self.marca.setProperty("role", "marcaSelecionado")
        self.marca.hide()
        topo = QHBoxLayout()
        topo.addWidget(titulo)
        topo.addStretch()
        topo.addWidget(self.marca)
        texto = _dica(
            "Tudo do usuário, e também cadastra usuários e faz backup."
            if admin else "Cadastra, lança e consulta. Não mexe em usuários nem em backup."
        )
        coluna = QVBoxLayout(self)
        coluna.setContentsMargins(14, 10, 14, 12)
        coluna.setSpacing(4)
        coluna.addLayout(topo)
        coluna.addWidget(texto)

    def marcar(self, sim: bool) -> None:
        self.setProperty("escolhido", "true" if sim else "false")
        self.marca.setVisible(sim)
        self.style().unpolish(self)
        self.style().polish(self)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.escolhido.emit(self.admin)
        event.accept()


class DialogoUsuario(QDialog):
    """Cadastrar (com senha) ou editar (nome, login e nível) um usuário."""

    def __init__(self, conn, usuario=None, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.usuario = usuario
        self.usuario_id = usuario.id if usuario else None
        self._admin = bool(usuario and usuario.admin)
        self.setWindowTitle("Editar usuário" if usuario else "Novo usuário")
        self.setMinimumWidth(520)

        self.avatar = Avatar(usuario.nome if usuario else "", 48)
        titulo = QLabel(usuario.nome if usuario else "Novo usuário")
        titulo.setProperty("role", "titulo")
        cabeca = QHBoxLayout()
        cabeca.setSpacing(12)
        cabeca.addWidget(self.avatar)
        cabeca.addWidget(titulo, 1)

        self.nome = QLineEdit(usuario.nome if usuario else "")
        self.nome.setPlaceholderText("Nome completo")
        self.nome.textChanged.connect(lambda t: self.avatar.definir(t))
        self.login = QLineEdit(usuario.login if usuario else "")
        self.login.setPlaceholderText("ex.: maria")
        self.login.setProperty("role", "mono")

        self.cartao_usuario = CartaoNivel(False)
        self.cartao_admin = CartaoNivel(True)
        for cartao in (self.cartao_usuario, self.cartao_admin):
            cartao.escolhido.connect(self._escolher_nivel)
        niveis = QHBoxLayout()
        niveis.setSpacing(10)
        niveis.addWidget(self.cartao_usuario, 1)
        niveis.addWidget(self.cartao_admin, 1)

        grade = QGridLayout()
        grade.setHorizontalSpacing(14)
        grade.setVerticalSpacing(4)
        grade.addWidget(_rotulo("Nome"), 0, 0)
        grade.addWidget(_rotulo("Login (para entrar)"), 0, 1)
        grade.addWidget(self.nome, 1, 0)
        grade.addWidget(self.login, 1, 1)
        grade.setColumnStretch(0, 3)
        grade.setColumnStretch(1, 2)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.addLayout(cabeca)
        layout.addSpacing(4)
        layout.addLayout(grade)
        layout.addWidget(_rotulo("Nível de acesso"))
        layout.addLayout(niveis)

        self.senha = self.confirmar = None
        if usuario is None:
            self.senha = CampoSenha(f"no mínimo {MINIMO_SENHA} caracteres")
            self.confirmar = CampoSenha("repita a senha")
            senhas = QGridLayout()
            senhas.setHorizontalSpacing(14)
            senhas.setVerticalSpacing(4)
            senhas.addWidget(_rotulo("Senha"), 0, 0)
            senhas.addWidget(_rotulo("Confirmar senha"), 0, 1)
            senhas.addWidget(self.senha, 1, 0)
            senhas.addWidget(self.confirmar, 1, 1)
            layout.addLayout(senhas)

        self.erro = QLabel("")
        self.erro.setProperty("role", "alerta")
        self.erro.setWordWrap(True)
        self.erro.hide()
        layout.addWidget(self.erro)

        self.btn_salvar = QPushButton("Salvar" if usuario else "Criar usuário")
        self.btn_salvar.setProperty("role", "primario")
        self.btn_salvar.setDefault(True)
        self.btn_salvar.clicked.connect(self._salvar)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        botoes = QHBoxLayout()
        botoes.addStretch()
        botoes.addWidget(cancelar)
        botoes.addWidget(self.btn_salvar)
        layout.addSpacing(4)
        layout.addLayout(botoes)

        self._escolher_nivel(self._admin)
        self.nome.setFocus()

    @property
    def admin(self) -> bool:
        return self._admin

    def _escolher_nivel(self, admin: bool) -> None:
        self._admin = admin
        self.cartao_usuario.marcar(not admin)
        self.cartao_admin.marcar(admin)

    def _problema(self) -> str:
        if not self.nome.text().strip():
            return "Informe o nome."
        if not self.login.text().strip():
            return "Informe o login — é com ele que a pessoa entra."
        if self.senha is not None:
            if len(self.senha.text()) < MINIMO_SENHA:
                return f"A senha precisa ter pelo menos {MINIMO_SENHA} caracteres."
            if self.senha.text() != self.confirmar.text():
                return "As duas senhas não são iguais."
        return ""

    def _salvar(self) -> None:
        problema = self._problema()
        if problema:
            self.erro.setText(f"⚠  {problema}")
            self.erro.show()
            return
        try:
            if self.usuario is None:
                self.usuario_id = repo.criar_usuario(
                    self.conn, self.nome.text().strip(), self.login.text().strip(), self.senha.text(),
                    admin=self._admin,
                )
            else:
                repo.atualizar_usuario(
                    self.conn, self.usuario.id, self.nome.text().strip(), self.login.text().strip(), self._admin
                )
        except ValueError as exc:
            self.erro.setText(f"⚠  {exc}")
            self.erro.show()
            return
        self.accept()


class _DialogoNovaSenha(QDialog):
    def __init__(self, nome_usuario: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Redefinir senha")
        self.setMinimumWidth(420)

        titulo = QLabel(f"Nova senha para {nome_usuario}")
        titulo.setProperty("role", "titulo")
        titulo.setWordWrap(True)
        self.senha = CampoSenha(f"no mínimo {MINIMO_SENHA} caracteres")
        self.confirmar = CampoSenha("repita a senha")

        self.erro = QLabel("")
        self.erro.setProperty("role", "alerta")
        self.erro.hide()

        salvar = QPushButton("Redefinir senha")
        salvar.setProperty("role", "primario")
        salvar.setDefault(True)
        salvar.clicked.connect(self._validar)
        cancelar = QPushButton("Cancelar")
        cancelar.clicked.connect(self.reject)
        botoes = QHBoxLayout()
        botoes.addStretch()
        botoes.addWidget(cancelar)
        botoes.addWidget(salvar)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(titulo)
        layout.addWidget(_dica("A pessoa entra com esta senha a partir de agora; a antiga deixa de valer."))
        layout.addSpacing(6)
        layout.addWidget(_rotulo("Nova senha"))
        layout.addWidget(self.senha)
        layout.addWidget(_rotulo("Confirmar"))
        layout.addWidget(self.confirmar)
        layout.addWidget(self.erro)
        layout.addSpacing(6)
        layout.addLayout(botoes)

    def _validar(self) -> None:
        if len(self.senha.text()) < MINIMO_SENHA:
            self.erro.setText(f"⚠  A senha precisa ter pelo menos {MINIMO_SENHA} caracteres.")
            self.erro.show()
            return
        if self.senha.text() != self.confirmar.text():
            self.erro.setText("⚠  As duas senhas não são iguais.")
            self.erro.show()
            return
        self.accept()


class UsuariosTab(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._usuarios = []
        self._usuario_atual_id: int | None = None

        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        painel_lista = self._montar_lista()
        painel_ficha = self._montar_ficha()
        splitter.addWidget(painel_lista)
        splitter.addWidget(painel_ficha)
        painel_lista.setMinimumWidth(280)
        painel_ficha.setMinimumWidth(520)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        splitter.setSizes([340, 860])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(splitter)

        self.atualizar()

    # ------------------------------------------------------------ montagem --
    def _montar_lista(self) -> QWidget:
        painel = QWidget()
        col = QVBoxLayout(painel)
        col.setContentsMargins(0, 0, 8, 0)
        col.setSpacing(10)

        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Buscar por nome ou login…")
        self.busca.setClearButtonEnabled(True)
        self.busca.textChanged.connect(lambda _t: self.atualizar())
        self.btn_novo = QPushButton("Novo usuário")
        self.btn_novo.setProperty("role", "primario")
        self.btn_novo.clicked.connect(self._novo_usuario)
        topo = QHBoxLayout()
        topo.addWidget(self.busca, 1)
        topo.addWidget(self.btn_novo)

        self.tabela = ListaFichas("Nenhum usuário cadastrado.")
        self.tabela.itemSelectionChanged.connect(self._ao_selecionar)
        self.tabela.itemDoubleClicked.connect(lambda _i: self._editar_usuario())

        self.contagem = QLabel()
        self.contagem.setProperty("role", "subtitulo")

        # Trocar a PRÓPRIA senha é outra coisa que redefinir a de um usuário
        # selecionado: pede a senha atual e não depende de seleção.
        minha, dentro = _bloco()
        self.minha_conta = QLabel()
        self.minha_conta.setProperty("role", "subtitulo")
        self.minha_conta.setWordWrap(True)
        self.btn_minha_senha = QPushButton("Trocar minha senha")
        self.btn_minha_senha.clicked.connect(self._trocar_minha_senha)
        dentro.setContentsMargins(14, 10, 14, 12)
        dentro.addWidget(_rotulo("Minha conta"))
        dentro.addWidget(self.minha_conta)
        dentro.addWidget(self.btn_minha_senha, 0, Qt.AlignLeft)

        col.addLayout(topo)
        col.addWidget(self.tabela, 1)
        col.addWidget(self.contagem)
        col.addWidget(minha)
        return painel

    def _montar_ficha(self) -> QWidget:
        painel = QWidget()
        col = QVBoxLayout(painel)
        col.setContentsMargins(20, 6, 6, 0)
        col.setSpacing(12)

        self.avatar = Avatar()
        self.titulo = QLabel()
        self.titulo.setProperty("role", "titulo")
        self.subtitulo = QLabel()
        self.subtitulo.setProperty("role", "subtitulo")
        self.subtitulo.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.etiqueta_nivel = _etiqueta("", "mudou")
        self.etiqueta_situacao = _etiqueta("", "ativo")
        etiquetas = QHBoxLayout()
        etiquetas.setSpacing(6)
        etiquetas.addWidget(self.etiqueta_nivel)
        etiquetas.addWidget(self.etiqueta_situacao)
        etiquetas.addStretch()
        texto = QVBoxLayout()
        texto.setSpacing(3)
        texto.addWidget(self.titulo)
        texto.addWidget(self.subtitulo)
        texto.addLayout(etiquetas)
        identificacao = QHBoxLayout()
        identificacao.setSpacing(16)
        identificacao.addWidget(self.avatar, 0, Qt.AlignTop)
        identificacao.addLayout(texto, 1)

        self.btn_editar = QPushButton("Editar dados")
        self.btn_editar.setToolTip("Nome, login e nível de acesso.")
        self.btn_editar.clicked.connect(self._editar_usuario)
        self.btn_redefinir_senha = QPushButton("Redefinir senha")
        self.btn_redefinir_senha.setToolTip("Para quem esqueceu a senha. Não pede a senha antiga.")
        self.btn_redefinir_senha.clicked.connect(self._redefinir_senha)
        self.btn_alternar_ativo = QPushButton("Desativar")
        self.btn_alternar_ativo.setProperty("role", "perigo")
        self.btn_alternar_ativo.clicked.connect(self._alternar_ativo)
        acoes = QHBoxLayout()
        acoes.setSpacing(8)
        acoes.addWidget(self.btn_editar)
        acoes.addWidget(self.btn_redefinir_senha)
        acoes.addStretch()
        acoes.addWidget(self.btn_alternar_ativo)

        self.cabecalho = QWidget()
        coluna_cabecalho = QVBoxLayout(self.cabecalho)
        coluna_cabecalho.setContentsMargins(0, 0, 0, 0)
        coluna_cabecalho.setSpacing(12)
        coluna_cabecalho.addLayout(identificacao)
        coluna_cabecalho.addLayout(acoes)

        self._corpo = QWidget()
        self._layout_corpo = QVBoxLayout(self._corpo)
        self._layout_corpo.setContentsMargins(0, 4, 8, 12)
        self._layout_corpo.setSpacing(14)
        self.rolagem = QScrollArea()
        self.rolagem.setProperty("role", "listaCartoes")
        self.rolagem.setWidgetResizable(True)
        self.rolagem.setFrameShape(QFrame.NoFrame)
        self.rolagem.setWidget(self._corpo)

        vazio_titulo = QLabel("Nenhum usuário selecionado")
        vazio_titulo.setProperty("role", "vazioTitulo")
        vazio_titulo.setAlignment(Qt.AlignCenter)
        vazio_texto = QLabel("Escolha alguém na lista para ver o acesso e a atividade, ou clique em Novo usuário.")
        vazio_texto.setProperty("role", "vazioTexto")
        vazio_texto.setAlignment(Qt.AlignCenter)
        vazio_texto.setWordWrap(True)
        self.painel_vazio = QWidget()
        coluna_vazio = QVBoxLayout(self.painel_vazio)
        coluna_vazio.addStretch(2)
        coluna_vazio.addWidget(vazio_titulo)
        coluna_vazio.addWidget(vazio_texto)
        coluna_vazio.addStretch(3)

        col.addWidget(self.cabecalho)
        col.addWidget(self.rolagem, 1)
        col.addWidget(self.painel_vazio, 1)
        return painel

    # --------------------------------------------------------------- dados --
    def atualizar(self) -> None:
        todos = repo.listar_usuarios(self.conn)
        termo = self.busca.text().strip().lower()
        self._usuarios = [u for u in todos if not termo or termo in u.nome.lower() or termo in u.login.lower()]
        self.tabela.blockSignals(True)
        self.tabela.clear()
        for u in self._usuarios:
            nivel = "Administrador" if u.admin else "Usuário"
            self.tabela.adicionar(u.id, u.nome, f"login {u.login} · {nivel}",
                                  "" if u.ativo else "desativado", apagado=not u.ativo)
        self.tabela.blockSignals(False)
        if not self.tabela.selecionar_id(self._usuario_atual_id):
            self._usuario_atual_id = None
        ativos = sum(1 for u in todos if u.ativo)
        self.contagem.setText(f"{len(todos)} usuário(s) · {ativos} ativo(s)")
        atual = sessao.usuario_atual()
        self.minha_conta.setText(
            f"Você está usando o sistema como <b>{atual.nome}</b> (login {atual.login})."
            if atual else "Nenhuma sessão aberta."
        )
        self._mostrar_ficha()

    def _ao_selecionar(self) -> None:
        self._usuario_atual_id = self.tabela.id_selecionado()
        self._mostrar_ficha()

    def _usuario(self):
        return next((u for u in self._usuarios if u.id == self._usuario_atual_id), None)

    def _mostrar_ficha(self) -> None:
        _limpar(self._layout_corpo)
        usuario = self._usuario()
        tem = usuario is not None
        self.cabecalho.setVisible(tem)
        self.rolagem.setVisible(tem)
        self.painel_vazio.setVisible(not tem)
        for botao in (self.btn_editar, self.btn_redefinir_senha, self.btn_alternar_ativo):
            botao.setEnabled(tem)
        if not tem:
            return

        self.avatar.definir(usuario.nome, apagado=not usuario.ativo)
        self.titulo.setText(usuario.nome)
        self.subtitulo.setText(f"login: {usuario.login}")
        self.etiqueta_nivel.setText("Administrador" if usuario.admin else "Usuário")
        self.etiqueta_situacao.setText("Ativo" if usuario.ativo else "Desativado")
        self.etiqueta_situacao.setProperty("tom", "ativo" if usuario.ativo else "saiu")
        self.etiqueta_situacao.style().unpolish(self.etiqueta_situacao)
        self.etiqueta_situacao.style().polish(self.etiqueta_situacao)
        eu = sessao.usuario_atual()
        sou_eu = eu is not None and eu.id == usuario.id
        self.btn_alternar_ativo.setText("Desativar" if usuario.ativo else "Reativar")
        self.btn_alternar_ativo.setProperty("role", "perigo" if usuario.ativo else "")
        self.btn_alternar_ativo.style().unpolish(self.btn_alternar_ativo)
        self.btn_alternar_ativo.style().polish(self.btn_alternar_ativo)
        self.btn_alternar_ativo.setEnabled(not sou_eu)
        self.btn_alternar_ativo.setToolTip("Você não pode desativar a própria conta." if sou_eu else
                                           "Desativado não entra no sistema; o histórico dele continua.")

        atividade = repo.listar_log_atividade(self.conn, usuario_id=usuario.id, limite=8)
        acessos = repo.quantidade_acessos_lembrados(self.conn, usuario.id)

        quadro, dentro = _bloco("Acesso")
        grade = QGridLayout()
        grade.setHorizontalSpacing(28)
        grade.setVerticalSpacing(2)
        numeros = (
            ("Usuário desde", formatar_data_br(usuario.criado_em[:10]) if usuario.criado_em else "—"),
            ("Última atividade", _data_hora_br(atividade[0].data_hora) if atividade else "nenhuma ainda"),
            ("Entra sem senha em", f"{acessos} computador(es)" if acessos else "nenhum computador"),
        )
        for coluna, (rotulo, valor) in enumerate(numeros):
            grade.addWidget(_rotulo(rotulo), 0, coluna)
            numero = QLabel(valor)
            numero.setProperty("role", "valorCampo")
            grade.addWidget(numero, 1, coluna)
            grade.setColumnStretch(coluna, 1)
        dentro.addLayout(grade)
        if acessos:
            self.btn_encerrar_acessos = QPushButton("Voltar a pedir a senha em todos os computadores")
            self.btn_encerrar_acessos.clicked.connect(self._encerrar_acessos)
            dentro.addWidget(self.btn_encerrar_acessos, 0, Qt.AlignLeft)
        self._layout_corpo.addWidget(quadro)

        quadro, dentro = _bloco("Atividade recente")
        if not atividade:
            dentro.addWidget(_dica("Nada registrado ainda."))
        for i, log in enumerate(atividade):
            if i:
                linha_fina = QFrame()
                linha_fina.setProperty("role", "hairline")
                dentro.addWidget(linha_fina)
            linha = QHBoxLayout()
            linha.setSpacing(14)
            quando = QLabel(_data_hora_br(log.data_hora))
            quando.setProperty("role", "subtitulo")
            quando.setFixedWidth(130)
            oque = QLabel(
                f"<b>{ACAO_LABEL.get(log.acao, log.acao)}</b> "
                f"{ENTIDADE_LABEL.get(log.entidade, log.entidade).lower()}"
                + (f" — {log.detalhes}" if log.detalhes else "")
            )
            oque.setWordWrap(True)
            linha.addWidget(quando, 0, Qt.AlignTop)
            linha.addWidget(oque, 1)
            dentro.addLayout(linha)
        if atividade:
            dentro.addWidget(_dica("O histórico completo fica em Sistema · Log de atividades."))
        self._layout_corpo.addWidget(quadro)
        self._layout_corpo.addStretch()

    # --------------------------------------------------------------- ações --
    def _novo_usuario(self) -> None:
        dialogo = DialogoUsuario(self.conn, parent=self)
        if dialogo.exec() != QDialog.Accepted:
            return
        self._usuario_atual_id = dialogo.usuario_id
        self.busca.clear()
        self.atualizar()

    def _editar_usuario(self) -> None:
        usuario = self._usuario()
        if usuario is None:
            return
        if DialogoUsuario(self.conn, usuario, self).exec() == QDialog.Accepted:
            self.atualizar()

    def _redefinir_senha(self) -> None:
        usuario = self._usuario()
        if usuario is None:
            return
        dialogo = _DialogoNovaSenha(usuario.nome, self)
        if dialogo.exec() != QDialog.Accepted:
            return
        repo.alterar_senha(self.conn, usuario.id, dialogo.senha.text())
        # O login vai junto: quem esqueceu a senha costuma ter esquecido o
        # login também, e entrar com o nome no lugar dele dava "senha
        # incorreta" com a senha nova certinha.
        aviso = f"Senha de {usuario.nome} atualizada.\n\nPara entrar, use o login: {usuario.login}"
        if not usuario.ativo:
            aviso += "\n\nAtenção: este usuário está DESATIVADO — reative-o para conseguir entrar."
        QMessageBox.information(self, "Senha redefinida", aviso)
        self.atualizar()

    def _alternar_ativo(self) -> None:
        usuario = self._usuario()
        if usuario is None:
            return
        if usuario.id == (sessao.usuario_atual().id if sessao.usuario_atual() else None):
            QMessageBox.warning(self, "Não permitido", "Você não pode desativar a própria conta.")
            return
        if usuario.ativo:
            resposta = QMessageBox.question(
                self, "Desativar usuário",
                f"Desativar {usuario.nome}? Ele deixa de conseguir entrar; o histórico dele continua.",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if resposta != QMessageBox.Yes:
                return
        repo.definir_ativo(self.conn, usuario.id, not usuario.ativo)
        self.atualizar()

    def _encerrar_acessos(self) -> None:
        usuario = self._usuario()
        if usuario is None:
            return
        repo.encerrar_acessos_lembrados(self.conn, usuario.id)
        self.atualizar()

    def _trocar_minha_senha(self) -> None:
        from .login import DialogoTrocarMinhaSenha

        usuario = sessao.usuario_atual()
        if usuario is None:
            return
        if DialogoTrocarMinhaSenha(self.conn, usuario, self).exec() == QDialog.Accepted:
            QMessageBox.information(self, "Senha alterada", "Sua senha foi atualizada.")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(1100, 700)
