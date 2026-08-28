from __future__ import annotations

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMainWindow, QMessageBox, QStackedWidget, QVBoxLayout, QWidget

from ..models import Usuario
from .alteracoes_view import AlteracoesView
from .backup_view import BackupView
from .dashboard_empresa import DashboardEmpresaView
from .dashboard_visao_geral import DashboardVisaoGeralView
from .distribuicao_anual_view import DistribuicaoAnualView
from .empresas_tab import EmpresasTab
from .importacao_cadastro_view import ImportacaoCadastroView
from .log_atividades_view import LogAtividadesView
from .login import DialogoTrocarMinhaSenha
from .sidebar import Sidebar
from .sobre_view import SobreView
from .socios_tab import SociosTab
from .theme import estado as tema_estado
from .usuarios_tab import UsuariosTab

TITULOS = {
    "empresas.cadastro": "Empresas  ·  Cadastro",
    "empresas.alteracoes": "Empresas  ·  Alterações contratuais",
    "empresas.importar": "Empresas  ·  Importação em massa",
    "socios": "Sócios",
    "distribuicao": "Distribuição anual",
    "dashboard.geral": "Dashboard  ·  Visão geral",
    "dashboard.empresa": "Dashboard  ·  Análise por empresa",
    "sistema.log": "Log de atividades",
    "sistema.usuarios": "Usuários",
    "sistema.backup": "Backup",
    "sistema.sobre": "Sobre",
}


class MainWindow(QMainWindow):
    def __init__(self, conn, usuario: Usuario, parent=None):
        super().__init__(parent)
        self.conn = conn
        self.usuario = usuario
        self.logout_solicitado = False
        self.setWindowTitle("Controle de Distribuição de Lucros")
        self.resize(1180, 720)

        self.cadastro = EmpresasTab(conn)
        self.alteracoes = AlteracoesView(conn)
        self.importacao_cadastro = ImportacaoCadastroView(conn)
        self.socios_tab = SociosTab(conn)
        self.distribuicao = DistribuicaoAnualView(conn)
        self.dashboard_geral = DashboardVisaoGeralView(conn)
        self.dashboard_empresa = DashboardEmpresaView(conn)
        self.log_atividades = LogAtividadesView(conn)
        self.usuarios_tab = UsuariosTab(conn)
        self.backup_view = BackupView(conn)
        self.sobre_view = SobreView()
        self.cadastro.definir_callback_selecao(lambda empresa: self.alteracoes.selecionar_empresa(empresa.id))

        self._paginas = {
            "empresas.cadastro": self.cadastro,
            "empresas.alteracoes": self.alteracoes,
            "empresas.importar": self.importacao_cadastro,
            "socios": self.socios_tab,
            "distribuicao": self.distribuicao,
            "dashboard.geral": self.dashboard_geral,
            "dashboard.empresa": self.dashboard_empresa,
            "sistema.log": self.log_atividades,
            "sistema.usuarios": self.usuarios_tab,
            "sistema.backup": self.backup_view,
            "sistema.sobre": self.sobre_view,
        }

        self.pilha = QStackedWidget()
        for pagina in self._paginas.values():
            self.pilha.addWidget(pagina)

        self.titulo_pagina = QLabel()
        self.titulo_pagina.setProperty("role", "titulo")

        coluna_conteudo = QVBoxLayout()
        coluna_conteudo.setContentsMargins(24, 20, 24, 0)
        coluna_conteudo.setSpacing(14)
        coluna_conteudo.addWidget(self.titulo_pagina)
        coluna_conteudo.addWidget(self.pilha, 1)
        conteudo = QWidget()
        conteudo.setLayout(coluna_conteudo)

        self.sidebar = Sidebar()
        self.sidebar.definir_usuario(usuario.nome, usuario.admin)
        self.sidebar.navegar.connect(self._ir_para)
        self.sidebar.trocar_senha.connect(self._trocar_senha)
        self.sidebar.sair.connect(self._sair)
        tema_estado().mudou.connect(self._retemar_pagina_atual)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.sidebar)
        layout.addWidget(conteudo, 1)
        self.setCentralWidget(central)

        self._ir_para("empresas.cadastro")

    def _ir_para(self, chave: str) -> None:
        if chave in ("sistema.usuarios", "sistema.backup") and not self.usuario.admin:
            return
        pagina = self._paginas[chave]
        self.pilha.setCurrentWidget(pagina)
        self.titulo_pagina.setText(TITULOS[chave])
        self.sidebar.marcar(chave)
        if hasattr(pagina, "atualizar"):
            pagina.atualizar()

    def _retemar_pagina_atual(self) -> None:
        """QSS global já se reaplica sozinho — isso só força a página visível
        a recarregar (gráficos e afins têm cor fixada em objetos nativos do
        Qt, não em QSS, então só atualizam de novo se a gente pedir)."""
        pagina = self.pilha.currentWidget()
        if hasattr(pagina, "atualizar"):
            pagina.atualizar()

    def _trocar_senha(self) -> None:
        dialogo = DialogoTrocarMinhaSenha(self.conn, self.usuario, self)
        if dialogo.exec() == QDialog.Accepted:
            QMessageBox.information(self, "Senha alterada", "Sua senha foi atualizada.")

    def _sair(self) -> None:
        resposta = QMessageBox.question(self, "Sair", "Deseja realmente sair e voltar pra tela de login?")
        if resposta != QMessageBox.Yes:
            return
        self.logout_solicitado = True
        self.close()
