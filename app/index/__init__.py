"""Lexical indexes used only by search_keyword. The agent never imports this package."""

from app.index.dual_index import build_precision_index, precision_lookup

__all__ = ["build_precision_index", "precision_lookup"]
