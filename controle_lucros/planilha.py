"""Leitura e escrita de planilhas (.xlsx/.csv) para importar/exportar em
massa a distribuição de lucro por sócio. Puro Python — sem dependência de UI
— pra dar pra testar a lógica de parsing isoladamente."""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

COLUNAS_DISTRIBUICAO = ["CPF", "Sócio", "Valor Distribuído", "Pró-labore", "IRRF"]

COLUNAS_CADASTRO = [
    "Nº Empresa", "Empresa", "CNPJ", "Capital Social", "Qtd. Cotas da Empresa",
    "Sócio", "CPF/CNPJ do Sócio", "Tipo (física/jurídica)",
    "% Capital do Sócio", "Cotas do Sócio", "Data de Entrada", "Data de Saída",
    "Ano Base", "Valor Distribuído", "Pró-labore", "IRRF",
]

# Campo interno de cada coluna, na mesma ordem. Antes essa ligação era
# implícita (uma lista de 16 linha.get(...) que precisava bater na posição
# com os 16 cabeçalhos); explícita, dá pra montar modelos menores escolhendo
# colunas sem risco de desalinhar valor com cabeçalho.
CAMPOS_CADASTRO = [
    "numero_chamada", "empresa_nome", "cnpj", "capital_social", "quantidade_cotas",
    "socio_nome", "socio_cpf", "tipo_pessoa",
    "percentual_capital", "cotas_socio", "data_entrada", "data_saida",
    "ano_base", "valor_distribuido", "pro_labore", "irrf",
]

LARGURAS_CADASTRO = {
    "numero_chamada": 11, "empresa_nome": 30, "cnpj": 21, "capital_social": 16,
    "quantidade_cotas": 20, "socio_nome": 30, "socio_cpf": 21, "tipo_pessoa": 19,
    "percentual_capital": 17, "cotas_socio": 15, "data_entrada": 15, "data_saida": 14,
    "ano_base": 10, "valor_distribuido": 17, "pro_labore": 14, "irrf": 12,
}


@dataclass(frozen=True)
class ModeloCadastro:
    """Um recorte de colunas do cadastro em massa. Todos são lidos pelo mesmo
    importador — as colunas são identificadas pelo cabeçalho, então um modelo
    menor é simplesmente um arquivo com menos colunas, não um formato novo."""

    id: str
    nome: str
    descricao: str
    campos: tuple[str, ...]
    uma_linha_por_empresa: bool = False

    @property
    def colunas(self) -> list[str]:
        return [COLUNAS_CADASTRO[CAMPOS_CADASTRO.index(campo)] for campo in self.campos]


_CAMPOS_EMPRESA = ("numero_chamada", "empresa_nome", "cnpj", "capital_social", "quantidade_cotas")
_CAMPOS_VINCULO = ("socio_nome", "socio_cpf", "tipo_pessoa", "percentual_capital", "cotas_socio", "data_entrada")

MODELOS_CADASTRO = (
    ModeloCadastro(
        "geral",
        "Completo (empresas, sócios e distribuição)",
        "Todas as colunas. Use quando for cadastrar tudo de uma vez, inclusive saída de "
        "sócio e a distribuição de um ano.",
        tuple(CAMPOS_CADASTRO),
    ),
    ModeloCadastro(
        "empresas_socios",
        "Empresas e sócios",
        "Empresas com seus sócios e participações, sem data de saída nem distribuição. "
        "É o recorte do dia a dia: montar ou completar o quadro societário.",
        _CAMPOS_EMPRESA + _CAMPOS_VINCULO,
    ),
    ModeloCadastro(
        "empresas",
        "Só empresas",
        "Só o cadastro das empresas, sem sócios. Uma linha por empresa — os sócios "
        "entram depois, por aqui mesmo ou pela aba Sócios.",
        _CAMPOS_EMPRESA,
        uma_linha_por_empresa=True,
    ),
)

