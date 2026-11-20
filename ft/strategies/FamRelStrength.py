"""Hyperoptable research strategy for the 'rel_strength' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamRelStrength(ResearchBase):
    pass


build_parameters(FamRelStrength, "rel_strength")
