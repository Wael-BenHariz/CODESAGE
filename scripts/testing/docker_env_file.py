#!/usr/bin/env python3
"""Convert dotenv syntax to Docker's unquoted env-file syntax privately."""

import os
import sys
from pathlib import Path

from dotenv import dotenv_values


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: docker_env_file.py DOTENV_PATH OUTPUT_PATH")
    source, output = map(Path, sys.argv[1:])
    values = dotenv_values(source)
    lines = []
    for key, value in values.items():
        if value is None:
            continue
        if "\n" in value or "\r" in value:
            raise SystemExit(
                f"{key} contains a newline; Docker env files cannot represent it"
            )
        lines.append(f"{key}={value}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.chmod(output, 0o600)


if __name__ == "__main__":
    main()
