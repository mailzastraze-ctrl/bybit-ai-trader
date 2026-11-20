"""Hyperoptable research strategy for the 'meanrev_bb' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamMeanRevBB(ResearchBase):
    pass


build_parameters(FamMeanRevBB, "meanrev_bb")
