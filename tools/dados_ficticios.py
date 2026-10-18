"""Popula um banco DE TESTE com um escritório fictício, pra ver e testar as
telas com dados que cobrem os casos do dia a dia.

Uso (da pasta do projeto):

    .venv/bin/python tools/dados_ficticios.py            # usa a conexão configurada
    .venv/bin/python tools/dados_ficticios.py --limpar   # apaga o que houver e popula de novo

Por segurança só roda em banco com "teste" no nome: rodar isto no banco do
escritório misturaria empresas fictícias com as de verdade. Os usuários do
sistema que já existem são mantidos, inclusive com --limpar.

O que entra, e o que cada empresa mostra:
- 101 PADARIA PAO DOURADO — caso básico, dois sócios, período de 2023 FECHADO.
- 102 CLINICA SAUDE INTEGRAL — sócio que saiu (2024) cedendo cotas, histórico
  com alteração contratual; distribuição de 2025 desproporcional.
- 103 TRANSPORTES RODOVIA SUL — sócio pessoa jurídica (holding), capital do
  sócio NÃO informado (aparece a estimativa "≈") e aumento de capital.
- 104 CONSULTORIA ALVES LIMA — três sócios com 33,3334% / 33,3333% / 33,3333%
  e distribuição TRIMESTRAL em 2025 e 2026.
- 105 HOLDING FAMILIA SOUZA — a holding, sócia da 103, como empresa também.
- 106 TECH NOVA SOLUCOES — fundada no ano corrente.
- 107 MERCADINHO BOA VISTA — sócio único, cotas que NÃO batem com o total da
  empresa ("Pelas cotas, hoje") e sem alteração contratual associada.
- 108 ODONTO SORRISO — troca de sócio em 2025 e alteração de constituição
  TRANCADA.
- 109 FARMACIA VIDA — como vem do relatório de sócios: sem capital nem cotas
  da empresa, e sócio com 250.000 cotas sem capital. É onde se testa informar
  o valor da cota (R$ 0,01) e ver o capital calculado.
- LUCAS FERREIRA GOMES — sócio cadastrado sem empresa nenhuma.
- JOAO CARLOS SOUZA — sócio de três empresas (bom pro Mapa de vínculos).

Usuários criados (senha teste123): carla (administradora) e maria (comum).
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from controle_lucros import db, repositories as repo  # noqa: E402
from controle_lucros.models import (  # noqa: E402
    AlteracaoContratual,
    Empresa,
    Movimentacao,
    Socio,
    VinculoSocietario,
)

SENHA_DOS_USUARIOS = "teste123"
ANO = dt.date.today().year


# ---------------------------------------------------- documentos válidos --


def _digito(numeros: list[int], pesos: list[int]) -> int:
    resto = sum(n * p for n, p in zip(numeros, pesos)) % 11
    return 0 if resto < 2 else 11 - resto


def cpf(base: str) -> str:
    """CPF com dígitos verificadores certos a partir de 9 dígitos — o
    sistema confere CPF no informe de rendimentos, e um inválido travaria o
    teste dessa tela."""
    n = [int(c) for c in base]
    n.append(_digito(n, list(range(10, 1, -1))))
    n.append(_digito(n, list(range(11, 1, -1))))
    d = "".join(map(str, n))
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def cnpj(base: str) -> str:
    n = [int(c) for c in base]
    n.append(_digito(n, [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    n.append(_digito(n, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2]))
    d = "".join(map(str, n))
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


# ------------------------------------------------------------- montagem --


class Escritorio:
    def __init__(self, conn):
        self.conn = conn
        self.socios: dict[str, int] = {}

    def socio(self, nome: str, documento: str, tipo: str = "fisica") -> int:
        self.socios[nome] = repo.salvar_socio(self.conn, Socio(None, nome, documento, tipo))
        return self.socios[nome]

    def empresa(self, numero: str, nome: str, documento: str, capital: float, cotas: float) -> int:
        return repo.salvar_empresa(self.conn, Empresa(None, numero, nome, documento, capital, cotas))

    def alteracao(self, empresa_id: int, numero: int, data: str, nome: str,
                  capital: float, cotas: float, descricao: str) -> int:
        return repo.salvar_alteracao(
            self.conn, AlteracaoContratual(None, empresa_id, numero, data, nome, capital, cotas, descricao)
        )

    def entra(self, empresa_id: int, socio: str, percentual: float, cotas: float, data: str,
              alteracao: int | None = None, capital: float | None = None, observacao: str = "") -> int:
        return repo.salvar_vinculo(
            self.conn,
            VinculoSocietario(
                None, empresa_id, self.socios[socio], percentual, cotas, data, None,
                alteracao_entrada_id=alteracao, observacao=observacao, valor_capital=capital,
            ),
        )

    def sai(self, vinculo_id: int, data: str, alteracao: int | None = None) -> None:
        repo.encerrar_vinculo(self.conn, vinculo_id, data, alteracao)

    def distribui(self, empresa_id: int, ano: int, socio: str, valor: float,
                  pro_labore: float = 0.0, irrf: float = 0.0) -> None:
        repo.salvar_distribuicao(self.conn, empresa_id, ano, self.socios[socio], valor, pro_labore, irrf)

    def movimenta(self, empresa_id: int, socio: str, tipo: str, valor: float, data: str) -> None:
        repo.salvar_movimentacao(self.conn, Movimentacao(None, empresa_id, self.socios[socio], tipo, valor, data))


def popular(conn) -> None:
    e = Escritorio(conn)

    # ---- sócios
    for nome, base in (
        ("MARIA APARECIDA SOUZA", "123456789"),
        ("JOAO CARLOS SOUZA", "234567891"),
        ("RICARDO MENDES ALVES", "345678912"),
        ("FERNANDA LIMA COSTA", "456789123"),
        ("PAULO HENRIQUE ROCHA", "567891234"),
        ("RENATO ALVES PEREIRA", "678912345"),
        ("BEATRIZ LIMA SANTOS", "789123456"),
        ("CARLOS EDUARDO ROCHA", "891234567"),
        ("DIEGO FREITAS MOURA", "912345678"),
        ("LARISSA MOURA FREITAS", "135792468"),
        ("ANTONIO SILVA NETO", "246813579"),
        ("CAMILA ROCHA DIAS", "357924681"),
        ("MARCOS VINICIUS TEIXEIRA", "468135792"),
        ("JULIANA PRADO NUNES", "579246813"),
        ("LUCAS FERREIRA GOMES", "681357924"),
    ):
        e.socio(nome, cpf(base))
    e.socio("HOLDING FAMILIA SOUZA PARTICIPACOES LTDA", cnpj("314159260001"), "juridica")

    # ---- 101 PADARIA: caso básico
    padaria = e.empresa("101", "PADARIA PAO DOURADO LTDA", cnpj("112233440001"), 100_000, 100_000)
    alt = e.alteracao(padaria, 1, "2015-03-10", "PADARIA PAO DOURADO LTDA", 100_000, 100_000,
                      "Constituição da sociedade")
    repo.definir_valor_da_cota(conn, padaria, 1.0)
    e.entra(padaria, "MARIA APARECIDA SOUZA", 60, 60_000, "2015-03-10", alt, 60_000)
    e.entra(padaria, "JOAO CARLOS SOUZA", 40, 40_000, "2015-03-10", alt, 40_000)
    for ano, lucro in ((2023, 120_000), (2024, 150_000), (2025, 180_000)):
        e.distribui(padaria, ano, "MARIA APARECIDA SOUZA", lucro * 0.6, 36_000, 2_500)
        e.distribui(padaria, ano, "JOAO CARLOS SOUZA", lucro * 0.4, 24_000, 1_200)
    e.movimenta(padaria, "JOAO CARLOS SOUZA", "emprestimo_empresa_para_socio", 8_000, "2025-04-10")

    # ---- 102 CLINICA: sócio que saiu, cotas cedidas
    clinica = e.empresa("102", "CLINICA SAUDE INTEGRAL LTDA", cnpj("223344550001"), 300_000, 3_000)
    alt1 = e.alteracao(clinica, 1, "2012-08-01", "CLINICA SAUDE INTEGRAL LTDA", 300_000, 3_000,
                       "Constituição da sociedade")
    e.entra(clinica, "RICARDO MENDES ALVES", 50, 1_500, "2012-08-01", alt1, 150_000)
    fernanda = e.entra(clinica, "FERNANDA LIMA COSTA", 30, 900, "2012-08-01", alt1, 90_000)
    paulo = e.entra(clinica, "PAULO HENRIQUE ROCHA", 20, 600, "2012-08-01", alt1, 60_000)
    alt2 = e.alteracao(clinica, 2, "2024-06-30", "CLINICA SAUDE INTEGRAL LTDA", 300_000, 3_000,
                       "Saída de Paulo Henrique Rocha; cotas cedidas a Fernanda Lima Costa")
    e.sai(paulo, "2024-06-30", alt2)
    e.sai(fernanda, "2024-06-30", alt2)
    e.entra(clinica, "FERNANDA LIMA COSTA", 50, 1_500, "2024-06-30", alt2, 150_000,
            observacao="Recebeu as 600 cotas de Paulo Henrique Rocha")
    e.distribui(clinica, 2024, "RICARDO MENDES ALVES", 100_000, 48_000, 6_800)
    e.distribui(clinica, 2024, "FERNANDA LIMA COSTA", 60_000, 36_000, 4_100)
    e.distribui(clinica, 2024, "PAULO HENRIQUE ROCHA", 40_000)
    # Desproporcional de propósito: 50% / 50% de capital, 58% / 42% do lucro.
    e.distribui(clinica, 2025, "RICARDO MENDES ALVES", 140_000, 48_000, 7_200)
    e.distribui(clinica, 2025, "FERNANDA LIMA COSTA", 100_000, 36_000, 4_300)
    e.movimenta(clinica, "RICARDO MENDES ALVES", "adiantamento_lucro", 20_000, "2025-03-15")

    # ---- 105 HOLDING (cadastrada antes, porque é sócia da 103)
    holding = e.empresa("105", "HOLDING FAMILIA SOUZA PARTICIPACOES LTDA", cnpj("314159260001"),
                        200_000, 200_000)
    alt = e.alteracao(holding, 1, "2019-01-10", "HOLDING FAMILIA SOUZA PARTICIPACOES LTDA",
                      200_000, 200_000, "Constituição da sociedade")
    e.entra(holding, "MARIA APARECIDA SOUZA", 50, 100_000, "2019-01-10", alt, 100_000)
    e.entra(holding, "JOAO CARLOS SOUZA", 50, 100_000, "2019-01-10", alt, 100_000)
    e.distribui(holding, 2025, "MARIA APARECIDA SOUZA", 50_000)
    e.distribui(holding, 2025, "JOAO CARLOS SOUZA", 50_000)

    # ---- 103 TRANSPORTES: sócio PJ, capital não informado, aumento de capital
    transportes = e.empresa("103", "TRANSPORTES RODOVIA SUL LTDA", cnpj("334455660001"), 50_000, 500)
    alt1 = e.alteracao(transportes, 1, "2018-02-15", "TRANSPORTES RODOVIA SUL LTDA", 50_000, 500,
                       "Constituição da sociedade")
    joao = e.entra(transportes, "JOAO CARLOS SOUZA", 70, 350, "2018-02-15", alt1)
    holding_v = e.entra(transportes, "HOLDING FAMILIA SOUZA PARTICIPACOES LTDA", 30, 150, "2018-02-15", alt1)
    alt2 = e.alteracao(transportes, 2, "2024-11-05", "TRANSPORTES RODOVIA SUL LTDA", 80_000, 800,
                       "Aumento de capital para R$ 80.000,00 em 800 cotas")
    e.sai(joao, "2024-11-05", alt2)
    e.sai(holding_v, "2024-11-05", alt2)
    e.entra(transportes, "JOAO CARLOS SOUZA", 70, 560, "2024-11-05", alt2)
    e.entra(transportes, "HOLDING FAMILIA SOUZA PARTICIPACOES LTDA", 30, 240, "2024-11-05", alt2)
    e.distribui(transportes, 2025, "JOAO CARLOS SOUZA", 35_000)
    e.distribui(transportes, 2025, "HOLDING FAMILIA SOUZA PARTICIPACOES LTDA", 15_000)

    # ---- 104 CONSULTORIA: três partes quase iguais, trimestral
    consultoria = e.empresa("104", "CONSULTORIA ALVES LIMA ASSOCIADOS LTDA", cnpj("445566770001"),
                            90_000, 90_000)
    alt = e.alteracao(consultoria, 1, "2022-06-01", "CONSULTORIA ALVES LIMA ASSOCIADOS LTDA",
                      90_000, 90_000, "Constituição da sociedade")
    for nome, percentual in (("RENATO ALVES PEREIRA", 33.3334), ("BEATRIZ LIMA SANTOS", 33.3333),
                             ("CARLOS EDUARDO ROCHA", 33.3333)):
        e.entra(consultoria, nome, percentual, 30_000, "2022-06-01", alt, 30_000)
    for ano, trimestres, valor in ((2025, (1, 2, 3, 4), 10_000), (2026, (1, 2, 3), 12_000)):
        if ano > ANO:
            continue
        for trimestre in trimestres:
            for nome in ("RENATO ALVES PEREIRA", "BEATRIZ LIMA SANTOS", "CARLOS EDUARDO ROCHA"):
                pro_labore = 6_000 if nome == "RENATO ALVES PEREIRA" else 0
                repo.salvar_distribuicao_trimestral(
                    conn, consultoria, ano, trimestre, e.socios[nome], valor, pro_labore, 0
                )

    # ---- 106 TECH: fundada no ano corrente
    tech = e.empresa("106", "TECH NOVA SOLUCOES LTDA", cnpj("556677880001"), 20_000, 20_000)
    alt = e.alteracao(tech, 1, f"{ANO}-03-02", "TECH NOVA SOLUCOES LTDA", 20_000, 20_000,
                      "Constituição da sociedade")
    e.entra(tech, "DIEGO FREITAS MOURA", 70, 14_000, f"{ANO}-03-02", alt, 14_000)
    e.entra(tech, "LARISSA MOURA FREITAS", 30, 6_000, f"{ANO}-03-02", alt, 6_000)

    # ---- 107 MERCADINHO: cotas que não batem, sem alteração associada
    mercadinho = e.empresa("107", "MERCADINHO BOA VISTA ME", cnpj("667788990001"), 30_000, 30_000)
    e.entra(mercadinho, "ANTONIO SILVA NETO", 100, 25_000, "2009-05-04", None, 30_000,
            observacao="Dados importados do sistema antigo")
    e.distribui(mercadinho, 2024, "ANTONIO SILVA NETO", 45_000, 18_000, 900)
    e.distribui(mercadinho, 2025, "ANTONIO SILVA NETO", 52_000, 18_000, 950)
    e.movimenta(mercadinho, "ANTONIO SILVA NETO", "emprestimo_socio_para_empresa", 10_000, "2024-08-01")

    # ---- 108 ODONTO: troca de sócio, constituição trancada
    odonto = e.empresa("108", "ODONTO SORRISO LTDA", cnpj("778899000001"), 120_000, 1_200)
    alt1 = e.alteracao(odonto, 1, "2016-05-20", "ODONTO SORRISO LTDA", 120_000, 1_200,
                       "Constituição da sociedade")
    e.entra(odonto, "CAMILA ROCHA DIAS", 50, 600, "2016-05-20", alt1, 60_000)
    marcos = e.entra(odonto, "MARCOS VINICIUS TEIXEIRA", 50, 600, "2016-05-20", alt1, 60_000)
    alt2 = e.alteracao(odonto, 2, "2025-09-15", "ODONTO SORRISO LTDA", 120_000, 1_200,
                       "Retirada de Marcos Vinicius Teixeira e ingresso de Juliana Prado Nunes")
    e.sai(marcos, "2025-09-15", alt2)
    e.entra(odonto, "JULIANA PRADO NUNES", 50, 600, "2025-09-15", alt2, 60_000)
    e.distribui(odonto, 2025, "CAMILA ROCHA DIAS", 70_000, 30_000, 2_000)
    e.distribui(odonto, 2025, "MARCOS VINICIUS TEIXEIRA", 35_000)
    e.distribui(odonto, 2025, "JULIANA PRADO NUNES", 25_000)
    repo.fechar_alteracao(conn, alt1)

    # ---- 109 FARMACIA: como chega do relatório de sócios
    farmacia = e.empresa("109", "FARMACIA VIDA LTDA", "", 0, 0)
    e.socio("ROBERTA CAMPOS LIMA", cpf("792468135"))
    e.entra(farmacia, "ROBERTA CAMPOS LIMA", 100, 250_000, "2017-09-01",
            observacao="Importado do relatório de sócios")

    # ---- por último: período fechado (depois dele, 2023 da padaria não muda mais)
    repo.fechar_periodo(conn, padaria, 2023)

    # ---- usuários
    for nome, login, admin in (("Carla Administradora", "carla", True), ("Maria Usuária", "maria", False)):
        if repo.buscar_usuario_por_login(conn, login) is None:
            repo.criar_usuario(conn, nome, login, SENHA_DOS_USUARIOS, admin=admin)


def main() -> None:
    argumentos = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    argumentos.add_argument("--limpar", action="store_true",
                            help="apaga empresas, sócios e lançamentos do banco antes de popular")
    opcoes = argumentos.parse_args()

    parametros = db.conexao_configurada()
    if parametros is None:
        sys.exit("Nenhuma conexão configurada. Abra o programa uma vez e configure o banco de teste.")
    if "teste" not in parametros.banco.lower():
        sys.exit(f'Recusado: o banco "{parametros.banco}" não tem "teste" no nome. '
                 "Isto só roda em banco de teste, nunca no do escritório.")

    conn = db.connect(parametros)
    db.init_schema(conn)
    if conn.execute("SELECT COUNT(*) FROM empresa").fetchone()[0]:
        if not opcoes.limpar:
            sys.exit("O banco já tem empresas. Use --limpar para apagar e popular de novo.")
        dados = [t for t in db.TABELAS if t != "usuario"]
        conn.execute(f"TRUNCATE {', '.join(dados)} RESTART IDENTITY CASCADE")
        conn.commit()

    popular(conn)
    resumo = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("empresa", "socio", "vinculo_societario", "alteracao_contratual",
                        "distribuicao_lucro", "distribuicao_trimestral", "movimentacao", "usuario")}
    print(f"Pronto — {parametros.descricao()}")
    for tabela, total in resumo.items():
        print(f"  {tabela}: {total}")
    print(f"Usuários de teste: carla (administradora) e maria — senha {SENHA_DOS_USUARIOS}")


if __name__ == "__main__":
    main()
