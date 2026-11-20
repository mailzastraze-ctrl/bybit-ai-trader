"""Hyperoptable research strategy for the 'stoch_cross' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamStoch(ResearchBase):
    pass


build_parameters(FamStoch, "stoch_cross")
