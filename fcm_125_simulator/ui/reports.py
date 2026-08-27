"""
Formal CFTC Rule 1.25 Investment Policy & Stress Testing Report Generator.
Outputs institutional-grade Markdown and HTML reports for the FCM Investment Committee and NFA/CFTC audit review.
"""

from decimal import Decimal
from datetime import date
from ..core.portfolio import TreasuryPortfolio
from ..rules.compliance import CFTC125ComplianceEngine
from ..analytics.fixed_income import FixedIncomeAnalytics
from ..simulation.scenarios import StressScenarioLibrary
from ..regulatory.cftc_1_32_seg import CFTC132SegregationEngine
from ..regulatory.cftc_1_22_ri import CFTC122ResidualInterestEngine

class GovernanceReportGenerator:
    """
    Produces formal compliance and risk committee memos.
    """

    @staticmethod
    def generate_markdown_report(portfolio: TreasuryPortfolio) -> str:
        as_of = portfolio.as_of_date
        engine = CFTC125ComplianceEngine()
        status, rule_results = engine.evaluate_portfolio(portfolio)
        fi = FixedIncomeAnalytics.calculate_portfolio_metrics(portfolio)
        seg = CFTC132SegregationEngine.generate_daily_statement(portfolio)
        ri = CFTC122ResidualInterestEngine.calculate_residual_interest_target(portfolio)
        scenarios = StressScenarioLibrary.get_all_scenarios(portfolio.customer_segregated_liability)
        scenario_results = [StressScenarioLibrary.run_stress_test(portfolio, sc) for sc in scenarios]

        md = []
        md.append(f"# CFTC § 1.25 Customer Fund Investment & Liquidity Stress Memo")
        md.append(f"**Entity:** Futures Commission Merchant (FCM) Treasury & Risk Desk  ")
        md.append(f"**As of Date:** {as_of.strftime('%B %d, %Y')} | **Statutory Basis:** 17 CFR § 1.25, § 1.32, § 1.22  ")
        md.append(f"**Overall Compliance Status:** `{status.value}`\n")

        md.append("---")
        md.append("## 1. Executive Summary & Key Risk Indicators (KRIs)")
        md.append(f"| Metric | Value | Statutory / Policy Limit | Status |")
        md.append(f"| :--- | :--- | :--- | :--- |")
        md.append(f"| **Customer Segregated Float (Par)** | `${portfolio.customer_segregated_liability:,.2f}` | $100\\%$ Par Liability | — |")
        md.append(f"| **Total Segregated Assets (MTM)** | `${portfolio.total_portfolio_market_value:,.2f}` | ≥ Customer Par | " + ("`SURPLUS`" if portfolio.total_portfolio_market_value >= portfolio.customer_segregated_liability else "`DEFICIT`") + " |")
        md.append(f"| **Annual Net Interest Income (NII)** | `${portfolio.annual_net_interest_income:,.2f}` | {portfolio.weighted_average_yield*100:.2f}% Weighted Yield | — |")
        md.append(f"| **Portfolio WAM** | `{portfolio.weighted_average_maturity_years():.3f} Years` ({portfolio.weighted_average_maturity_days():.1f} d) | `≤ 2.000 Years (24 Mo)` | " + ("`PASS`" if portfolio.weighted_average_maturity_years() <= 2.0 else "`BREACH`") + " |")
        md.append(f"| **Portfolio DV01** | `${fi['total_dv01']:,.2f}` | Max Rate Sensitivity | — |")
        md.append(f"| **Firm Residual Interest Cushion** | `${ri.actual_firm_ri_deposited:,.2f}` | Target: `${ri.targeted_residual_interest:,.2f}` | " + ("`PASS`" if ri.is_adequate else "`BREACH`") + " |\n")

        md.append("---")
        md.append("## 2. CFTC Rule 1.25 Concentration & Tenor Compliance Matrix")
        md.append(f"| Rule Name | Regulatory Citation | Current Exposure | Statutory Cap | Audit Finding |")
        md.append(f"| :--- | :--- | :--- | :--- | :--- |")
        for r in rule_results:
            curr_str = f"{r.current_value*100:.2f}%" if r.unit == "ratio" else (f"{r.current_value:.3f} yrs" if r.unit == "years" else str(r.current_value))
            limit_str = f"{r.limit_value*100:.1f}%" if r.unit == "ratio" else (f"{r.limit_value:.1f} yrs" if r.unit == "years" else str(r.limit_value))
            status_badge = f"`{r.status.value}`"
            md.append(f"| **{r.rule_name}** | `{r.citation}` | `{curr_str}` | `{limit_str}` | {status_badge} {r.message} |")

        md.append("\n---")
        md.append("## 3. CFTC § 1.32 Schedule of Segregation Requirements (Form 1-FR-FCM)")
        md.append(f"```")
        md.append(f"1. Customer Net Ledger & Par Liabilities:                ${seg.line_3_total_segregation_requirement:>14,.2f}")
        md.append(f"2. Cash in Segregated Bank Accounts:                     ${seg.line_4_cash_at_banks:>14,.2f}")
        md.append(f"3. Rule 1.25 Permitted Securities (MTM Value):           ${seg.line_5_securities_market_value:>14,.2f}")
        md.append(f"4. Overnight Reverse Repurchase Agreements:              ${seg.line_6_reverse_repos:>14,.2f}")
        md.append(f"5. Firm Residual Interest Deposited:                     ${portfolio.firm_residual_interest:>14,.2f}")
        md.append(f"------------------------------------------------------------------------")
        md.append(f"Total Funds in Segregated Accounts (Line 8):             ${seg.line_8_total_segregated_funds:>14,.2f}")
        md.append(f"Excess / (Deficiency) in Segregation (Line 9):           ${seg.line_9_excess_or_deficit:>14,.2f}")
        md.append(f"Targeted Residual Interest (CFTC 1.11 / Line 10):        ${seg.line_10_target_residual_interest:>14,.2f}")
        md.append(f"Excess Funds Over Target Residual Interest (Line 11):    ${seg.line_11_excess_over_target_ri:>14,.2f}")
        md.append(f"```\n")

        md.append("---")
        md.append("## 4. Stress Testing & Liquidity Liquidation Post-Mortem")
        md.append(f"| Historical / Tail Scenario | Yield Shift | DCO Margin Call | MTM Loss | Stressed Surplus | Result | Summary |")
        md.append(f"| :--- | :--- | :--- | :--- | :--- | :--- | :--- |")
        for sr in scenario_results:
            tag = f"`{ 'SURVIVED' if sr.fcm_survived_scenario else 'FAILED' }`"
            md.append(f"| **{sr.scenario.name}** | `{sr.scenario.yield_shift_bps:+5.0f} bps` | `${sr.scenario.dco_margin_call_amount/1000000:,.0f}M` | `-${sr.unrealized_mtm_loss:,.2f}` | `${sr.stressed_seg_excess:,.2f}` | {tag} | {sr.post_mortem_summary} |")

        md.append("\n---")
        md.append("## 5. Investment Committee Sign-Off")
        md.append("The Chief Investment Officer (CIO) and Chief Risk Officer (CRO) hereby certify that the above portfolio has been evaluated under 17 CFR § 1.25, § 1.32, and § 1.22 policies.")
        
        return "\n".join(md)
