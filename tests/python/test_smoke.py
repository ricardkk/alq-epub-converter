"""Testes smoke iniciais para validar importação e versão do pacote `alq`."""

from __future__ import annotations

import alq


def test_package_version() -> None:
    """Verifica se o pacote `alq` é importável e expõe a versão esperada."""
    assert alq.__version__ == "0.1.0"
