"""Hyperoptable research strategy for the 'hull_turn' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamHull(ResearchBase):
    pass


build_parameters(FamHull, "hull_turn")
