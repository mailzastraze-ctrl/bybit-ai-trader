"""Hyperoptable research strategy for the 'zscore_revert' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamZscore(ResearchBase):
    pass


build_parameters(FamZscore, "zscore_revert")
