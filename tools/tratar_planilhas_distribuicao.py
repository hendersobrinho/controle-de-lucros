"""Trata as planilhas anuais "001.Distribuição de lucros AAAA.xlsx" (2019 a
2025) do escritório e gera uma planilha única, no formato de importação do
sistema, com o histórico consolidado.

    python tools/tratar_planilhas_distribuicao.py [pasta_das_planilhas] [--saida PASTA]

Gera, na pasta de saída (padrão: dados_tratados/):

- Importacao_historico_2019_2025.xlsx
    * aba "Cadastro": o modelo "Completo" do sistema — uma linha por empresa ×
      sócio × ano, em ordem cronológica, com entrada/saída de cada período da
      participação e a distribuição do ano. Importa pela tela de Importação
      (formato "Completo") ou pelo tools/importar_historico.py.
    * aba "Movimentações": adiantamentos, empréstimos e devolução de capital.
    * aba "Empresas": código, nome, capital, valor da cota e anotações.
    * aba "Revisar": tudo o que o tratamento teve de supor e que vale
      conferir (datas que não estavam na planilha, nomes parecidos…).

Como as planilhas de origem são organizadas (e o que muda entre os anos):

- Cada empresa é um bloco: na coluna A, o apelido na 1ª linha, o código na
  2ª e anotações nas seguintes ("Capital - 30.000,00", "Valor da cota 0,01",
  "Alteração em 22.07.2024", "Const. 08/04/19", "Empresa suspensa em …").
- As colunas mudam com os anos; aqui elas são achadas pelo texto do
  cabeçalho, não pela posição.
- De 2023 em diante o grupo AMMARE vem em abas próprias, às vezes com duas
  tabelas no mesmo ano (antes e depois de uma alteração): vale a última
  para o quadro e a soma das duas para o lucro.
- A aba U&E de 2025 é cópia da de 2024 (empresa suspensa em 22/10/2024) e é
  ignorada.
- CPF só existe em 2024/2025; nos anos anteriores o sócio é ligado pelo nome
  (sem acento, maiúsculo, espaços normalizados).
"""
from __future__ import annotations

import argparse
import datetime as dt
import difflib
import re
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from controle_lucros.planilha import exportar_modelo_cadastro, modelo_cadastro  # noqa: E402

PRIMEIRO_ANO = 2019

# Abas que são cópia de outra e não podem entrar duas vezes.
ABAS_IGNORADAS = {(2025, "U&E"): "cópia idêntica da aba U&E de 2024 (empresa suspensa em 22/10/2024)"}

# Apelido de empresa (sem acento, maiúsculo) -> código, para as abas que não
# trazem o código. Completado sozinho com o que as abas principais dizem.
CODIGOS_CONHECIDOS: dict[str, str] = {}


# ----------------------------------------------------------------- texto --
def sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn")


def limpar_espacos(texto: str) -> str:
    return re.sub(r"\s+", " ", str(texto or "")).strip()


def chave_nome(nome: str) -> str:
    """Como dois nomes são comparados: sem acento, maiúsculo, sem pontuação."""
    texto = sem_acento(limpar_espacos(nome)).upper()
    texto = re.sub(r"[^A-Z0-9& ]", " ", texto)
    return re.sub(r"\s+", " ", texto).strip()


def maiusculo(texto: str) -> str:
    return limpar_espacos(texto).upper()


def so_digitos(valor) -> str:
    if valor is None:
        return ""
    if isinstance(valor, float):
        valor = int(valor)
    return re.sub(r"\D", "", str(valor))


