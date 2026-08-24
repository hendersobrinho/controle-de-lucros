"""Hash e verificação de senha — PBKDF2-HMAC-SHA256 com salt aleatório por
usuário, só com a biblioteca padrão do Python (sem dependência nova)."""
from __future__ import annotations

import binascii
import hashlib
import hmac
import os

ITERACOES = 200_000


def gerar_hash_senha(senha: str, salt_hex: str | None = None) -> tuple[str, str]:
    """Retorna (hash_hex, salt_hex). Se salt_hex não for informado, gera um
    novo salt aleatório — use isso ao criar/trocar senha."""
    salt = bytes.fromhex(salt_hex) if salt_hex else os.urandom(16)
    hash_bytes = hashlib.pbkdf2_hmac("sha256", senha.encode("utf-8"), salt, ITERACOES)
    return binascii.hexlify(hash_bytes).decode("ascii"), salt.hex()


def senha_confere(senha: str, hash_esperado: str, salt_hex: str) -> bool:
    hash_calculado, _ = gerar_hash_senha(senha, salt_hex)
    return hmac.compare_digest(hash_calculado, hash_esperado)
