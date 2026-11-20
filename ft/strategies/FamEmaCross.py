"""Hyperoptable research strategy for the 'ema_cross' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamEmaCross(ResearchBase):
    pass


build_parameters(FamEmaCross, "ema_cross")
