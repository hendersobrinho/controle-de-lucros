"""Importação de planilha de distribuição — a parte comum entre a aba anual
e a trimestral.

As duas telas leem a mesma planilha (CPF, Sócio, Valor Distribuído,
Pró-labore, IRRF) e enfrentam o mesmo problema antes de aplicar: descobrir a
qual sócio cadastrado cada linha se refere, sem nunca criar duplicata. O que
muda entre elas é só onde o valor é gravado no fim.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from .. import repositories as repo
from ..models import Socio
from .common import formatar_valor_br
from .theme import SAIU_FG


def associar_linhas(
    conn,
    linhas_importadas: list[dict],
    socios_ativos: set[int],
    periodo: str,
) -> tuple[list[tuple[dict, int]], list[dict]]:
    """Reconhece cada linha da planilha contra os sócios já cadastrados (por
    CPF, com nome como retaguarda) pra nunca criar duplicata — o que não bate
    com segurança vira pendência pra revisão humana.

    `socios_ativos` são os sócios que a tela está mostrando no período; quem
    existe no cadastro mas está fora dessa lista também vira pendência, que é
    a trava que pega planilha importada na empresa (ou no período) errado.
    `periodo` entra nesse aviso — "em 2025", "no 2º trimestre de 2025"."""
    todos_socios = repo.listar_socios(conn)
    por_cpf = {repo.normalizar_documento(s.cpf): s for s in todos_socios if s.cpf and s.cpf.strip()}
    por_nome: dict[str, list] = {}
    for s in todos_socios:
        por_nome.setdefault(s.nome.strip().lower(), []).append(s)

    resolvidos: list[tuple[dict, int]] = []
    pendencias: list[dict] = []

    for linha in linhas_importadas:
        socio = por_cpf.get(repo.normalizar_documento(linha["cpf"])) if linha["cpf"] else None
        motivo = None

        if socio is None and linha["nome"]:
            candidatos = por_nome.get(linha["nome"].strip().lower(), [])
            if len(candidatos) == 1:
                socio = candidatos[0]
            elif len(candidatos) > 1:
                motivo = f'Encontrei {len(candidatos)} sócios cadastrados com o nome "{linha["nome"]}" — escolha o correto.'

        if socio is not None and socio.id not in socios_ativos:
            pendencias.append(
                {
                    **linha,
                    "sugestao": socio,
                    "aviso": f"Sócio já cadastrado, mas sem vínculo ativo com esta empresa {periodo}. Confirme antes de aplicar.",
                }
            )
            continue

        if socio is not None:
            resolvidos.append((linha, socio.id))
            continue

        if motivo is None:
            motivo = "Nenhum sócio cadastrado bate com esse CPF/nome — cadastre um novo ou vincule manualmente."
        pendencias.append({**linha, "sugestao": None, "aviso": motivo})

    return resolvidos, pendencias


class DialogoRevisaoImportacao(QDialog):
    """Linhas da planilha que não bateram com segurança contra um sócio já
    cadastrado (CPF ausente, nome ambíguo, ou sócio sem vínculo com esta
    empresa) — cada uma exige uma decisão humana antes de aplicar, pra nunca
    duplicar sócio por engano."""

    def __init__(self, conn, pendencias: list[dict], parent=None):
        super().__init__(parent)
        self.conn = conn
        self._socios = repo.listar_socios(conn)
        self._linhas_ui: list[tuple[dict, QComboBox]] = []

        self.setWindowTitle("Revisar linhas da planilha")
        self.setMinimumSize(680, 480)

        aviso = QLabel(
            f"{len(pendencias)} linha(s) da planilha não puderam ser associadas automaticamente a um "
            "sócio já cadastrado. Confira cada uma abaixo — nada é aplicado sem sua confirmação."
        )
        aviso.setWordWrap(True)
        aviso.setProperty("role", "subtitulo")

        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        conteudo = QWidget()
        coluna = QVBoxLayout(conteudo)
        coluna.setSpacing(10)
        for pendencia in pendencias:
            coluna.addWidget(self._montar_linha(pendencia))
        coluna.addStretch()
        area.setWidget(conteudo)

        botoes = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        botoes.button(QDialogButtonBox.Ok).setText("Aplicar selecionados")
        botoes.accepted.connect(self.accept)
        botoes.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(aviso)
        layout.addWidget(area, 1)
        layout.addWidget(botoes)

    def _montar_linha(self, pendencia: dict) -> QWidget:
        caixa = QFrame()
        caixa.setProperty("role", "card")
        col = QVBoxLayout(caixa)
        col.setContentsMargins(14, 10, 14, 10)
        col.setSpacing(6)

        cpf_texto = pendencia["cpf"] or "não informado"
        nome_texto = pendencia["nome"] or "(sem nome na planilha)"
        titulo = QLabel(
            f"<b>{nome_texto}</b> — CPF: {cpf_texto} — R$ {formatar_valor_br(pendencia['valor_distribuido'])}"
        )
        col.addWidget(titulo)

        if pendencia.get("aviso"):
            rotulo_aviso = QLabel(f"⚠ {pendencia['aviso']}")
            rotulo_aviso.setWordWrap(True)
            rotulo_aviso.setStyleSheet(f"color: {SAIU_FG()}; font-size: 11px;")
            col.addWidget(rotulo_aviso)

        linha_acoes = QHBoxLayout()
        combo = QComboBox()
        self._preencher_combo_socios(combo)
        sugestao = pendencia.get("sugestao")
        if sugestao is not None:
            idx = combo.findData(sugestao.id)
            if idx >= 0:
                combo.setCurrentIndex(idx)

        btn_cadastrar = QPushButton("Cadastrar como novo sócio")
        btn_cadastrar.clicked.connect(lambda: self._cadastrar_novo(pendencia, combo, btn_cadastrar))

        linha_acoes.addWidget(QLabel("Vincular a:"))
        linha_acoes.addWidget(combo, 1)
        linha_acoes.addWidget(btn_cadastrar)
        col.addLayout(linha_acoes)

        self._linhas_ui.append((pendencia, combo))
        return caixa

    def _preencher_combo_socios(self, combo: QComboBox) -> None:
        combo.clear()
        combo.addItem("— não importar esta linha —", None)
        for s in self._socios:
            combo.addItem(f"{s.nome} ({s.cpf or 'sem CPF'})", s.id)

    def _cadastrar_novo(self, pendencia: dict, combo: QComboBox, botao: QPushButton) -> None:
        if not pendencia["nome"]:
            QMessageBox.warning(
                self, "Cadastrar sócio",
                "Esta linha não tem nome na planilha — cadastre manualmente na aba Sócios e volte aqui pra vincular.",
            )
            return
        resposta = QMessageBox.question(
            self,
            "Cadastrar novo sócio",
            f'Cadastrar "{pendencia["nome"]}" (CPF: {pendencia["cpf"] or "não informado"}) como um sócio novo?',
        )
        if resposta != QMessageBox.Yes:
            return
        try:
            novo_id = repo.salvar_socio(self.conn, Socio(id=None, nome=pendencia["nome"], cpf=pendencia["cpf"] or ""))
        except ValueError as exc:
            QMessageBox.warning(self, "Erro ao cadastrar sócio", str(exc))
            return
        self._socios = repo.listar_socios(self.conn)
        self._preencher_combo_socios(combo)
        idx = combo.findData(novo_id)
        combo.setCurrentIndex(idx if idx >= 0 else 0)
        botao.setEnabled(False)
        botao.setText("Sócio cadastrado ✓")

    def resolvidos(self) -> list[tuple[dict, int]]:
        """Pares (linha da planilha, id do sócio) que a pessoa confirmou."""
        return [
            (pendencia, combo.currentData())
            for pendencia, combo in self._linhas_ui
            if combo.currentData() is not None
        ]
