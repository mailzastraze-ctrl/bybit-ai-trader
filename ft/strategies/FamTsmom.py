"""Hyperoptable research strategy for the 'tsmom' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamTsmom(ResearchBase):
    pass


build_parameters(FamTsmom, "tsmom")
