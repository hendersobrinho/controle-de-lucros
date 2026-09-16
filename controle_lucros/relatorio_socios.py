"""Leitura do relatório "Cadastro de Sócios" emitido por outro sistema
contábil, em PDF, para alimentar o cadastro daqui sem redigitar.

O relatório traz, por empresa, uma linha por sócio mais ou menos assim:

    1041 CAIO GUIMARAES ARAUJO 142.575.367-13 16/02/2024 0,51
    707 LUIZA DIAS TORRES 103.285.827-35 02/03/2023 20/05/2026 0

ou seja: código, nome, inscrição (CPF ou CNPJ), data de ingresso, data de
saída (só para quem saiu) e participação.

O "mais ou menos" é o ponto deste módulo. Cada sistema contábil imprime esse
relatório de um jeito: com ou sem a coluna de código, com "%" no percentual,
com uma coluna de qualificação no fim, com o cabeçalho quebrado em duas
linhas, com travessão em vez de hífen. Uma expressão regular que descrevesse
a linha inteira acertaria um layout e recusaria todos os outros — e recusar é
o pior resultado possível, porque a pessoa não tem como saber o que no arquivo
desagradou.

A leitura aqui é por ÂNCORA: acha-se primeiro o CPF ou CNPJ, que é o único
campo com formato inconfundível, e o resto da linha é lido em relação a ele —
o que vem antes é código e nome, o que vem depois são as datas e o percentual,
em qualquer ordem e com qualquer coluna extra no meio. O que não for
reconhecido é devolvido em `ignoradas`, para a tela poder dizer quantas linhas
ficaram de fora em vez de importar menos gente em silêncio.

Quem já saiu costuma aparecer com participação zerada — é o que o relatório
informa, e é o que gravamos: o percentual que a pessoa tinha enquanto era
sócia não está no documento.

Este módulo não importa Qt: ele recebe o TEXTO já extraído do PDF (ver
ui/leitor_pdf.py) e devolve estrutura pronta, testável sem abrir janela.

As linhas geradas por linhas_para_importacao() têm exatamente o mesmo formato
das que vêm de planilha.importar_cadastro(), então o resto do caminho
(casamento de empresa e sócio, revisão de pendências, criação de vínculo) é o
mesmo já usado pela importação em massa.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .fiscal import cpf_valido, formatar_cnpj, formatar_cpf
from .planilha import normalizar_nome

# ------------------------------------------------------------------ formatos
# O CNPJ alfanumérico (vigente na Receita desde 2026) tem letras nas oito
# primeiras posições, então o padrão aceita letra e dígito ali.
_CNPJ_PONTUADO = r"[0-9A-Za-z]{2}\.[0-9A-Za-z]{3}\.[0-9A-Za-z]{3}/[0-9A-Za-z]{4}-\d{2}"
_CPF_PONTUADO = r"\d{3}\.\d{3}\.\d{3}-\d{2}"
_SO_DIGITOS = r"\d{11,14}"

_INSCRICAO = re.compile(rf"(?<![\w.\-/]){_CNPJ_PONTUADO}|{_CPF_PONTUADO}|{_SO_DIGITOS}(?![\w.\-/])")

# dd/mm/aaaa, dd/mm/aa, dd-mm-aaaa e aaaa-mm-dd: os quatro aparecem em
# relatório por aí, e nenhum deles é ambíguo com os outros.
_DATA = re.compile(r"\b(?:\d{4}-\d{2}-\d{2}|\d{2}[/\-]\d{2}[/\-]\d{4}|\d{2}[/\-]\d{2}[/\-]\d{2})\b")

# "Empresa: 91 - NOME", "EMPRESA 91 – NOME", "Empresa nº 91 - NOME". O número
# é obrigatório de propósito: o cabeçalho do escritório que emitiu o relatório
# também fala em empresa, mas sem número, e não pode virar uma empresa do
# quadro.
# "Empresa", "Cliente" e "Estabelecimento" são o mesmo cabeçalho em sistemas
# diferentes.
_PALAVRA_EMPRESA = r"(?:empresa|cliente|estabelecimento)"

# "Empresa: 91 - NOME", e também "Empresa: 91 NOME" — na planilha o número e o
# nome costumam estar em colunas separadas, e o hífen que os liga no papel
# simplesmente não existe.
_CABECALHO_EMPRESA = re.compile(
    rf"\b{_PALAVRA_EMPRESA}\b\s*[:.\-]?\s*(?:n[º°o]?\.?\s*)?"
    r"(?P<numero>\d{1,8})\s*(?:[-–—]\s*)?(?P<nome>\S.*?)\s*$",
    re.IGNORECASE,
)

# Cabeçalho que identifica a empresa pelo CNPJ em vez de por um número de
# ordem. O CNPJ é aproveitado: é justamente o campo que o relatório costuma
# não trazer, e com ele a empresa nasce identificada.
_CABECALHO_POR_CNPJ = re.compile(
    rf"\b{_PALAVRA_EMPRESA}\b\s*[:.\-]?\s*(?P<cnpj>{_CNPJ_PONTUADO}|\d{{14}})"
    r"\s*(?:[-–—]\s*)?(?P<nome>\S.*?)\s*$",
    re.IGNORECASE,
)

# Última tentativa, usada só quando o arquivo inteiro não tem nenhum cabeçalho
# numerado: "Empresa: NOME", sem número nenhum. Fica por último porque é a
# mesma forma do cabeçalho do escritório que emite o relatório — ver
# ler_relatorio_socios.
_CABECALHO_SEM_NUMERO = re.compile(
    rf"^\s*{_PALAVRA_EMPRESA}\s*[:.\-]\s*(?P<nome>\S.*?)\s*$", re.IGNORECASE
)

_DATA_DO_QUADRO = re.compile(
    r"data\s+do\s+quadro\s+societ[áa]rio\s*[:\-]?\s*(?P<data>\S+)", re.IGNORECASE
)

# Número com vírgula ou ponto decimal, com ou sem separador de milhar. A
# forma com milhar vem primeiro porque a alternância do re para na primeira
# que casa: com a ordem trocada, "46.94" casaria só o "46" e a participação
# entraria errada — silenciosamente, que é o pior jeito de errar.
_NUMERO = re.compile(
    r"(?<![\w,.])(?P<valor>\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(?P<pct>%?)"
)

_MOEDA_ANTES = re.compile(r"(?:R\$|RS)\s*$", re.IGNORECASE)

# Rótulo de coluna colado no documento: "... ANDRE CARDOSO CPF: 076.925.727-55".
# É retirado do fim do nome, senão o sócio entraria no cadastro chamado
# "ANDRE CARDOSO CPF".
_PADRAO_ROTULO = (
    r"(?:c\.?\s?p\.?\s?f\.?(?:\s*/\s*c\.?\s?n\.?\s?p\.?\s?j\.?)?"
    r"|c\.?\s?n\.?\s?p\.?\s?j\.?(?:\s*/\s*mf)?"
    r"|inscri[çc][ãa]o|documento|doc)"
)

_ROTULO_DOCUMENTO = re.compile(
    rf"[\s\-–—]*\b{_PADRAO_ROTULO}\s*[:.\-]?\s*$", re.IGNORECASE
)

# Uma linha cujo texto antes do documento é SÓ um rótulo desses não é sócio
# nenhum: é o cabeçalho do escritório que emitiu o relatório.
_SO_ROTULO = re.compile(rf"[\s\-–—]*{_PADRAO_ROTULO}\s*[:.\-]?\s*", re.IGNORECASE)

# Palavras que sozinhas nunca formam nome de pessoa nem razão social. Servem
# para recusar linha de total, de rodapé e de cabeçalho repetido por página.
_PALAVRAS_QUE_NAO_SAO_NOME = frozenset(
    {"TOTAL", "SUBTOTAL", "SOMA", "PAGINA", "EMITIDO", "EMISSAO", "RELATORIO",
     "SISTEMA", "LICENCIADO", "EMPRESA", "CONTINUA", "CONTINUACAO"}
)

# Palavras que aparecem em cabeçalho de coluna. Uma linha dessas nunca traz
# CPF junto, mas a checagem é barata e evita surpresa em layout estranho.
_CABECALHO_DE_COLUNA = re.compile(
    r"\b(c[óo]digo|inscri[çc][ãa]o|participa[çc][ãa]o|ingresso|sa[íi]da)\b.*"
    r"\b(c[óo]digo|inscri[çc][ãa]o|participa[çc][ãa]o|ingresso|sa[íi]da)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SocioDoRelatorio:
    codigo: str
    nome: str
    inscricao: str
    tipo_pessoa: str
    percentual: float
    data_entrada: str
    data_saida: str | None


@dataclass
class EmpresaDoRelatorio:
    numero: str
    nome: str
    data_quadro: str | None = None
    cnpj: str = ""
    socios: list[SocioDoRelatorio] = field(default_factory=list)


@dataclass
class LeituraDoRelatorio:
    """O que o arquivo rendeu — e o que ficou de fora.

    `ignoradas` são linhas que pareciam dados (tinham data ou documento) e
    mesmo assim não foram entendidas. Existe para a tela poder avisar: importar
    17 de 19 sócios sem dizer nada é pior do que não importar."""

    empresas: list[EmpresaDoRelatorio] = field(default_factory=list)
    ignoradas: list[str] = field(default_factory=list)

    @property
    def total_socios(self) -> int:
        return sum(len(e.socios) for e in self.empresas)


class RelatorioInvalido(ValueError):
    """O arquivo não é o relatório de sócios esperado."""


# --------------------------------------------------------------- conversões
def _para_iso(data: str) -> str | None:
    """Qualquer um dos formatos aceitos vira aaaa-mm-dd. Devolve None quando a
    data não existe de verdade (32/13/2020), em vez de inventar uma."""
    import datetime as dt

    texto = data.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", texto):
        ano, mes, dia = texto.split("-")
    else:
        partes = re.split(r"[/\-]", texto)
        if len(partes) != 3:
            return None
        dia, mes, ano = partes
        if len(ano) == 2:
            # Convenção do POSIX: 00-69 é 2000, 70-99 é 1900. Serve bem para
            # data de entrada de sócio, que vai de meados do século passado
            # até hoje.
            ano = f"20{ano}" if int(ano) <= 69 else f"19{ano}"
    try:
        return dt.date(int(ano), int(mes), int(dia)).isoformat()
    except ValueError:
        return None


def _para_percentual(texto: str) -> float | None:
    """"46,94", "46.94" e "0" viram número. Ponto é separador de milhar quando
    vem seguido de três dígitos e não há vírgula — "1.000" é mil, "46.94" é
    quarenta e seis e noventa e quatro."""
    limpo = texto.strip()
    if "," in limpo:
        limpo = limpo.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", limpo):
        limpo = limpo.replace(".", "")
    try:
        return float(limpo)
    except ValueError:
        return None


def _limpar_nome(nome: str) -> str:
    """Padroniza igual à importação por planilha e troca a aspa tipográfica
    que o PDF usa (SANT’ANA) pela reta, pra o nome não ficar diferente do
    que alguém digitaria na mão."""
    return normalizar_nome(nome.replace("’", "'").replace("‘", "'"))


# ------------------------------------------------------------------ leitura
def ler_relatorio_socios(texto: str) -> LeituraDoRelatorio:
    """Empresas e seus sócios, na ordem em que aparecem no relatório.

    Aceita relatório com várias empresas: cada cabeçalho "Empresa: N - NOME"
    abre uma seção, e os sócios seguintes pertencem a ela até o próximo
    cabeçalho.

    Quando o arquivo inteiro não tem nenhum cabeçalho numerado, há uma segunda
    passada que aceita "Empresa: NOME" sem número. Ela não é a primeira opção
    porque essa é exatamente a forma do cabeçalho do escritório que emite o
    relatório — o que salva a segunda passada é descartar a seção que não
    recebeu nenhum sócio: o topo do relatório é seguido de mais cabeçalho, não
    de gente."""
    leitura = _varrer(texto, aceitar_sem_numero=False)
    if leitura.empresas:
        return leitura

    tentativa = _varrer(texto, aceitar_sem_numero=True)
    tentativa.empresas = [e for e in tentativa.empresas if e.socios]
    if tentativa.empresas:
        return tentativa
    raise RelatorioInvalido(
        "Não encontrei nenhuma empresa neste arquivo. Confira se é o relatório "
        '"Cadastro de Sócios" — ele precisa ter uma linha no formato '
        '"Empresa: 91 - NOME DA EMPRESA" antes dos sócios.'
    )


def _varrer(texto: str, aceitar_sem_numero: bool) -> LeituraDoRelatorio:
    leitura = LeituraDoRelatorio()
    atual: EmpresaDoRelatorio | None = None

    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha:
            continue

        cabecalho = _cabecalho_de(linha, aceitar_sem_numero)
        if cabecalho is not None:
            # Relatório de várias páginas repete o cabeçalho da empresa em
            # cada uma. Sem juntar, a mesma empresa apareceria duas vezes no
            # resumo ("2 empresas") e o quadro societário sairia partido ao
            # meio — o cadastro até casaria pelo número, mas quem confere
            # antes de importar veria uma contagem que não existe.
            ja_vista = next(
                (e for e in leitura.empresas
                 if (e.numero and e.numero == cabecalho.numero) or e.nome == cabecalho.nome),
                None,
            )
            if ja_vista is not None:
                atual = ja_vista
                if atual.data_quadro is None:
                    atual.data_quadro = cabecalho.data_quadro
            else:
                atual = cabecalho
                leitura.empresas.append(atual)
            continue

        # A data do quadro pode vir na linha do nome ou sozinha logo abaixo,
        # dependendo da largura do papel na hora da impressão.
        if atual is not None and atual.data_quadro is None:
            achada = _DATA_DO_QUADRO.search(linha)
            if achada is not None:
                atual.data_quadro = _para_iso(achada.group("data"))
                continue

        if _CABECALHO_DE_COLUNA.search(linha):
            continue

        socio = _socio_de(linha)
        if socio is not None:
            if atual is None:
                # Sócio antes de qualquer empresa: sem a quem vincular, entra
                # no relato de ignoradas em vez de sumir.
                leitura.ignoradas.append(linha)
            else:
                atual.socios.append(socio)
        elif _parece_socio_perdido(linha):
            leitura.ignoradas.append(linha)

    return leitura


def ler_relatorio_de_planilha(linhas: list[list]) -> LeituraDoRelatorio:
    """O mesmo relatório, quando vem em planilha em vez de PDF.

    Cada linha da planilha vira uma linha de texto e segue pelo leitor de
    sempre. É de propósito: as duas origens trazem o mesmo relatório, e manter
    duas listas de regras de layout garantiria que uma ficasse para trás. Como
    a leitura se ancora no CPF/CNPJ e não em posição de coluna, a planilha
    ainda pode ter as colunas em outra ordem — e tem: no arquivo que motivou
    isto, a participação vem antes das datas, ao contrário do PDF."""
    return ler_relatorio_socios("\n".join(_linha_em_texto(linha) for linha in linhas))


def _linha_em_texto(celulas: list) -> str:
    return " ".join(filter(None, (_celula_em_texto(celula) for celula in celulas)))


def _celula_em_texto(celula) -> str:
    """Uma célula como ela apareceria impressa.

    Três detalhes decidem se a linha vai ser entendida depois: data vira ISO
    (que o leitor aceita), número inteiro perde o ".0" que o Excel carrega
    (senão "75.0 FULANO" não teria código reconhecível), e número que é um CPF
    ao qual o Excel comeu o zero à esquerda é devolvido com ele."""
    import datetime as dt

    if celula is None:
        return ""
    if isinstance(celula, (dt.datetime, dt.date)):
        return (celula.date() if isinstance(celula, dt.datetime) else celula).isoformat()
    if isinstance(celula, float) and celula.is_integer():
        celula = int(celula)
    if isinstance(celula, int):
        return _talvez_cpf(celula)
    return str(celula).strip()


def _talvez_cpf(numero: int) -> str:
    """Planilha que guarda o CPF como número perde o zero da frente: 076.925...
    vira 76925727-55. Só é reposto quando o resultado tem dígito verificador
    válido — sem isso, qualquer código de dez dígitos viraria um CPF."""
    texto = str(numero)
    if 9 <= len(texto) <= 10:
        candidato = texto.zfill(11)
        if cpf_valido(candidato):
            return candidato
    return texto


def _cabecalho_de(linha: str, aceitar_sem_numero: bool = False) -> EmpresaDoRelatorio | None:
    # A data do quadro costuma vir na mesma linha do nome; recortar antes
    # evita que ela seja engolida como parte da razão social.
    data_quadro = None
    encontrada = _DATA_DO_QUADRO.search(linha)
    if encontrada is not None:
        data_quadro = _para_iso(encontrada.group("data"))
        linha = linha[: encontrada.start()].rstrip()

    por_cnpj = _CABECALHO_POR_CNPJ.search(linha)
    if por_cnpj is not None and _nome_de_empresa(por_cnpj.group("nome")):
        return EmpresaDoRelatorio(
            numero="",
            nome=normalizar_nome(por_cnpj.group("nome")),
            data_quadro=data_quadro,
            cnpj=formatar_cnpj(por_cnpj.group("cnpj")),
        )

    achado = _CABECALHO_EMPRESA.search(linha)
    if achado is None or not _nome_de_empresa(achado.group("nome")):
        if aceitar_sem_numero:
            sem_numero = _CABECALHO_SEM_NUMERO.match(linha)
            if sem_numero is not None and _nome_de_empresa(sem_numero.group("nome")):
                return EmpresaDoRelatorio(
                    numero="",
                    nome=normalizar_nome(sem_numero.group("nome")),
                    data_quadro=data_quadro,
                )
        return None
    return EmpresaDoRelatorio(
        numero=achado.group("numero"),
        nome=normalizar_nome(achado.group("nome")),
        data_quadro=data_quadro,
    )


def _nome_de_empresa(texto: str) -> bool:
    """Sem o hífen separando, o que vem depois do número precisa provar que é
    razão social: "Empresa: 3 de 5" não é empresa nenhuma."""
    nome = normalizar_nome(texto)
    if len(re.sub(r"[^A-ZÀ-Ü]", "", nome)) < 3:
        return False
    palavras = [p for p in re.split(r"[\s\-.]+", _sem_acento(nome)) if p]
    return bool(palavras) and not all(p in _PALAVRAS_QUE_NAO_SAO_NOME for p in palavras)


def _parece_socio_perdido(linha: str) -> bool:
    """Linha que tinha tudo para ser um sócio e mesmo assim não foi lida.

    Exige documento válido e mais algum sinal de registro — uma data, um
    percentual ou o código na frente. A data sozinha não serve de critério:
    linha de sócio sem data de ingresso existe, e é justamente a que seria
    descartada sem ninguém ficar sabendo.

    Por outro lado, avisar demais é tão ruim quanto não avisar: um aviso que
    aparece em toda importação por causa do cabeçalho do escritório ensina a
    pessoa a ignorar o aviso. Por isso rótulo solto ("C.N.P.J.:") e linha de
    rodapé, que trazem documento e nada mais, ficam de fora."""
    achado = _inscricao_em(linha)
    if achado is None:
        return False
    _inscricao, inicio, fim = achado
    antes, depois = linha[:inicio], linha[fim:]
    if _SO_ROTULO.fullmatch(antes):
        return False
    tem_sinal = bool(
        _DATA.search(depois)
        or _percentual_em(depois) is not None
        or re.match(r"^\s*\d{1,8}\s+\D", antes)
    )
    return tem_sinal


def _socio_de(linha: str) -> SocioDoRelatorio | None:
    """Lê uma linha de sócio ancorando na inscrição.

    Exige nome, documento e pelo menos uma data. A data é o que separa um
    sócio do cabeçalho do escritório, que também traz nome e CNPJ — sem essa
    exigência, o emissor do relatório entraria no cadastro como sócio."""
    achado = _inscricao_em(linha)
    if achado is None:
        return None
    inscricao, inicio, fim = achado

    codigo, nome = _codigo_e_nome(linha[:inicio])
    if not nome:
        return None

    depois = linha[fim:]
    datas = [_para_iso(d) for d in _DATA.findall(depois)]
    datas = [d for d in datas if d]
    if not datas:
        return None

    juridica = _e_juridica(inscricao)
    return SocioDoRelatorio(
        codigo=codigo,
        nome=nome,
        # Pontuação padronizada na leitura: o PDF traz o CPF com pontos e a
        # planilha sem, e o cadastro não pode ficar com os dois jeitos
        # dependendo de por onde a pessoa entrou. (O casamento já ignorava a
        # pontuação; isto é sobre o que fica gravado.)
        inscricao=formatar_cnpj(inscricao) if juridica else formatar_cpf(inscricao),
        tipo_pessoa="juridica" if juridica else "fisica",
        percentual=_percentual_em(depois) or 0.0,
        data_entrada=datas[0],
        data_saida=datas[1] if len(datas) > 1 else None,
    )


def _inscricao_em(linha: str) -> tuple[str, int, int] | None:
    """O primeiro CPF/CNPJ da linha, formatado ou não.

    Documento sem pontuação só é aceito se for um CNPJ (14 dígitos) ou um CPF
    com dígitos verificadores válidos: uma sequência de onze dígitos também
    poderia ser um número de contrato ou um código interno, e o dígito
    verificador é o que separa um do outro."""
    for achado in _INSCRICAO.finditer(linha):
        bruto = achado.group(0)
        if any(c in bruto for c in ".-/"):
            return bruto, achado.start(), achado.end()
        if len(bruto) == 14:
            return bruto, achado.start(), achado.end()
        if len(bruto) == 11 and cpf_valido(bruto):
            return bruto, achado.start(), achado.end()
    return None


def _e_juridica(inscricao: str) -> bool:
    if "/" in inscricao:
        return True
    return len(re.sub(r"\D", "", inscricao)) == 14


def _codigo_e_nome(antes: str) -> tuple[str, str]:
    """Separa o código do nome no trecho anterior ao documento.

    A coluna de código é opcional: há relatório que não a imprime, e aí a
    linha começa direto no nome. Número solto no começo é código; o resto é
    nome, desde que sobre alguma letra — "1041 " sem nome nenhum não é sócio."""
    texto = antes.strip()
    codigo = ""
    achado = re.match(r"^(\d{1,8})\b\s+(?=\D)", texto)
    if achado is not None:
        codigo = achado.group(1)
        texto = texto[achado.end():]

    texto = _ROTULO_DOCUMENTO.sub("", texto)
    nome = _limpar_nome(texto)
    if len(re.sub(r"[^A-ZÀ-Ü]", "", nome)) < 3:
        return codigo, ""

    palavras = [p for p in re.split(r"[\s\-.]+", _sem_acento(nome)) if p]
    if not palavras or all(p in _PALAVRAS_QUE_NAO_SAO_NOME for p in palavras):
        return codigo, ""
    return codigo, nome


def _sem_acento(texto: str) -> str:
    import unicodedata

    return "".join(
        c for c in unicodedata.normalize("NFKD", texto) if not unicodedata.combining(c)
    ).upper()


def _percentual_em(depois: str) -> float | None:
    """O percentual entre o que sobra depois do documento.

    Vale mais o número marcado com "%"; sem marca, o primeiro número que caiba
    num percentual. Valor precedido de "R$" é descartado — relatório que traz
    o valor da participação em dinheiro na mesma linha não pode fazer o capital
    virar percentual."""
    sem_datas = _DATA.sub(" ", depois)
    candidatos = []
    for achado in _NUMERO.finditer(sem_datas):
        if _MOEDA_ANTES.search(sem_datas[: achado.start()]):
            continue
        valor = _para_percentual(achado.group("valor"))
        if valor is None:
            continue
        candidatos.append((bool(achado.group("pct")), valor))

    for marcado, valor in candidatos:
        if marcado:
            return valor
    for _marcado, valor in candidatos:
        if 0 <= valor <= 100:
            return valor
    return None


# ---------------------------------------------------------------- saída
def linhas_para_importacao(empresas: list[EmpresaDoRelatorio]) -> list[dict]:
    """Converte para o mesmo formato de linha que planilha.importar_cadastro()
    devolve, pra reaproveitar todo o caminho de importação já existente.

    Os campos que o relatório não traz ficam vazios: ele não informa CNPJ da
    empresa, capital social, quantidade de cotas nem distribuição. Empresa
    criada a partir daqui nasce com capital e cotas zerados, pra completar
    depois no cadastro.

    Os sócios saem ordenados por data de entrada, não pelo código do outro
    sistema: quem saiu e voltou aparece em duas linhas, e o vínculo antigo
    precisa ser encerrado antes de o novo ser aberto."""
    linhas = []
    for empresa in empresas:
        for socio in sorted(empresa.socios, key=lambda s: (s.data_entrada, s.codigo)):
            linhas.append(
                {
                    "numero_chamada": empresa.numero,
                    "empresa_nome": empresa.nome,
                    "cnpj": empresa.cnpj,
                    "capital_social": 0.0,
                    "quantidade_cotas": 0.0,
                    "socio_nome": socio.nome,
                    "socio_cpf": socio.inscricao,
                    "tipo_pessoa": socio.tipo_pessoa,
                    "percentual_capital": socio.percentual,
                    "cotas_socio": 0.0,
                    "data_entrada": socio.data_entrada,
                    "data_saida": socio.data_saida,
                    "ano_base": None,
                    "valor_distribuido": 0.0,
                    "pro_labore": 0.0,
                    "irrf": 0.0,
                }
            )
    return linhas


def resumo(empresas: list[EmpresaDoRelatorio]) -> str:
    """Uma frase com o que o relatório trouxe, pra tela confirmar antes de
    aplicar — quem importa precisa ver que o arquivo foi lido direito."""
    total_socios = sum(len(e.socios) for e in empresas)
    sairam = sum(1 for e in empresas for s in e.socios if s.data_saida)
    partes = [
        f"{len(empresas)} empresa(s)",
        f"{total_socios} sócio(s)",
    ]
    if sairam:
        partes.append(f"{sairam} com saída registrada")
    return " · ".join(partes)
