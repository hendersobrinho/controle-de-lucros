"""Visualização do log de atividade: quem fez o quê e quando. Filtra por
usuário e período — aqui uma tabela cronológica é o formato certo, não um
gráfico (não tem "insight" pra extrair de uma lista de eventos, só histórico)."""
from __future__ import annotations

import datetime as dt

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import repositories as repo

ACAO_LABEL = {
    "criar": "Criou",
    "atualizar": "Atualizou",
    "excluir": "Excluiu",
    "fechar": "Fechou",
    "reabrir": "Reabriu",
    "encerrar": "Encerrou",
    "ativar": "Ativou",
    "desativar": "Desativou",
    "trocar_senha": "Trocou senha",
}

ENTIDADE_LABEL = {
    "empresa": "Empresa",
    "socio": "Sócio",
    "alteracao_contratual": "Alteração contratual",
    "vinculo_societario": "Vínculo societário",
    "distribuicao_lucro": "Distribuição de lucro",
    "movimentacao": "Movimentação",
    "usuario": "Usuário",
}


class LogAtividadesView(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn

        self.usuario = QComboBox()
        self.usuario.currentIndexChanged.connect(lambda _: self._carregar())

        self.data_de = QDateEdit(calendarPopup=True)
        self.data_de.setDisplayFormat("dd/MM/yyyy")
        self.data_de.setDate(dt.date.today() - dt.timedelta(days=30))
        self.data_de.dateChanged.connect(lambda _: self._carregar())

        self.data_ate = QDateEdit(calendarPopup=True)
        self.data_ate.setDisplayFormat("dd/MM/yyyy")
        self.data_ate.setDate(dt.date.today())
        self.data_ate.dateChanged.connect(lambda _: self._carregar())

        self.busca = QLineEdit()
        self.busca.setPlaceholderText("Buscar nos detalhes…")
        self.busca.textChanged.connect(lambda _: self._filtrar_exibicao())

        topo = QHBoxLayout()
        topo.addWidget(QLabel("Usuário:"))
        topo.addWidget(self.usuario)
        topo.addWidget(QLabel("De:"))
        topo.addWidget(self.data_de)
        topo.addWidget(QLabel("até:"))
        topo.addWidget(self.data_ate)
        topo.addWidget(self.busca, 1)

        self.resumo = QLabel()
        self.resumo.setProperty("role", "subtitulo")

        self.tabela = QTableWidget(0, 5)
        self.tabela.setHorizontalHeaderLabels(["Data/hora", "Usuário", "Ação", "Onde", "Detalhes"])
        self.tabela.setAlternatingRowColors(True)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela.verticalHeader().setVisible(False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addLayout(topo)
        layout.addWidget(self.resumo)
        layout.addWidget(self.tabela, 1)

        self._logs: list = []
        self.atualizar()

    def atualizar(self) -> None:
        usuario_id_anterior = self.usuario.currentData()
        self.usuario.blockSignals(True)
        self.usuario.clear()
        self.usuario.addItem("Todos os usuários", None)
        for u in repo.listar_usuarios(self.conn):
            self.usuario.addItem(u.nome, u.id)
        idx = self.usuario.findData(usuario_id_anterior)
        self.usuario.setCurrentIndex(idx if idx >= 0 else 0)
        self.usuario.blockSignals(False)
        self._carregar()

    def _carregar(self) -> None:
        self._logs = repo.listar_log_atividade(
            self.conn,
            data_de=self.data_de.date().toString("yyyy-MM-dd"),
            data_ate=self.data_ate.date().toString("yyyy-MM-dd"),
            usuario_id=self.usuario.currentData(),
        )
        self._filtrar_exibicao()

    def _filtrar_exibicao(self) -> None:
        termo = self.busca.text().strip().lower()
        logs = self._logs
        if termo:
            logs = [
                l
                for l in logs
                if termo in (l.detalhes or "").lower() or termo in ENTIDADE_LABEL.get(l.entidade, l.entidade).lower()
            ]

        self.resumo.setText(f"{len(logs)} evento(s) no período.")
        self.tabela.setRowCount(len(logs))
        for row, log in enumerate(logs):
            data_hora = log.data_hora.replace("T", " ")
            valores = [
                data_hora,
                log.usuario_nome,
                ACAO_LABEL.get(log.acao, log.acao),
                ENTIDADE_LABEL.get(log.entidade, log.entidade),
                log.detalhes or "—",
            ]
            for col, valor in enumerate(valores):
                self.tabela.setItem(row, col, QTableWidgetItem(valor))
        self.tabela.resizeColumnsToContents()
