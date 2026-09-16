"""Layout de importação: qual coluna da planilha tem cada informação.

A importação por cabeçalho resolve o caso de quem usa o modelo exportado
daqui, mas não o de quem já tem uma planilha pronta — vinda de outro sistema
contábil, do banco ou de um relatório antigo — onde as colunas estão em outra
ordem e com outro nome. Obrigar a pessoa a remontar a planilha inteira pra
importar é justamente o trabalho que a importação em massa deveria evitar.

Um layout é o desenho dessa planilha: pra cada campo que o sistema sabe
cadastrar, a LETRA da coluna onde ele está ("A", "B", "AC"...), mais a linha
em que os dados começam. Campo sem letra é campo que aquela planilha não tem,
e simplesmente não é importado. Salvo com um nome, o layout vira o formato
daquela origem: configura-se uma vez e todo mês é só apontar o arquivo.

Este módulo não importa Qt nem toca no banco: recebe caminho de arquivo e
layout, devolve as mesmas linhas que planilha.importar_cadastro() devolveria.
Daí pra frente o caminho é o mesmo de sempre — casamento de empresa e sócio,
revisão das pendências, nada criado sem confirmação.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .planilha import (
    CAMPOS_CADASTRO,
    COLUNAS_CADASTRO,
    ler_linhas_brutas,
    montar_linhas_cadastro,
)

LINHA_INICIAL_PADRAO = 2


@dataclass(frozen=True)
class GrupoCampos:
    """Os campos agrupados como a pessoa pensa neles — dados da empresa, do
    sócio, da participação, do dinheiro — em vez da ordem em que estão no
    arquivo. É o que a tela usa pra montar os quadrinhos."""

    nome: str
    ajuda: str
    campos: tuple[str, ...]


GRUPOS_CAMPOS = (
    GrupoCampos(
        "Empresa",
        "Identificam a empresa. Se ela ainda não existir, é criada.",
        ("numero_chamada", "empresa_nome", "cnpj", "capital_social", "quantidade_cotas"),
    ),
    GrupoCampos(
        "Sócio",
        "Identificam a pessoa. Sócio novo nunca é criado sem sua confirmação.",
        ("socio_nome", "socio_cpf", "tipo_pessoa"),
    ),
    GrupoCampos(
        "Participação",
        "O vínculo do sócio com aquela empresa, com entrada e saída.",
        ("percentual_capital", "cotas_socio", "data_entrada", "data_saida"),
    ),
    GrupoCampos(
        "Distribuição do ano",
        "Opcional: preencha só se a planilha também trouxer valores pagos.",
        ("ano_base", "valor_distribuido", "pro_labore", "irrf"),
    ),
)

CAMPOS_POR_GRUPO = {grupo.nome: grupo.campos for grupo in GRUPOS_CAMPOS}

# Rótulo de cada campo — o mesmo cabeçalho da planilha modelo, pra quem já
# conhece um reconhecer o outro.
ROTULOS_CAMPOS = dict(zip(CAMPOS_CADASTRO, COLUNAS_CADASTRO))

CAMPO_OBRIGATORIO = "empresa_nome"

# Mapear qualquer um destes sem mapear o nome do sócio deixaria a importação
# sem ninguém pra vincular: toda linha seria descartada por estar incompleta,
# em silêncio. Melhor dizer isso na hora de salvar o layout.
_CAMPOS_QUE_EXIGEM_SOCIO = frozenset(
    CAMPOS_POR_GRUPO["Sócio"] + CAMPOS_POR_GRUPO["Participação"] + CAMPOS_POR_GRUPO["Distribuição do ano"]
) - {"socio_nome"}

_LETRA_VALIDA = re.compile(r"^[A-Z]{1,3}$")


class LayoutInvalido(ValueError):
    """O layout não dá pra usar como está — a mensagem diz o quê."""


def letra_para_indice(letra: str) -> int:
    """"A" -> 0, "Z" -> 25, "AA" -> 26. É a numeração de colunas do Excel, que
    é base 26 sem zero: cada letra vale de 1 a 26."""
    texto = str(letra or "").strip().upper()
    if not _LETRA_VALIDA.match(texto):
        raise LayoutInvalido(
            f'"{letra}" não é uma coluna de planilha. Use a letra que aparece no '
            "topo da coluna no Excel — A, B, C... até AZ."
        )
    indice = 0
    for caractere in texto:
        indice = indice * 26 + (ord(caractere) - ord("A") + 1)
    return indice - 1


def indice_para_letra(indice: int) -> str:
    """Caminho de volta, pro sistema sugerir um layout a partir de uma
    planilha que ele mesmo exportou."""
    if indice < 0:
        raise LayoutInvalido("Coluna de planilha não pode ser negativa.")
    letras = ""
    numero = indice + 1
    while numero > 0:
        numero, resto = divmod(numero - 1, 26)
        letras = chr(ord("A") + resto) + letras
    return letras


@dataclass
class LayoutImportacao:
    """O desenho de uma planilha de origem. `colunas` leva campo -> letra, só
    com os campos que aquela planilha tem."""

    nome: str
    colunas: dict[str, str] = field(default_factory=dict)
    linha_inicial: int = LINHA_INICIAL_PADRAO
    id: int | None = None

    def letra(self, campo: str) -> str:
        return self.colunas.get(campo, "")

    def campos_mapeados(self) -> list[str]:
        """Na ordem dos campos do cadastro, não na ordem das colunas — é como
        a tela mostra e como o resumo lê melhor."""
        return [campo for campo in CAMPOS_CADASTRO if self.colunas.get(campo)]

    def indices(self) -> dict[str, int]:
        """Campo -> posição da coluna (base zero), pronto pro conversor."""
        return {campo: letra_para_indice(letra) for campo, letra in self.colunas.items() if letra}

    def resumo(self) -> str:
        mapeados = self.campos_mapeados()
        if not mapeados:
            return "nenhuma coluna configurada"
        return f"{len(mapeados)} coluna(s) · dados a partir da linha {self.linha_inicial}"


def limpar_colunas(colunas: dict[str, str]) -> dict[str, str]:
    """Descarta campo em branco e padroniza a letra em maiúsculo, pra "a" e
    "A" não virarem layouts diferentes."""
    return {
        campo: str(letra).strip().upper()
        for campo, letra in colunas.items()
        if campo in CAMPOS_CADASTRO and str(letra or "").strip()
    }


def validar(layout: LayoutImportacao) -> list[str]:
    """Todos os problemas do layout de uma vez, em linguagem de quem preenche.

    Devolve lista em vez de levantar na primeira: quem está configurando
    prefere ver os três erros juntos a corrigir um, salvar, e descobrir o
    seguinte."""
    erros: list[str] = []

    if not layout.nome.strip():
        erros.append("Dê um nome ao layout, pra reconhecê-lo depois na lista.")

    if layout.linha_inicial < 1:
        erros.append("A linha em que os dados começam precisa ser 1 ou maior.")

    for campo, letra in layout.colunas.items():
        try:
            letra_para_indice(letra)
        except LayoutInvalido as exc:
            erros.append(f"{ROTULOS_CAMPOS.get(campo, campo)}: {exc}")

    if not layout.colunas.get(CAMPO_OBRIGATORIO):
        erros.append(
            f'"{ROTULOS_CAMPOS[CAMPO_OBRIGATORIO]}" é obrigatório: sem o nome da empresa '
            "não há a quem ligar a linha."
        )

    tem_dados_de_socio = any(layout.colunas.get(campo) for campo in _CAMPOS_QUE_EXIGEM_SOCIO)
    if tem_dados_de_socio and not layout.colunas.get("socio_nome"):
        erros.append(
            f'Informe a coluna de "{ROTULOS_CAMPOS["socio_nome"]}": o layout traz dados de '
            "sócio, e sem o nome nenhuma linha pode ser aproveitada."
        )

    por_letra: dict[str, list[str]] = {}
    for campo, letra in layout.colunas.items():
        por_letra.setdefault(str(letra).strip().upper(), []).append(campo)
    for letra, campos in por_letra.items():
        if len(campos) > 1:
            nomes = ", ".join(ROTULOS_CAMPOS.get(c, c) for c in campos)
            erros.append(f"A coluna {letra} está em mais de um campo: {nomes}.")

    return erros


def garantir_valido(layout: LayoutImportacao) -> None:
    erros = validar(layout)
    if erros:
        raise LayoutInvalido("\n".join(f"• {erro}" for erro in erros))


def importar_com_layout(caminho: Path, layout: LayoutImportacao) -> list[dict]:
    """Lê a planilha pelas posições do layout, ignorando o cabeçalho dela.

    O resultado é o mesmo de planilha.importar_cadastro(): a partir daqui a
    origem do arquivo deixa de importar."""
    garantir_valido(layout)
    # Sem descartar linha vazia: aqui a posição é a informação, e linha em
    # branco antes do início deslocaria tudo. As que sobrarem no meio não
    # atrapalham — linha sem nome de empresa já é ignorada na conversão.
    linhas_brutas = ler_linhas_brutas(caminho, descartar_vazias=False)
    if not linhas_brutas:
        return []

    # A pessoa conta as linhas como o Excel mostra (1, 2, 3...); aqui o corte
    # é base zero. Linha inicial 2 = pula só o cabeçalho.
    dados = linhas_brutas[layout.linha_inicial - 1:]
    return montar_linhas_cadastro(dados, layout.indices(), numero_primeira_linha=layout.linha_inicial)


def previa(caminho: Path, layout: LayoutImportacao, quantidade: int = 5) -> list[list[str]]:
    """As primeiras linhas já lidas pelo layout, em (campo, valor), pra tela
    mostrar antes de aplicar.

    Errar uma letra é fácil e o estrago aparece só depois, com o CNPJ no lugar
    do capital social; ver a primeira linha interpretada custa um instante e
    evita isso."""
    mapeados = layout.campos_mapeados()
    linhas = importar_com_layout(caminho, layout)[:quantidade]
    return [[_texto_previa(linha.get(campo)) for campo in mapeados] for linha in linhas]


def _texto_previa(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor)


def layout_do_modelo(modelo) -> LayoutImportacao:
    """Layout equivalente a um modelo do sistema: as colunas dele, na ordem,
    a partir da coluna A. Serve de ponto de partida pra quem vai configurar um
    layout novo — é mais fácil corrigir umas letras do que preencher dezesseis."""
    return LayoutImportacao(
        nome=f"Cópia de {modelo.nome}",
        colunas={campo: indice_para_letra(i) for i, campo in enumerate(modelo.campos)},
        linha_inicial=LINHA_INICIAL_PADRAO,
    )


def para_json(colunas: dict[str, str]) -> str:
    return json.dumps(colunas, ensure_ascii=False, sort_keys=True)


def de_json(texto: str) -> dict[str, str]:
    """Campo que saiu do sistema depois que o layout foi salvo é descartado na
    leitura, em vez de explodir na tela."""
    try:
        dados = json.loads(texto or "{}")
    except (TypeError, ValueError):
        return {}
    if not isinstance(dados, dict):
        return {}
    return limpar_colunas({str(k): str(v) for k, v in dados.items()})


def exportar_com_layout(caminho: Path, linhas: list[dict], layout: LayoutImportacao) -> None:
    """Grava o cadastro atual no desenho do layout: cada campo na coluna dele,
    os dados começando na linha configurada.

    É o mesmo layout servindo pros dois lados. Exportar no formato que a outra
    ponta espera fecha o ciclo — o arquivo sai daqui, vai pro outro sistema (ou
    pra conferência) e volta pela mesma configuração, sem ninguém remontar
    coluna nenhuma."""
    import openpyxl
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    from .planilha import LARGURAS_CADASTRO, _valor_cadastro

    garantir_valido(layout)
    indices = layout.indices()

    workbook = openpyxl.Workbook()
    aba = workbook.active
    aba.title = "Cadastro"

    linha_cabecalho = layout.linha_inicial - 1
    for campo, indice in indices.items():
        coluna = indice + 1
        aba.column_dimensions[get_column_letter(coluna)].width = LARGURAS_CADASTRO[campo]
        # Layout que começa na linha 1 não tem onde pôr cabeçalho — e é
        # justamente o caso de quem exporta pra um sistema que lê só dados.
        if linha_cabecalho >= 1:
            celula = aba.cell(row=linha_cabecalho, column=coluna, value=ROTULOS_CAMPOS[campo])
            celula.font = Font(bold=True, color="FFFFFF")
            celula.fill = PatternFill("solid", fgColor="1B2A41")

    for numero, linha in enumerate(linhas, start=layout.linha_inicial):
        for campo, indice in indices.items():
            aba.cell(row=numero, column=indice + 1, value=_valor_cadastro(linha, campo))

    workbook.save(caminho)
