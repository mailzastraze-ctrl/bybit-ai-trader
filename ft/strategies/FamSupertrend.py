"""Hyperoptable research strategy for the 'supertrend' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamSupertrend(ResearchBase):
    pass


build_parameters(FamSupertrend, "supertrend")
