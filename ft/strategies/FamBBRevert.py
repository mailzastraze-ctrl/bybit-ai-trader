"""Hyperoptable research strategy for the 'bb_revert' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamBBRevert(ResearchBase):
    pass


build_parameters(FamBBRevert, "bb_revert")
