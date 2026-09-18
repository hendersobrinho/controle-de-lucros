"""Montagem do Comprovante de Rendimentos Pagos e de Imposto sobre a Renda
Retido na Fonte — o "informe de rendimentos" — no modelo aprovado pela
Instrução Normativa RFB nº 2.060, de 13 de dezembro de 2021.

Regras da própria IN que explicam o formato do código abaixo:

* É um informe POR FONTE PAGADORA. Sócio de três empresas recebe três
  comprovantes, cada um com o CNPJ da respectiva empresa — por isso a tela
  emite vários de uma vez, um por empresa, em vez de um documento só.
* O exercício é sempre o ano seguinte ao ano-calendário: o que foi pago em
  2025 é declarado no exercício 2026.
* Pró-labore é rendimento tributável (Quadro 3, linha 1), com o INSS na linha
  2 e o IRRF na linha 5. Distribuição de lucro é isento (Quadro 4, linha 5).
  Empréstimo da empresa ao sócio não é rendimento nenhum: vai pro Quadro 7,
  porque o sócio precisa do saldo pra ficha de Dívidas e Ônus Reais.
* Sair da sociedade e comprar/vender cotas também não é rendimento, mas muda
  o patrimônio declarado: a saída vai pra ficha de Dívidas e Ônus Reais e a
  variação de cotas pra ficha de Bens e Direitos. Os dois saem no Quadro 7,
  porque é lá que o comprovante diz ao sócio o que lançar em cada ficha.
* Papel A4, preto sobre branco.

Os textos das linhas são a redação impressa do modelo oficial — mudar uma
palavra aqui gera um documento divergente do que a Receita aprovou.

Este módulo não importa Qt: ele produz o HTML, e ui/informe_pdf.py converte
pra PDF. Assim toda a lógica do informe é testável sem abrir janela.
"""
from __future__ import annotations

import datetime as dt
import html
from pathlib import Path

from .fiscal import de_centavos, formatar_cnpj, formatar_cotas, formatar_cpf
from .models import InformeRendimento

RODAPE_LEGAL = "Aprovado pela Instrução Normativa RFB nº 2.060, de 13 de dezembro de 2021."
AVISO_CABECALHO = (
    "Verifique as condições e o prazo para a apresentação da Declaração do Imposto sobre a "
    "Renda da Pessoa Física para este ano - calendário no site da Secretaria Especial da "
    "Receita Federal do Brasil na Internet, no endereço "
    "&lt;https://www.gov.br/receitafederal/pt-br&gt;"
)
BRASAO_ARQUIVO = "brasao_republica.png"
# Tamanho do brasão no cabeçalho. A proporção tem que ser a do arquivo, senão
# o Qt estica a imagem pra caber — tests/test_informe_pdf.py confere isso
# contra o PNG de verdade, pra trocar o arquivo não deformar o brasão calado.
BRASAO_LARGURA = 45
BRASAO_ALTURA = 45

TITULO_QUADRO_3 = "3. Rendimentos Tributáveis, Deduções e Imposto sobre a Renda Retido na Fonte"
TITULO_QUADRO_4 = "4. Rendimentos Isentos e Não Tributáveis"
TITULO_QUADRO_5 = "5. Rendimentos Sujeitos a Tributação Exclusiva (rendimento líquido)"
TITULO_QUADRO_6 = (
    "6. Rendimentos Recebidos Acumuladamente - Art. 12-A da Lei nº7.713, de 1988 "
    "(sujeitos a tributação exclusiva)"
)
TITULO_QUADRO_7 = "7. Informações Complementares"

# (campo do informe, número da linha, redação exata do modelo oficial)
QUADRO_3_LINHAS = (
    ("q3_total_rendimentos", "1", "Total dos rendimentos (inclusive férias)."),
    ("q3_previdencia_oficial", "2", "Contribuição previdenciária oficial."),
    (
        "q3_previdencia_complementar",
        "3",
        "Contribuição a entidades de previdência complementar, pública ou privada, e a Fundo de "
        "Aposentadoria Programada Individual - (Fapi) (preencher também o Quadro 7).",
    ),
    ("q3_pensao_alimenticia", "4", "Pensão alimentícia (preencher também o Quadro 7)."),
    ("q3_irrf", "5", "Imposto sobre a Renda Retido na Fonte (IRRF)."),
)

