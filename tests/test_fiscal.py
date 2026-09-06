import pytest

from controle_lucros.fiscal import (
    cpf_valido,
    de_centavos,
    formatar_cnpj,
    formatar_cpf,
    para_centavos,
    reais_para_centavos,
)


# ------------------------------------------------------------------- CPF --


@pytest.mark.parametrize("cpf", ["005.169.717-35", "00516971735", "072.525.437-81"])
def test_cpf_valido_aceita_cpf_real(cpf):
    assert cpf_valido(cpf)


@pytest.mark.parametrize(
    "cpf",
    [
        "005.169.717-34",  # dígito verificador errado
        "111.111.111-11",  # repetido passa na conta dos dígitos, mas não existe
        "000.000.000-00",
        "0051697173",  # curto
        "005169717355",  # longo
        "",
        None,
    ],
)
def test_cpf_valido_rejeita_invalido(cpf):
    assert not cpf_valido(cpf)


def test_formatar_cpf():
    assert formatar_cpf("00516971735") == "005.169.717-35"
    # Documento incompleto sai como está: a tela mostra o que está cadastrado
    # em vez de esconder o problema atrás de uma formatação bonita.
    assert formatar_cpf("123") == "123"


def test_formatar_cnpj_aceita_numerico_e_alfanumerico():
    assert formatar_cnpj("36415149000189") == "36.415.149/0001-89"
    assert formatar_cnpj("36.415.149/0001-89") == "36.415.149/0001-89"
    assert formatar_cnpj("12ABC34501DE35") == "12.ABC.345/01DE-35"
    assert formatar_cnpj("nada") == "nada"


# -------------------------------------------------------------- Dinheiro --


@pytest.mark.parametrize(
    "texto,esperado",
    [
        ("560.619,85", 56061985),
        ("1234,56", 123456),
        ("1234.56", 123456),
        ("R$ 1.000,00", 100000),
        ("1.234.567,89", 123456789),
        ("785.516,16", 78551616),
        ("1234", 123400),
        ("0,05", 5),
        ("10,5", 1050),
        ("", 0),
        (None, 0),
        ("-100,00", -10000),
    ],
)
def test_para_centavos(texto, esperado):
    assert para_centavos(texto) == esperado


@pytest.mark.parametrize("texto", ["abc", "1.2a3", "12,ab"])
def test_para_centavos_recusa_lixo(texto):
    with pytest.raises(ValueError):
        para_centavos(texto)


def test_de_centavos():
    assert de_centavos(56061985) == "560.619,85"
    assert de_centavos(0) == "0,00"
    assert de_centavos(5) == "0,05"
    assert de_centavos(None) == "0,00"
    assert de_centavos(-10000) == "-100,00"


def test_ida_e_volta_preserva_o_valor():
    for texto in ("560.619,85", "0,01", "1.000.000,00", "785.516,16"):
        assert de_centavos(para_centavos(texto)) == texto


def test_somar_centavos_nao_acumula_erro_de_float():
    """O motivo de o informe usar inteiro: somar cem parcelas de 0,29 em float
    dá 28,999999999999996, e um centavo a menos num documento fiscal já é um
    documento errado. Em centavos a soma é exata."""
    assert sum([0.29] * 100) != 29.00  # o problema que estamos evitando
    assert sum(para_centavos("0,29") for _ in range(100)) == para_centavos("29,00")
    assert de_centavos(sum(para_centavos("0,29") for _ in range(100))) == "29,00"


def test_reais_para_centavos_arredonda_a_representacao_binaria():
    """Os valores vêm do banco como REAL; 1234.56 não é exato em binário, e
    truncar (int) daria 123455. Essa é a única fronteira float -> centavos."""
    assert reais_para_centavos(1234.56) == 123456
    assert reais_para_centavos(560619.85) == 56061985
    assert reais_para_centavos(0) == 0
    assert reais_para_centavos(None) == 0