MODELO_CADASTRO_PADRAO = MODELOS_CADASTRO[0]


def modelo_cadastro(id_modelo: str) -> ModeloCadastro:
    for modelo in MODELOS_CADASTRO:
        if modelo.id == id_modelo:
            return modelo
    raise ValueError(f"Modelo de cadastro desconhecido: {id_modelo!r}.")


# Dados fictícios que aparecem na aba "Exemplo" de todo modelo exportado.
# Foram escolhidos pra mostrar, sem precisar de legenda, as três dúvidas que
# aparecem sempre: como repetir a empresa pra cada sócio, que o mesmo sócio
# se repete em empresas diferentes (e é o mesmo cadastro), e que sócio pode
# ser pessoa jurídica.
LINHAS_EXEMPLO_CADASTRO = [
    {
        "numero_chamada": "001", "empresa_nome": "PADARIA MODELO LTDA",
        "cnpj": "11.111.111/0001-11", "capital_social": 100000, "quantidade_cotas": 100000,
        "socio_nome": "MARIA EXEMPLO DA SILVA", "socio_cpf": "111.111.111-11",
        "tipo_pessoa": "Física", "percentual_capital": 60, "cotas_socio": 60000,
        "data_entrada": "01/01/2020", "data_saida": "",
        "ano_base": 2025, "valor_distribuido": 60000, "pro_labore": 24000, "irrf": 1500,
    },
    {
        "numero_chamada": "001", "empresa_nome": "PADARIA MODELO LTDA",
        "cnpj": "11.111.111/0001-11", "capital_social": 100000, "quantidade_cotas": 100000,
        "socio_nome": "JOAO EXEMPLO SOUZA", "socio_cpf": "222.222.222-22",
        "tipo_pessoa": "Física", "percentual_capital": 40, "cotas_socio": 40000,
        "data_entrada": "01/01/2020", "data_saida": "",
        "ano_base": 2025, "valor_distribuido": 40000, "pro_labore": 18000, "irrf": 900,
    },
    {
        "numero_chamada": "002", "empresa_nome": "TRANSPORTES EXEMPLO ME",
        "cnpj": "22.222.222/0001-22", "capital_social": 50000, "quantidade_cotas": 50000,
        "socio_nome": "MARIA EXEMPLO DA SILVA", "socio_cpf": "111.111.111-11",
        "tipo_pessoa": "Física", "percentual_capital": 100, "cotas_socio": 50000,
        "data_entrada": "15/03/2021", "data_saida": "",
        "ano_base": 2025, "valor_distribuido": 30000, "pro_labore": 0, "irrf": 0,
    },
    {
        "numero_chamada": "003", "empresa_nome": "CLINICA EXEMPLO LTDA",
        "cnpj": "33.333.333/0001-33", "capital_social": 200000, "quantidade_cotas": 200000,
        "socio_nome": "HOLDING EXEMPLO PARTICIPACOES LTDA", "socio_cpf": "44.444.444/0001-44",
        "tipo_pessoa": "Jurídica", "percentual_capital": 70, "cotas_socio": 140000,
        "data_entrada": "01/01/2019", "data_saida": "",
        "ano_base": "", "valor_distribuido": "", "pro_labore": "", "irrf": "",
    },
    {
        "numero_chamada": "003", "empresa_nome": "CLINICA EXEMPLO LTDA",
        "cnpj": "33.333.333/0001-33", "capital_social": 200000, "quantidade_cotas": 200000,
        "socio_nome": "JOAO EXEMPLO SOUZA", "socio_cpf": "222.222.222-22",
        "tipo_pessoa": "Física", "percentual_capital": 30, "cotas_socio": 60000,
        "data_entrada": "01/01/2019", "data_saida": "30/06/2025",
        "ano_base": "", "valor_distribuido": "", "pro_labore": "", "irrf": "",
    },
]

