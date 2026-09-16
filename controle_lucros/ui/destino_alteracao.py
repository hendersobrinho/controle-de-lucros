"""Em qual alteração contratual entra a movimentação que está sendo importada.

Movimentar sócio é alterar o contrato social, então o que vem do relatório
precisa cair dentro de uma alteração contratual — nova ou já aberta. Esta é a
pergunta que falta entre ler o arquivo e gravar, e ela é feita uma vez só,
valendo pra todas as linhas daquela empresa.

Fica em módulo próprio porque quem pergunta são duas telas: o card da aba
Alterações (que já tem uma alteração aberta e só confirma) e a tela geral de
Importação de cadastro (que não tem nenhuma escolhida ainda).
"""
from __future__ import annotations

import datetime as dt

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
)

from .. import repositories as repo
from ..models import AlteracaoContratual

DESCRICAO_PADRAO = "Importação do relatório de sócios"


class DialogoDestinoAlteracao(QDialog):
    """Devolve, em `resolver()`, o id da alteração que vai receber a
    importação — criando-a na hora, se a escolha tiver sido essa.

    Alteração fechada não entra na lista: ela não aceita movimentação nova
    sem ser destrancada antes, e oferecê-la só levaria a um erro no fim."""

    def __init__(
        self,
        conn,
        empresa_id: int,
        resumo_leitura: str,
        data_sugerida: str | None = None,
        alteracao_atual_id: int | None = None,
        parent=None,
    ):
        super().__init__(parent)
        self.conn = conn
        self.empresa_id = empresa_id
        self.resumo_leitura = resumo_leitura
        self.setWindowTitle("Onde lançar esta importação")
        self.setMinimumWidth(520)

        self._abertas = [a for a in repo.listar_alteracoes(conn, empresa_id) if not a.fechada]

        explicacao = QLabel(
            f"{resumo_leitura}\n\nMovimentar sócio é alteração contratual: escolha em qual "
            "delas esta importação entra. Todos os vínculos criados ou encerrados por ela "
            "ficam amarrados à alteração escolhida."
        )
        explicacao.setWordWrap(True)
        explicacao.setProperty("role", "subtitulo")

        self.opcao_nova = QRadioButton("Cadastrar uma alteração contratual nova")
        self.opcao_existente = QRadioButton("Associar a uma alteração já existente")
        grupo = QButtonGroup(self)
        grupo.addButton(self.opcao_nova)
        grupo.addButton(self.opcao_existente)

        estado = repo.estado_atual_empresa(conn, empresa_id)
        numero = repo.proximo_numero_alteracao(conn, empresa_id)
        self.rotulo_nova = QLabel(
            f"Vai nascer como a alteração Nº {numero} de {estado['nome']}, herdando o capital "
            "social e a quantidade de cotas vigentes."
        )
        self.rotulo_nova.setWordWrap(True)
        self.rotulo_nova.setProperty("role", "subtitulo")

        self.data = QDateEdit(calendarPopup=True)
        self.data.setDisplayFormat("dd/MM/yyyy")
        # A data do quadro societário é a data em que o relatório retrata a
        # sociedade — é ela que a alteração está registrando, não o dia em que
        # a importação foi feita.
        self.data.setDate(_para_qdate(data_sugerida))

        self.descricao = QLineEdit(DESCRICAO_PADRAO)

        self.existentes = QComboBox()
        for a in self._abertas:
            rotulo = f"Nº {a.numero} — {_data_br(a.data)}"
            if a.descricao:
                rotulo += f" — {a.descricao}"
            self.existentes.addItem(rotulo, a.id)

        self.botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.botoes.button(QDialogButtonBox.Ok).setText("Importar")
        self.botoes.accepted.connect(self.accept)
        self.botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.addWidget(explicacao)
        layout.addSpacing(6)
        layout.addWidget(self.opcao_nova)
        layout.addWidget(self.rotulo_nova)
        layout.addWidget(QLabel("Data da alteração"))
        layout.addWidget(self.data)
        layout.addWidget(QLabel("Descrição"))
        layout.addWidget(self.descricao)
        layout.addSpacing(6)
        layout.addWidget(self.opcao_existente)
        layout.addWidget(self.existentes)
        layout.addSpacing(6)
        layout.addWidget(self.botoes)

        self.opcao_nova.toggled.connect(self._ajustar_campos)

        # Chamada de dentro de uma alteração já aberta, a escolha óbvia é ela
        # mesma — o contrário obrigaria a reescolher o que a pessoa acabou de
        # abrir na tela.
        indice_atual = self.existentes.findData(alteracao_atual_id) if alteracao_atual_id else -1
        if indice_atual >= 0:
            self.existentes.setCurrentIndex(indice_atual)
            self.opcao_existente.setChecked(True)
        else:
            self.opcao_nova.setChecked(True)

        if not self._abertas:
            self.opcao_existente.setEnabled(False)
            self.existentes.setEnabled(False)
            self.existentes.addItem("— esta empresa não tem alteração aberta —", None)

        self._ajustar_campos()

    def _ajustar_campos(self, *_args) -> None:
        nova = self.opcao_nova.isChecked()
        for campo in (self.rotulo_nova, self.data, self.descricao):
            campo.setEnabled(nova)
        self.existentes.setEnabled(not nova and bool(self._abertas))

    def resolver(self) -> int:
        """O id da alteração escolhida, criando-a se for o caso. Levanta
        ValueError (de repositories) se o período estiver trancado — quem
        chama já trata isso pra avisar em vez de quebrar."""
        if not self.opcao_nova.isChecked():
            return self.existentes.currentData()

        estado = repo.estado_atual_empresa(self.conn, self.empresa_id)
        return repo.salvar_alteracao(
            self.conn,
            AlteracaoContratual(
                id=None,
                empresa_id=self.empresa_id,
                numero=repo.proximo_numero_alteracao(self.conn, self.empresa_id),
                data=self.data.date().toString("yyyy-MM-dd"),
                nome_empresa=estado["nome"],
                capital_social=estado["capital_social"],
                quantidade_cotas=estado["quantidade_cotas"],
                descricao=self.descricao.text().strip() or DESCRICAO_PADRAO,
            ),
        )


def _para_qdate(data_iso: str | None):
    from PySide6.QtCore import QDate

    if data_iso:
        convertida = QDate.fromString(data_iso, "yyyy-MM-dd")
        if convertida.isValid():
            return convertida
    return QDate.currentDate()


def _data_br(data_iso: str) -> str:
    try:
        return dt.datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    except ValueError:
        return data_iso
