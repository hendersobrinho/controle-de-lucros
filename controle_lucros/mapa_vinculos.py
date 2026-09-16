"""Mapa de vínculos: o desenho de quais empresas um sócio participa.

A tabela de vínculos responde "quais são", mas não mostra a forma da coisa —
quem tem participação grande em duas e simbólica em seis, quem saiu de metade
das empresas no ano passado. Um desenho responde isso de relance, e é o que se
leva para uma reunião ou se anexa a um processo.

O formato é um <b>hub</b>: o sócio no meio, as empresas em duas colunas ao
redor, ligadas por um traço com o percentual. Duas colunas, e não um círculo,
porque razão social é comprida ("ENDOGASTRO CLINICA MEDICA LTDA") — em volta de
um círculo os nomes se atropelariam já no quinto.

Este módulo não importa Qt: recebe os vínculos já lidos do banco e devolve
onde cada caixa fica, em pixels. Assim a parte que erra feio — caixa por cima
de caixa quando o sócio tem quinze empresas — é testável sem abrir janela, e o
mesmo cálculo serve para a tela, para o PDF e para o SVG.
"""
from __future__ import annotations

import datetime as dt
import unicodedata
from dataclasses import dataclass

# A largura sai de uma conta, não de gosto: duas colunas de caixa, o hub no
# meio e, entre eles, folga para a etiqueta do percentual não encostar em
# nenhum dos dois. Razão social é comprida, então a caixa é larga.
LARGURA_PADRAO = 1180

CAIXA_LARGURA = 290
CAIXA_ALTURA = 58
ESPACO_VERTICAL = 16
MARGEM = 26

HUB_LARGURA = 300
HUB_ALTURA = 86

# O vão entre a caixa e o hub não é sobra: é onde a etiqueta do percentual fica
# em cima da linha. Com a conta acima sobram 124px de cada lado — a etiqueta
# ocupa cerca de 50 e o resto é respiro, pra ela não encostar nem na caixa nem
# na dobra do traço.
VAO_LATERAL = (LARGURA_PADRAO - 2 * MARGEM - 2 * CAIXA_LARGURA - HUB_LARGURA) / 2

ALTURA_CABECALHO = 78
ALTURA_RODAPE = 34


@dataclass(frozen=True)
class Caixa:
    """Um retângulo em pixels, com a origem no canto superior esquerdo."""

    x: float
    y: float
    largura: float
    altura: float

    @property
    def centro_y(self) -> float:
        return self.y + self.altura / 2

    @property
    def direita(self) -> float:
        return self.x + self.largura

    @property
    def centro_x(self) -> float:
        return self.x + self.largura / 2


@dataclass(frozen=True)
class NoEmpresa:
    nome: str
    percentual: float
    ativo: bool
    data_entrada: str
    data_saida: str | None
    lado: str  # "esquerda" ou "direita"
    caixa: Caixa

    @property
    def periodo(self) -> str:
        """Como a linha do tempo daquele vínculo aparece na caixa."""
        entrada = _data_br(self.data_entrada)
        if self.data_saida:
            return f"{entrada} — {_data_br(self.data_saida)}"
        return f"desde {entrada}"


@dataclass(frozen=True)
class MapaVinculos:
    socio_nome: str
    socio_documento: str
    empresas: tuple[NoEmpresa, ...]
    hub: Caixa
    largura: float
    altura: float
    gerado_em: str = ""
    empresas_omitidas: int = 0

    @property
    def ativos(self) -> int:
        return sum(1 for e in self.empresas if e.ativo)

    @property
    def encerrados(self) -> int:
        return sum(1 for e in self.empresas if not e.ativo)

    def resumo(self) -> str:
        if not self.empresas:
            return "Sem vínculos societários registrados."
        partes = [f"{self.ativos} vínculo(s) ativo(s)"]
        if self.encerrados:
            partes.append(f"{self.encerrados} encerrado(s)")
        if self.empresas_omitidas:
            partes.append(f"{self.empresas_omitidas} não cabem no desenho")
        return " · ".join(partes)


def _data_br(iso: str | None) -> str:
    """Data ISO do banco no formato que se lê no papel. Valor estranho passa
    inteiro em vez de derrubar o desenho — um mapa com uma data torta ainda
    serve; um mapa que não abre, não."""
    try:
        return dt.date.fromisoformat(str(iso)).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(iso or "")


