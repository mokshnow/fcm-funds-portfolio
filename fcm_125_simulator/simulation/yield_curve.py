"""
Yield Curve and Term Structure Generator for CFTC 1.25 Stress Testing.
Supports baseline SOFR/Treasury curves, Nelson-Siegel parametric curves, and curve twists.
"""

from decimal import Decimal
import math
from typing import Dict, List, Tuple
from dataclasses import dataclass
from ..core.types import to_decimal, round_bps

@dataclass
class YieldCurvePoint:
    tenor_name: str
    tenor_years: Decimal
    par_yield: Decimal     # e.g. Decimal("0.0525") for 5.25%

@dataclass
class YieldCurve:
    name: str
    description: str
    points: List[YieldCurvePoint]

    def get_yield_for_tenor(self, years: Decimal) -> Decimal:
        """Linear interpolation of yield for any tenor in years."""
        if not self.points:
            return Decimal("0.0500")
        
        if years <= self.points[0].tenor_years:
            return self.points[0].par_yield
        if years >= self.points[-1].tenor_years:
            return self.points[-1].par_yield

        for i in range(len(self.points) - 1):
            p1 = self.points[i]
            p2 = self.points[i + 1]
            if p1.tenor_years <= years <= p2.tenor_years:
                span = p2.tenor_years - p1.tenor_years
                weight = (years - p1.tenor_years) / span
                y = p1.par_yield + weight * (p2.par_yield - p1.par_yield)
                return round_bps(y)
        
        return self.points[-1].par_yield

class YieldCurveEngine:
    """
    Builds baseline and stressed term structures.
    """

    @staticmethod
    def get_baseline_curve() -> YieldCurve:
        """Standard August 2026 US Treasury curve (~3.64% to 4.38%)."""
        return YieldCurve(
            name="Baseline US Treasury Curve (August 2026)",
            description="Active SOFR / Treasury benchmark yield curve",
            points=[
                YieldCurvePoint("1M (4W)", Decimal("0.08"), Decimal("0.03701")),
                YieldCurvePoint("3M (13W)", Decimal("0.25"), Decimal("0.03802")),
                YieldCurvePoint("6M (26W)", Decimal("0.50"), Decimal("0.03907")),
                YieldCurvePoint("1Y (52W)", Decimal("1.00"), Decimal("0.04054")),
                YieldCurvePoint("2Y Note", Decimal("2.00"), Decimal("0.04250")),
                YieldCurvePoint("3Y Note", Decimal("3.00"), Decimal("0.04250")),
                YieldCurvePoint("5Y Note", Decimal("5.00"), Decimal("0.04375")),
            ]
        )

    @staticmethod
    def apply_parallel_shock(base_curve: YieldCurve, shift_bps: Decimal) -> YieldCurve:
        shift_dec = shift_bps / Decimal("10000.0")
        new_points = [
            YieldCurvePoint(
                p.tenor_name,
                p.tenor_years,
                max(Decimal("0.0001"), round_bps(p.par_yield + shift_dec))
            )
            for p in base_curve.points
        ]
        sign = "+" if shift_bps >= 0 else ""
        return YieldCurve(
            name=f"Parallel Shock ({sign}{shift_bps} bps)",
            description=f"Parallel shift of {sign}{shift_bps} bps across all tenors",
            points=new_points
        )

    @staticmethod
    def apply_bear_flattening(base_curve: YieldCurve, short_shift_bps: Decimal = Decimal("250"), long_shift_bps: Decimal = Decimal("50")) -> YieldCurve:
        """Short rates jump sharply while long rates move moderately (Inversion / Bear Flattening)."""
        new_points = []
        for p in base_curve.points:
            # Interpolate shift: 1M gets short_shift, 5Y gets long_shift
            w = min(Decimal("1.0"), p.tenor_years / Decimal("5.0"))
            shift_bps = short_shift_bps - w * (short_shift_bps - long_shift_bps)
            shift_dec = shift_bps / Decimal("10000.0")
            new_points.append(
                YieldCurvePoint(
                    p.tenor_name,
                    p.tenor_years,
                    max(Decimal("0.0001"), round_bps(p.par_yield + shift_dec))
                )
            )
        return YieldCurve(
            name="Bear Flattening / Severe Inversion",
            description="Aggressive short-rate hikes with yield curve inversion",
            points=new_points
        )

    @staticmethod
    def apply_bull_steepening(base_curve: YieldCurve, short_cut_bps: Decimal = Decimal("200"), long_cut_bps: Decimal = Decimal("25")) -> YieldCurve:
        """Emergency Fed rate cuts: front end drops by 200 bps, long end drops by only 25 bps."""
        new_points = []
        for p in base_curve.points:
            w = min(Decimal("1.0"), p.tenor_years / Decimal("5.0"))
            cut_bps = short_cut_bps - w * (short_cut_bps - long_cut_bps)
            cut_dec = cut_bps / Decimal("10000.0")
            new_points.append(
                YieldCurvePoint(
                    p.tenor_name,
                    p.tenor_years,
                    max(Decimal("0.0001"), round_bps(p.par_yield - cut_dec))
                )
            )
        return YieldCurve(
            name="Bull Steepening (Fed Emergency Easing)",
            description="Front-end rates plunge during financial liquidity easing",
            points=new_points
        )
