"""Leitura de planilha .xls antiga (formato BIFF8, o do Excel 97-2003).

O openpyxl só lê .xlsx. E o .xls é justamente o que os sistemas contábeis
antigos exportam — inclusive o relatório de sócios que este programa importa.

A alternativa seria a biblioteca xlrd, mas ela recusa o arquivo real que
motivou este módulo: aquele exportador grava 433 registros BLANK soltos entre
o fim do bloco global e o início da planilha, e o xlrd, que confia na estrutura
declarada, para na primeira coisa fora do lugar. O leitor daqui não confia:
percorre os registros de ponta a ponta e recolhe as células onde elas
estiverem. Planilha mal formada é a regra nessa origem, não a exceção.

Só leitura, e só o necessário: texto, número, data e célula vazia. Fórmula é
lida pelo último valor calculado quando o arquivo o traz. Nada aqui escreve
.xls — para exportar, o sistema usa .xlsx pelo openpyxl.
"""
from __future__ import annotations

import datetime as dt
import re
import struct
from pathlib import Path

# --------------------------------------------------------------- OLE (CFB)
_ASSINATURA_OLE = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_FIM_DE_CADEIA = 0xFFFFFFFE

# ------------------------------------------------------------ registros BIFF
_BOF = 0x0809
_SST = 0x00FC
_CONTINUE = 0x003C
_LABELSST = 0x00FD
_LABEL = 0x0204
_NUMBER = 0x0203
_RK = 0x027E
_MULRK = 0x00BD
_BLANK = 0x0201
_MULBLANK = 0x00BE
_BOOLERR = 0x0205
_FORMULA = 0x0006
_STRING = 0x0207
_FORMAT = 0x041E
_XF = 0x00E0
_DATEMODE = 0x0022

# Formatos de data embutidos no Excel, que não vêm num registro FORMAT: sem
# esta lista, planilha que usa o formato padrão de data traria o número de
# série cru (45000 em vez de 2023-03-02).
_FORMATOS_DE_DATA_EMBUTIDOS = frozenset(
    {14, 15, 16, 17, 18, 19, 20, 21, 22, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36,
     45, 46, 47, 50, 51, 52, 53, 54, 55, 56, 57, 58}
)


class XlsIlegivel(ValueError):
    """O arquivo não é um .xls que a gente consiga ler."""


def e_xls_antigo(caminho: Path) -> bool:
    """Diz se o arquivo é mesmo um .xls binário, sem confiar na extensão —
    metade dos "xls" que circulam por aí são HTML ou CSV renomeados."""
    try:
        with open(caminho, "rb") as arquivo:
            return arquivo.read(8) == _ASSINATURA_OLE
    except OSError:
        return False


def ler_xls(caminho: Path) -> list[list]:
    """A primeira planilha do arquivo como uma matriz de linhas.

    Cada célula vem como texto, número (float), data (datetime.date) ou ""
    para vazia — o mesmo formato que planilha.ler_linhas_brutas() devolve para
    .xlsx, pra quem chama não precisar saber de qual dos dois veio."""
    caminho = Path(caminho)
    try:
        bruto = caminho.read_bytes()
    except OSError as exc:
        raise XlsIlegivel(f'Não consegui abrir "{caminho.name}": {exc}') from None

    if not bruto.startswith(_ASSINATURA_OLE):
        raise XlsIlegivel(
            f'"{caminho.name}" não é uma planilha .xls de verdade. Se o arquivo foi '
            "renomeado, abra-o no Excel e salve como .xlsx ou .csv."
        )

    fluxo = _fluxo_do_workbook(bruto)
    if fluxo is None:
        raise XlsIlegivel(
            f'"{caminho.name}" não tem a planilha dentro (falta o fluxo "Workbook"). '
            "Abra no Excel e salve de novo."
        )
    return _celulas_do_fluxo(fluxo)