NOTAS_EXEMPLO_CADASTRO = [
    "Uma linha por (empresa, sócio). Empresa com três sócios ocupa três linhas, "
    "repetindo os dados da empresa igual em todas.",
    "O mesmo sócio pode aparecer em empresas diferentes (veja MARIA nas empresas 001 e 002) "
    "— é o mesmo cadastro, reconhecido pelo CPF, e não vira sócio duplicado.",
    "Sócio pode ser pessoa jurídica: preencha o CNPJ no lugar do CPF e marque o tipo como "
    "Jurídica (veja a HOLDING na empresa 003).",
    "Empresa é reconhecida pelo nº da empresa, pelo CNPJ ou pelo nome; se não existir, "
    "é criada. Sócio nunca é criado sem você confirmar na tela.",
    "Data de Saída só para quem já saiu da sociedade. Ano Base, Valor Distribuído, "
    "Pró-labore e IRRF só se for lançar a distribuição daquele ano junto.",
]


LINHAS_EXEMPLO_DISTRIBUICAO = [
    {"cpf": "111.111.111-11", "nome": "MARIA EXEMPLO DA SILVA", "valor_distribuido": 60000,
     "pro_labore": 24000, "irrf": 1500},
    {"cpf": "222.222.222-22", "nome": "JOAO EXEMPLO SOUZA", "valor_distribuido": 40000,
     "pro_labore": 18000, "irrf": 900},
    {"cpf": "333.333.333-33", "nome": "ANA EXEMPLO PEREIRA", "valor_distribuido": 0,
     "pro_labore": 0, "irrf": 0},
]

NOTAS_EXEMPLO_DISTRIBUICAO = [
    "Esta planilha é de UMA empresa e UM ano — os da tela de onde você exportou. "
    "Para outra empresa, exporte o modelo dela.",
    "Uma linha por sócio. O sócio é reconhecido pelo CPF; o nome só é usado se o CPF "
    "não bater, e precisa ser exatamente igual ao cadastrado.",
    "Sócio que não recebeu nada pode ficar com 0 (veja ANA) ou ser apagado da planilha.",
    "Pró-labore e IRRF são opcionais: apague as duas colunas se só for lançar a "
    "distribuição de lucro.",
    "Importar substitui os valores do ano para os sócios que estiverem na planilha; "
    "quem não estiver nela não é alterado.",
]


def _montar_aba_exemplo_distribuicao(workbook) -> None:
    aba = workbook.create_sheet("Exemplo")
    aba["A1"] = "Exemplo de preenchimento — distribuição do ano"
    aba["A1"].font = Font(size=13, bold=True, color="1B2A41")
    aba["A2"] = "Dados fictícios, só para consulta. Preencha os seus na aba anterior."
    aba["A2"].font = Font(italic=True, color="5B6472")

    linha = 4
    for nota in NOTAS_EXEMPLO_DISTRIBUICAO:
        aba.cell(row=linha, column=1, value=f"• {nota}")
        linha += 1

    linha += 1
    for indice, nome in enumerate(COLUNAS_DISTRIBUICAO, start=1):
        celula = aba.cell(row=linha, column=indice, value=nome)
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = PatternFill("solid", fgColor="1B2A41")
    for coluna, largura in zip("ABCDE", (20, 32, 18, 14, 14)):
        aba.column_dimensions[coluna].width = largura

    for exemplo in LINHAS_EXEMPLO_DISTRIBUICAO:
        linha += 1
        for indice, campo in enumerate(("cpf", "nome", "valor_distribuido", "pro_labore", "irrf"), start=1):
            aba.cell(row=linha, column=indice, value=exemplo[campo])


