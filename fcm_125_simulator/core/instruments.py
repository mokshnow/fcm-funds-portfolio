"""
Instrument definitions for CFTC Rule 1.25 permitted asset classes.
"""

from decimal import Decimal
from dataclasses import dataclass, field
from typing import Optional
from datetime import date
from .types import AssetClass, CreditRating, LiquidityTier, YieldType, to_decimal, round_money, round_bps

@dataclass
class Instrument:
    id: str
    name: str
    asset_class: AssetClass
    issuer: str
    issuer_family: str
    maturity_date: Optional[date]
    coupon_rate: Decimal = Decimal("0.00")          # e.g. Decimal("0.0425") for 4.250% annual coupon
    credit_rating: CreditRating = CreditRating.AAA  # Informational rating
    credit_rating_informational: str = "AAA"       # e.g. "AAA (Moody's/S&P/Fitch)"
    credit_risk_assessment: str = "Minimal Credit Risk (CFTC § 1.25(b)(1) Internal Due Diligence Passed)"
    liquidity_tier: LiquidityTier = LiquidityTier.TIER_0_INSTANT
    settlement_terms: str = "T+1 Secondary Market DVP / Fedwire" # Documented settlement terms
    cash_conversion_within_1_biz_day: bool = True   # Rule 1.25 1-business-day test
    yield_to_maturity: Decimal = Decimal("0.00")    # Current market yield (e.g. 0.03802 for 3.802%)
    yield_type: YieldType = YieldType.YTM           # Yield calculation methodology
    yield_as_of: str = "2026-08-27 16:00 EDT"       # Exact yield timestamp
    clean_price: Decimal = Decimal("100.00")        # Clean price per $100 par
    bid_ask_spread_bps: Decimal = Decimal("0.0")    # Secondary market liquidation spread
    is_floating: bool = False
    reset_frequency_days: int = 0
    fund_total_aum: Optional[Decimal] = None        # For MMMFs, total external fund size in USD
    cusip: Optional[str] = None                     # Live 9-char CUSIP (None for Cash & Repos)
    internal_id: Optional[str] = None               # Internal Account/Transaction ID for Cash & Repos
    master_agreement_ref: Optional[str] = None      # SIFMA MRA / Tri-Party Agreement Reference
    depository_account_type: Optional[str] = None   # § 1.20 Central Bank vs Commercial Bank Segregated
    rule_125_status: str = "Eligible (§ 1.25(a)(1)(i) Direct U.S. Government Obligation)"
    liquidity_evidence_date: date = field(default_factory=lambda: date(2026, 8, 27))
    offering_doc_reviewed: str = "Passed (Prospectus / Official Statement Reviewed 2026-08-20; Compliant)"
    embedded_derivative_check: str = "Passed (Plain vanilla; no prohibited features under § 1.25(b)(2)(ii))"

    def days_to_maturity(self, as_of_date: date) -> int:
        if self.maturity_date is None or self.asset_class == AssetClass.CASH_CENTRAL_BANK:
            return 0
        delta = (self.maturity_date - as_of_date).days
        return max(0, delta)

    def years_to_maturity(self, as_of_date: date) -> Decimal:
        days = self.days_to_maturity(as_of_date)
        return to_decimal(days) / Decimal("365.0")

    def remaining_tenor_formatted(self, as_of_date: date) -> str:
        if self.maturity_date is None or self.asset_class == AssetClass.CASH_CENTRAL_BANK:
            return "Demand / Same-Day"
        d = self.days_to_maturity(as_of_date)
        if d == 0:
            return "Same-Day (Demand)"
        elif d == 1:
            return "1 day (Overnight)"
        elif d < 365:
            return f"{d} days"
        else:
            yrs = d / 365.0
            return f"{d} days ({yrs:.2f} yrs)"

@dataclass
class Position:
    instrument: Instrument
    par_amount: Decimal           # Face value / Par quantity in USD
    book_cost: Decimal            # Original purchase cost in USD
    accrued_interest: Decimal = Decimal("0.00")

    @property
    def market_value(self) -> Decimal:
        """Market value based on clean price + accrued interest."""
        clean_val = (self.par_amount * self.instrument.clean_price) / Decimal("100.0")
        return round_money(clean_val + self.accrued_interest)

    @property
    def unrealized_pnl(self) -> Decimal:
        return self.market_value - self.book_cost

    @property
    def annual_interest_income(self) -> Decimal:
        """Annual interest income projected from yield on market value."""
        return round_money(self.market_value * self.instrument.yield_to_maturity)

    def wam_contribution_days(self, portfolio_total_mv: Decimal, as_of_date: date) -> Decimal:
        """Days contributed to portfolio weighted average maturity."""
        if portfolio_total_mv == Decimal("0"):
            return Decimal("0.00")
        days = to_decimal(self.instrument.days_to_maturity(as_of_date))
        return (self.market_value / portfolio_total_mv) * days

    def wam_contribution_years(self, portfolio_total_mv: Decimal, as_of_date: date) -> Decimal:
        """Years contributed to portfolio WAM."""
        days_contrib = self.wam_contribution_days(portfolio_total_mv, as_of_date)
        return round_bps(days_contrib / Decimal("365.0"))

    def concentration_usage_pct(self, customer_liability: Decimal) -> Decimal:
        """Percentage of customer segregated liability."""
        if customer_liability == Decimal("0"):
            return Decimal("0.00")
        return round_bps((self.market_value / customer_liability) * Decimal("100.0"))
