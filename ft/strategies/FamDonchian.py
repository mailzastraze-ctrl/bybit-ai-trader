"""Hyperoptable research strategy for the 'donchian_breakout' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamDonchian(ResearchBase):
    pass


build_parameters(FamDonchian, "donchian_breakout")