def exportar_modelo_distribuicao(caminho: Path, linhas: list[dict]) -> None:
    """Gera um .xlsx pronto pra preencher: uma linha por sócio informado, já
    com CPF e nome preenchidos — só falta digitar o valor distribuído (e,
    se houver, pró-labore/IRRF). Sai com uma aba "Exemplo" preenchida."""
    workbook = openpyxl.Workbook()
    aba = workbook.active
    aba.title = "Distribuição"
    for indice, nome in enumerate(COLUNAS_DISTRIBUICAO, start=1):
        celula = aba.cell(row=1, column=indice, value=nome)
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = PatternFill("solid", fgColor="1B2A41")
    aba.freeze_panes = "A2"
    for linha in linhas:
        aba.append(
            [
                linha.get("cpf", ""),
                linha.get("nome", ""),
                linha.get("valor_distribuido") or 0,
                linha.get("pro_labore") or 0,
                linha.get("irrf") or 0,
            ]
        )
    for coluna, largura in zip("ABCDE", (20, 32, 18, 14, 14)):
        aba.column_dimensions[coluna].width = largura

    _montar_aba_exemplo_distribuicao(workbook)
    workbook.active = 0
    workbook.save(caminho)


def importar_distribuicao(caminho: Path) -> list[dict]:
    """Lê uma planilha (.xlsx ou .csv) com colunas CPF / Sócio / Valor
    Distribuído / Pró-labore / IRRF (nessa ordem ou não, identificadas pelo
    cabeçalho — as duas últimas são opcionais) e retorna uma lista de
    {"cpf", "nome", "valor_distribuido", "pro_labore", "irrf"}. Não valida
    contra o banco — isso é responsabilidade de quem chama."""
    caminho = Path(caminho)
    linhas_brutas = _ler_csv(caminho) if caminho.suffix.lower() == ".csv" else _ler_xlsx(caminho)
    linhas_brutas = [linha for linha in linhas_brutas if any(c not in (None, "") for c in linha)]

    if not linhas_brutas:
        return []

    cabecalho = [str(c or "").strip().lower() for c in linhas_brutas[0]]
    indice_cpf = _indice_coluna(cabecalho, ["cpf"])
    indice_nome = _indice_coluna(cabecalho, ["sócio", "socio", "nome"])
    indice_valor = _indice_coluna(cabecalho, ["valor distribuído", "valor distribuido", "valor"])
    indice_pro_labore = _indice_coluna(cabecalho, ["pró-labore", "pro-labore", "pro labore", "prolabore"])
    indice_irrf = _indice_coluna(cabecalho, ["irrf"])

    if indice_valor is None:
        raise ValueError(
            'Não encontrei a coluna "Valor Distribuído" na planilha. '
            "Use o modelo exportado pelo sistema (botão \"Exportar modelo\") pra garantir o formato certo."
        )
    if indice_cpf is None and indice_nome is None:
        raise ValueError('A planilha precisa ter uma coluna "CPF" ou "Sócio" pra identificar cada linha.')

    def numero_opcional(linha: list, indice: int | None, numero_linha: int, rotulo: str) -> float:
        if indice is None or indice >= len(linha):
            return 0.0
        try:
            return _para_numero(linha[indice])
        except ValueError:
            raise ValueError(f'Linha {numero_linha}: {rotulo} inválido "{linha[indice]}".') from None

    resultado = []
    for numero_linha, linha in enumerate(linhas_brutas[1:], start=2):
        cpf = str(linha[indice_cpf]).strip() if indice_cpf is not None and indice_cpf < len(linha) and linha[indice_cpf] else ""
        nome = str(linha[indice_nome]).strip() if indice_nome is not None and indice_nome < len(linha) and linha[indice_nome] else ""
        valor_bruto = linha[indice_valor] if indice_valor < len(linha) else None
        try:
            valor = _para_numero(valor_bruto)
        except ValueError:
            raise ValueError(f'Linha {numero_linha}: valor inválido "{valor_bruto}".') from None
        if not cpf and not nome:
            continue
        resultado.append(
            {
                "cpf": cpf,
                "nome": nome,
                "valor_distribuido": valor,
                "pro_labore": numero_opcional(linha, indice_pro_labore, numero_linha, "pró-labore"),
                "irrf": numero_opcional(linha, indice_irrf, numero_linha, "IRRF"),
            }
        )
    return resultado