QUADRO_4_LINHAS = (
    (
        "q4_parcela_isenta_65",
        "1",
        "Parcela isenta dos proventos de aposentadoria, reserva remunerada, reforma e pensão "
        "(65 anos ou mais), exceto a parcela isenta do 13º (décimo terceiro) salário.",
    ),
    (
        "q4_parcela_isenta_13_65",
        "2",
        "Parcela isenta do 13º salário de aposentadoria, reserva remunerada, reforma e pensão "
        "(65 anos ou mais).",
    ),
    ("q4_diarias_ajudas_custo", "3", "Diárias e ajudas de custo."),
    (
        "q4_pensao_molestia_grave",
        "4",
        "Pensão e proventos de aposentadoria ou reforma por moléstia grave; proventos de "
        "aposentadoria ou reforma por acidente em serviço.",
    ),
    (
        "q4_lucros_dividendos",
        "5",
        "Lucros e dividendos, apurados a partir de 1996, pagos por pessoa jurídica (lucro real, "
        "presumido ou arbitrado).",
    ),
    (
        "q4_valores_socio_microempresa",
        "6",
        "Valores pagos ao titular ou sócio da microempresa ou empresa de pequeno porte, exceto "
        "pró-labore, aluguéis ou serviços prestados.",
    ),
    (
        "q4_indenizacoes_rescisao",
        "7",
        "Indenizações por rescisão de contrato de trabalho, inclusive a título de PDV e por "
        "acidente de trabalho.",
    ),
    (
        "q4_juros_mora",
        "8",
        "Juros de mora recebidos, devidos pelo atraso no pagamento de remuneração por exercício "
        "de emprego, cargo ou função.",
    ),
    ("q4_outros", "9", "Outros (especificar)."),
)

QUADRO_5_LINHAS = (
    ("q5_decimo_terceiro", "1", "13º (décimo terceiro) salário."),
    (
        "q5_irrf_decimo_terceiro",
        "2",
        "Imposto sobre a Renda Retido na Fonte sobre 13º (décimo terceiro) salário.",
    ),
    ("q5_outros", "3", "Outros."),
)

# Como o escritório chama cada linha no dia a dia. A tela mostra esse apelido
# junto do texto oficial pra quem preenche não precisar decorar que pró-labore
# é a linha 1 do Quadro 3 e lucro é a linha 5 do Quadro 4.
APELIDOS_CAMPOS = {
    "q3_total_rendimentos": "Pró-labore",
    "q3_previdencia_oficial": "INSS",
    "q3_irrf": "IRRF",
    "q4_lucros_dividendos": "Distribuição de lucros",
    "emprestimo_saldo": "Empréstimo ao sócio",
    "cota_valor_nominal": "Valor da cota",
}

# Campos que o sistema preenche sozinho a partir dos lançamentos do ano.
CAMPOS_SUGERIDOS = (
    "q3_total_rendimentos",
    "q3_irrf",
    "q4_lucros_dividendos",
    "emprestimo_saldo",
    "cota_valor_nominal",
)


def bloco_emprestimo(saldo_centavos: int, ano_base: int) -> str:
    """Texto do Quadro 7 para o empréstimo. A redação é a do modelo em uso —
    ela é o que orienta o sócio a lançar o saldo na ficha certa da
    declaração, então não é texto livre."""
    return (
        "EMPRÉSTIMO A SÓCIOS (Ficha de Dívidas e Ônus Reais):\n"
        f"Empréstimo da Empresa para o Sócio - Saldo em 31/12/{ano_base} "
        f"R$ {de_centavos(saldo_centavos)}"
    )


def _data_br(data_iso: str) -> str:
    """dd/mm/aaaa a partir do ISO do banco. Data que não vier em ISO sai como
    está: é dado digitado, e esconder o que está gravado seria pior."""
    try:
        return dt.date.fromisoformat(str(data_iso)).strftime("%d/%m/%Y")
    except (TypeError, ValueError):
        return str(data_iso or "")


def bloco_saida_sociedade(data_saida: str) -> str:
    """Texto do Quadro 7 para a saída da sociedade. Vai na ficha de Dívidas e
    Ônus Reais: é lá que a declaração baixa a participação que o sócio tinha."""
    return (
        "SAÍDA DE SOCIEDADE DE DIREITO PRIVADO (Ficha de Dívidas e Ônus Reais):\n"
        f"Data da saída {_data_br(data_saida)}"
    )


def bloco_variacao_cotas(informe: InformeRendimento) -> str:
    """Texto do Quadro 7 para a compra/venda de cotas do ano.

    A ficha de Bens e Direitos do sócio tem que fechar com o que ele tinha em
    31/12 — então o comprovante informa quantas cotas mudaram de mão no ano,
    por quanto, e qual ficou sendo o saldo. Sem variação não há bloco: quem
    continuou com as mesmas cotas repete a declaração do ano anterior."""
    variacao = (informe.cotas_fim or 0) - (informe.cotas_inicio or 0)
    if not variacao:
        return ""
    quantidade = abs(variacao)
    nominal = informe.cota_valor_nominal or 0
    return (
        "VARIAÇÃO DE COTAS (por alteração contratual) (Ficha de Bens e Direitos):\n"
        f"{'Alienação' if variacao < 0 else 'Aquisição'} de {formatar_cotas(quantidade)} "
        f"Cotas Societárias, no valor nominal de R$ {de_centavos(nominal)} cada uma, "
        f"totalizando R$ {de_centavos(round(quantidade * nominal))}. "
        f"Saldo em 31/12/{informe.ano_base}: {formatar_cotas(informe.cotas_fim)} Cotas = "
        f"R$ {de_centavos(round((informe.cotas_fim or 0) * nominal))}"
    )


