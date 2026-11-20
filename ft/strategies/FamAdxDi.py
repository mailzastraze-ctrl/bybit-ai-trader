"""Hyperoptable research strategy for the 'adx_di' family (logic in aitrader.families)."""

from aitrader.ftbase import ResearchBase, build_parameters


class FamAdxDi(ResearchBase):
    pass


build_parameters(FamAdxDi, "adx_di")