def _indice_coluna(cabecalho: list[str], nomes_possiveis: list[str]) -> int | None:
    for nome in nomes_possiveis:
        if nome in cabecalho:
            return cabecalho.index(nome)
    return None


def _para_numero(valor) -> float:
    if valor is None or valor == "":
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip().replace("R$", "").strip()
    if "," in texto and texto.rfind(",") > texto.rfind("."):
        texto = texto.replace(".", "").replace(",", ".")
    return float(texto)


def _ler_csv(caminho: Path) -> list[list[str]]:
    with open(caminho, newline="", encoding="utf-8-sig") as arquivo:
        amostra = arquivo.read(2048)
        arquivo.seek(0)
        delimitador = ";" if amostra.count(";") >= amostra.count(",") else ","
        return list(csv.reader(arquivo, delimiter=delimitador))


def _ler_xlsx(caminho: Path) -> list[list]:
    workbook = openpyxl.load_workbook(caminho, data_only=True)
    aba = workbook.active
    return [list(linha) for linha in aba.iter_rows(values_only=True)]


_NUMERICOS_CADASTRO = frozenset(
    {"capital_social", "quantidade_cotas", "percentual_capital", "cotas_socio",
     "valor_distribuido", "pro_labore", "irrf"}
)


def _valor_cadastro(linha: dict, campo: str):
    valor = linha.get(campo)
    if campo in _NUMERICOS_CADASTRO:
        return valor or 0
    if campo == "tipo_pessoa":
        return valor or "fisica"
    return valor if valor is not None else ""


def _formatar_cabecalho(aba, colunas: list[str], campos: tuple[str, ...], linha: int = 1) -> None:
    for indice, nome in enumerate(colunas, start=1):
        celula = aba.cell(row=linha, column=indice, value=nome)
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = PatternFill("solid", fgColor="1B2A41")
    for indice, campo in enumerate(campos, start=1):
        aba.column_dimensions[get_column_letter(indice)].width = LARGURAS_CADASTRO[campo]


def _montar_aba_exemplo(workbook, modelo: ModeloCadastro) -> None:
    """Aba separada, nunca a de dados: exemplo dentro da planilha que vai ser
    importada viraria empresa fictícia no banco de quem esquecesse de apagar.
    Aqui dá pra consultar e copiar sem esse risco."""
    aba = workbook.create_sheet("Exemplo")

    aba["A1"] = f"Exemplo de preenchimento — modelo \"{modelo.nome}\""
    aba["A1"].font = Font(size=13, bold=True, color="1B2A41")
    aba["A2"] = "Dados fictícios, só para consulta. Preencha os seus na aba anterior."
    aba["A2"].font = Font(italic=True, color="5B6472")

    linha = 4
    for nota in NOTAS_EXEMPLO_CADASTRO:
        aba.cell(row=linha, column=1, value=f"• {nota}").font = Font(color="1B2A41")
        linha += 1

    linha += 1
    _formatar_cabecalho(aba, modelo.colunas, modelo.campos, linha=linha)

    exemplos = LINHAS_EXEMPLO_CADASTRO
    if modelo.uma_linha_por_empresa:
        # Sem coluna de sócio, repetir a empresa não ensina nada — só confunde
        # quem for contar quantas empresas o exemplo tem.
        vistas, unicas = set(), []
        for exemplo in exemplos:
            if exemplo["empresa_nome"] not in vistas:
                vistas.add(exemplo["empresa_nome"])
                unicas.append(exemplo)
        exemplos = unicas

    for exemplo in exemplos:
        linha += 1
        for indice, campo in enumerate(modelo.campos, start=1):
            aba.cell(row=linha, column=indice, value=_valor_cadastro(exemplo, campo))


