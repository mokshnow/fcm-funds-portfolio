"""
Portfolio state management and aggregation for CFTC Rule 1.25 investments.
"""

from decimal import Decimal
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import date
from .types import AssetClass, LiquidityTier, to_decimal, round_money, round_bps
from .instruments import Position, Instrument

@dataclass
class TreasuryPortfolio:
    as_of_date: date
    customer_segregated_liability: Decimal  # Customer float owed at 100% par
    firm_residual_interest: Decimal         # FCM proprietary capital buffer
    cash_at_fed: Decimal                    # Pure T+0 cash at Federal Reserve Bank
    positions: List[Position] = field(default_factory=list)

    @property
    def total_invested_market_value(self) -> Decimal:
        return sum((p.market_value for p in self.positions), Decimal("0.00"))

    @property
    def total_portfolio_market_value(self) -> Decimal:
        """Total segregated assets (investments at MTM + cash at central bank)."""
        return self.cash_at_fed + self.total_invested_market_value

    @property
    def total_unrealized_pnl(self) -> Decimal:
        return sum((p.unrealized_pnl for p in self.positions), Decimal("0.00"))

    @property
    def annual_net_interest_income(self) -> Decimal:
        """Annual gross interest income in USD."""
        # Cash at Fed earns Fed Funds / IORB rate (3.80%)
        fed_funds_rate = Decimal("0.0380")
        cash_nii = self.cash_at_fed * fed_funds_rate
        pos_nii = sum((p.annual_interest_income for p in self.positions), Decimal("0.00"))
        return round_money(cash_nii + pos_nii)

    @property
    def weighted_average_yield(self) -> Decimal:
        """Portfolio weighted average yield."""
        tot_val = self.total_portfolio_market_value
        if tot_val == Decimal("0"):
            return Decimal("0")
        return round_bps(self.annual_net_interest_income / tot_val)

    def weighted_average_maturity_days(self) -> Decimal:
        """
        Dollar-weighted average maturity in days under CFTC § 1.25(b)(5).
        Cash is treated as 0 days.
        """
        tot_val = self.total_portfolio_market_value
        if tot_val == Decimal("0"):
            return Decimal("0")
        
        weighted_sum = Decimal("0")
        for p in self.positions:
            days = to_decimal(p.instrument.days_to_maturity(self.as_of_date))
            weighted_sum += p.market_value * days
        
        return weighted_sum / tot_val

    def weighted_average_maturity_years(self) -> Decimal:
        """WAM in years (CFTC § 1.25 limit is 2.0 years / 24 months)."""
        days = self.weighted_average_maturity_days()
        return (days / Decimal("365.0")).quantize(Decimal("0.001"))

    def asset_class_breakdown(self) -> Dict[AssetClass, Decimal]:
        """Returns market value per asset class."""
        breakdown = {ac: Decimal("0.00") for ac in AssetClass}
        breakdown[AssetClass.CASH_CENTRAL_BANK] = self.cash_at_fed
        for p in self.positions:
            breakdown[p.instrument.asset_class] += p.market_value
        return breakdown

    def asset_class_percentages(self) -> Dict[AssetClass, Decimal]:
        """Returns percentage of total portfolio for each asset class."""
        tot_val = self.total_portfolio_market_value
        if tot_val == Decimal("0"):
            return {ac: Decimal("0") for ac in AssetClass}
        bd = self.asset_class_breakdown()
        return {ac: round_bps(val / tot_val) for ac, val in bd.items()}

    def issuer_breakdown(self) -> Dict[str, Decimal]:
        """Returns market value per issuer."""
        issuers: Dict[str, Decimal] = {}
        if self.cash_at_fed > Decimal("0"):
            issuers["FEDERAL_RESERVE"] = self.cash_at_fed
        for p in self.positions:
            iss = p.instrument.issuer
            issuers[iss] = issuers.get(iss, Decimal("0.00")) + p.market_value
        return issuers

    def issuer_percentages(self) -> Dict[str, Decimal]:
        tot_val = self.total_portfolio_market_value
        if tot_val == Decimal("0"):
            return {}
        bd = self.issuer_breakdown()
        return {iss: round_bps(val / tot_val) for iss, val in bd.items()}

    def issuer_family_breakdown(self) -> Dict[str, Decimal]:
        """Returns market value per issuer family (e.g. fund families)."""
        families: Dict[str, Decimal] = {}
        if self.cash_at_fed > Decimal("0"):
            families["FEDERAL_RESERVE"] = self.cash_at_fed
        for p in self.positions:
            fam = p.instrument.issuer_family
            families[fam] = families.get(fam, Decimal("0.00")) + p.market_value
        return families

    def liquidity_tier_breakdown(self) -> Dict[LiquidityTier, Decimal]:
        """Returns market value per liquidity tier."""
        tiers = {lt: Decimal("0.00") for lt in LiquidityTier}
        tiers[LiquidityTier.TIER_0_INSTANT] = self.cash_at_fed
        for p in self.positions:
            tiers[p.instrument.liquidity_tier] += p.market_value
        return tiers

    def add_position(self, pos: Position):
        self.positions.append(pos)
