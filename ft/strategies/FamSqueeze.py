"""Hyperoptable research strategy for the 'squeeze_momentum' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamSqueeze(ResearchBase):
    pass


build_parameters(FamSqueeze, "squeeze_momentum")
