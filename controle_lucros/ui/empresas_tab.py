from __future__ import annotations

from PySide6.QtWidgets import QDoubleSpinBox, QFormLayout, QLineEdit, QPushButton

from .. import repositories as repo
from ..mapa_vinculos import PAPEL_EMPRESA
from ..models import Empresa
from .common import CrudTab, cnpj_valido_ou_vazio, configurar_campo_cnpj, formatar_numero, formatar_valor_br
from .diagrama_vinculos import DialogoMapaVinculos


class EmpresasTab(CrudTab):
    # O nº da empresa é curto e fixo; quem se beneficia da largura é a razão
    # social, que é longa e varia.
    coluna_flexivel = 1
    mensagem_tabela_vazia = "Nenhuma empresa cadastrada ainda."
    colunas = [
        ("Nº empresa", "numero_chamada"),
        ("Nome", "nome"),
        ("CNPJ", "cnpj"),
        ("Capital social", "capital_social"),
        ("Cotas", "quantidade_cotas"),
    ]

    def __init__(self, conn, parent=None):
        super().__init__(conn, parent)

        # O outro lado do mapa da aba Sócios: lá o sócio está no meio e as
        # empresas em volta; aqui a empresa está no meio e os sócios em volta.
        # Mesmo desenho, mesma exportação — muda só quem é o centro.
        self.btn_quadro = QPushButton("Quadro societário")
        self.btn_quadro.setToolTip(
            "Abre um diagrama com os sócios ligados a esta empresa e a participação de cada "
            "um — dá pra exportar em PDF ou SVG para anexar a processo ou apresentação."
        )
        self.btn_quadro.clicked.connect(self._abrir_quadro_societario)
        self.linha_busca.addWidget(self.btn_quadro)
        self._definir_modo(self._modo, self._descricao_modo)

    def _definir_modo(self, modo: str, descricao: str = "") -> None:
        """Sem empresa escolhida não há quadro pra desenhar. Este é o ponto
        por onde toda mudança de estado passa — selecionar, criar, cancelar,
        excluir —, então o botão acompanha os quatro de uma vez.

        O hasattr não é defesa: a base chama _definir_modo uma vez dentro do
        próprio __init__, antes de este botão existir."""
        super()._definir_modo(modo, descricao)
        if hasattr(self, "btn_quadro"):
            self.btn_quadro.setEnabled(self._registro_atual_id is not None)

    def _abrir_quadro_societario(self) -> None:
        """O quadro societário desenhado: quem está na empresa, com quanto, e
        quem já saiu. A tabela de sócios responde "quem"; o desenho mostra o
        peso de cada um de relance, que é o que se leva pra reunião."""
        empresa = next((e for e in self._registros if e.id == self._registro_atual_id), None)
        if empresa is None:
            return
        socios = {s.id: s for s in repo.listar_socios(self.conn)}
        vinculos = [
            {
                "socio_nome": socios[v.socio_id].nome if v.socio_id in socios else "?",
                # O percentual registrado no vínculo, igual ao que a aba
                # Sócios usa no mapa do outro lado — não o recalculado por
                # cotas, que muda com o capital e faria os dois desenhos
                # discordarem sobre a mesma participação.
                "percentual": v.percentual_capital,
                "data_entrada": v.data_entrada,
                "data_saida": v.data_saida,
            }
            for v in repo.listar_vinculos_empresa(self.conn, empresa.id)
        ]
        DialogoMapaVinculos(
            empresa.nome, empresa.cnpj or "", vinculos, self, papel=PAPEL_EMPRESA
        ).exec()

    def montar_formulario(self, form_layout: QFormLayout) -> None:
        self.numero_chamada = QLineEdit()
        self.numero_chamada.setProperty("role", "mono")
        self.numero_chamada.setPlaceholderText("ex.: 042")

        self.nome = QLineEdit()
        self.nome.setPlaceholderText("Razão social")

        self.cnpj = QLineEdit()
        self.cnpj.setProperty("role", "mono")
        configurar_campo_cnpj(self.cnpj)
        self.cnpj.setPlaceholderText("AA.AAA.AAA/AAAA-DV")

        self.capital = QDoubleSpinBox()
        self.capital.setMaximum(1_000_000_000)
        self.capital.setDecimals(2)
        self.capital.setPrefix("R$ ")
        formatar_numero(self.capital)

        self.cotas = QDoubleSpinBox()
        self.cotas.setMaximum(1_000_000_000)
        self.cotas.setDecimals(0)
        formatar_numero(self.cotas)

        form_layout.addRow("Nº da empresa", self.numero_chamada)
        form_layout.addRow("Nome da empresa", self.nome)
        form_layout.addRow("CNPJ", self.cnpj)
        form_layout.addRow("Capital social (fundação)", self.capital)
        form_layout.addRow("Quantidade de cotas (fundação)", self.cotas)

    def listar(self):
        return repo.listar_empresas(self.conn)

    def placeholder_busca(self) -> str:
        return "Buscar por nome ou nº da empresa…"

    def corresponde_busca(self, registro: Empresa, termo: str) -> bool:
        return termo in registro.nome.lower() or termo in (registro.numero_chamada or "").lower()

    def valor_coluna(self, registro: Empresa, attr: str):
        if attr == "capital_social":
            return f"R$ {formatar_valor_br(registro.capital_social)}"
        if attr == "quantidade_cotas":
            return formatar_valor_br(registro.quantidade_cotas, 0)
        return getattr(registro, attr, None)

    def carregar_form(self, e: Empresa) -> None:
        self.numero_chamada.setText(e.numero_chamada or "")
        self.nome.setText(e.nome)
        self.cnpj.setText(e.cnpj or "")
        self.capital.setValue(e.capital_social)
        self.cotas.setValue(e.quantidade_cotas)

    def ler_form(self, id_atual):
        return Empresa(
            id=id_atual,
            numero_chamada=self.numero_chamada.text().strip(),
            nome=self.nome.text().strip(),
            cnpj=cnpj_valido_ou_vazio(self.cnpj),
            capital_social=self.capital.value(),
            quantidade_cotas=self.cotas.value(),
        )

    def limpar_form(self) -> None:
        self.numero_chamada.clear()
        self.nome.clear()
        self.cnpj.clear()
        self.capital.setValue(0)
        self.cotas.setValue(0)

    def salvar_registro(self, registro: Empresa) -> None:
        if not registro.nome:
            raise ValueError("Informe o nome da empresa.")
        if not registro.numero_chamada:
            raise ValueError("Informe o número da empresa.")
        repo.salvar_empresa(self.conn, registro)

    def excluir_registro(self, id_) -> None:
        repo.excluir_empresa(self.conn, id_)
