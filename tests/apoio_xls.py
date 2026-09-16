"""Escreve um .xls mínimo (OLE + BIFF8) para os testes do leitor.

Existe porque nenhuma biblioteca instalada escreve .xls, e testar o leitor
contra um arquivo de verdade — com container OLE, tabela de textos
compartilhados e data como número formatado — é a única forma de garantir que
ele funciona. É o menor arquivo que ainda exercita o formato: só o que o
leitor precisa entender, nada de estilos ou fórmulas.

Não faz parte do programa: nada aqui escreve .xls em produção.
"""
from __future__ import annotations

import struct

_LIVRE = 0xFFFFFFFF
_FIM = 0xFFFFFFFE
_FAT = 0xFFFFFFFD
_TAMANHO_SETOR = 512
_TAMANHO_MINI = 64


def _registro(tipo: int, corpo: bytes) -> bytes:
    return struct.pack("<HH", tipo, len(corpo)) + corpo


def _texto_biff(texto: str) -> bytes:
    """String do BIFF8 no jeito largo (UTF-16), que é o caso que precisa
    funcionar com nome acentuado."""
    bruto = texto.encode("utf-16-le")
    return struct.pack("<HB", len(texto), 0x01) + bruto


def fluxo_biff(linhas: list[list], formato_data: str = "DD/MM/YYYY") -> bytes:
    """Monta o fluxo Workbook: bloco global (com SST, FORMAT, XF e BOUNDSHEET)
    e a planilha. Texto vira LABELSST, número vira NUMBER, e data vira NUMBER
    com o XF de data — que é como o Excel guarda data de verdade."""
    import datetime as dt

    textos: list[str] = []
    indice_do_texto: dict[str, int] = {}
    celulas: list[bytes] = []
    for numero_linha, linha in enumerate(linhas):
        for numero_coluna, valor in enumerate(linha):
            if valor is None or valor == "":
                continue
            if isinstance(valor, (dt.date, dt.datetime)):
                data = valor.date() if isinstance(valor, dt.datetime) else valor
                serie = (data - dt.date(1899, 12, 30)).days
                celulas.append(_registro(0x0203, struct.pack(
                    "<HHHd", numero_linha, numero_coluna, 1, float(serie))))
            elif isinstance(valor, (int, float)):
                celulas.append(_registro(0x0203, struct.pack(
                    "<HHHd", numero_linha, numero_coluna, 0, float(valor))))
            else:
                if valor not in indice_do_texto:
                    indice_do_texto[valor] = len(textos)
                    textos.append(valor)
                celulas.append(_registro(0x00FD, struct.pack(
                    "<HHHi", numero_linha, numero_coluna, 0, indice_do_texto[valor])))

    corpo_sst = struct.pack("<ii", len(textos), len(textos))
    corpo_sst += b"".join(_texto_biff(t) for t in textos)

    global_ = b"".join([
        _registro(0x0809, struct.pack("<HHHHHI", 0x0600, 0x0005, 0, 0, 0, 0)),
        _registro(0x0022, struct.pack("<H", 0)),          # datas a partir de 1900
        _registro(0x041E, struct.pack("<H", 164) + _texto_biff(formato_data)),
        _registro(0x00E0, struct.pack("<HHH", 0, 0, 0) + b"\x00" * 14),    # XF 0: geral
        _registro(0x00E0, struct.pack("<HHH", 0, 164, 0) + b"\x00" * 14),  # XF 1: data
        _registro(0x00FC, corpo_sst),
    ])
    inicio_da_planilha = len(global_) + 4 + 8 + 4  # BOUNDSHEET + EOF
    global_ += _registro(0x0085, struct.pack("<IBB", inicio_da_planilha, 0, 0) + b"\x05Plan1")
    global_ += _registro(0x000A, b"")

    planilha = _registro(0x0809, struct.pack("<HHHHHI", 0x0600, 0x0010, 0, 0, 0, 0))
    planilha += b"".join(celulas)
    planilha += _registro(0x000A, b"")
    return global_ + planilha


def _entrada_diretorio(nome: str, tipo: int, setor: int, tamanho: int) -> bytes:
    """Uma entrada do diretório do container: exatamente 128 bytes.

    O tamanho é conferido no fim porque errar por quatro bytes desalinha todas
    as entradas seguintes, e o arquivo resultante parece não ter planilha
    nenhuma — que foi exatamente o que aconteceu ao escrever isto."""
    bruto = nome.encode("utf-16-le") + b"\x00\x00"
    entrada = bruto.ljust(64, b"\x00")                      # 0x00 nome
    entrada += struct.pack("<HBB", len(bruto), tipo, 1)      # 0x40 tamanho, tipo, cor
    entrada += struct.pack("<III", _LIVRE, _LIVRE, _LIVRE)   # 0x44 irmãos e filho
    entrada += b"\x00" * 16                                  # 0x50 CLSID
    entrada += b"\x00" * 4                                   # 0x60 bits de estado
    entrada += b"\x00" * 16                                  # 0x64 datas
    entrada += struct.pack("<IQ", setor, tamanho)            # 0x74 setor e tamanho
    assert len(entrada) == 128, len(entrada)
    return entrada


