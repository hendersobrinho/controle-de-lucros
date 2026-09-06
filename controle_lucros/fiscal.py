"""Helpers fiscais do informe de rendimentos: CPF/CNPJ e dinheiro em centavos.

Dinheiro aqui é sempre inteiro de centavos, nunca float. O resto do sistema
guarda valores como REAL (é o que basta pra somar distribuições e desenhar
gráficos), mas o informe é documento fiscal entregue à Receita: um centavo de
diferença de arredondamento já é um documento errado. A conversão pra texto
("560.619,85") acontece só na borda — tela e PDF.
"""
from __future__ import annotations

import re

DIGITOS_CPF = 11
_NAO_DIGITOS = re.compile(r"\D")
_PONTUACAO_CNPJ = re.compile(r"[.\-/\s]")


# ------------------------------------------------------------------- CPF --


def cpf_valido(valor: str | None) -> bool:
    """Valida o CPF de verdade, conferindo os dois dígitos verificadores —
    não basta ter 11 dígitos. CPF errado no informe inviabiliza a declaração
    do beneficiário, e o erro só aparece meses depois, na malha fina."""
    digitos = _NAO_DIGITOS.sub("", str(valor or ""))
    if len(digitos) != DIGITOS_CPF:
        return False
    if digitos == digitos[0] * DIGITOS_CPF:
        return False
    for posicao in (9, 10):
        peso_inicial = posicao + 1
        soma = sum(int(digitos[i]) * (peso_inicial - i) for i in range(posicao))
        resto = (soma * 10) % 11
        esperado = 0 if resto == 10 else resto
        if esperado != int(digitos[posicao]):
            return False
    return True


def formatar_cpf(valor: str | None) -> str:
    """000.000.000-00. Devolve o texto original quando não são 11 dígitos —
    a tela mostra o que está cadastrado em vez de esconder um dado torto."""
    digitos = _NAO_DIGITOS.sub("", str(valor or ""))
    if len(digitos) != DIGITOS_CPF:
        return str(valor or "")
    return f"{digitos[:3]}.{digitos[3:6]}.{digitos[6:9]}-{digitos[9:]}"


def formatar_cnpj(valor: str | None) -> str:
    """00.000.000/0000-00, aceitando também o CNPJ alfanumérico (12 posições
    alfanuméricas + 2 dígitos verificadores) — mesma regra da máscara usada
    no cadastro de empresas."""
    limpo = _PONTUACAO_CNPJ.sub("", str(valor or "")).upper()
    if not re.fullmatch(r"[A-Z0-9]{12}\d{2}", limpo):
        return str(valor or "")
    return f"{limpo[:2]}.{limpo[2:5]}.{limpo[5:8]}/{limpo[8:12]}-{limpo[12:]}"


# -------------------------------------------------------------- Dinheiro --


def para_centavos(valor: str | int | float | None) -> int:
    """Lê um valor digitado em pt-BR ("1.234,56", "1234,5", "R$ 1.000,00") e
    devolve centavos. Vazio vira 0 — no informe, linha em branco é 0,00."""
    if valor is None:
        return 0
    if isinstance(valor, bool):  # bool é subclasse de int; nunca é dinheiro
        raise ValueError("Valor monetário inválido.")
    if isinstance(valor, int):
        return valor * 100
    if isinstance(valor, float):
        return round(valor * 100)

    texto = str(valor).strip().replace("R$", "").replace(" ", "").replace(" ", "")
    if not texto:
        return 0

    negativo = texto.startswith("-")
    texto = texto.lstrip("+-")

    # "1.234,56" (pt-BR) e "1,234.56" (en-US) convivem em planilhas coladas de
    # fontes diferentes; o ÚLTIMO separador é sempre o decimal nos dois.
    ultima_virgula = texto.rfind(",")
    ultimo_ponto = texto.rfind(".")
    if ultima_virgula > ultimo_ponto:
        inteiros, _, decimais = texto.rpartition(",")
    elif ultimo_ponto > ultima_virgula:
        inteiros, _, decimais = texto.rpartition(".")
    else:
        inteiros, decimais = texto, ""
    inteiros = inteiros.replace(".", "").replace(",", "")

    inteiros = inteiros or "0"
    if not inteiros.isdigit() or (decimais and not decimais.isdigit()):
        raise ValueError(f'Valor monetário inválido: "{valor}".')

    decimais = (decimais + "00")[:2] if decimais else "00"
    centavos = int(inteiros) * 100 + int(decimais)
    return -centavos if negativo else centavos


def de_centavos(centavos: int | None) -> str:
    """Formata centavos no padrão do informe ("560.619,85") — sem "R$", que
    no modelo oficial aparece só no título da coluna ("Valores em Reais")."""
    valor = int(centavos or 0)
    negativo = valor < 0
    reais, resto = divmod(abs(valor), 100)
    texto = f"{reais:,}".replace(",", ".") + f",{resto:02d}"
    return f"-{texto}" if negativo else texto


def reais_para_centavos(valor: float | None) -> int:
    """Converte um REAL do banco (distribuição, pró-labore, IRRF) em centavos.
    É a única fronteira float -> centavos: daqui pra frente, no informe, só
    inteiro."""
    return round(float(valor or 0) * 100)
