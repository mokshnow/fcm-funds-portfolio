"""
CFTC Regulation § 1.22 and § 1.11 Targeted Residual Interest (RI) Adequacy Engine.
Calculates the firm's required and target residual interest cushion to protect customer segregated funds from 1.25 MTM losses.
"""

from decimal import Decimal
from dataclasses import dataclass
from typing import Dict, Any
from ..core.types import to_decimal, round_money
from ..core.portfolio import TreasuryPortfolio
from ..analytics.fixed_income import FixedIncomeAnalytics

@dataclass
class ResidualInterestAdequacyReport:
    actual_firm_ri_deposited: Decimal
    regulatory_minimum_ri_required: Decimal # sum of customer under-margin (UM_c)
    market_risk_ri_buffer_99pct: Decimal    # 99% VaR/ES MTM loss on 1.25 portfolio
    operational_liquidity_buffer: Decimal   # Intraday buffer for DCO calls / settlement delays
    targeted_residual_interest: Decimal     # Total target RI under CFTC 1.11 policy
    cushion_above_target: Decimal          # actual - targeted
    is_adequate: bool
    deadline_hour_et: str                   # "6:00 PM Eastern"
    notes: str

class CFTC122ResidualInterestEngine:
    """
    Computes Targeted Residual Interest buffer under 17 CFR § 1.22 & § 1.11.
    """

    @staticmethod
    def calculate_residual_interest_target(
        portfolio: TreasuryPortfolio,
        customer_under_margin_sum: Decimal = Decimal("5000000.00"), # Baseline UM_c
        operational_buffer_pct: Decimal = Decimal("0.02")           # 2% of customer float
    ) -> ResidualInterestAdequacyReport:
        """
        Targeted RI = max(
            Regulatory_UM,
            Regulatory_UM + Q99(MTM Loss over 1-day) + Operational Liquidity Buffer
        )
        """
        metrics = FixedIncomeAnalytics.calculate_portfolio_metrics(portfolio)
        
        # 99% 1-day rate shock for Treasuries ~ 25-35 bps daily move
        # 1-day 99% MTM loss ~ 25 * DV01
        dv01 = metrics["total_dv01"]
        daily_99_loss = round_money(dv01 * Decimal("35.0")) # 35 bps tail shock

        op_buffer = round_money(portfolio.customer_segregated_liability * operational_buffer_pct)

        target_ri = customer_under_margin_sum + daily_99_loss + op_buffer
        actual_ri = portfolio.firm_residual_interest

        cushion = actual_ri - target_ri
        is_adequate = actual_ri >= target_ri

        if is_adequate:
            notes = f"COMPLIANT: Firm maintains ${actual_ri:,.2f} RI, exceeding CFTC 1.11 target of ${target_ri:,.2f} by ${cushion:,.2f}."
        else:
            notes = f"DEFICIENT: Firm RI of ${actual_ri:,.2f} is below CFTC 1.11 Target of ${target_ri:,.2f} by ${abs(cushion):,.2f}. Mandatory top-up required before 6:00 PM ET deadline."

        return ResidualInterestAdequacyReport(
            actual_firm_ri_deposited=actual_ri,
            regulatory_minimum_ri_required=customer_under_margin_sum,
            market_risk_ri_buffer_99pct=daily_99_loss,
            operational_liquidity_buffer=op_buffer,
            targeted_residual_interest=target_ri,
            cushion_above_target=cushion,
            is_adequate=is_adequate,
            deadline_hour_et="6:00 PM Eastern",
            notes=notes
        )
