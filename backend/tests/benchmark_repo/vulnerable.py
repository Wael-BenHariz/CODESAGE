"""Controlled benchmark fixture. Deliberately unsafe; never import or deploy."""

import subprocess


def run_user_command(command: str) -> bytes:
    return subprocess.check_output(command, shell=True)  # nosec B602


def query_user(value: str) -> str:
    return "SELECT * FROM users WHERE name = '" + value + "'"
