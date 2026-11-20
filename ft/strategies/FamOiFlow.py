"""Hyperoptable research strategy for the 'oi_flow' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamOiFlow(ResearchBase):
    pass


build_parameters(FamOiFlow, "oi_flow")
