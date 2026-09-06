"""Dataclasses que espelham as entidades do domínio."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Empresa:
    """Cadastro-base da empresa. nome/cnpj/capital_social/quantidade_cotas
    aqui são os valores de fundação; o estado *atual* de uma empresa com
    alterações contratuais é o snapshot da alteração mais recente (ver
    repositories.estado_atual_empresa)."""

    id: int | None
    numero_chamada: str
    nome: str
    cnpj: str
    capital_social: float
    quantidade_cotas: float


@dataclass
class Socio:
    """cpf guarda o documento — CPF pra pessoa física, CNPJ pra pessoa
    jurídica (holding sócia de outra empresa é comum). tipo_pessoa decide a
    máscara e o rótulo mostrados na tela."""

    id: int | None
    nome: str
    cpf: str
    tipo_pessoa: str = "fisica"


@dataclass
class AlteracaoContratual:
    """Um evento formal de alteração do contrato social — snapshot versionado
    do estado da empresa (nome, capital, cotas) num dado momento, mais a
    movimentação de sócios ocorrida nesse evento. Uma vez fechada, não pode
    mais ser editada (precisa ser reaberta explicitamente)."""

    id: int | None
    empresa_id: int
    numero: int
    data: str
    nome_empresa: str
    capital_social: float
    quantidade_cotas: float
    descricao: str
    fechada: bool = False


@dataclass
class VinculoSocietario:
    """Histórico de participação de um sócio numa empresa. alteracao_entrada_id
    e alteracao_saida_id rastreiam qual alteração contratual trouxe/tirou o
    sócio — nulo quando o vínculo é anterior ao controle por alteração."""

    id: int | None
    empresa_id: int
    socio_id: int
    percentual_capital: float
    quantidade_cotas: float | None
    data_entrada: str
    data_saida: str | None
    alteracao_entrada_id: int | None = None
    alteracao_saida_id: int | None = None
    observacao: str = ""


@dataclass
class DistribuicaoLucro:
    """Quanto um sócio recebeu de distribuição de lucro de uma empresa num
    ano — um registro por (empresa, ano, sócio); editar substitui o valor
    porque é uma deliberação única do ano, não um histórico de eventos."""

    id: int | None
    empresa_id: int
    ano_base: int
    socio_id: int
    valor_distribuido: float
    pro_labore: float = 0.0
    irrf: float = 0.0


TIPOS_MOVIMENTACAO = (
    "emprestimo_empresa_para_socio",
    "emprestimo_socio_para_empresa",
    "adiantamento_lucro",
    "devolucao_capital",
)

TIPOS_MOVIMENTACAO_LABEL = {
    "emprestimo_empresa_para_socio": "Empréstimo da empresa ao sócio",
    "emprestimo_socio_para_empresa": "Empréstimo do sócio à empresa",
    "adiantamento_lucro": "Adiantamento de lucro",
    "devolucao_capital": "Devolução de capital",
}


@dataclass
class Movimentacao:
    """Lançamento de um movimento financeiro entre empresa e sócio — um
    lançamento por evento (ao contrário da distribuição, que é uma soma
    anual), então o histórico de cada tipo fica rastreável."""

    id: int | None
    empresa_id: int
    socio_id: int
    tipo: str
    valor: float
    data: str


@dataclass
class Usuario:
    """Conta de acesso ao sistema — separada do usuário do Windows, porque a
    máquina é compartilhada e o app precisa saber quem é quem pra auditoria."""

    id: int | None
    nome: str
    login: str
    senha_hash: str
    senha_salt: str
    admin: bool = False
    ativo: bool = True
    criado_em: str = ""


@dataclass
class LogAtividade:
    """Um evento de auditoria: quem fez o quê, quando. usuario_nome é
    guardado duplicado (não só o id) pra o log continuar legível mesmo que a
    conta do usuário seja excluída depois."""

    id: int | None
    usuario_id: int | None
    usuario_nome: str
    data_hora: str
    acao: str
    entidade: str
    entidade_id: int | None
    detalhes: str


# Campos de valor do informe, na ordem em que aparecem nos quadros 3, 4 e 5.
# emprestimo_saldo fica fora porque não é rendimento: vai pro Quadro 7.
CAMPOS_VALOR_INFORME = (
    "q3_total_rendimentos",
    "q3_previdencia_oficial",
    "q3_previdencia_complementar",
    "q3_pensao_alimenticia",
    "q3_irrf",
    "q4_parcela_isenta_65",
    "q4_parcela_isenta_13_65",
    "q4_diarias_ajudas_custo",
    "q4_pensao_molestia_grave",
    "q4_lucros_dividendos",
    "q4_valores_socio_microempresa",
    "q4_indenizacoes_rescisao",
    "q4_juros_mora",
    "q4_outros",
    "q5_decimo_terceiro",
    "q5_irrf_decimo_terceiro",
    "q5_outros",
)

NATUREZA_RENDIMENTO_PADRAO = "RENDIMENTO DO TRABALHO ASSALARIADO NO PAÍS"


@dataclass
class InformeRendimento:
    """Os valores do Comprovante de Rendimentos de um sócio numa empresa num
    ano — um registro por (empresa, ano, sócio), igual à distribuição, porque
    cada empresa é uma fonte pagadora distinta e emite o seu próprio informe.

    Todos os campos de dinheiro são INTEIRO de centavos (ver controle_lucros.
    fiscal): o informe é documento fiscal, e float acumularia erro de centavo.
    O sistema já sabe pró-labore, IRRF, lucros distribuídos e empréstimos, e
    esses vêm sugeridos; o que ele não tem (INSS, 13º, pensão...) é digitado
    aqui e fica guardado pra reemissão."""

    id: int | None
    empresa_id: int
    socio_id: int
    ano_base: int
    codigo_beneficiario: str = ""
    natureza_rendimento: str = NATUREZA_RENDIMENTO_PADRAO
    q3_total_rendimentos: int = 0
    q3_previdencia_oficial: int = 0
    q3_previdencia_complementar: int = 0
    q3_pensao_alimenticia: int = 0
    q3_irrf: int = 0
    q4_parcela_isenta_65: int = 0
    q4_parcela_isenta_13_65: int = 0
    q4_diarias_ajudas_custo: int = 0
    q4_pensao_molestia_grave: int = 0
    q4_lucros_dividendos: int = 0
    q4_valores_socio_microempresa: int = 0
    q4_indenizacoes_rescisao: int = 0
    q4_juros_mora: int = 0
    q4_outros: int = 0
    q5_decimo_terceiro: int = 0
    q5_irrf_decimo_terceiro: int = 0
    q5_outros: int = 0
    emprestimo_saldo: int = 0
    informacoes_complementares: str = ""
    responsavel_nome: str = ""
    atualizado_em: str = ""

    @property
    def exercicio(self) -> int:
        """O exercício da declaração é sempre o ano seguinte ao ano-calendário:
        o que foi pago em 2025 é declarado no exercício 2026."""
        return self.ano_base + 1


TRIMESTRES = (1, 2, 3, 4)

TRIMESTRES_LABEL = {
    1: "1º trimestre (jan–mar)",
    2: "2º trimestre (abr–jun)",
    3: "3º trimestre (jul–set)",
    4: "4º trimestre (out–dez)",
}


def periodo_trimestre(ano_base: int, trimestre: int) -> tuple[str, str]:
    """Primeiro e último dia do trimestre, em ISO — usado pra decidir quais
    sócios estavam na sociedade naquele pedaço do ano."""
    primeiro_mes = 3 * (trimestre - 1) + 1
    ultimo_mes = primeiro_mes + 2
    ultimo_dia = 31 if ultimo_mes in (3, 12) else 30
    return f"{ano_base}-{primeiro_mes:02d}-01", f"{ano_base}-{ultimo_mes:02d}-{ultimo_dia:02d}"


@dataclass
class DistribuicaoTrimestral:
    """Quanto um sócio recebeu num trimestre. Um registro por (empresa, ano,
    trimestre, sócio) — salvar de novo substitui, porque é a deliberação
    daquele trimestre, não um histórico de eventos.

    A distribuição anual do sócio é atualizada com a soma dos trimestres
    lançados a cada gravação: quem distribui trimestralmente vê o anual ir
    acumulando sozinho, em vez de ter que somar à mão no fim do ano."""

    id: int | None
    empresa_id: int
    ano_base: int
    trimestre: int
    socio_id: int
    valor_distribuido: float
    pro_labore: float = 0.0
    irrf: float = 0.0
