"""Backup e restauração do banco — só para administradores. Backup manual a
qualquer momento, backup automático opcional (uma vez por dia ao entrar no
sistema), pasta de destino configurável, e restauração a partir de um
arquivo de backup (da pasta configurada ou de qualquer lugar).

No topo, onde o banco fica: é daqui que o administrador leva o banco pra
pasta do servidor, pra os outros PCs do escritório usarem o mesmo."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .. import backup, db
from .common import TabelaLista
from .local_banco import botao_tutorial, descrever_local, escolher_banco_existente, levar_banco_para_rede
from .ocupado import ocupado

COLUNAS = ["Arquivo", "Criado em", "Tamanho"]


class BackupView(QWidget):
    def __init__(self, conn, parent=None):
        super().__init__(parent)
        self.conn = conn
        self._backups: list[dict] = []

        titulo_local = QLabel("Onde fica o banco")
        titulo_local.setProperty("role", "secao")

        self.rotulo_banco = QLabel()
        self.rotulo_banco.setWordWrap(True)
        self.rotulo_banco.setProperty("role", "mono")
        self.rotulo_banco.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.rotulo_local = QLabel()
        self.rotulo_local.setWordWrap(True)
        self.rotulo_local.setProperty("role", "subtitulo")

        btn_levar = QPushButton("Levar o banco para o servidor…")
        btn_levar.setToolTip(
            "Copia o banco deste computador para uma pasta compartilhada. Depois, nos outros "
            "computadores, use \"Usar um banco que já está no servidor\"."
        )
        btn_levar.clicked.connect(self._levar_para_servidor)

        btn_usar_outro = QPushButton("Usar um banco que já está no servidor…")
        btn_usar_outro.clicked.connect(self._usar_outro_banco)

        linha_local = QHBoxLayout()
        linha_local.addWidget(btn_levar)
        linha_local.addWidget(btn_usar_outro)
        linha_local.addSpacing(8)
        linha_local.addWidget(botao_tutorial(self))
        linha_local.addStretch()

        titulo = QLabel("Backup do banco de dados")
        titulo.setProperty("role", "secao")

        explicacao = QLabel(
            "Faça uma cópia de segurança do banco a qualquer momento, ou deixe o sistema fazer "
            "automaticamente (uma vez por dia) ao entrar. Restaurar um backup substitui todos os "
            "dados atuais pelos daquele arquivo — o sistema fecha depois pra recarregar do zero."
        )
        explicacao.setWordWrap(True)
        explicacao.setProperty("role", "subtitulo")

        self.rotulo_pasta = QLabel()
        self.rotulo_pasta.setWordWrap(True)
        self.rotulo_pasta.setProperty("role", "mono")

        btn_escolher_pasta = QPushButton("Escolher pasta de destino…")
        btn_escolher_pasta.clicked.connect(self._escolher_pasta)

        linha_pasta = QHBoxLayout()
        linha_pasta.addWidget(QLabel("Pasta dos backups:"))
        linha_pasta.addWidget(self.rotulo_pasta, 1)
        linha_pasta.addWidget(btn_escolher_pasta)

        self.check_automatico = QCheckBox("Fazer backup automaticamente ao entrar no sistema (uma vez por dia)")
        self.check_automatico.toggled.connect(self._alternar_automatico)

        self.btn_backup_agora = QPushButton("Fazer backup agora")
        self.btn_backup_agora.setProperty("role", "primario")
        self.btn_backup_agora.clicked.connect(self._fazer_backup_agora)

        self.btn_importar = QPushButton("Importar arquivo de backup…")
        self.btn_importar.clicked.connect(self._importar_arquivo)

        linha_acoes = QHBoxLayout()
        linha_acoes.addWidget(self.btn_backup_agora)
        linha_acoes.addWidget(self.btn_importar)
        linha_acoes.addStretch()

        subtitulo_lista = QLabel("Backups existentes")
        subtitulo_lista.setProperty("role", "secao")

        self.tabela = TabelaLista(0, len(COLUNAS), coluna_flexivel=0,
                                  mensagem_vazia="Nenhum backup gerado ainda.")
        self.tabela.setHorizontalHeaderLabels(COLUNAS)
        self.tabela.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tabela.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tabela.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tabela.itemSelectionChanged.connect(self._atualizar_disponibilidade)

        self.btn_abrir_pasta = QPushButton("Abrir pasta")
        self.btn_abrir_pasta.clicked.connect(self._abrir_pasta)

        self.btn_restaurar = QPushButton("Restaurar este backup")
        self.btn_restaurar.setProperty("role", "perigo")
        self.btn_restaurar.clicked.connect(self._restaurar_selecionado)

        linha_lista_botoes = QHBoxLayout()
        linha_lista_botoes.addWidget(self.btn_abrir_pasta)
        linha_lista_botoes.addStretch()
        linha_lista_botoes.addWidget(self.btn_restaurar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(titulo_local)
        layout.addWidget(self.rotulo_banco)
        layout.addWidget(self.rotulo_local)
        layout.addLayout(linha_local)
        layout.addSpacing(12)
        layout.addWidget(titulo)
        layout.addWidget(explicacao)
        layout.addLayout(linha_pasta)
        layout.addWidget(self.check_automatico)
        layout.addLayout(linha_acoes)
        layout.addWidget(subtitulo_lista)
        layout.addWidget(self.tabela, 1)
        layout.addLayout(linha_lista_botoes)

        self.atualizar()

    def atualizar(self) -> None:
        caminho_banco = db.get_db_path()
        self.rotulo_banco.setText(str(caminho_banco))
        self.rotulo_local.setText(descrever_local(caminho_banco))
        self.rotulo_pasta.setText(str(backup.pasta_backup_configurada()))
        self.check_automatico.blockSignals(True)
        self.check_automatico.setChecked(backup.automatico_habilitado())
        self.check_automatico.blockSignals(False)

        self._backups = backup.listar_backups()
        self.tabela.setRowCount(len(self._backups))
        for row, item in enumerate(self._backups):
            valores = [
                item["nome"],
                item["modificado_em"].strftime("%d/%m/%Y %H:%M"),
                backup.formatar_tamanho(item["tamanho"]),
            ]
            for col, valor in enumerate(valores):
                self.tabela.setItem(row, col, QTableWidgetItem(valor))
        self.tabela.ajustar_colunas()
        self._atualizar_disponibilidade()

    def _atualizar_disponibilidade(self) -> None:
        self.btn_restaurar.setEnabled(bool(self.tabela.selectionModel().selectedRows()))

    def _levar_para_servidor(self) -> None:
        resposta = QMessageBox.question(
            self,
            "Levar o banco para o servidor",
            "O banco deste computador vai ser copiado para a pasta que você escolher, e este "
            "computador passa a usar a cópia de lá. O arquivo daqui fica como estava, mas deixa "
            "de ser usado.\n\nDepois, em cada um dos outros computadores, escolha \"Usar um "
            "banco que já está no servidor\" e aponte para o mesmo arquivo.\n\nContinuar?",
        )
        if resposta != QMessageBox.Yes:
            return
        destino = levar_banco_para_rede(self.conn, self)
        if destino is not None:
            self._fechar_para_trocar_de_banco(destino)

    def _usar_outro_banco(self) -> None:
        destino = escolher_banco_existente(self)
        if destino is not None:
            self._fechar_para_trocar_de_banco(destino)

    def _fechar_para_trocar_de_banco(self, destino: Path) -> None:
        """A conexão aberta continua no banco antigo e as telas mostram o que
        leram dele — recomeçar do zero é o jeito seguro de ninguém gravar no
        arquivo errado."""
        QMessageBox.information(
            self,
            "Banco trocado",
            f"Este computador agora usa o banco em:\n{destino}\n\n"
            "O sistema vai fechar agora — abra novamente.",
        )
        QApplication.instance().quit()

    def _escolher_pasta(self) -> None:
        pasta = QFileDialog.getExistingDirectory(
            self, "Escolher pasta de destino dos backups", str(backup.pasta_backup_configurada())
        )
        if not pasta:
            return
        backup.definir_pasta_backup(Path(pasta))
        self.atualizar()

    def _alternar_automatico(self, ligado: bool) -> None:
        backup.definir_automatico(ligado)

    def _fazer_backup_agora(self) -> None:
        try:
            with ocupado(self, "Backup", "Copiando o banco de dados…"):
                caminho = backup.criar_backup(self.conn)
        except (OSError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Erro ao fazer backup", db.explicar_erro(exc))
            return
        self.atualizar()
        QMessageBox.information(self, "Backup concluído", f"Backup salvo em:\n{caminho}")

    def _abrir_pasta(self) -> None:
        pasta = backup.pasta_backup_configurada()
        pasta.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(pasta)))

    def _importar_arquivo(self) -> None:
        caminho, _ = QFileDialog.getOpenFileName(
            self, "Selecionar arquivo de backup", str(backup.pasta_backup_configurada()), "Banco de dados (*.db)"
        )
        if not caminho:
            return
        self._confirmar_e_restaurar(Path(caminho))

    def _restaurar_selecionado(self) -> None:
        linhas = self.tabela.selectionModel().selectedRows()
        if not linhas:
            return
        item = self._backups[linhas[0].row()]
        self._confirmar_e_restaurar(item["caminho"])

    def _confirmar_e_restaurar(self, caminho_backup: Path) -> None:
        resposta = QMessageBox.warning(
            self,
            "Restaurar backup",
            f"Isso vai substituir TODOS os dados atuais pelos do arquivo:\n\n{caminho_backup.name}\n\n"
            "Essa ação não pode ser desfeita. O sistema vai fechar em seguida — abra de novo pra "
            "carregar os dados restaurados."
            + (
                "\n\nO banco fica no servidor: peça a quem estiver com o programa aberto em outro "
                "computador que feche e abra de novo depois."
                if db.banco_em_rede(db.get_db_path()) else ""
            )
            + "\n\nTem certeza que quer continuar?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if resposta != QMessageBox.Yes:
            return
        try:
            with ocupado(self, "Backup", "Restaurando o banco de dados…"):
                backup.restaurar_backup(caminho_backup)
        except (OSError, ValueError, sqlite3.Error) as exc:
            QMessageBox.warning(self, "Erro ao restaurar", db.explicar_erro(exc))
            return
        QMessageBox.information(
            self, "Backup restaurado", "Dados restaurados com sucesso. O sistema vai fechar agora — abra novamente."
        )
        QApplication.instance().quit()