def informacoes_complementares(informe: InformeRendimento) -> str:
    """Quadro 7 completo: empréstimo, saída da sociedade, variação de cotas e
    o texto livre digitado, nessa ordem, separados por linha em branco.

    A ordem é a do modelo em uso no escritório — primeiro o que o sócio lança
    em Dívidas e Ônus Reais, depois o que ele lança em Bens e Direitos."""
    blocos = []
    if informe.emprestimo_saldo:
        blocos.append(bloco_emprestimo(informe.emprestimo_saldo, informe.ano_base))
    if informe.saida_sociedade_data:
        blocos.append(bloco_saida_sociedade(informe.saida_sociedade_data))
    variacao = bloco_variacao_cotas(informe)
    if variacao:
        blocos.append(variacao)
    livre = (informe.informacoes_complementares or "").strip()
    if livre:
        blocos.append(livre)
    return "\n\n".join(blocos)


def nome_arquivo_sugerido(informe: InformeRendimento, socio_nome: str, empresa_nome: str) -> str:
    """Nome por sócio + empresa + ano: emitindo em lote, vários informes do
    mesmo sócio caem na mesma pasta e não podem colidir."""
    base = " - ".join(p for p in (f"Informe {informe.ano_base}", socio_nome, empresa_nome) if p)
    limpo = "".join("-" if c in '<>:"/\\|?*' else c for c in base).strip()
    return f"{limpo or 'Informe de rendimentos'}.pdf"


def caminho_brasao() -> Path | None:
    """Import tardio do módulo de assets (que depende do Qt) pra este módulo
    continuar importável — e testável — sem interface gráfica."""
    from .ui.icones import pasta_assets

    caminho = pasta_assets() / BRASAO_ARQUIVO
    return caminho if caminho.exists() else None


# ------------------------------------------------------------------ HTML --


def montar_html(
    informe: InformeRendimento,
    empresa_nome: str,
    empresa_cnpj: str,
    socio_nome: str,
    socio_cpf: str,
    data_emissao: str,
    brasao: Path | None = ...,
) -> str:
    """HTML do informe pronto pra virar PDF (e pra ser mostrado na
    conferência da tela — é o mesmo HTML nos dois, senão conferir não prova
    nada sobre o que vai sair impresso).

    O layout é feito com tabelas HTML porque o motor de texto do Qt suporta
    um subconjunto de CSS que não inclui grid nem flex; tabela aninhada com
    border=1 é o que reproduz as caixas do modelo oficial."""
    if brasao is ...:
        brasao = caminho_brasao()
    return f"""<html><body>
{_cabecalho(informe, brasao)}
{_quadro_1(empresa_cnpj, empresa_nome)}
{_quadro_2(informe, socio_nome, socio_cpf)}
{_quadro_valores(TITULO_QUADRO_3, QUADRO_3_LINHAS, informe)}
{_quadro_valores(TITULO_QUADRO_4, QUADRO_4_LINHAS, informe)}
{_quadro_valores(TITULO_QUADRO_5, QUADRO_5_LINHAS, informe)}
{_quadro_texto(TITULO_QUADRO_6, "")}
{_quadro_texto(TITULO_QUADRO_7, informacoes_complementares(informe))}
{_quadro_8(informe, data_emissao)}
<p style="font-size:7pt; margin-top:6px">{html.escape(RODAPE_LEGAL)}</p>
</body></html>"""


