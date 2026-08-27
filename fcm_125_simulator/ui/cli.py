"""
Command Line Interface (CLI) for CFTC Rule 1.25 Customer Fund Simulator.
"""

import sys
import argparse
from decimal import Decimal
from datetime import date

from ..core.types import AssetClass, ComplianceStatus, to_decimal
from ..core.portfolio import TreasuryPortfolio
from ..core.presets import PortfolioPresets, get_standard_universe
from ..rules.compliance import CFTC125ComplianceEngine
from ..analytics.fixed_income import FixedIncomeAnalytics
from ..analytics.mtm_pricing import MTMPricingEngine
from ..analytics.optimizer import TreasuryOptimizer
from ..simulation.scenarios import StressScenarioLibrary
from ..simulation.liquidity_stress import LiquidityStressEngine
from ..regulatory.cftc_1_32_seg import CFTC132SegregationEngine
from ..regulatory.cftc_1_22_ri import CFTC122ResidualInterestEngine
from .server import run_server

def print_banner():
    print("=" * 80)
    print("  CFTC § 1.25 // FCM CUSTOMER FUND INVESTING & LIQUIDITY SIMULATOR")
    print("  Regulatory Capital & Treasury Management System | 17 CFR § 1.25 / 1.32 / 1.22")
    print("=" * 80)

def display_portfolio_summary(portfolio: TreasuryPortfolio):
    as_of = portfolio.as_of_date
    engine = CFTC125ComplianceEngine()
    status, rules = engine.evaluate_portfolio(portfolio)
    fi = FixedIncomeAnalytics.calculate_portfolio_metrics(portfolio)
    seg = CFTC132SegregationEngine.generate_daily_statement(portfolio)
    ri = CFTC122ResidualInterestEngine.calculate_residual_interest_target(portfolio)

    print("\n--- [1] EXECUTIVE PORTFOLIO SUMMARY ---")
    print(f"As of Date:                  {as_of}")
    print(f"Customer Seg Par Liability:  ${portfolio.customer_segregated_liability:,.2f}")
    print(f"Total Invested Market Value: ${portfolio.total_invested_market_value:,.2f}")
    print(f"Cash on Deposit at Fed:      ${portfolio.cash_at_fed:,.2f}")
    print(f"Total Segregated Assets:     ${portfolio.total_portfolio_market_value:,.2f}")
    print(f"Annual Net Interest Income:  ${portfolio.annual_net_interest_income:,.2f} ({portfolio.weighted_average_yield*100:.2f}% Yield)")
    print(f"Portfolio WAM:               {portfolio.weighted_average_maturity_years():.3f} Years ({portfolio.weighted_average_maturity_days():.1f} Days) [Limit: <= 2.0 Yrs]")
    print(f"Portfolio DV01:              ${fi['total_dv01']:,.2f} per 1 bp rate shift")
    print(f"CFTC 1.25 Compliance:        [{status.value}]")

    print("\n--- [2] CFTC § 1.25 ASSET ALLOCATION & CAPS ---")
    bd = portfolio.asset_class_percentages()
    bd_val = portfolio.asset_class_breakdown()
    for ac in AssetClass:
        val = bd_val.get(ac, Decimal("0"))
        if val > Decimal("0"):
            pct = bd.get(ac, Decimal("0")) * 100
            cap = "100%" if ac in (AssetClass.US_TREASURY, AssetClass.CASH_CENTRAL_BANK, AssetClass.REVERSE_REPO) else (
                "50%" if "MMMF" in ac.value else (
                    "25%" if ac in (AssetClass.US_AGENCY, AssetClass.BANK_CD) else "10%"
                )
            )
            print(f"  {ac.value:<22} : ${val:>14,.2f}  ({pct:>5.1f}% / Cap: {cap:>4})")

    print("\n--- [3] CFTC § 1.32 SEGREGATION STATEMENT (FORM 1-FR-FCM) ---")
    print(f"  Line 1: Customer Net Par Liability:      ${seg.line_3_total_segregation_requirement:>14,.2f}")
    print(f"  Line 4: Cash in Segregated Bank Accounts: ${seg.line_4_cash_at_banks:>14,.2f}")
    print(f"  Line 5: Permitted Securities (MTM Value): ${seg.line_5_securities_market_value:>14,.2f}")
    print(f"  Line 6: Reverse Repurchase Agreements:    ${seg.line_6_reverse_repos:>14,.2f}")
    print(f"  Line 8: Total Funds in Segregation:       ${seg.line_8_total_segregated_funds:>14,.2f}")
    print(f"  Line 9: Excess Segregated Funds:          ${seg.line_9_excess_or_deficit:>14,.2f}")
    print(f"  Line 10: Target Residual Interest:        ${seg.line_10_target_residual_interest:>14,.2f}")
    print(f"  Line 11: Excess Over Target RI:           ${seg.line_11_excess_over_target_ri:>14,.2f}")

    print("\n--- [4] CRISIS SCENARIOS & STRESS TESTS ---")
    scenarios = StressScenarioLibrary.get_all_scenarios(portfolio.customer_segregated_liability)
    for sc in scenarios:
        res = StressScenarioLibrary.run_stress_test(portfolio, sc)
        status_tag = "PASSED" if res.fcm_survived_scenario else "FAILED"
        print(f"  [{status_tag}] {sc.name:<45}")
        print(f"         Yield: {sc.yield_shift_bps:+5.0f} bps | Margin Call: ${sc.dco_margin_call_amount/1000000:,.0f}M | MTM Loss: -${res.unrealized_mtm_loss:,.2f} ({res.mtm_loss_pct:.1f}%)")
        print(f"         Finding: {res.post_mortem_summary}")

def main():
    parser = argparse.ArgumentParser(description="CFTC Rule 1.25 Customer Fund Simulator CLI")
    parser.add_argument("--preset", choices=["balanced", "aggressive", "optimized", "breached"], default="balanced")
    parser.add_argument("--float", type=float, default=500000000.0, help="Customer segregated float in USD")
    parser.add_argument("--serve", action="store_true", help="Launch interactive macro-density web dashboard")
    parser.add_argument("--port", type=int, default=8080, help="Port for web dashboard")
    parser.add_argument("--stress-yield", type=float, default=0.0, help="Shift yield curve by X bps")
    parser.add_argument("--margin-call", type=float, default=50000000.0, help="Test intraday DCO margin call")

    args = parser.parse_args()
    as_of = date.today()
    tot_float = to_decimal(args.float)

    if args.preset == "balanced":
        portfolio = PortfolioPresets.get_balanced_institutional_fcm(as_of, tot_float)
    elif args.preset == "aggressive":
        portfolio = PortfolioPresets.get_aggressive_yield_chaser(as_of, tot_float)
    elif args.preset == "breached":
        portfolio = PortfolioPresets.get_breached_mf_global_style(as_of, tot_float)
    elif args.preset == "optimized":
        universe = get_standard_universe(as_of)
        portfolio = TreasuryOptimizer.optimize_allocation(as_of, tot_float, universe)

    print_banner()
    display_portfolio_summary(portfolio)

    if args.serve:
        print(f"\nStarting Web Server on http://127.0.0.1:{args.port} ...")
        from .server import DashboardRequestHandler
        DashboardRequestHandler.current_portfolio = portfolio
        run_server(args.port)

if __name__ == "__main__":
    main()
