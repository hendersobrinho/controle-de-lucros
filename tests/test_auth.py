from controle_lucros.auth import gerar_hash_senha, senha_confere


def test_hash_e_confere_senha_correta():
    hash_, salt = gerar_hash_senha("segredo123")
    assert senha_confere("segredo123", hash_, salt)


def test_confere_rejeita_senha_errada():
    hash_, salt = gerar_hash_senha("segredo123")
    assert not senha_confere("outra_coisa", hash_, salt)


def test_mesmo_salt_reproduz_o_mesmo_hash():
    hash1, salt = gerar_hash_senha("segredo123")
    hash2, _ = gerar_hash_senha("segredo123", salt)
    assert hash1 == hash2


def test_salts_diferentes_para_senhas_iguais():
    _, salt1 = gerar_hash_senha("segredo123")
    _, salt2 = gerar_hash_senha("segredo123")
    assert salt1 != salt2


def test_senha_nao_fica_em_texto_puro_no_hash():
    hash_, _ = gerar_hash_senha("minhasenha")
    assert "minhasenha" not in hash_
