"""
CFTC Regulation § 1.32 Daily Segregated Account Calculation & Reporting Schedule.
Generates Form 1-FR-FCM Schedule of Segregation Requirements and Funds in Segregation.
"""

from decimal import Decimal
from dataclasses import dataclass
from typing import Dict, Any, List
from datetime import date
from ..core.types import (
    AssetClass,
    SegregationStatement,
    to_decimal,
    round_money
)
from ..core.portfolio import TreasuryPortfolio

@dataclass
class Form1FRFCMSchedule:
    as_of_date: date
    # Line 1: Net ledger balance (Cash & collateral from customers)
    line_1_customer_ledger_balance: Decimal
    # Line 2: Net unrealized profit / (loss) in open futures contracts
    line_2_customer_unrealized_pnl: Decimal
    # Line 3: Total amount required to be segregated (Customer Net Equity at Par)
    line_3_total_segregation_requirement: Decimal

    # Funds in Segregated Accounts (Rule 1.25 Permitted Investments)
    # Line 4: Cash in segregated bank accounts
    line_4_cash_at_banks: Decimal
    # Line 5: Securities in segregated accounts under Rule 1.25 (at market value)
    line_5_securities_market_value: Decimal
    # Line 6: Reverse repurchase agreements (Rule 1.25(b)(3)(v))
    line_6_reverse_repos: Decimal
    # Line 7: Deposits with DCO clearing organizations
    line_7_clearinghouse_deposits: Decimal
    # Line 8: Total funds in segregation
    line_8_total_segregated_funds: Decimal

    # Line 9: Excess / (Deficiency) in segregation (Line 8 minus Line 3)
    line_9_excess_or_deficit: Decimal
    # Line 10: Firm Residual Interest Target
    line_10_target_residual_interest: Decimal
    # Line 11: Excess funds over targeted residual interest
    line_11_excess_over_target_ri: Decimal

class CFTC132SegregationEngine:
    """
    Computes statutory daily segregation statement under 17 CFR § 1.32.
    """

    @staticmethod
    def generate_daily_statement(
        portfolio: TreasuryPortfolio,
        clearinghouse_deposits: Decimal = Decimal("0.00"),
        customer_unrealized_pnl: Decimal = Decimal("0.00"),
        target_ri_buffer: Decimal = Decimal("15000000.00") # $15M default target
    ) -> Form1FRFCMSchedule:
        """
        Builds the standard Form 1-FR-FCM Daily Statement of Segregation.
        """
        bd = portfolio.asset_class_breakdown()

        cash_at_banks = bd.get(AssetClass.CASH_CENTRAL_BANK, Decimal("0.00"))
        reverse_repos = bd.get(AssetClass.REVERSE_REPO, Decimal("0.00"))
        
        # Securities = Treasuries + Agencies + MMMFs + CDs + CP + Munis
        securities_mv = (
            bd.get(AssetClass.US_TREASURY, Decimal("0.00")) +
            bd.get(AssetClass.US_AGENCY, Decimal("0.00")) +
            bd.get(AssetClass.MMMF_GOVT, Decimal("0.00")) +
            bd.get(AssetClass.MMMF_GOVT_LARGE, Decimal("0.00")) +
            bd.get(AssetClass.MMMF_GOVT_SMALL, Decimal("0.00")) +
            bd.get(AssetClass.MMMF_PRIME, Decimal("0.00")) +
            bd.get(AssetClass.BANK_CD, Decimal("0.00")) +
            bd.get(AssetClass.COMMERCIAL_PAPER, Decimal("0.00")) +
            bd.get(AssetClass.MUNICIPAL, Decimal("0.00"))
        )

        customer_net_equity = portfolio.customer_segregated_liability + customer_unrealized_pnl
        total_funds_in_seg = cash_at_banks + securities_mv + reverse_repos + clearinghouse_deposits

        excess_or_deficit = total_funds_in_seg - customer_net_equity
        excess_over_target = excess_or_deficit - target_ri_buffer

        return Form1FRFCMSchedule(
            as_of_date=portfolio.as_of_date,
            line_1_customer_ledger_balance=portfolio.customer_segregated_liability,
            line_2_customer_unrealized_pnl=customer_unrealized_pnl,
            line_3_total_segregation_requirement=customer_net_equity,
            line_4_cash_at_banks=cash_at_banks,
            line_5_securities_market_value=securities_mv,
            line_6_reverse_repos=reverse_repos,
            line_7_clearinghouse_deposits=clearinghouse_deposits,
            line_8_total_segregated_funds=total_funds_in_seg,
            line_9_excess_or_deficit=excess_or_deficit,
            line_10_target_residual_interest=target_ri_buffer,
            line_11_excess_over_target_ri=excess_over_target
        )
