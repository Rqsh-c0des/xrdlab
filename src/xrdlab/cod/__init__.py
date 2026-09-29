"""Crystallography Open Database (COD) integration — open CIFs with citations."""

from xrdlab.cod.client import CODClient, CODError, cod_url

__all__ = ["CODClient", "CODError", "cod_url"]