def escrever_xls(caminho, linhas: list[list], formato_data: str = "DD/MM/YYYY",
                 no_mini_fluxo: bool = False):
    """Grava um .xls de verdade com o conteúdo dado.

    `no_mini_fluxo` escolhe onde o fluxo mora: dentro do mini fluxo, como o
    formato manda para fluxo pequeno, ou nos setores normais, como fazem os
    exportadores desleixados. Os dois casos existem em arquivo de verdade, e o
    leitor precisa dar conta dos dois."""
    fluxo = fluxo_biff(linhas, formato_data)

    if no_mini_fluxo:
        return _escrever_no_mini_fluxo(caminho, fluxo)

    setores_do_fluxo = max(1, -(-len(fluxo) // _TAMANHO_SETOR))

    # setor 0 = FAT, setor 1 = diretório, setores 2.. = fluxo
    fat = [_FAT, _FIM] + [i + 3 for i in range(setores_do_fluxo - 1)] + [_FIM]
    fat += [_LIVRE] * (_TAMANHO_SETOR // 4 - len(fat))

    diretorio = _entrada_diretorio("Root Entry", 5, _FIM, 0)
    diretorio += _entrada_diretorio("Workbook", 2, 2, len(fluxo))
    diretorio = diretorio.ljust(_TAMANHO_SETOR, b"\x00")

    cabecalho = bytearray(b"\x00" * _TAMANHO_SETOR)
    cabecalho[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HH", cabecalho, 0x18, 0x003E, 0x0003)
    struct.pack_into("<H", cabecalho, 0x1C, 0xFFFE)
    struct.pack_into("<HH", cabecalho, 0x1E, 9, 6)          # 512 e 64 bytes
    struct.pack_into("<I", cabecalho, 0x2C, 1)              # um setor de FAT
    struct.pack_into("<I", cabecalho, 0x30, 1)              # diretório no setor 1
    struct.pack_into("<I", cabecalho, 0x38, 4096)           # corte do mini fluxo
    struct.pack_into("<I", cabecalho, 0x3C, _FIM)
    struct.pack_into("<I", cabecalho, 0x44, _FIM)
    for i in range(109):
        struct.pack_into("<I", cabecalho, 0x4C + 4 * i, 0 if i == 0 else _LIVRE)

    corpo = fluxo.ljust(setores_do_fluxo * _TAMANHO_SETOR, b"\x00")
    dados = bytes(cabecalho) + struct.pack(f"<{len(fat)}I", *fat) + diretorio + corpo
    caminho = str(caminho)
    with open(caminho, "wb") as arquivo:
        arquivo.write(dados)
    return caminho


def _escrever_no_mini_fluxo(caminho, fluxo: bytes):
    """O mesmo arquivo, com o fluxo guardado no mini fluxo — que é onde o
    formato manda pôr fluxo menor que o corte de 4 KB."""
    mini_setores = max(1, -(-len(fluxo) // _TAMANHO_MINI))
    container = fluxo.ljust(mini_setores * _TAMANHO_MINI, b"\x00")
    setores_container = max(1, -(-len(container) // _TAMANHO_SETOR))

    mini_fat = [i + 1 for i in range(mini_setores - 1)] + [_FIM]
    mini_fat += [_LIVRE] * (_TAMANHO_SETOR // 4 - len(mini_fat))

    # setor 0 = FAT, 1 = diretório, 2 = mini FAT, 3.. = container do mini fluxo
    fat = [_FAT, _FIM, _FIM] + [i + 4 for i in range(setores_container - 1)] + [_FIM]
    fat += [_LIVRE] * (_TAMANHO_SETOR // 4 - len(fat))

    diretorio = _entrada_diretorio("Root Entry", 5, 3, len(container))
    diretorio += _entrada_diretorio("Workbook", 2, 0, len(fluxo))
    diretorio = diretorio.ljust(_TAMANHO_SETOR, b"\x00")

    cabecalho = bytearray(b"\x00" * _TAMANHO_SETOR)
    cabecalho[0:8] = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
    struct.pack_into("<HH", cabecalho, 0x18, 0x003E, 0x0003)
    struct.pack_into("<H", cabecalho, 0x1C, 0xFFFE)
    struct.pack_into("<HH", cabecalho, 0x1E, 9, 6)
    struct.pack_into("<I", cabecalho, 0x2C, 1)
    struct.pack_into("<I", cabecalho, 0x30, 1)
    struct.pack_into("<I", cabecalho, 0x38, 4096)
    struct.pack_into("<I", cabecalho, 0x3C, 2)      # mini FAT no setor 2
    struct.pack_into("<I", cabecalho, 0x40, 1)
    struct.pack_into("<I", cabecalho, 0x44, _FIM)
    for i in range(109):
        struct.pack_into("<I", cabecalho, 0x4C + 4 * i, 0 if i == 0 else _LIVRE)

    dados = (bytes(cabecalho) + struct.pack(f"<{len(fat)}I", *fat) + diretorio
             + struct.pack(f"<{len(mini_fat)}I", *mini_fat)
             + container.ljust(setores_container * _TAMANHO_SETOR, b"\x00"))
    caminho = str(caminho)
    with open(caminho, "wb") as arquivo:
        arquivo.write(dados)
    return caminho
