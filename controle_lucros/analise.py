"""Duas leituras dos dados que o sistema já tem, mas não mostrava.

Os dashboards respondiam "quanto" e "como ficou dividido". Estas duas
respondem "o que fazer a respeito", que é o que o escritório leva para a
reunião com o cliente:

1. `sem_pro_labore` — sócio pessoa física que recebeu distribuição de lucros e
   nenhum pró-labore no ano. É o que a fiscalização olha para requalificar a
   distribuição como remuneração, com a contribuição previdenciária que vem
   junto. O sistema já guardava os dois valores lado a lado sem nunca
   cruzá-los.

2. `desvio_por_socio` — quanto, em reais, cada sócio recebeu além (ou aquém)
   do que a participação dele daria. A classificação existente diz *se* a
   distribuição foi desproporcional; esta diz *quanto*, que é o número que
   cabe numa conversa: "o João recebeu R$ 120 mil acima dos 40% dele".

Módulo puro: recebe as linhas que repositories.analise_empresa_periodo() e
visao_geral() já produzem, e devolve listas ordenadas. Sem banco, sem Qt —
a conta é o que importa aqui, e ela se testa sozinha.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SocioSemProLabore:
    """Um sócio, numa empresa, somando o período consultado."""

    socio_id: int
    socio_nome: str
    socio_cpf: str
    empresa_nome: str
    valor_distribuido: float
    pro_labore: float
    anos: tuple[int, ...] = ()

    @property
    def anos_sem_pro_labore(self) -> int:
        return len(self.anos)

    @property
    def razao(self) -> float | None:
        """Quantas vezes o pró-labore o sócio recebeu em lucros. `None` quando
        não houve pró-labore nenhum — dividir por zero não é "infinito", é um
        caso diferente, e é o mais grave dos dois."""
        if self.pro_labore <= 0:
            return None
        return self.valor_distribuido / self.pro_labore


@dataclass
class DesvioDoSocio:
    socio_id: int
    socio_nome: str
    empresa_nome: str
    percentual_capital: float
    percentual_distribuido: float
    valor_distribuido: float
    valor_proporcional: float

    @property
    def desvio(self) -> float:
        """Positivo: recebeu além do que a participação daria. Negativo:
        aquém."""
        return self.valor_distribuido - self.valor_proporcional


def _chave_empresa(linha: dict):
    """Identidade da empresa numa linha de análise.

    Uma chave só, usada em todo lugar: o id quando ele vem (visão geral) e o
    nome quando não vem (análise de uma empresa só, que não precisa repetir o
    id em cada linha). Agrupar o total por um campo e os sócios por outro
    parece igual até aparecer uma linha com um deles faltando — e aí os totais
    de empresas diferentes se somam em silêncio."""
    return linha.get("empresa_id") if linha.get("empresa_id") is not None else linha.get("empresa_nome")


def _chave_empresa_ano(linha: dict) -> tuple:
    return (_chave_empresa(linha), linha.get("ano_base"))


def sem_pro_labore(linhas: list[dict], limite: int | None = None) -> list[SocioSemProLabore]:
    """Sócios pessoa física que receberam distribuição sem pró-labore, do maior
    valor para o menor.

    Pessoa jurídica fica de fora de propósito: holding sócia de empresa não
    tem pró-labore, e listá-la encheria o relatório de casos que não são caso
    nenhum — o aviso que grita sempre deixa de ser lido.

    O período é somado por (sócio, empresa), e `anos` guarda em quais anos
    houve distribuição sem pró-labore: três anos seguidos é uma história
    diferente de um ano isolado."""
    acumulado: dict[tuple, SocioSemProLabore] = {}
    for linha in linhas:
        if linha.get("socio_tipo_pessoa", "fisica") != "fisica":
            continue
        distribuido = float(linha.get("valor_distribuido") or 0)
        if distribuido <= 0:
            continue

        chave = (linha.get("socio_id"), _chave_empresa(linha))
        item = acumulado.get(chave)
        if item is None:
            item = SocioSemProLabore(
                socio_id=linha.get("socio_id"),
                socio_nome=linha.get("socio_nome", "?"),
                socio_cpf=linha.get("socio_cpf", ""),
                empresa_nome=linha.get("empresa_nome", ""),
                valor_distribuido=0.0,
                pro_labore=0.0,
            )
            acumulado[chave] = item
        item.valor_distribuido += distribuido
        item.pro_labore += float(linha.get("pro_labore") or 0)
        if float(linha.get("pro_labore") or 0) <= 0 and linha.get("ano_base") is not None:
            item.anos = tuple(sorted({*item.anos, linha["ano_base"]}))

    # Só entra quem tem pelo menos um ano sem pró-labore. Quem recebeu
    # pró-labore em todos os anos não é o caso deste painel, por menor que ele
    # tenha sido — julgar se o valor é compatível com o trabalho não é conta
    # que o programa possa fazer.
    resultado = [i for i in acumulado.values() if i.anos]
    resultado.sort(key=lambda i: (-i.valor_distribuido, i.socio_nome))
    return resultado[:limite] if limite else resultado


def desvio_por_socio(linhas: list[dict], limite: int | None = None) -> list[DesvioDoSocio]:
    """Quanto cada sócio recebeu a mais ou a menos do que a participação dele
    daria, em reais, somando o período.

    O esperado sai do total distribuído pela empresa naquele ano: é ele que a
    participação divide. Por isso as linhas são agrupadas por (empresa, ano)
    antes da conta — misturar anos daria um "esperado" que nunca existiu.

    A lista sai ordenada pelo tamanho do desvio, para cima ou para baixo: o
    que interessa é quem mais saiu do eixo, e receber a menos é tão fora do
    eixo quanto receber a mais."""
    total_por_empresa_ano: dict[tuple, float] = {}
    for linha in linhas:
        chave = _chave_empresa_ano(linha)
        total_por_empresa_ano[chave] = total_por_empresa_ano.get(chave, 0.0) + float(
            linha.get("valor_distribuido") or 0
        )

    acumulado: dict[tuple, DesvioDoSocio] = {}
    for linha in linhas:
        total = total_por_empresa_ano.get(_chave_empresa_ano(linha), 0.0)
        if total <= 0:
            continue  # empresa que não distribuiu naquele ano não tem desvio nenhum
        distribuido = float(linha.get("valor_distribuido") or 0)
        proporcional = total * float(linha.get("percentual_capital") or 0) / 100

        chave = (linha.get("socio_id"), _chave_empresa(linha))
        item = acumulado.get(chave)
        if item is None:
            item = DesvioDoSocio(
                socio_id=linha.get("socio_id"),
                socio_nome=linha.get("socio_nome", "?"),
                empresa_nome=linha.get("empresa_nome", ""),
                percentual_capital=float(linha.get("percentual_capital") or 0),
                percentual_distribuido=0.0,
                valor_distribuido=0.0,
                valor_proporcional=0.0,
            )
            acumulado[chave] = item
        item.valor_distribuido += distribuido
        item.valor_proporcional += proporcional

    # O percentual do sócio é sobre o total da empresa no período inteiro, não
    # sobre o de um ano — é assim que ele fica comparável com o percentual de
    # capital, que é o outro lado da conta.
    total_por_empresa: dict = {}
    for (_socio, empresa), item in acumulado.items():
        total_por_empresa[empresa] = total_por_empresa.get(empresa, 0.0) + item.valor_distribuido
    for (_socio, empresa), item in acumulado.items():
        total = total_por_empresa.get(empresa, 0.0)
        item.percentual_distribuido = 100 * item.valor_distribuido / total if total else 0.0

    resultado = sorted(acumulado.values(), key=lambda i: (-abs(i.desvio), i.socio_nome))
    return resultado[:limite] if limite else resultado


def _em_reais(valor: float) -> str:
    """1234567.5 -> "1.234.567,50". A troca de separadores é feita só no
    número: aplicada à frase inteira, ela trocava também o ponto final por
    vírgula."""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def resumo_sem_pro_labore(itens: list[SocioSemProLabore]) -> str:
    if not itens:
        return "Nenhum sócio recebeu distribuição sem pró-labore no período."
    total = sum(i.valor_distribuido for i in itens)
    pessoas = len({i.socio_id for i in itens})
    plural = "sócio recebeu" if pessoas == 1 else "sócios receberam"
    return f"{pessoas} {plural} R$ {_em_reais(total)} em lucros sem pró-labore no período."