def exportar_modelo_cadastro(
    caminho: Path, linhas: list[dict] | None = None, modelo: str | ModeloCadastro = "geral"
) -> None:
    """Gera um .xlsx pronto pra preencher com o cadastro em massa. Sem linhas,
    sai só com o cabeçalho — útil pra cadastrar do zero. Com linhas (cadastro
    atual), serve de referência/edição.

    `modelo` escolhe o recorte de colunas (ver MODELOS_CADASTRO): o completo
    faz tudo, e os menores existem porque a maior parte das importações não
    mexe em saída de sócio nem em distribuição, e dezesseis colunas para
    preencher cinco assusta mais do que ajuda.

    Toda planilha sai com uma aba "Exemplo" preenchida com dados fictícios."""
    modelo = modelo if isinstance(modelo, ModeloCadastro) else modelo_cadastro(modelo)

    workbook = openpyxl.Workbook()
    aba = workbook.active
    aba.title = "Cadastro"
    _formatar_cabecalho(aba, modelo.colunas, modelo.campos)
    aba.freeze_panes = "A2"

    for linha in linhas or []:
        aba.append([_valor_cadastro(linha, campo) for campo in modelo.campos])

    _montar_aba_exemplo(workbook, modelo)
    # A aba de dados tem que continuar sendo a ativa: é ela que o importador
    # lê (workbook.active), e é nela que a pessoa deve digitar ao abrir.
    workbook.active = 0
    workbook.save(caminho)