def _cabecalho(informe: InformeRendimento, brasao: Path | None) -> str:
    imagem = (
        f'<img src="{brasao.as_posix()}" width="{BRASAO_LARGURA}" height="{BRASAO_ALTURA}">'
        if brasao
        else "&nbsp;"
    )
    return f"""<table width="100%" border="1" cellspacing="0" cellpadding="3">
<tr>
  <td width="55%" rowspan="2">
    <table border="0" cellspacing="0" cellpadding="0" width="100%">
      <tr>
        <td width="52" valign="middle">{imagem}</td>
        <td valign="middle"><b>MINISTÉRIO DA ECONOMIA</b><br>
        <b>SECRETARIA DA RECEITA FEDERAL DO BRASIL</b><br>
        <b>IMPOSTO SOBRE A RENDA DA PESSOA FÍSICA</b><br>
        <b>EXERCÍCIO:</b>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<b>{informe.exercicio}</b></td>
      </tr>
    </table>
  </td>
  <td width="45%" valign="middle"><b>COMPROVANTE DE RENDIMENTOS PAGOS E DE<br>
  IMPOSTO SOBRE A RENDA RETIDO NA FONTE</b></td>
</tr>
<tr>
  <td valign="middle"><b>ANO-CALENDÁRIO:</b>&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;<b>{informe.ano_base}</b></td>
</tr>
</table>
<table width="100%" border="1" cellspacing="0" cellpadding="3">
<tr><td>{AVISO_CABECALHO}</td></tr>
</table>"""


def _quadro_1(empresa_cnpj: str, empresa_nome: str) -> str:
    return f"""<p style="margin-top:7px; margin-bottom:2px"><b>1. Fonte Pagadora Pessoa Jurídica ou Pessoa Física</b></p>
<table width="100%" border="1" cellspacing="0" cellpadding="3">
<tr>
  <td width="30%">CNPJ/CPF<br>{html.escape(formatar_cnpj(empresa_cnpj)) or "&nbsp;"}</td>
  <td>Nome Empresarial / Nome Completo<br>{html.escape(empresa_nome)}</td>
</tr>
</table>"""


def _quadro_2(informe: InformeRendimento, socio_nome: str, socio_cpf: str) -> str:
    codigo = html.escape(informe.codigo_beneficiario or "")
    nome = html.escape(socio_nome)
    # Rótulo e nome ficam na MESMA tabela aninhada (em vez de "rótulo<br>tabela"):
    # o Qt insere espaçamento de parágrafo antes de uma tabela, e isso abriria
    # um buraco na caixa que não existe no modelo.
    nome_html = (
        '<table border="0" cellspacing="0" cellpadding="0" width="100%">'
        '<tr><td colspan="2">Nome Completo</td></tr>'
        f"<tr><td>{nome}</td>"
        f'<td align="right" width="110">-&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{codigo}</td></tr>'
        "</table>"
        if codigo
        else f"Nome Completo<br>{nome}"
    )
    return f"""<p style="margin-top:7px; margin-bottom:2px"><b>2. Pessoa Física Beneficiária dos Rendimentos</b></p>
<table width="100%" border="1" cellspacing="0" cellpadding="3">
<tr>
  <td width="30%">CPF<br>{html.escape(formatar_cpf(socio_cpf))}</td>
  <td>{nome_html}</td>
</tr>
<tr>
  <td colspan="2">Natureza do Rendimento<br>{html.escape(informe.natureza_rendimento or "") or "&nbsp;"}</td>
</tr>
</table>"""


def _quadro_valores(titulo: str, linhas: tuple, informe: InformeRendimento) -> str:
    corpo = "\n".join(
        f'<tr><td width="86%">{numero}. {html.escape(descricao)}</td>'
        f'<td width="14%" align="right">{de_centavos(getattr(informe, campo))}</td></tr>'
        for campo, numero, descricao in linhas
    )
    return f"""<table width="100%" border="0" cellspacing="0" cellpadding="0" style="margin-top:7px">
<tr><td><b>{html.escape(titulo)}</b></td><td align="right"><b>Valores em Reais</b></td></tr>
</table>
<table width="100%" border="1" cellspacing="0" cellpadding="2">
{corpo}
</table>"""


def _quadro_texto(titulo: str, conteudo: str) -> str:
    # No modelo, o texto do quadro não encosta nas bordas da caixa: fica uma
    # linha em branco antes e depois. Quadro vazio continua sendo uma linha fina.
    if conteudo:
        corpo = "&nbsp;<br>" + html.escape(conteudo).replace("\n", "<br>") + "<br>&nbsp;"
    else:
        corpo = "&nbsp;"
    return f"""<p style="margin-top:7px; margin-bottom:2px"><b>{html.escape(titulo)}</b></p>
<table width="100%" border="1" cellspacing="0" cellpadding="3">
<tr><td>{corpo}</td></tr>
</table>"""


def _quadro_8(informe: InformeRendimento, data_emissao: str) -> str:
    return f"""<p style="margin-top:7px; margin-bottom:2px"><b>8. Responsável pelas Informações</b></p>
<table width="100%" border="1" cellspacing="0" cellpadding="3">
<tr>
  <td width="46%">Nome<br>{html.escape(informe.responsavel_nome or "") or "&nbsp;"}</td>
  <td width="18%">Data<br>{html.escape(data_emissao)}</td>
  <td>Assinatura<br>&nbsp;</td>
</tr>
</table>"""
