"""
Mark-to-Market (MTM) Pricing Engine for CFTC Rule 1.25 investments.
Revalues securities under yield curve shifts, credit spread widening, and liquidation bid-ask spreads.
"""

from decimal import Decimal
from typing import Dict, List, Tuple
from ..core.types import to_decimal, round_money, round_bps, AssetClass
from ..core.instruments import Instrument, Position
from ..core.portfolio import TreasuryPortfolio
from .fixed_income import FixedIncomeAnalytics

class MTMPricingEngine:
    """
    Revalues positions and portfolios under market yield shifts and liquidity haircut shocks.
    """

    @staticmethod
    def price_instrument_with_yield_shift(
        instrument: Instrument,
        as_of_date,
        yield_shift_bps: Decimal,
        credit_spread_shift_bps: Decimal = Decimal("0.0")
    ) -> Decimal:
        """
        Calculates new clean price per $100 par given an annualized yield shift (in basis points).
        Uses exact bond pricing or second-order Taylor expansion (Duration + Convexity).
        """
        # Cash and overnight repo stay at par ($100.00)
        if instrument.years_to_maturity(as_of_date) <= Decimal("0.003") or instrument.asset_class in (
            AssetClass.CASH_CENTRAL_BANK, AssetClass.REVERSE_REPO, AssetClass.MMMF_GOVT, AssetClass.MMMF_PRIME
        ):
            return Decimal("100.00")

        total_shift_bps = yield_shift_bps + credit_spread_shift_bps
        dy = total_shift_bps / Decimal("10000.0") # bps to decimal

        _, mod_dur, conv = FixedIncomeAnalytics.calculate_instrument_duration_convexity(
            instrument, as_of_date
        )

        # Price percentage change = - ModDur * dy + 0.5 * Conv * (dy)^2
        pct_change = (-mod_dur * dy) + (Decimal("0.5") * conv * (dy ** 2))
        new_price = instrument.clean_price * (Decimal("1.0") + pct_change)
        return max(Decimal("0.01"), new_price.quantize(Decimal("0.0001")))

    @staticmethod
    def revalue_portfolio_under_shock(
        portfolio: TreasuryPortfolio,
        yield_shift_bps: Decimal,
        credit_spread_shift_bps: Decimal = Decimal("0.0"),
        apply_bid_ask_haircut: bool = False
    ) -> Tuple[Decimal, Decimal, List[Dict[str, Decimal]]]:
        """
        Revalues entire portfolio under a yield shock.
        Returns:
            (new_total_portfolio_market_value, total_mtm_pnl, position_details)
        """
        new_pos_val_sum = Decimal("0.00")
        pos_details = []

        for p in portfolio.positions:
            new_clean_price = MTMPricingEngine.price_instrument_with_yield_shift(
                p.instrument,
                portfolio.as_of_date,
                yield_shift_bps,
                credit_spread_shift_bps
            )

            # Optional liquidation bid-ask spread deduction
            if apply_bid_ask_haircut:
                spread_pct = p.instrument.bid_ask_spread_bps / Decimal("10000.0")
                effective_price = new_clean_price * (Decimal("1.0") - (spread_pct / Decimal("2.0")))
            else:
                effective_price = new_clean_price

            new_mv = round_money((p.par_amount * effective_price) / Decimal("100.0") + p.accrued_interest)
            pnl = new_mv - p.book_cost
            new_pos_val_sum += new_mv

            pos_details.append({
                "instrument_id": p.instrument.id,
                "name": p.instrument.name,
                "asset_class": p.instrument.asset_class.value,
                "original_price": p.instrument.clean_price,
                "stressed_price": effective_price.quantize(Decimal("0.0001")),
                "original_market_value": p.market_value,
                "stressed_market_value": new_mv,
                "mtm_pnl": pnl
            })

        new_total_portfolio_val = portfolio.cash_at_fed + new_pos_val_sum
        total_pnl = new_total_portfolio_val - portfolio.total_portfolio_market_value

        return new_total_portfolio_val, total_pnl, pos_details
