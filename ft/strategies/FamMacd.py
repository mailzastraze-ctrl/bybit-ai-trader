"""Hyperoptable research strategy for the 'macd_cross' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamMacd(ResearchBase):
    pass


build_parameters(FamMacd, "macd_cross")
