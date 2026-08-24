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