def importar_cadastro(caminho: Path) -> list[dict]:
    """Lê uma planilha (.xlsx ou .csv) de cadastro em massa — colunas
    identificadas pelo cabeçalho, na ordem de COLUNAS_CADASTRO ou não — e
    retorna uma lista de dicts com os campos crus (ainda não validados nem
    casados contra o banco; isso é responsabilidade de quem chama)."""
    caminho = Path(caminho)
    linhas_brutas = _ler_csv(caminho) if caminho.suffix.lower() == ".csv" else _ler_xlsx(caminho)
    linhas_brutas = [linha for linha in linhas_brutas if any(c not in (None, "") for c in linha)]

    if not linhas_brutas:
        return []

    cabecalho = [str(c or "").strip().lower() for c in linhas_brutas[0]]
    idx = {
        # "chamada" continua na lista: planilhas exportadas antes da mudança de
        # nome trazem o cabeçalho antigo, e recusá-las obrigaria a refazer
        # arquivo que já está preenchido.
        "numero_chamada": _indice_coluna(
            cabecalho,
            ["nº empresa", "numero empresa", "n° empresa", "número da empresa", "numero da empresa",
             "nº chamada", "numero chamada", "n° chamada", "chamada"],
        ),
        "empresa_nome": _indice_coluna(cabecalho, ["empresa", "nome da empresa", "razão social"]),
        "cnpj": _indice_coluna(cabecalho, ["cnpj"]),
        "capital_social": _indice_coluna(cabecalho, ["capital social", "capital"]),
        "quantidade_cotas": _indice_coluna(cabecalho, ["qtd. cotas da empresa", "cotas da empresa", "quantidade de cotas"]),
        "socio_nome": _indice_coluna(cabecalho, ["sócio", "socio", "nome do sócio", "nome do socio"]),
        "socio_cpf": _indice_coluna(cabecalho, ["cpf/cnpj do sócio", "cpf/cnpj do socio", "cpf do sócio", "cpf do socio", "cpf"]),
        "tipo_pessoa": _indice_coluna(cabecalho, ["tipo (física/jurídica)", "tipo (fisica/juridica)", "tipo"]),
        "percentual_capital": _indice_coluna(cabecalho, ["% capital do sócio", "% capital do socio", "percentual capital", "% capital"]),
        "cotas_socio": _indice_coluna(cabecalho, ["cotas do sócio", "cotas do socio"]),
        "data_entrada": _indice_coluna(cabecalho, ["data de entrada", "data entrada"]),
        "data_saida": _indice_coluna(cabecalho, ["data de saída", "data de saida", "data saída", "data saida"]),
        "ano_base": _indice_coluna(cabecalho, ["ano base", "ano_base", "ano"]),
        "valor_distribuido": _indice_coluna(cabecalho, ["valor distribuído", "valor distribuido", "valor"]),
        "pro_labore": _indice_coluna(cabecalho, ["pró-labore", "pro-labore", "pro labore", "prolabore"]),
        "irrf": _indice_coluna(cabecalho, ["irrf"]),
    }

    if idx["empresa_nome"] is None:
        raise ValueError(
            'Não encontrei a coluna "Empresa" na planilha. '
            "Use o modelo exportado pelo sistema (botão \"Exportar modelo\") pra garantir o formato certo."
        )
    # Planilha sem coluna de sócio é o modelo "Só empresas": cada linha cadastra
    # uma empresa e pronto. Diferente de ter a coluna e deixá-la em branco, que
    # continua sendo linha incompleta e é ignorada mais abaixo — a coluna
    # ausente é uma decisão do modelo, a coluna vazia é quase sempre descuido.
    so_empresas = idx["socio_nome"] is None and idx["socio_cpf"] is None

    def texto(linha: list, chave: str) -> str:
        i = idx[chave]
        if i is None or i >= len(linha) or linha[i] is None:
            return ""
        return str(linha[i]).strip()

    def numero_opcional(linha: list, chave: str, numero_linha: int, rotulo: str) -> float:
        i = idx[chave]
        if i is None or i >= len(linha) or linha[i] in (None, ""):
            return 0.0
        try:
            return _para_numero(linha[i])
        except ValueError:
            raise ValueError(f'Linha {numero_linha}: {rotulo} inválido "{linha[i]}".') from None

    resultado = []
    for numero_linha, linha in enumerate(linhas_brutas[1:], start=2):
        empresa_nome = texto(linha, "empresa_nome")
        socio_nome = texto(linha, "socio_nome")
        if not empresa_nome or (not socio_nome and not so_empresas):
            continue

        try:
            capital_social = numero_opcional(linha, "capital_social", numero_linha, "capital social")
            quantidade_cotas = numero_opcional(linha, "quantidade_cotas", numero_linha, "quantidade de cotas")
            percentual_capital = numero_opcional(linha, "percentual_capital", numero_linha, "percentual de capital")
            cotas_socio = numero_opcional(linha, "cotas_socio", numero_linha, "cotas do sócio")
            valor_distribuido = numero_opcional(linha, "valor_distribuido", numero_linha, "valor distribuído")
            pro_labore = numero_opcional(linha, "pro_labore", numero_linha, "pró-labore")
            irrf = numero_opcional(linha, "irrf", numero_linha, "IRRF")
        except ValueError:
            raise

        i_data = idx["data_entrada"]
        data_bruta = linha[i_data] if i_data is not None and i_data < len(linha) else None
        if so_empresas:
            data_entrada = ""
        else:
            try:
                data_entrada = _para_data(data_bruta)
            except ValueError:
                raise ValueError(f'Linha {numero_linha}: data de entrada inválida "{data_bruta}".') from None

        i_saida = idx["data_saida"]
        saida_bruta = linha[i_saida] if i_saida is not None and i_saida < len(linha) else None
        try:
            data_saida = _para_data_opcional(saida_bruta)
        except ValueError:
            raise ValueError(f'Linha {numero_linha}: data de saída inválida "{saida_bruta}".') from None

        i_ano = idx["ano_base"]
        ano_bruto = linha[i_ano] if i_ano is not None and i_ano < len(linha) else None
        ano_base = None
        if ano_bruto not in (None, ""):
            try:
                ano_base = int(_para_numero(ano_bruto))
            except ValueError:
                raise ValueError(f'Linha {numero_linha}: ano base inválido "{ano_bruto}".') from None

        tipo_bruto = texto(linha, "tipo_pessoa").lower()
        tipo_pessoa = "juridica" if tipo_bruto.startswith(("j", "pj")) else "fisica"

        resultado.append(
            {
                "numero_chamada": texto(linha, "numero_chamada"),
                "empresa_nome": empresa_nome,
                "cnpj": texto(linha, "cnpj"),
                "capital_social": capital_social,
                "quantidade_cotas": quantidade_cotas,
                "socio_nome": socio_nome,
                "socio_cpf": texto(linha, "socio_cpf"),
                "tipo_pessoa": tipo_pessoa,
                "percentual_capital": percentual_capital,
                "data_saida": data_saida,
                "ano_base": ano_base,
                "valor_distribuido": valor_distribuido,
                "pro_labore": pro_labore,
                "irrf": irrf,
                "cotas_socio": cotas_socio,
                "data_entrada": data_entrada,
            }
        )
    return resultado