def _ordenar(vinculos: list[dict]) -> list[dict]:
    """Ativos primeiro, do maior percentual para o menor; encerrados depois,
    do mais recente para o mais antigo. Quem olha o mapa quer ver primeiro
    onde a pessoa é sócia hoje, e mais ainda onde ela pesa."""
    ativos = [v for v in vinculos if not v.get("data_saida")]
    encerrados = [v for v in vinculos if v.get("data_saida")]
    ativos.sort(key=lambda v: (-float(v.get("percentual") or 0), str(v.get("empresa_nome") or "")))
    encerrados.sort(key=lambda v: (str(v.get("data_saida") or ""), str(v.get("empresa_nome") or "")), reverse=True)
    return ativos + encerrados


def montar_mapa(
    socio_nome: str,
    socio_documento: str,
    vinculos: list[dict],
    largura: float = LARGURA_PADRAO,
    gerado_em: str = "",
    maximo: int = 24,
) -> MapaVinculos:
    """Onde cada caixa fica, dado o sócio e seus vínculos.

    `vinculos` são dicts com empresa_nome, percentual, data_entrada e
    data_saida (None = ativo) — de propósito não são os objetos do banco: o
    desenho não precisa saber de id nem de cotas, e assim dá pra montar um
    mapa de teste sem tocar no repositório.

    `maximo` é um limite de segurança: acima dele o desenho vira uma parede de
    caixas ilegível, então as menos relevantes ficam de fora e o rodapé diz
    quantas foram — melhor um mapa honesto e legível do que um completo e
    inútil."""
    ordenados = _ordenar(list(vinculos))
    omitidas = max(0, len(ordenados) - maximo)
    ordenados = ordenados[:maximo]

    # Ímpares à esquerda, pares à direita: as participações maiores sobem para
    # o topo das duas colunas, em vez de encher um lado inteiro primeiro.
    esquerda = ordenados[0::2]
    direita = ordenados[1::2]

    linhas = max(len(esquerda), len(direita), 1)
    altura_coluna = linhas * CAIXA_ALTURA + (linhas - 1) * ESPACO_VERTICAL
    altura_util = max(altura_coluna, HUB_ALTURA)
    altura = ALTURA_CABECALHO + altura_util + ALTURA_RODAPE
    centro_y = ALTURA_CABECALHO + altura_util / 2

    hub = Caixa((largura - HUB_LARGURA) / 2, centro_y - HUB_ALTURA / 2, HUB_LARGURA, HUB_ALTURA)

    nos: list[NoEmpresa] = []
    for lado, coluna in (("esquerda", esquerda), ("direita", direita)):
        x = MARGEM if lado == "esquerda" else largura - MARGEM - CAIXA_LARGURA
        total = len(coluna) * CAIXA_ALTURA + (len(coluna) - 1) * ESPACO_VERTICAL
        topo = centro_y - total / 2
        for i, vinculo in enumerate(coluna):
            y = topo + i * (CAIXA_ALTURA + ESPACO_VERTICAL)
            nos.append(
                NoEmpresa(
                    nome=str(vinculo.get("empresa_nome") or "?"),
                    percentual=float(vinculo.get("percentual") or 0),
                    ativo=not vinculo.get("data_saida"),
                    data_entrada=str(vinculo.get("data_entrada") or ""),
                    data_saida=vinculo.get("data_saida") or None,
                    lado=lado,
                    caixa=Caixa(x, y, CAIXA_LARGURA, CAIXA_ALTURA),
                )
            )

    return MapaVinculos(
        socio_nome=socio_nome,
        socio_documento=socio_documento,
        empresas=tuple(nos),
        hub=hub,
        largura=largura,
        altura=altura,
        gerado_em=gerado_em,
        empresas_omitidas=omitidas,
    )


def nome_de_arquivo(socio_nome: str, extensao: str) -> str:
    """Nome sugerido na hora de exportar, só com letras sem acento, número e
    "_": o arquivo costuma acabar anexado em e-mail ou juntado a processo, e
    acento em nome de arquivo ainda hoje volta trocado de sistema antigo.

    Acento é retirado, não substituído por "_" — "joão" vira "joao", e não
    "jo_o", que ninguém reconheceria."""
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", socio_nome) if not unicodedata.combining(c)
    )
    limpo = "".join(c if c.isalnum() and c.isascii() else "_" for c in sem_acento).strip("_").lower()
    return f"mapa_vinculos_{limpo or 'socio'}.{extensao}"
