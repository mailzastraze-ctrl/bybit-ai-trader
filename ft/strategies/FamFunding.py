"""Hyperoptable research strategy for the 'funding_reversal' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamFunding(ResearchBase):
    pass


build_parameters(FamFunding, "funding_reversal")