def formatar_documento(valor) -> str:
    digitos = so_digitos(valor)
    if not digitos:
        return ""
    if len(digitos) <= 11:
        d = digitos.zfill(11)
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    d = digitos.zfill(14)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def numero(valor) -> float | None:
    """Número de célula: aceita número, "12.000", "5.000,00"; texto que não é
    número ("-", "distrib. na matriz") vira None."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    texto = str(valor).strip()
    if not texto or not re.search(r"\d", texto):
        return None
    texto = re.sub(r"[^\d,.\-]", "", texto)
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    elif texto.count(".") >= 1 and re.fullmatch(r"-?\d{1,3}(\.\d{3})+", texto):
        texto = texto.replace(".", "")
    try:
        return float(texto)
    except ValueError:
        return None


_DATA = re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})")


def data_do_texto(texto) -> str | None:
    if isinstance(texto, (dt.datetime, dt.date)):
        return texto.strftime("%Y-%m-%d")
    achado = _DATA.search(str(texto or ""))
    if not achado:
        return None
    dia, mes, ano = (int(x) for x in achado.groups())
    if ano < 100:
        ano += 2000
    try:
        return dt.date(ano, mes, dia).isoformat()
    except ValueError:
        return None


# ------------------------------------------------------- leitura das abas --
@dataclass
class LinhaSocio:
    ano: int
    aba: str
    linha: int
    tabela: int
    empresa: "Bloco"
    nome: str
    nome_original: str
    observacao: str
    documento: str
    percentual: float | None
    capital_socio: float | None
    lucro: float | None
    pro_labore: float | None
    irrf: float | None
    evento: str | None  # "E" ou "S"
    data_evento: str | None
    adiantamento: float | None
    emprestimo_a_socio: float | None
    emprestimo_de_socio: float | None
    devolucao_capital: float | None
    texto_lucro: str = ""


@dataclass(eq=False)
class Bloco:
    ano: int
    aba: str
    linha: int
    apelido: str = ""
    codigo: str | None = None
    capital: float | None = None
    valor_cota: float | None = None
    datas_alteracao: list[str] = field(default_factory=list)
    data_constituicao: str | None = None
    anotacoes: list[str] = field(default_factory=list)
    socios: list[LinhaSocio] = field(default_factory=list)


_CAMPOS_CABECALHO = [
    # (campo, teste no texto do cabeçalho em minúsculo e sem acento)
    ("socio", lambda t: t.startswith("socio")),
    ("documento", lambda t: "cpf" in t.split()),
    ("quant_cotas", lambda t: "quant" in t and "cota" in t),
    ("saldo", lambda t: t.startswith("saldo")),
    ("percentual", lambda t: t.startswith("capital") and "saldo" not in t),
    ("lucro", lambda t: "lucros distribu" in t),
    ("deliberado", lambda t: t.startswith("deliber")),
    ("pro_labore", lambda t: "pro-labore" in t or "pro labore" in t),
    ("irrf", lambda t: "irrf" in t.split()),
    ("evento", lambda t: "data saida" in t or "entrada de socio" in t),
    ("variacao", lambda t: "variacao" in t),
    ("devolucao", lambda t: "devolucao" in t),
    ("adiantamento", lambda t: "adiantamento" in t),
    ("emprestimo_a_socio", lambda t: ("emprestimo a socio" in t or "emprestimos a socio" in t)),
    ("emprestimo_de_socio", lambda t: "emprestimos de socio" in t or "emprestimo de socio" in t),
    ("legenda", lambda t: t.startswith("legenda")),
]


def mapear_cabecalho(linha: tuple) -> dict[str, int]:
    mapa: dict[str, int] = {}
    for indice, celula in enumerate(linha):
        texto = sem_acento(limpar_espacos(celula)).lower()
        if not texto:
            continue
        for campo, teste in _CAMPOS_CABECALHO:
            if campo not in mapa and teste(texto):
                mapa[campo] = indice
                break
    return mapa


_NOTA = re.compile(
    r"^(ca+pital\b|valor da cota|cliente desde|veio para|foi para|aumento|distrato|apenas|empresa constitu|atera|const\b|const\.|constitu|alt\b|alt\.|altera|empresa suspensa|suspens|"
    r"baixa|baixad|tranaferid|transferid|na altera|a diferen|obs|distrib)",
    re.IGNORECASE,
)


def tipo_da_celula_a(valor) -> tuple[str, object]:
    """("codigo", int) | ("data", iso) | ("nota", texto) | ("apelido", texto) | ("vazio", None)."""
    if valor is None:
        return "vazio", None
    if isinstance(valor, (dt.datetime, dt.date)):
        return "data", valor.strftime("%Y-%m-%d")
    if isinstance(valor, float) and not valor.is_integer():
        return "codigo", str(valor)  # filial anotada como 6.2
    if isinstance(valor, (int, float)):
        return "codigo", str(int(valor))
    texto = limpar_espacos(valor)
    if not texto:
        return "vazio", None
    # Código: "137", e o das filiais, "247-2" ou "6.2".
    if re.fullmatch(r"\d{1,6}([.-]\d{1,3})?", texto):
        return "codigo", texto
    if _NOTA.match(sem_acento(texto).lower()) or len(texto) > 45:
        return "nota", texto
    return "apelido", texto


def interpretar_nota(bloco: Bloco, texto: str) -> None:
    simples = sem_acento(texto).lower()
    bloco.anotacoes.append(texto)
    if re.match(r"ca+pital", simples):
        valor = numero(texto.split("-", 1)[-1]) if "-" in texto else numero(texto)
        if valor:
            bloco.capital = valor
    elif simples.startswith("valor da cota"):
        valor = numero(re.sub(r"(?i)centavos?", "", texto.split("cota", 1)[-1]))
        if valor:
            bloco.valor_cota = valor
    elif simples.startswith(("const", "constitu", "empresa constitu")):
        bloco.data_constituicao = data_do_texto(texto) or bloco.data_constituicao
    elif simples.startswith(("alt", "na altera")):
        data = data_do_texto(texto)
        if data:
            bloco.datas_alteracao.append(data)


_MARCA = re.compile(r"\s*\((E|S)\)\s*$", re.IGNORECASE)
_PARENTESES = re.compile(r"\s*\(([^)]*)\)\s*")


def limpar_nome_socio(bruto: str) -> tuple[str, str, str | None]:
    """(nome, observação, marca E/S do nome)."""
    texto = limpar_espacos(bruto)
    marca = None
    achado = _MARCA.search(texto)
    if achado:
        marca = achado.group(1).upper()
        texto = texto[: achado.start()]
    observacao = ""
    parenteses = _PARENTESES.search(texto)
    if parenteses:
        observacao = f"({limpar_espacos(parenteses.group(1))})"
        texto = _PARENTESES.sub(" ", texto)
    elif "(" in texto:
        # Parêntese que não fecha ("… LTDA (MAYKE ARMANI"): o resto é anotação.
        texto, _, resto = texto.partition("(")
        observacao = f"({limpar_espacos(resto)})"
    # Sobra de parêntese digitado errado ("(MAYKE ARMANI)\nMIRANDA)"): fora.
    texto = " ".join(p for p in texto.split() if "(" not in p and ")" not in p)
    return maiusculo(texto), observacao, marca


def ler_evento(texto) -> tuple[str | None, str | None]:
    if texto is None:
        return None, None
    bruto = sem_acento(limpar_espacos(texto)).upper()
    if not bruto:
        return None, None
    tipo = None
    if bruto.startswith(("S", "SAIDA")):
        tipo = "S"
    elif bruto.startswith(("E", "ENTRADA")):
        tipo = "E"
    return tipo, data_do_texto(texto)


def ler_aba(ano: int, aba, principal: bool) -> list[Bloco]:
    linhas = list(aba.iter_rows(values_only=True))

    def vazia(linha) -> bool:
        return not any(c not in (None, "") and str(c).strip() for c in linha)

    def e_apelido(indice: int) -> bool:
        """Texto na coluna A só abre empresa nova quando o código vem logo
        embaixo, ou quando abre um bloco (linha anterior em branco) com sócio
        ao lado. Senão é anotação no meio do bloco ("DISTRATO …",
        "(ALTERAÇÃO CONTRATO", "AUMENTO DE CAPITAL…")."""
        seguinte = next((l for l in linhas[indice + 1: indice + 3] if not vazia(l)), None)
        if seguinte is not None and tipo_da_celula_a(seguinte[0])[0] == "codigo":
            return True
        anterior = linhas[indice - 1] if indice > 0 else None
        tem_socio = len(linhas[indice]) > 1 and limpar_espacos(linhas[indice][1])
        return bool(tem_socio) and (anterior is None or vazia(anterior))

    blocos: list[Bloco] = []
    mapa: dict[str, int] = {}
    tabela = 0
    atual: Bloco | None = None
    for numero_linha, linha in enumerate(linhas, start=1):
        if not any(c not in (None, "") and str(c).strip() for c in linha):
            continue
        celula_b = sem_acento(limpar_espacos(linha[1] if len(linha) > 1 else "")).lower()
        if celula_b.startswith("socio"):
            # Cabeçalho (de novo, numa aba com duas tabelas no ano). Ele ocupa
            # duas linhas — "capital" numa e "%" na outra —, então as duas
            # são lidas juntas.
            anterior = next((l for l in reversed(linhas[: numero_linha - 1]) if not vazia(l)), ())
            juntas = tuple(
                f"{limpar_espacos(anterior[i]) if i < len(anterior) and anterior[i] is not None else ''} "
                f"{limpar_espacos(c) if c is not None else ''}".strip()
                for i, c in enumerate(linha)
            )
            mapa = mapear_cabecalho(juntas)
            tabela += 1
            if not principal:
                atual = Bloco(ano, aba.title, numero_linha)
                blocos.append(atual)
            continue
        if not mapa:
            continue
        tipo, valor = tipo_da_celula_a(linha[0])
        if tipo == "apelido" and principal and not e_apelido(numero_linha - 1):
            tipo = "nota"
        if principal and tipo == "apelido":
            atual = Bloco(ano, aba.title, numero_linha, apelido=maiusculo(valor))
            blocos.append(atual)
        elif atual is None:
            continue
        elif tipo == "apelido":
            atual.apelido = atual.apelido or maiusculo(valor)
        if tipo == "codigo" and atual.codigo is None:
            atual.codigo = valor
        elif tipo == "nota":
            interpretar_nota(atual, valor)
        elif tipo == "data":
            atual.anotacoes.append(f"data anotada: {valor}")
            atual.datas_alteracao.append(valor)

        nome_bruto = linha[mapa["socio"]] if "socio" in mapa and mapa["socio"] < len(linha) else None
        if not nome_bruto or not limpar_espacos(nome_bruto):
            continue
        nome, observacao, marca = limpar_nome_socio(str(nome_bruto))
        if not nome or re.fullmatch(r"(SUB)?TOTA(L|IS)( GERAL)?|SOMA", sem_acento(nome)):
            continue

        def pegar(campo):
            indice = mapa.get(campo)
            return linha[indice] if indice is not None and indice < len(linha) else None

        tipo_evento, data_evento = ler_evento(pegar("evento"))
        if tipo_evento is None and marca:
            tipo_evento = marca
        if tipo_evento is None and data_evento:
            # Só a data, sem "E"/"S": quem ficou com 0% saiu; os outros entraram.
            tipo_evento = "S" if not (numero(pegar("percentual")) or 0) else "E"
        lucro_bruto = pegar("lucro")
        capital_socio = numero(pegar("saldo")) if "quant_cotas" in mapa else None
        atual.socios.append(LinhaSocio(
            ano=ano, aba=aba.title, linha=numero_linha, tabela=tabela, empresa=atual,
            nome=nome, nome_original=limpar_espacos(nome_bruto), observacao=observacao,
            documento=formatar_documento(pegar("documento")),
            percentual=numero(pegar("percentual")),
            capital_socio=capital_socio,
            lucro=numero(lucro_bruto), pro_labore=numero(pegar("pro_labore")), irrf=numero(pegar("irrf")),
            evento=tipo_evento, data_evento=data_evento,
            adiantamento=numero(pegar("adiantamento")),
            emprestimo_a_socio=numero(pegar("emprestimo_a_socio")),
            emprestimo_de_socio=numero(pegar("emprestimo_de_socio")),
            devolucao_capital=numero(pegar("devolucao")),
            texto_lucro=limpar_espacos(lucro_bruto) if isinstance(lucro_bruto, str) else "",
        ))
    return [b for b in blocos if b.socios or b.codigo is not None]


def ler_todas(pasta: Path, revisar: list) -> list[Bloco]:
    blocos: list[Bloco] = []
    for arquivo in sorted(pasta.glob("001.Distribui*o de lucros 20*.xlsx")):
        ano = int(re.search(r"(20\d\d)", arquivo.name).group(1))
        livro = openpyxl.load_workbook(arquivo, data_only=True)
        for indice, aba in enumerate(livro.worksheets):
            if (ano, aba.title) in ABAS_IGNORADAS:
                revisar.append((ano, "", aba.title, "Aba ignorada", ABAS_IGNORADAS[(ano, aba.title)]))
                continue
            blocos.extend(ler_aba(ano, aba, principal=indice == 0))
    return blocos


# ------------------------------------------------------------ consolidar --
@dataclass(eq=False)
class Empresa:
    chave: str
    codigo: str | None
    nome: str
    apelidos: set = field(default_factory=set)
    capital: float | None = None
    valor_cota: float | None = None
    data_constituicao: str | None = None
    anotacoes: list = field(default_factory=list)
    anos: set = field(default_factory=set)


@dataclass(eq=False)
class Socio:
    chave: str
    nome: str
    documento: str = ""
    nomes_vistos: set = field(default_factory=set)
    observacoes: set = field(default_factory=set)

    @property
    def tipo(self) -> str:
        if len(so_digitos(self.documento)) == 14 or re.search(r"\b(LTDA|S/?A|EIRELI|ME)\b", self.nome):
            return "juridica"
        return "fisica"


def consolidar(blocos: list[Bloco], revisar: list):
    # Código das empresas que aparecem sem código (abas do grupo AMMARE).
    for b in blocos:
        if b.codigo is not None and b.apelido:
            CODIGOS_CONHECIDOS.setdefault(chave_nome(b.apelido), b.codigo)
    for b in blocos:
        if b.codigo is None and b.apelido:
            b.codigo = CODIGOS_CONHECIDOS.get(chave_nome(b.apelido))

    empresas: dict[str, Empresa] = {}
    for b in sorted(blocos, key=lambda b: b.ano):
        chave = f"cod:{b.codigo}" if b.codigo is not None else f"nome:{chave_nome(b.apelido)}"
        b.chave = chave
        empresa = empresas.get(chave)
        if empresa is None:
            empresa = empresas[chave] = Empresa(chave, b.codigo, b.apelido or f"EMPRESA {b.codigo}")
            if b.codigo is None:
                revisar.append((b.ano, b.apelido, b.aba, "Empresa sem código",
                                f"linha {b.linha}: a planilha não traz o código; ficou sem nº."))
        if b.apelido:
            empresa.apelidos.add(b.apelido)
            empresa.nome = b.apelido  # o mais recente vale
        empresa.capital = b.capital or empresa.capital
        empresa.valor_cota = b.valor_cota or empresa.valor_cota
        empresa.data_constituicao = empresa.data_constituicao or b.data_constituicao
        empresa.anotacoes.extend(f"{b.ano}: {a}" for a in b.anotacoes)
        empresa.anos.add(b.ano)

    # Sócios: CPF quando houver; o nome liga os anos sem CPF.
    por_documento: dict[str, Socio] = {}
    por_nome: dict[str, Socio] = {}
    linhas = [s for b in blocos for s in b.socios]
    for s in sorted(linhas, key=lambda s: -s.ano):  # anos com CPF primeiro
        chave = chave_nome(s.nome)
        socio = None
        if s.documento:
            socio = por_documento.get(s.documento)
        if socio is None:
            socio = por_nome.get(chave)
        if socio is None:
            socio = Socio(chave=s.documento or chave, nome=s.nome, documento=s.documento)
        if s.documento and not socio.documento:
            socio.documento = s.documento
        if s.documento and socio.documento and s.documento != socio.documento:
            revisar.append((s.ano, s.empresa.apelido, s.aba, "Mesmo nome, CPFs diferentes",
                            f"{s.nome}: {socio.documento} e {s.documento} — tratados como pessoas diferentes."))
            socio = Socio(chave=s.documento, nome=s.nome, documento=s.documento)
        if socio.documento:
            por_documento[socio.documento] = socio
        por_nome.setdefault(chave, socio)
        socio.nomes_vistos.add(s.nome)
        if s.observacao:
            socio.observacoes.add(s.observacao)
        s.socio = socio

    socios = {id(s): s for s in por_nome.values()} | {id(s): s for s in por_documento.values()}
    socios = list(socios.values())
    contagem = defaultdict(lambda: defaultdict(int))
    for s in linhas:
        contagem[id(s.socio)][s.nome] += 1
    for socio in socios:
        if len(socio.nomes_vistos) > 1:
            # O nome que fica é o mais usado nas planilhas (e, empatado, o mais
            # completo): o mais longo sozinho às vezes é o que tem erro.
            vezes = contagem[id(socio)]
            socio.nome = max(socio.nomes_vistos, key=lambda n: (vezes[n], len(n)))

    # Nomes parecidos que não foram juntados (ex.: VAN DER ZWAAG x VAN DER WAAG).
    sem_cpf = sorted(socios, key=lambda s: s.nome)
    chaves = [chave_nome(s.nome) for s in sem_cpf]
    for i, a in enumerate(sem_cpf):
        for j in range(i + 1, min(i + 8, len(sem_cpf))):
            b = sem_cpf[j]
            if a.documento and b.documento:
                continue
            if difflib.SequenceMatcher(None, chaves[i], chaves[j]).ratio() >= 0.92:
                revisar.append(("", "", "", "Nomes parecidos",
                                f"{a.nome} {a.documento or '(sem CPF)'}  ×  {b.nome} {b.documento or '(sem CPF)'} "
                                "— confira se é a mesma pessoa."))
    return empresas, socios, linhas


@dataclass
class Periodo:
    empresa: Empresa
    socio: Socio
    percentual: float
    capital_socio: float | None
    entrada: str
    saida: str | None = None
    anos: list = field(default_factory=list)


def montar_periodos(empresas, linhas, revisar):
    """A participação de cada sócio em cada empresa, em períodos de % fixo."""
    ultimo_ano = max(l.ano for l in linhas)
    anos_da_empresa: dict[str, set] = {chave: e.anos for chave, e in empresas.items()}
    por_par: dict[tuple, dict[int, list[LinhaSocio]]] = defaultdict(lambda: defaultdict(list))
    for l in linhas:
        por_par[(l.empresa.chave, id(l.socio))][l.ano].append(l)

    periodos: list[Periodo] = []
    for (chave_empresa, _id), por_ano in por_par.items():
        empresa = empresas[chave_empresa]
        anos = sorted(por_ano)
        socio = por_ano[anos[0]][0].socio
        atual: Periodo | None = None
        for ano in anos:
            registros = sorted(por_ano[ano], key=lambda r: (r.tabela, r.linha))
            final = registros[-1]  # a última tabela do ano é o quadro vigente
            # % em branco na planilha é "não informado", não zero: zero é saída.
            informado = final.percentual is not None
            percentual = final.percentual or 0.0
            # Quem saiu no ano ainda aparece com a fatia de antes na primeira
            # tabela; é ela que vale para o período que está terminando.
            percentual_inicio = next((r.percentual for r in registros if r.percentual), 0.0)
            recebeu = any((r.lucro or 0) or (r.pro_labore or 0) or (r.irrf or 0) for r in registros)
            entradas = [r.data_evento for r in registros if r.evento == "E" and r.data_evento]
            saidas = [r.data_evento for r in registros if r.evento == "S" and r.data_evento]
            blocos_do_ano = {r.empresa for r in registros}
            alteracoes = sorted({d for b in blocos_do_ano for d in b.datas_alteracao if d.startswith(str(ano))})
            constituicao = next((b.data_constituicao for b in blocos_do_ano if b.data_constituicao), None)

            if atual is not None and atual.saida is not None and entradas and entradas[0] <= atual.saida:
                # A mesma entrada repetida na planilha do ano seguinte: é o
                # mesmo período, que não tinha acabado.
                atual.saida = None
            if atual is None or atual.saida is not None:
                if percentual <= 0 and not entradas and not percentual_inicio and not recebeu:
                    continue  # aparece só como saída de alguém que não estava aqui
                if percentual <= 0 and percentual_inicio:
                    percentual = percentual_inicio
                if entradas:
                    entrada = entradas[0]
                elif constituicao and constituicao.startswith(str(ano)):
                    entrada = constituicao
                elif ano == PRIMEIRO_ANO and atual is None:
                    entrada = f"{ano}-01-01"
                    revisar.append((ano, empresa.nome, final.aba, "Entrada anterior a 2019",
                                    f"{socio.nome}: já era sócio em 2019; entrada registrada em 01/01/2019."))
                elif alteracoes:
                    entrada = alteracoes[0]
                    revisar.append((ano, empresa.nome, final.aba, "Entrada sem data",
                                    f"{socio.nome}: entrou em {ano} sem data na planilha; usada a alteração de "
                                    f"{_br(entrada)}."))
                else:
                    entrada = f"{ano}-01-01"
                    revisar.append((ano, empresa.nome, final.aba, "Entrada sem data",
                                    f"{socio.nome}: aparece a partir de {ano} sem data de entrada; usado 01/01/{ano}."))
                atual = Periodo(empresa, socio, percentual, final.capital_socio, entrada)
                periodos.append(atual)
            elif informado and percentual > 0 and abs(percentual - atual.percentual) > 0.0005:
                # Participação refeita: fecha o período e abre outro.
                data = (alteracoes[0] if alteracoes else f"{ano}-01-01")
                if data <= atual.entrada:
                    data = f"{ano}-01-01" if f"{ano}-01-01" > atual.entrada else atual.entrada
                if not alteracoes:
                    revisar.append((ano, empresa.nome, final.aba, "Mudança de % sem data",
                                    f"{socio.nome}: {_pct(atual.percentual)} → {_pct(percentual)} em {ano}; "
                                    f"usado {_br(data)}."))
                atual.saida = data
                atual = Periodo(empresa, socio, percentual, final.capital_socio, data)
                periodos.append(atual)
            if final.capital_socio:
                atual.capital_socio = final.capital_socio
            atual.anos.append(ano)

            if saidas or (final.evento == "S"):
                atual.saida = saidas[-1] if saidas else f"{ano}-12-31"
                if not saidas:
                    revisar.append((ano, empresa.nome, final.aba, "Saída sem data",
                                    f"{socio.nome}: marcado como saída em {ano} sem data; usado 31/12/{ano}."))
            elif informado and (final.percentual or 0) <= 0:
                # Zerou no ano: saiu na alteração do ano, se a planilha a anota.
                depois = [d for d in alteracoes if d >= atual.entrada]
                atual.saida = depois[-1] if depois else f"{ano}-12-31"
                revisar.append((ano, empresa.nome, final.aba, "Participação zerada",
                                f"{socio.nome}: 0% em {ano} sem data de saída; considerado saída em "
                                f"{_br(atual.saida)}."))

        # Sumiu da planilha do ano seguinte (com a empresa ainda lá): saiu.
        if atual is not None and atual.saida is None:
            ultimo = max(atual.anos)
            seguintes = [a for a in anos_da_empresa[chave_empresa] if a > ultimo]
            if seguintes and ultimo < ultimo_ano:
                atual.saida = f"{ultimo}-12-31"
                revisar.append((ultimo + 1, empresa.nome, "", "Saída sem registro",
                                f"{socio.nome}: estava em {ultimo} e não aparece em {min(seguintes)}; "
                                f"considerado saída em 31/12/{ultimo}."))
    for p in periodos:
        if p.saida is not None and p.saida < p.entrada:
            revisar.append(("", p.empresa.nome, "", "Saída antes da entrada",
                            f"{p.socio.nome}: entrada {_br(p.entrada)}, saída {_br(p.saida)} — saída ajustada."))
            p.saida = p.entrada
    return periodos


def _ordem_codigo(codigo: str | None) -> tuple:
    """"6" < "6.2" < "7" < "247-2": número da matriz, depois a filial."""
    if not codigo:
        return (999999, 0, "")
    partes = re.split(r"[.-]", codigo)
    try:
        return (int(partes[0]), int(partes[1]) if len(partes) > 1 else 0, codigo)
    except ValueError:
        return (999998, 0, codigo)


def _br(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else ""


def _pct(valor: float) -> str:
    return f"{valor:.4f}".replace(".", ",") + "%"


# --------------------------------------------------------------- saída --
def linhas_de_cadastro(empresas, periodos, linhas) -> list[dict]:
    """Uma linha por empresa × sócio × ano, em ordem cronológica: é a ordem
    em que o importador do sistema monta o histórico certo (cria o período,
    fecha na saída, abre o seguinte)."""
    distribuicao: dict[tuple, dict[str, float]] = defaultdict(lambda: {"lucro": 0.0, "pro": 0.0, "irrf": 0.0})
    for l in linhas:
        soma = distribuicao[(l.empresa.chave, id(l.socio), l.ano)]
        soma["lucro"] += l.lucro or 0.0
        soma["pro"] += l.pro_labore or 0.0
        soma["irrf"] += l.irrf or 0.0

    saida = []
    for p in sorted(periodos, key=lambda p: (_ordem_codigo(p.empresa.codigo), p.empresa.nome, p.entrada, p.socio.nome)):
        e = p.empresa
        valor_cota = e.valor_cota or 1.0
        capital_socio = p.capital_socio
        if e.capital and p.percentual:
            capital_socio = round(e.capital * p.percentual / 100, 2)
        for ano in sorted(p.anos):
            soma = distribuicao.get((e.chave, id(p.socio), ano), {"lucro": 0, "pro": 0, "irrf": 0})
            ultimo = ano == max(p.anos)
            saida.append({
                "numero_chamada": e.codigo or "",
                "empresa_nome": e.nome,
                "cnpj": "",
                "capital_social": e.capital or 0.0,
                "quantidade_cotas": round(e.capital / valor_cota, 2) if e.capital else 0.0,
                "socio_nome": p.socio.nome,
                "socio_cpf": p.socio.documento,
                "tipo_pessoa": "jurídica" if p.socio.tipo == "juridica" else "física",
                "percentual_capital": round(p.percentual, 4),
                "cotas_socio": round(capital_socio / valor_cota, 2) if capital_socio else None,
                "valor_capital_socio": capital_socio,
                "data_entrada": p.entrada,
                "data_saida": p.saida if ultimo else None,
                "ano_base": ano,
                "valor_distribuido": round(soma["lucro"], 2) or None,
                "pro_labore": round(soma["pro"], 2) or None,
                "irrf": round(soma["irrf"], 2) or None,
            })
    saida.sort(key=lambda l: (l["ano_base"], _ordem_codigo(l["numero_chamada"]), l["data_entrada"], l["socio_nome"]))
    return saida


def movimentacoes(linhas) -> list[dict]:
    tipos = (
        ("adiantamento", "adiantamento_lucro", "Adiantamento de lucro"),
        ("emprestimo_a_socio", "emprestimo_empresa_para_socio", "Empréstimo da empresa ao sócio"),
        ("emprestimo_de_socio", "emprestimo_socio_para_empresa", "Empréstimo do sócio à empresa"),
        ("devolucao_capital", "devolucao_capital", "Devolução de capital"),
    )
    soma: dict[tuple, float] = defaultdict(float)
    for l in linhas:
        for campo, tipo, _rotulo in tipos:
            valor = getattr(l, campo) or 0.0
            if valor:
                soma[(l.ano, l.empresa.chave, id(l.socio), tipo)] += valor
    por_id = {id(l.socio): l.socio for l in linhas}
    empresas = {l.empresa.chave: l.empresa for l in linhas}
    rotulos = {tipo: rotulo for _c, tipo, rotulo in tipos}
    saida = []
    for (ano, chave, socio_id, tipo), valor in sorted(soma.items(), key=lambda x: (x[0][0], str(x[0][1]))):
        if abs(valor) < 0.005:
            continue
        bloco = empresas[chave]
        saida.append({
            "ano": ano, "numero_chamada": bloco.codigo or "",
            "empresa": bloco.apelido, "socio": por_id[socio_id].nome, "cpf": por_id[socio_id].documento,
            "tipo": tipo, "tipo_rotulo": rotulos[tipo], "data": f"{ano}-12-31", "valor": round(valor, 2),
        })
    return saida


def escrever(destino: Path, cadastro, movs, empresas, revisar) -> None:
    exportar_modelo_cadastro(destino, cadastro, modelo=modelo_cadastro("geral"))
    livro = openpyxl.load_workbook(destino)
    if "Exemplo" in livro.sheetnames:
        del livro["Exemplo"]
    cabecalho_estilo = Font(bold=True, color="FFFFFF")
    fundo = PatternFill("solid", fgColor="203461")

    def aba(nome, cabecalho, linhas, larguras):
        planilha = livro.create_sheet(nome)
        planilha.append(cabecalho)
        for celula in planilha[1]:
            celula.font = cabecalho_estilo
            celula.fill = fundo
        for linha in linhas:
            planilha.append(linha)
        for indice, largura in enumerate(larguras, start=1):
            planilha.column_dimensions[get_column_letter(indice)].width = largura
        planilha.freeze_panes = "A2"

    aba("Movimentações", ["Ano", "Nº Empresa", "Empresa", "Sócio", "CPF/CNPJ", "Tipo", "Data", "Valor"],
        [[m["ano"], m["numero_chamada"], m["empresa"], m["socio"], m["cpf"], m["tipo_rotulo"], m["data"], m["valor"]]
         for m in movs], [7, 11, 30, 40, 20, 32, 12, 16])
    aba("Empresas", ["Nº Empresa", "Empresa", "Outros nomes nas planilhas", "Capital social", "Valor da cota",
                     "Constituição", "Anos nas planilhas", "Anotações"],
        [[e.codigo, e.nome, ", ".join(sorted(e.apelidos - {e.nome})), e.capital, e.valor_cota,
          e.data_constituicao, ", ".join(str(a) for a in sorted(e.anos)), " | ".join(e.anotacoes)[:3000]]
         for e in sorted(empresas.values(), key=lambda e: (_ordem_codigo(e.codigo), e.nome))],
        [11, 34, 30, 16, 12, 13, 30, 80])
    aba("Revisar", ["Ano", "Empresa", "Aba", "O que conferir", "Detalhe"],
        [list(r) for r in revisar], [7, 30, 16, 28, 110])
    livro.save(destino)


def tratar(pasta: Path, saida: Path) -> dict:
    revisar: list = []
    blocos = ler_todas(pasta, revisar)
    empresas, socios, linhas = consolidar(blocos, revisar)
    periodos = montar_periodos(empresas, linhas, revisar)
    cadastro = linhas_de_cadastro(empresas, periodos, linhas)
    movs = movimentacoes(linhas)
    saida.mkdir(parents=True, exist_ok=True)
    destino = saida / "Importacao_historico_2019_2025.xlsx"
    escrever(destino, cadastro, movs, empresas, revisar)
    return {
        "arquivo": destino, "blocos": len(blocos), "empresas": len(empresas), "socios": len(socios),
        "periodos": len(periodos), "linhas_cadastro": len(cadastro), "movimentacoes": len(movs),
        "revisar": len(revisar), "cadastro": cadastro, "movs": movs,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("pasta", nargs="?", default=".", help="onde estão as planilhas 001.Distribuição…")
    parser.add_argument("--saida", default="dados_tratados", help="pasta da planilha gerada")
    args = parser.parse_args()
    resultado = tratar(Path(args.pasta), Path(args.saida))
    for chave in ("blocos", "empresas", "socios", "periodos", "linhas_cadastro", "movimentacoes", "revisar"):
        print(f"{chave:>16}: {resultado[chave]}")
    print(f"\nPlanilha gerada: {resultado['arquivo']}")


if __name__ == "__main__":
    main()