# ------------------------------------------------------- container OLE/CFB --
def _fluxo_do_workbook(bruto: bytes) -> bytes | None:
    """Extrai o fluxo "Workbook" do arquivo composto.

    Fluxo pequeno (abaixo do corte declarado no cabeçalho, em geral 4 KB) não
    mora nos setores normais: mora dentro do "mini fluxo", que é ele próprio
    um fluxo guardado na entrada raiz. Relatório de uma empresa com dois
    sócios cai justamente nesse caso, então os dois caminhos são tratados."""
    tamanho_setor = 1 << struct.unpack_from("<H", bruto, 0x1E)[0]
    tamanho_mini = 1 << struct.unpack_from("<H", bruto, 0x20)[0]
    setor_do_diretorio = struct.unpack_from("<I", bruto, 0x30)[0]
    quantidade_fat = struct.unpack_from("<I", bruto, 0x2C)[0]
    corte_mini = struct.unpack_from("<I", bruto, 0x38)[0] or 4096
    primeiro_mini_fat = struct.unpack_from("<I", bruto, 0x3C)[0]

    difat = [struct.unpack_from("<I", bruto, 0x4C + 4 * i)[0] for i in range(109)]
    fat: list[int] = []
    for setor in difat[:quantidade_fat]:
        bloco = _setor(bruto, setor, tamanho_setor)
        fat += list(struct.unpack(f"<{len(bloco) // 4}I", bloco))

    diretorio = _ler_cadeia(bruto, fat, setor_do_diretorio, tamanho_setor)
    entradas = _entradas_do_diretorio(diretorio)

    alvo = next((e for e in entradas if e[0].lower() in ("workbook", "book")), None)
    if alvo is None:
        return None
    _nome, inicio, tamanho = alvo

    def pelos_setores() -> bytes:
        return _ler_cadeia(bruto, fat, inicio, tamanho_setor)[:tamanho]

    def pelo_mini_fluxo() -> bytes:
        raiz = next((e for e in entradas if e[0].lower() == "root entry"), None)
        if raiz is None or primeiro_mini_fat >= _FIM_DE_CADEIA:
            return b""
        mini_fluxo = _ler_cadeia(bruto, fat, raiz[1], tamanho_setor)
        bytes_mini_fat = _ler_cadeia(bruto, fat, primeiro_mini_fat, tamanho_setor)
        mini_fat = list(struct.unpack(f"<{len(bytes_mini_fat) // 4}I", bytes_mini_fat))
        return _ler_cadeia_mini(mini_fluxo, mini_fat, inicio, tamanho_mini)[:tamanho]

    # O tamanho diz onde o fluxo deveria estar, e é por aí que se começa. Mas
    # há exportador que grava um fluxo pequeno nos setores normais mesmo assim
    # — tentar o outro caminho custa nada e é a diferença entre ler o arquivo
    # e mandar a pessoa "salvar de novo no Excel".
    caminhos = [pelo_mini_fluxo, pelos_setores] if tamanho < corte_mini else [pelos_setores, pelo_mini_fluxo]
    for tentar in caminhos:
        fluxo = tentar()
        if fluxo[:2] == b"\x09\x08":  # começa com um BOF: é o Workbook mesmo
            return fluxo
    return None


def _entradas_do_diretorio(diretorio: bytes) -> list[tuple[str, int, int]]:
    entradas = []
    for i in range(0, len(diretorio), 128):
        entrada = diretorio[i:i + 128]
        if len(entrada) < 128:
            break
        tamanho_nome = struct.unpack_from("<H", entrada, 0x40)[0]
        nome = entrada[: max(0, tamanho_nome - 2)].decode("utf-16-le", "replace")
        if nome:
            entradas.append((
                nome,
                struct.unpack_from("<I", entrada, 0x74)[0],
                struct.unpack_from("<I", entrada, 0x78)[0],
            ))
    return entradas


def _ler_cadeia_mini(mini_fluxo: bytes, mini_fat: list[int], inicio: int, tamanho_mini: int) -> bytes:
    partes, atual, vistos = [], inicio, set()
    while atual < _FIM_DE_CADEIA and atual < len(mini_fat) and atual not in vistos:
        vistos.add(atual)
        comeco = atual * tamanho_mini
        partes.append(mini_fluxo[comeco:comeco + tamanho_mini])
        atual = mini_fat[atual]
    return b"".join(partes)


def _setor(bruto: bytes, numero: int, tamanho_setor: int) -> bytes:
    inicio = (numero + 1) * tamanho_setor
    return bruto[inicio:inicio + tamanho_setor]


def _ler_cadeia(bruto: bytes, fat: list[int], inicio: int, tamanho_setor: int) -> bytes:
    partes, atual, vistos = [], inicio, set()
    while atual < _FIM_DE_CADEIA and atual < len(fat) and atual not in vistos:
        vistos.add(atual)  # cadeia circular em arquivo corrompido não pode travar o programa
        partes.append(_setor(bruto, atual, tamanho_setor))
        atual = fat[atual]
    return b"".join(partes)


# ----------------------------------------------------------- registros BIFF --
def _registros(fluxo: bytes):
    posicao = 0
    while posicao + 4 <= len(fluxo):
        tipo, tamanho = struct.unpack_from("<HH", fluxo, posicao)
        corpo = fluxo[posicao + 4: posicao + 4 + tamanho]
        if len(corpo) < tamanho:
            return  # arquivo truncado: o que veio até aqui vale, o resto não existe
        yield tipo, corpo
        posicao += 4 + tamanho