def _converter_data(valor) -> str:
    """Aceita datetime/date (openpyxl já converte células de data) ou texto
    em dd/mm/aaaa ou aaaa-mm-dd. Não aceita vazio — quem chama decide o que
    fazer nesse caso (ver _para_data e _para_data_opcional)."""
    import datetime as _dt

    if isinstance(valor, _dt.datetime):
        return valor.date().isoformat()
    if isinstance(valor, _dt.date):
        return valor.isoformat()
    texto = str(valor).strip()
    if "/" in texto:
        dia, mes, ano = texto.split("/")
        return _dt.date(int(ano), int(mes), int(dia)).isoformat()
    return _dt.date.fromisoformat(texto).isoformat()


def _para_data(valor) -> str:
    """Vazio vira hoje — toda linha de vínculo precisa de uma data de
    entrada, então na ausência de uma informada assume-se a data atual."""
    import datetime as _dt

    if valor is None or valor == "":
        return _dt.date.today().isoformat()
    return _converter_data(valor)


def _para_data_opcional(valor) -> str | None:
    """Vazio vira None — ausência de data de saída significa que o sócio
    continua ativo, bem diferente de "saiu hoje"."""
    if valor is None or valor == "":
        return None
    return _converter_data(valor)


def exportar_relatorio_excel(
    caminho: Path, titulo: str, cabecalho: list[str], linhas: list[list], aba_nome: str = "Relatório"
) -> None:
    """Exporta um relatório tabular genérico (título + cabeçalho + linhas)
    com formatação básica — cabeçalho destacado, colunas com largura
    ajustada ao conteúdo, primeira linha congelada pra rolar com contexto."""
    workbook = openpyxl.Workbook()
    aba = workbook.active
    aba.title = aba_nome[:31]

    aba.append([titulo])
    if cabecalho:
        aba.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(cabecalho))
    aba["A1"].font = Font(size=14, bold=True, color="1B2A41")
    aba.append([])

    linha_cabecalho = 3
    aba.append(cabecalho)
    for celula in aba[linha_cabecalho]:
        celula.font = Font(bold=True, color="FFFFFF")
        celula.fill = PatternFill("solid", fgColor="1B2A41")

    for linha in linhas:
        aba.append(linha)

    aba.freeze_panes = f"A{linha_cabecalho + 1}"
    for indice_coluna in range(1, len(cabecalho) + 1):
        letra = get_column_letter(indice_coluna)
        maior = max(
            (len(str(aba.cell(row=r, column=indice_coluna).value or "")) for r in range(linha_cabecalho, aba.max_row + 1)),
            default=10,
        )
        aba.column_dimensions[letra].width = min(max(maior + 2, 10), 42)

    workbook.save(caminho)
