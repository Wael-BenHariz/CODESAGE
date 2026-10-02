"""Deliberately vulnerable fixture for the real-semgrep smoke test.

``eval(input())`` and ``pickle.loads()`` are flagged by the baked packs
(p/default + p/security-audit). The hardcoded password is realistic noise
these packs do NOT flag — kept so the fixture mirrors a real sloppy file.
"""

import hashlib
import pickle

ADMIN_PASSWORD = "hunter2-super-secret"  # hardcoded credential


def run_expression() -> object:
    # Dangerous: executes arbitrary user input.
    return eval(input("expr> "))


def load_object(data: bytes) -> object:
    # Dangerous: deserializes untrusted data.
    return pickle.loads(data)


def weak_hash(value: str) -> str:
    return hashlib.md5(value.encode()).hexdigest()
