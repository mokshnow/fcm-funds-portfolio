"""
Fixed Income Quantitative Analytics Engine.
Calculates exact Yield to Maturity, Macaulay Duration, Modified Duration,
Convexity, DV01, and Key Rate Durations for CFTC 1.25 investments.
"""

from decimal import Decimal
import math
from typing import Dict, List, Tuple
from ..core.types import to_decimal, round_money, round_bps
from ..core.instruments import Instrument, Position
from ..core.portfolio import TreasuryPortfolio

class FixedIncomeAnalytics:
    """
    Fixed income analytics for Treasury Bills, Notes, Repos, MMMFs, Agencies, and CP.
    """

    @staticmethod
    def calculate_instrument_duration_convexity(
        instrument: Instrument, 
        as_of_date
    ) -> Tuple[Decimal, Decimal, Decimal]:
        """
        Returns (Macaulay Duration in years, Modified Duration in years, Convexity).
        For overnight repo / cash / MMMFs with floating NAV ~ $1.00: Duration = 0, Convexity = 0.
        """
        years_to_mat = instrument.years_to_maturity(as_of_date)
        ytm = instrument.yield_to_maturity

        # Money market instruments, Cash, Overnight Repo, MMMF: effective duration ~ 0 or reset period
        if years_to_mat <= Decimal("0.003"): # <= 1 day
            return Decimal("0.0"), Decimal("0.0"), Decimal("0.0")

        # Zero-coupon discount instruments (T-Bills, CP, Discount Notes)
        if instrument.coupon_rate == Decimal("0.0"):
            mac_dur = years_to_mat
            mod_dur = mac_dur / (Decimal("1.0") + ytm)
            # Convexity for zero coupon: t*(t+1) / (1+y)^2 roughly ~ t^2 / (1+y)^2
            convexity = (years_to_mat * (years_to_mat + Decimal("1.0"))) / ((Decimal("1.0") + ytm) ** 2)
            return mac_dur, mod_dur, convexity

        # Coupon-bearing Notes / Bonds (semi-annual coupon frequency m=2)
        # Analytical approximation / exact summation
        m = 2
        coupon = instrument.coupon_rate
        # For floating rate notes: duration ~ reset frequency
        if instrument.is_floating:
            reset_years = to_decimal(instrument.reset_frequency_days) / Decimal("365.0")
            mod_dur = reset_years / (Decimal("1.0") + ytm / Decimal(str(m)))
            return reset_years, mod_dur, Decimal("0.0")

        n_periods = max(1, int(float(years_to_mat) * m))
        c_per_period = (coupon / Decimal(str(m))) * Decimal("100.0")
        y_per_period = ytm / Decimal(str(m))
        df = Decimal("1.0") + y_per_period

        pv_cash_flows = Decimal("0.0")
        weighted_time_sum = Decimal("0.0")
        convexity_sum = Decimal("0.0")

        for t in range(1, n_periods + 1):
            cf = c_per_period if t < n_periods else (c_per_period + Decimal("100.0"))
            discount_factor = df ** Decimal(str(t))
            pv = cf / discount_factor
            pv_cash_flows += pv
            t_years = Decimal(str(t)) / Decimal(str(m))
            weighted_time_sum += pv * t_years
            convexity_sum += pv * (t_years * (t_years + Decimal("1.0") / Decimal(str(m))))

        if pv_cash_flows > Decimal("0"):
            mac_dur = weighted_time_sum / pv_cash_flows
            mod_dur = mac_dur / df
            convexity = convexity_sum / (pv_cash_flows * (df ** 2))
        else:
            mac_dur = years_to_mat
            mod_dur = years_to_mat
            convexity = Decimal("0.0")

        return mac_dur, mod_dur, convexity

    @staticmethod
    def calculate_position_dv01(position: Position, as_of_date) -> Decimal:
        """
        DV01 = Dollar Value of a 1 basis point (0.01% = 0.0001) upward parallel yield shift.
        DV01 = Modified Duration * Market Value * 0.0001
        """
        _, mod_dur, _ = FixedIncomeAnalytics.calculate_instrument_duration_convexity(
            position.instrument, as_of_date
        )
        dv01 = mod_dur * position.market_value * Decimal("0.0001")
        return round_money(dv01)

    @staticmethod
    def calculate_portfolio_metrics(portfolio: TreasuryPortfolio) -> Dict[str, Decimal]:
        """
        Calculates aggregate portfolio Modified Duration, Convexity, and DV01.
        """
        tot_val = portfolio.total_portfolio_market_value
        if tot_val == Decimal("0"):
            return {
                "modified_duration": Decimal("0.0"),
                "macaulay_duration": Decimal("0.0"),
                "convexity": Decimal("0.0"),
                "total_dv01": Decimal("0.00"),
                "max_100bps_loss": Decimal("0.00"),
                "max_250bps_loss": Decimal("0.00"),
                "max_500bps_loss": Decimal("0.00")
            }

        weighted_mod_dur = Decimal("0.0")
        weighted_mac_dur = Decimal("0.0")
        weighted_conv = Decimal("0.0")
        total_dv01 = Decimal("0.00")

        for pos in portfolio.positions:
            mac_dur, mod_dur, conv = FixedIncomeAnalytics.calculate_instrument_duration_convexity(
                pos.instrument, portfolio.as_of_date
            )
            weight = pos.market_value / tot_val
            weighted_mac_dur += mac_dur * weight
            weighted_mod_dur += mod_dur * weight
            weighted_conv += conv * weight
            pos_dv01 = mod_dur * pos.market_value * Decimal("0.0001")
            total_dv01 += pos_dv01

        # Estimated paper losses for standard shocks using duration + convexity:
        # Loss = - [ - ModDur * dY + 0.5 * Conv * (dY)^2 ] * PortfolioValue
        def estimate_loss(dy_bps: int) -> Decimal:
            dy = Decimal(str(dy_bps)) / Decimal("10000.0")
            pct_change = (-weighted_mod_dur * dy) + (Decimal("0.5") * weighted_conv * (dy ** 2))
            loss = -(pct_change * tot_val)
            return round_money(max(Decimal("0.00"), loss))

        return {
            "modified_duration": weighted_mod_dur.quantize(Decimal("0.001")),
            "macaulay_duration": weighted_mac_dur.quantize(Decimal("0.001")),
            "convexity": weighted_conv.quantize(Decimal("0.001")),
            "total_dv01": round_money(total_dv01),
            "max_100bps_loss": estimate_loss(100),
            "max_250bps_loss": estimate_loss(250),
            "max_500bps_loss": estimate_loss(500)
        }
