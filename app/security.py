"""
Senha para abrir o Prumo.

A senha não é guardada: só um resumo dela (PBKDF2-SHA256, 200 mil rodadas, com um valor
aleatório próprio), suficiente para conferir a senha digitada. A trava protege a tela do
Prumo; os PDFs continuam como arquivos comuns na pasta da biblioteca. Para proteger um
arquivo em si, há "Proteger com senha" na tela do PDF (criptografia padrão de PDF).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

ITERATIONS = 200_000


def hash_password(password: str, iterations: int = ITERATIONS) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(iterations, base64.b64encode(salt).decode(),
                                           base64.b64encode(digest).decode())


def verify_password(password: str, stored: str | None) -> bool:
    if not stored:
        return False
    try:
        algo, iterations, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        test = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(test, base64.b64decode(digest))
    except (ValueError, TypeError):
        return False


IDLE_OPTIONS = [(0, "Só ao abrir o Prumo"), (1, "Depois de 1 minuto sem uso"), (5, "Depois de 5 minutos sem uso"),
                (10, "Depois de 10 minutos sem uso"), (30, "Depois de 30 minutos sem uso")]