def _celulas_do_fluxo(fluxo: bytes) -> list[list]:
    registros = list(_registros(fluxo))
    if not any(tipo == _BOF for tipo, _corpo in registros):
        raise XlsIlegivel(
            "Não reconheci o conteúdo como planilha do Excel. Abra o arquivo e "
            "salve como .xlsx ou .csv."
        )

    textos: list[str] = []
    formatos: dict[int, str] = {}
    formato_do_xf: list[int] = []
    data_base = dt.date(1899, 12, 30)
    celulas: dict[tuple[int, int], object] = {}
    string_pendente: tuple[int, int] | None = None

    for indice, (tipo, corpo) in enumerate(registros):
        if tipo == _SST:
            textos = _ler_sst(corpo, _continuacoes(registros, indice))
        elif tipo == _DATEMODE:
            if struct.unpack_from("<H", corpo, 0)[0]:
                data_base = dt.date(1904, 1, 1)
        elif tipo == _FORMAT:
            indice_formato = struct.unpack_from("<H", corpo, 0)[0]
            formatos[indice_formato] = _texto_unicode(corpo, 2)
        elif tipo == _XF:
            formato_do_xf.append(struct.unpack_from("<H", corpo, 2)[0])
        elif tipo == _STRING and string_pendente is not None:
            # Valor de uma fórmula que resulta em texto: vem no registro
            # seguinte, e sem ele a célula ficaria vazia.
            celulas[string_pendente] = _texto_unicode(corpo, 0)
            string_pendente = None
        elif tipo in (_LABELSST, _LABEL, _NUMBER, _RK, _BLANK, _BOOLERR, _FORMULA):
            posicao, valor = _celula(tipo, corpo, textos)
            if tipo == _FORMULA and valor is None:
                string_pendente = posicao
                continue
            if valor is not None:
                celulas[posicao] = _converter(valor, corpo, formato_do_xf, formatos, data_base)
        elif tipo == _MULRK:
            linha, primeira = struct.unpack_from("<HH", corpo, 0)
            for k in range((len(corpo) - 6) // 6):
                xf, bits = struct.unpack_from("<HI", corpo, 4 + k * 6)
                valor = _de_rk(bits)
                celulas[(linha, primeira + k)] = _converter_numero(
                    valor, xf, formato_do_xf, formatos, data_base
                )
        elif tipo == _MULBLANK:
            linha, primeira = struct.unpack_from("<HH", corpo, 0)
            for k in range((len(corpo) - 6) // 2):
                celulas[(linha, primeira + k)] = ""

    if not celulas:
        return []
    ultima_linha = max(linha for linha, _coluna in celulas)
    ultima_coluna = max(coluna for _linha, coluna in celulas)
    return [
        [celulas.get((linha, coluna), "") for coluna in range(ultima_coluna + 1)]
        for linha in range(ultima_linha + 1)
    ]


def _continuacoes(registros: list, indice: int) -> list[bytes]:
    """Os CONTINUE que vêm logo depois de um registro. A tabela de textos de
    uma planilha grande não cabe num registro só e é partida assim."""
    seguintes = []
    for tipo, corpo in registros[indice + 1:]:
        if tipo != _CONTINUE:
            break
        seguintes.append(corpo)
    return seguintes


def _celula(tipo: int, corpo: bytes, textos: list[str]):
    linha, coluna, _xf = struct.unpack_from("<HHH", corpo, 0)
    posicao = (linha, coluna)
    if tipo == _LABELSST:
        indice = struct.unpack_from("<i", corpo, 6)[0]
        return posicao, textos[indice] if 0 <= indice < len(textos) else ""
    if tipo == _LABEL:
        return posicao, _texto_unicode(corpo, 6)
    if tipo == _NUMBER:
        return posicao, struct.unpack_from("<d", corpo, 6)[0]
    if tipo == _RK:
        return posicao, _de_rk(struct.unpack_from("<I", corpo, 6)[0])
    if tipo == _BLANK:
        return posicao, ""
    if tipo == _BOOLERR:
        return posicao, "" if corpo[7] else ("VERDADEIRO" if corpo[6] else "FALSO")
    if tipo == _FORMULA:
        # Fórmula com resultado numérico traz o número aqui; com resultado de
        # texto, os primeiros bytes são um marcador e o texto vem no STRING
        # seguinte.
        if struct.unpack_from("<H", corpo, 12)[0] == 0xFFFF:
            return posicao, None
        return posicao, struct.unpack_from("<d", corpo, 6)[0]
    return posicao, ""


def _converter(valor, corpo: bytes, formato_do_xf: list[int], formatos: dict[int, str],
               data_base: dt.date):
    if not isinstance(valor, float):
        return valor
    xf = struct.unpack_from("<H", corpo, 4)[0]
    return _converter_numero(valor, xf, formato_do_xf, formatos, data_base)


def _converter_numero(valor: float, xf: int, formato_do_xf: list[int],
                      formatos: dict[int, str], data_base: dt.date):
    """Número que está formatado como data vira data de verdade.

    No Excel, data é um número com uma roupa: 45000 é 2023-03-02 se a célula
    estiver formatada como data, e quarenta e cinco mil se não estiver. Sem
    olhar o formato, toda data importada viraria esse número."""
    indice_formato = formato_do_xf[xf] if xf < len(formato_do_xf) else 0
    if not _e_formato_de_data(indice_formato, formatos):
        return valor
    try:
        return data_base + dt.timedelta(days=int(valor))
    except (OverflowError, ValueError):
        return valor


def _e_formato_de_data(indice: int, formatos: dict[int, str]) -> bool:
    if indice in _FORMATOS_DE_DATA_EMBUTIDOS:
        return True
    texto = formatos.get(indice)
    if not texto:
        return False
    # Fora literais entre aspas, cor entre colchetes e escapes, sobra o
    # desenho do número: se houver d/m/a lá, é data.
    limpo = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.|_.', "", texto)
    return bool(re.search(r"[dmyah]", limpo, re.IGNORECASE))


def _de_rk(bits: int) -> float:
    """O RK guarda o número comprimido em 32 bits: inteiro deslocado ou a
    metade alta de um double, opcionalmente dividido por 100."""
    inteiro = bits & 0xFFFFFFFC
    if bits & 0x02:
        valor = float(struct.unpack("<i", struct.pack("<I", inteiro))[0] >> 2)
    else:
        valor = struct.unpack("<d", struct.pack("<q", inteiro << 32))[0]
    return valor / 100 if bits & 0x01 else valor


def _texto_unicode(corpo: bytes, deslocamento: int) -> str:
    """String do BIFF8: tamanho em caracteres, um byte de bandeiras e então o
    texto — em latin-1 quando cabe, em UTF-16 quando não cabe."""
    if len(corpo) < deslocamento + 3:
        return ""
    quantidade, bandeiras = struct.unpack_from("<HB", corpo, deslocamento)
    largo = bandeiras & 0x01
    inicio = deslocamento + 3
    bytes_do_texto = corpo[inicio: inicio + quantidade * (2 if largo else 1)]
    return bytes_do_texto.decode("utf-16-le" if largo else "latin-1", "replace")


def _ler_sst(corpo: bytes, continuacoes: list[bytes]) -> list[str]:
    """A tabela de textos compartilhados.

    É o pedaço mais chato do formato: a tabela atravessa vários registros, e a
    quebra pode cair no meio de uma palavra — quando isso acontece, o
    registro seguinte recomeça com um byte dizendo se o resto veio em UTF-16
    ou em latin-1, que pode ser diferente do começo da mesma palavra."""
    if len(corpo) < 8:
        return []
    _total, unicos = struct.unpack_from("<ii", corpo, 0)
    buffer = corpo[8:]
    restantes = list(continuacoes)
    posicao = 0
    textos: list[str] = []

    def repor() -> bool:
        nonlocal buffer, posicao
        if not restantes:
            return False
        buffer = buffer[posicao:] + restantes.pop(0)
        posicao = 0
        return True

    for _ in range(max(0, unicos)):
        while posicao + 3 > len(buffer):
            if not repor():
                return textos
        quantidade, bandeiras = struct.unpack_from("<HB", buffer, posicao)
        posicao += 3
        largo = bandeiras & 0x01
        pedacos_ricos = struct.unpack_from("<H", buffer, posicao)[0] if bandeiras & 0x08 else 0
        if bandeiras & 0x08:
            posicao += 2
        tamanho_extra = struct.unpack_from("<i", buffer, posicao)[0] if bandeiras & 0x04 else 0
        if bandeiras & 0x04:
            posicao += 4

        partes, faltam = [], quantidade
        while faltam > 0:
            largura = 2 if largo else 1
            cabem = (len(buffer) - posicao) // largura
            pegar = min(faltam, max(0, cabem))
            if pegar:
                trecho = buffer[posicao: posicao + pegar * largura]
                partes.append(trecho.decode("utf-16-le" if largo else "latin-1", "replace"))
                posicao += pegar * largura
                faltam -= pegar
            if faltam:
                if not repor():
                    faltam = 0
                    break
                largo = buffer[posicao] & 0x01
                posicao += 1
        textos.append("".join(partes))
        posicao += pedacos_ricos * 4 + tamanho_extra
    return textos
