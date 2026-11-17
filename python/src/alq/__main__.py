"""Ponto de entrada executável para `python -m alq`."""

from __future__ import annotations

import sys

from alq.cli import main

if __name__ == "__main__":
    sys.exit(main())
