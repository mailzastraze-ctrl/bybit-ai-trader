"""Hyperoptable research strategy for the 'trend_ema' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamTrendEma(ResearchBase):
    pass


build_parameters(FamTrendEma, "trend_ema")
