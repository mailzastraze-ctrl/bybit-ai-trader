"""Hyperoptable research strategy for the 'rsi_revert' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamRsiRevert(ResearchBase):
    pass


build_parameters(FamRsiRevert, "rsi_revert")
