"""
Local HTTP Server & REST API for the CFTC Rule 1.25 Macro-Density Web Dashboard.
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import os
import sys
from decimal import Decimal
from datetime import date
from typing import Dict, Any, Optional, List

from ..core.types import AssetClass, ComplianceStatus, LiquidityTier, to_decimal, round_bps, round_money
from ..core.portfolio import TreasuryPortfolio
from ..core.presets import PortfolioPresets, get_standard_universe
from ..rules.compliance import CFTC125ComplianceEngine
from ..analytics.fixed_income import FixedIncomeAnalytics
from ..analytics.mtm_pricing import MTMPricingEngine
from ..analytics.optimizer import TreasuryOptimizer
from ..simulation.scenarios import StressScenarioLibrary
from ..simulation.liquidity_stress import LiquidityStressEngine
from ..simulation.yield_curve import YieldCurveEngine
from ..regulatory.cftc_1_32_seg import CFTC132SegregationEngine
from ..regulatory.cftc_1_22_ri import CFTC122ResidualInterestEngine

# Custom JSON encoder for Decimal, Date, Enum
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, date):
            return obj.isoformat()
        if hasattr(obj, "value"):
            return obj.value
        return super().default(obj)

def build_full_dashboard_payload(
    portfolio: TreasuryPortfolio,
    yield_shift_bps: float = 0.0,
    margin_call_amount: float = 50000000.0,
    credit_facility_allowed: bool = False
) -> Dict[str, Any]:
    as_of = portfolio.as_of_date
    dec_yield_shift = to_decimal(yield_shift_bps)
    dec_margin_call = to_decimal(margin_call_amount)

    # 1. Compliance Audit
    compliance_engine = CFTC125ComplianceEngine()
    overall_status, rule_results = compliance_engine.evaluate_portfolio(portfolio)

    # 2. Fixed Income Risk Metrics
    fi_metrics = FixedIncomeAnalytics.calculate_portfolio_metrics(portfolio)

    # 3. MTM Stress Revaluation
    stressed_mv, mtm_pnl, pos_details = MTMPricingEngine.revalue_portfolio_under_shock(
        portfolio=portfolio,
        yield_shift_bps=dec_yield_shift,
        credit_spread_shift_bps=Decimal("0.0"),
        apply_bid_ask_haircut=True
    )

    # 4. Intraday DCO Margin Call Liquidity Waterfall
    liq_result = LiquidityStressEngine.simulate_dco_margin_call(
        portfolio=portfolio,
        margin_call_amount=dec_margin_call,
        allow_t1_credit_facility=credit_facility_allowed
    )

    # 5. CFTC 1.32 Segregation Statement
    seg_statement = CFTC132SegregationEngine.generate_daily_statement(portfolio)

    # 6. CFTC 1.22 Residual Interest Adequacy
    ri_report = CFTC122ResidualInterestEngine.calculate_residual_interest_target(portfolio)

    # 7. Stress Scenario Matrix
    scenarios = StressScenarioLibrary.get_all_scenarios(portfolio.customer_segregated_liability)
    scenario_results = [
        StressScenarioLibrary.run_stress_test(portfolio, sc, allow_t1_credit_facility=credit_facility_allowed)
        for sc in scenarios
    ]

    # 8. Asset Class & Liquidity Tier Breakdowns
    bd_asset = portfolio.asset_class_percentages()
    bd_liq = portfolio.liquidity_tier_breakdown()
    tot_val = portfolio.total_portfolio_market_value

    asset_allocations = [
        {
            "asset_class": ac.value,
            "name": ac.value.replace("_", " ").title(),
            "market_value": float(portfolio.asset_class_breakdown().get(ac, Decimal("0"))),
            "percentage": float(bd_asset.get(ac, Decimal("0")) * 100),
            "cap_percentage": 100.0 if ac in (AssetClass.US_TREASURY, AssetClass.CASH_CENTRAL_BANK, AssetClass.REVERSE_REPO) else (
                50.0 if "MMMF" in ac.value or ac == AssetClass.US_AGENCY else 10.0
            )
        }
        for ac in AssetClass
        if portfolio.asset_class_breakdown().get(ac, Decimal("0")) > Decimal("0") or ac in (AssetClass.US_TREASURY, AssetClass.MMMF_GOVT, AssetClass.US_AGENCY)
    ]

    return {
        "as_of_date": as_of.isoformat(),
        "total_customer_float": float(portfolio.customer_segregated_liability),
        "total_portfolio_market_value": float(portfolio.total_portfolio_market_value),
        "firm_residual_interest": float(portfolio.firm_residual_interest),
        "annual_nii": float(portfolio.annual_net_interest_income),
        "portfolio_yield_pct": float(portfolio.weighted_average_yield * 100),
        "wam_years": float(portfolio.weighted_average_maturity_years()),
        "wam_days": float(portfolio.weighted_average_maturity_days()),
        "compliance_status": overall_status.value,
        "fixed_income": {
            "modified_duration": float(fi_metrics["modified_duration"]),
            "macaulay_duration": float(fi_metrics["macaulay_duration"]),
            "convexity": float(fi_metrics["convexity"]),
            "dv01": float(fi_metrics["total_dv01"]),
            "loss_100bps": float(fi_metrics["max_100bps_loss"]),
            "loss_250bps": float(fi_metrics["max_250bps_loss"]),
            "loss_500bps": float(fi_metrics["max_500bps_loss"])
        },
        "stress_interactive": {
            "yield_shift_bps": float(dec_yield_shift),
            "stressed_market_value": float(stressed_mv),
            "mtm_pnl": float(mtm_pnl),
            "mtm_loss_pct": float((abs(mtm_pnl) / tot_val * 100) if tot_val > 0 else 0.0),
            "new_seg_excess": float((stressed_mv + portfolio.firm_residual_interest) - portfolio.customer_segregated_liability),
            "positions": pos_details
        },
        "liquidity_waterfall": {
            "call_amount": float(liq_result.call_amount),
            "funded_t0": float(liq_result.funded_amount_t0),
            "funded_t1": float(liq_result.funded_amount_t1),
            "shortfall_t0": float(liq_result.shortfall_amount_t0),
            "total_liquidation_costs": float(liq_result.total_liquidation_costs),
            "is_fully_funded": liq_result.is_fully_funded_t0,
            "is_default": liq_result.is_settlement_default,
            "steps": [
                {
                    "step_number": s.step_number,
                    "source_name": s.source_name,
                    "asset_class": s.asset_class,
                    "amount_drawn": float(s.amount_drawn),
                    "liquidation_cost": float(s.liquidation_cost),
                    "settlement_horizon": s.settlement_horizon,
                    "is_immediate_t0": s.is_immediate_t0,
                    "notes": s.notes
                }
                for s in liq_result.steps
            ]
        },
        "rules": [
            {
                "rule_name": r.rule_name,
                "citation": r.citation,
                "status": r.status.value,
                "current_value": float(r.current_value),
                "limit_value": float(r.limit_value),
                "unit": r.unit,
                "message": r.message
            }
            for r in rule_results
        ],
        "segregation_statement": {
            "customer_net_equity_par": float(seg_statement.line_3_total_segregation_requirement),
            "cash_at_banks": float(seg_statement.line_4_cash_at_banks),
            "securities_mv": float(seg_statement.line_5_securities_market_value),
            "reverse_repos": float(seg_statement.line_6_reverse_repos),
            "total_segregated_funds": float(seg_statement.line_8_total_segregated_funds),
            "excess_or_deficit": float(seg_statement.line_9_excess_or_deficit),
            "target_residual_interest": float(seg_statement.line_10_target_residual_interest),
            "excess_over_target": float(seg_statement.line_11_excess_over_target_ri)
        },
        "residual_interest_report": {
            "actual_firm_ri": float(ri_report.actual_firm_ri_deposited),
            "target_ri": float(ri_report.targeted_residual_interest),
            "cushion": float(ri_report.cushion_above_target),
            "is_adequate": ri_report.is_adequate,
            "notes": ri_report.notes
        },
        "scenario_matrix": [
            {
                "id": sr.scenario.id,
                "name": sr.scenario.name,
                "description": sr.scenario.description,
                "yield_shift_bps": float(sr.scenario.yield_shift_bps),
                "margin_call_amount": float(sr.scenario.dco_margin_call_amount),
                "unrealized_mtm_loss": float(sr.unrealized_mtm_loss),
                "mtm_loss_pct": float(sr.mtm_loss_pct),
                "is_seg_deficit": sr.is_segregation_deficit,
                "stressed_seg_excess": float(sr.stressed_seg_excess),
                "survived": sr.fcm_survived_scenario,
                "summary": sr.post_mortem_summary
            }
            for sr in scenario_results
        ],
        "asset_allocations": asset_allocations,
        "positions_table": (
            [
                {
                    "id": "CASH-FED-RESERVE",
                    "name": "Federal Reserve Bank Segregated Cash Deposit",
                    "asset_class": AssetClass.CASH_CENTRAL_BANK.value,
                    "issuer": "FEDERAL_RESERVE",
                    "issuer_family": "FEDERAL_RESERVE",
                    "par_amount": float(portfolio.cash_at_fed),
                    "market_value": float(portfolio.cash_at_fed),
                    "customer_amount": float(max(Decimal("0.00"), portfolio.cash_at_fed - portfolio.firm_residual_interest)),
                    "firm_ri_amount": float(portfolio.firm_residual_interest),
                    "coupon_rate_pct": 0.0,
                    "yield_pct": 3.80,
                    "yield_type": "FED_IORB",
                    "yield_type_label": "Federal Reserve IORB Rate",
                    "yield_as_of": "2026-08-27 16:00 EDT",
                    "price": 100.0,
                    "maturity_date": "Demand / N/A",
                    "days_to_maturity": 0,
                    "remaining_tenor_formatted": "Demand / Same-Day",
                    "liquidity_tier": LiquidityTier.TIER_0_INSTANT.value,
                    "liq_tier": "T0_CASH",
                    "liq_label": "T+0 Instant Wire",
                    "settlement_terms": "Immediate Fedwire Real-Time Gross Settlement (RTGS Intraday Availability)",
                    "cash_conversion_within_1_biz_day": True,
                    "statutory_cap_pct": 100.0,
                    "statutory_cap_label": "",
                    "issuer_cap": 100.0,
                    "issuer_cap_label": "",
                    "cusip": None,
                    "internal_id": "FED-MA-102948-NY",
                    "master_agreement_ref": None,
                    "depository_account_type": "17 CFR § 1.20 Federal Reserve Master Account",
                    "credit_rating": "AAA",
                    "credit_rating_informational": "AAA (Informational Only)",
                    "credit_risk_assessment": "Minimal Credit Risk (U.S. Central Bank Reserve Balance § 1.20)",
                    "rule_125_status": "Segregated Depository Cash (§ 1.20 / Central Bank)",
                    "liquidity_evidence_date": "2026-08-27",
                    "offering_doc_reviewed": "Passed (Federal Reserve Operating Circular 1 & 4 on file)",
                    "embedded_derivative_check": "Passed (Pure central bank reserve deposit; no derivatives)",
                    "annual_nii": float(portfolio.cash_at_fed * Decimal("0.0380")),
                    "wam_contribution_days": 0.0,
                    "wam_contribution_years": 0.0,
                    "concentration_usage_pct": float(round_bps(portfolio.cash_at_fed / portfolio.customer_segregated_liability * Decimal("100.0"))) if portfolio.customer_segregated_liability > 0 else 0.0
                }
            ] if portfolio.cash_at_fed > Decimal("0") else []
        ) + [
            {
                "id": p.instrument.id,
                "name": p.instrument.name,
                "asset_class": p.instrument.asset_class.value,
                "issuer": p.instrument.issuer,
                "issuer_family": p.instrument.issuer_family,
                "par_amount": float(p.par_amount),
                "market_value": float(p.market_value),
                "coupon_rate_pct": float(p.instrument.coupon_rate * 100),
                "yield_pct": float(p.instrument.yield_to_maturity * 100),
                "yield_type": p.instrument.yield_type.value,
                "yield_type_label": (
                    "Auction Investment Rate" if p.instrument.yield_type.value == "AUCTION_INVESTMENT_RATE" else (
                        "Yield to Maturity (YTM)" if p.instrument.yield_type.value == "YTM" else (
                            "Index Effective Rate" if p.instrument.yield_type.value == "INDEX_EFFECTIVE" else (
                                "7-Day SEC Current Yield" if p.instrument.yield_type.value == "SEC_7DAY" else (
                                    "Overnight Repo Rate" if p.instrument.yield_type.value == "REPO_RATE" else (
                                        "Federal Reserve IORB Rate" if p.instrument.yield_type.value == "FED_IORB" else "Contractual Custody Rate"
                                    )
                                )
                            )
                        )
                    )
                ),
                "yield_as_of": p.instrument.yield_as_of,
                "price": float(p.instrument.clean_price),
                "maturity_date": p.instrument.maturity_date.isoformat() if p.instrument.maturity_date else "Demand / N/A",
                "days_to_maturity": p.instrument.days_to_maturity(as_of),
                "remaining_tenor_formatted": p.instrument.remaining_tenor_formatted(as_of),
                "liquidity_tier": p.instrument.liquidity_tier.value,
                "liq_tier": "T0_CASH" if p.instrument.asset_class in (AssetClass.CASH_CENTRAL_BANK, AssetClass.REVERSE_REPO) else (
                    "T0_BILLS" if p.instrument.asset_class == AssetClass.US_TREASURY else (
                        "T1_MMMF" if "MMMF" in p.instrument.asset_class.value else "T2_TERM"
                    )
                ),
                "liq_label": "T+0 Instant Wire" if p.instrument.asset_class in (AssetClass.CASH_CENTRAL_BANK, AssetClass.REVERSE_REPO) else (
                    "T+0 Same-Day" if p.instrument.asset_class == AssetClass.US_TREASURY else (
                        "T+1 Delay Risk" if "MMMF" in p.instrument.asset_class.value else "Term Paper"
                    )
                ),
                "settlement_terms": p.instrument.settlement_terms,
                "cash_conversion_within_1_biz_day": p.instrument.cash_conversion_within_1_biz_day,
                "statutory_cap_pct": 100.0 if p.instrument.asset_class in (AssetClass.US_TREASURY, AssetClass.CASH_CENTRAL_BANK, AssetClass.REVERSE_REPO) else (
                    50.0 if p.instrument.asset_class in (AssetClass.US_AGENCY, AssetClass.MMMF_GOVT_LARGE, AssetClass.MMMF_GOVT) else 10.0
                ),
                "statutory_cap_label": "" if p.instrument.asset_class in (
                    AssetClass.US_TREASURY, AssetClass.CASH_CENTRAL_BANK, AssetClass.REVERSE_REPO,
                    AssetClass.US_AGENCY, AssetClass.MMMF_GOVT_LARGE, AssetClass.MMMF_GOVT,
                    AssetClass.MMMF_GOVT_SMALL, AssetClass.MUNICIPAL,
                ) else "",
                "issuer_cap": 100.0 if p.instrument.asset_class in (AssetClass.US_TREASURY, AssetClass.CASH_CENTRAL_BANK) else (
                    25.0 if p.instrument.asset_class in (AssetClass.US_AGENCY, AssetClass.REVERSE_REPO) else (
                        10.0 if "MMMF" in p.instrument.asset_class.value else 5.0
                    )
                ),
                "issuer_cap_label": "" if p.instrument.asset_class in (AssetClass.US_TREASURY, AssetClass.CASH_CENTRAL_BANK, AssetClass.MUNICIPAL) else (
                    "25% per issuer" if p.instrument.asset_class == AssetClass.US_AGENCY else (
                        "25% per counterparty group" if p.instrument.asset_class == AssetClass.REVERSE_REPO else (
                            "10% per fund; 25% per family" if "MMMF" in p.instrument.asset_class.value else "5% per issuer"
                        )
                    )
                ),
                "cusip": p.instrument.cusip,
                "internal_id": p.instrument.internal_id,
                "master_agreement_ref": p.instrument.master_agreement_ref,
                "depository_account_type": p.instrument.depository_account_type,
                "credit_rating": p.instrument.credit_rating.value,
                "credit_rating_informational": p.instrument.credit_rating_informational,
                "credit_risk_assessment": p.instrument.credit_risk_assessment,
                "rule_125_status": p.instrument.rule_125_status,
                "liquidity_evidence_date": p.instrument.liquidity_evidence_date.isoformat(),
                "offering_doc_reviewed": p.instrument.offering_doc_reviewed,
                "embedded_derivative_check": p.instrument.embedded_derivative_check,
                "annual_nii": float(p.annual_interest_income),
                "wam_contribution_days": float(p.wam_contribution_days(portfolio.total_portfolio_market_value, as_of)),
                "wam_contribution_years": float(p.wam_contribution_years(portfolio.total_portfolio_market_value, as_of)),
                "concentration_usage_pct": float(p.concentration_usage_pct(portfolio.customer_segregated_liability))
            }
            for p in portfolio.positions
        ],
        "allowed_universe": [
            {
                "id": inst.id,
                "name": inst.name,
                "asset_class": inst.asset_class.value,
                "category_name": (
                    "U.S. Direct Treasury" if inst.asset_class == AssetClass.US_TREASURY else (
                        "Segregated Cash Deposit" if inst.asset_class == AssetClass.CASH_CENTRAL_BANK else (
                            "Reverse Repurchase Agreement" if inst.asset_class == AssetClass.REVERSE_REPO else (
                                "Large Govt MMF / ETF" if inst.asset_class in (AssetClass.MMMF_GOVT_LARGE, AssetClass.MMMF_GOVT) else (
                                    "Smaller Govt MMF (< $1B)" if inst.asset_class == AssetClass.MMMF_GOVT_SMALL else (
                                        "U.S. Agency GSE Obligation" if inst.asset_class == AssetClass.US_AGENCY else "Municipal GO Security"
                                    )
                                )
                            )
                        )
                    )
                ),
                "issuer": inst.issuer,
                "issuer_family": inst.issuer_family,
                "coupon_rate_pct": float(inst.coupon_rate * 100),
                "yield_pct": float(inst.yield_to_maturity * 100),
                "yield_type": inst.yield_type.value,
                "yield_type_label": (
                    "Auction Investment Rate" if inst.yield_type.value == "AUCTION_INVESTMENT_RATE" else (
                        "Yield to Maturity (YTM)" if inst.yield_type.value == "YTM" else (
                            "Index Effective Rate" if inst.yield_type.value == "INDEX_EFFECTIVE" else (
                                "7-Day SEC Current Yield" if inst.yield_type.value == "SEC_7DAY" else (
                                    "Overnight Repo Rate" if inst.yield_type.value == "REPO_RATE" else (
                                        "Federal Reserve IORB Rate" if inst.yield_type.value == "FED_IORB" else "Contractual Custody Rate"
                                    )
                                )
                            )
                        )
                    )
                ),
                "yield_as_of": inst.yield_as_of,
                "clean_price": float(inst.clean_price),
                "bid_ask_spread_bps": float(inst.bid_ask_spread_bps),
                "maturity_date": inst.maturity_date.isoformat() if inst.maturity_date else "Demand / N/A",
                "days_to_maturity": inst.days_to_maturity(as_of),
                "remaining_tenor_formatted": inst.remaining_tenor_formatted(as_of),
                "liquidity_tier": inst.liquidity_tier.value,
                "liq_tier": "T0_CASH" if inst.asset_class in (AssetClass.CASH_CENTRAL_BANK, AssetClass.REVERSE_REPO) else (
                    "T0_BILLS" if inst.asset_class == AssetClass.US_TREASURY else (
                        "T1_MMMF" if "MMMF" in inst.asset_class.value else "T2_TERM"
                    )
                ),
                "liq_label": "T+0 Instant Wire" if inst.asset_class in (AssetClass.CASH_CENTRAL_BANK, AssetClass.REVERSE_REPO) else (
                    "T+0 Same-Day" if inst.asset_class == AssetClass.US_TREASURY else (
                        "T+1 Delay Risk" if "MMMF" in inst.asset_class.value else "Term Paper"
                    )
                ),
                "settlement_terms": inst.settlement_terms,
                "cash_conversion_within_1_biz_day": inst.cash_conversion_within_1_biz_day,
                "statutory_cap_pct": 100.0 if inst.asset_class in (AssetClass.US_TREASURY, AssetClass.CASH_CENTRAL_BANK, AssetClass.REVERSE_REPO) else (
                    50.0 if inst.asset_class in (AssetClass.US_AGENCY, AssetClass.MMMF_GOVT_LARGE, AssetClass.MMMF_GOVT) else 10.0
                ),
                "statutory_cap_label": "" if inst.asset_class in (
                    AssetClass.US_TREASURY, AssetClass.CASH_CENTRAL_BANK, AssetClass.REVERSE_REPO,
                    AssetClass.US_AGENCY, AssetClass.MMMF_GOVT_LARGE, AssetClass.MMMF_GOVT,
                    AssetClass.MMMF_GOVT_SMALL, AssetClass.MUNICIPAL,
                ) else "",
                "issuer_cap": 100.0 if inst.asset_class in (AssetClass.US_TREASURY, AssetClass.CASH_CENTRAL_BANK) else (
                    25.0 if inst.asset_class in (AssetClass.US_AGENCY, AssetClass.REVERSE_REPO) else (
                        10.0 if "MMMF" in inst.asset_class.value else 5.0
                    )
                ),
                "issuer_cap_label": "" if inst.asset_class in (AssetClass.US_TREASURY, AssetClass.CASH_CENTRAL_BANK, AssetClass.MUNICIPAL) else (
                    "25% per issuer" if inst.asset_class == AssetClass.US_AGENCY else (
                        "25% per counterparty group" if inst.asset_class == AssetClass.REVERSE_REPO else (
                            "10% per fund; 25% per family" if "MMMF" in inst.asset_class.value else "5% per issuer"
                        )
                    )
                ),
                "cusip": inst.cusip,
                "internal_id": inst.internal_id,
                "master_agreement_ref": inst.master_agreement_ref,
                "depository_account_type": inst.depository_account_type,
                "credit_rating": inst.credit_rating.value,
                "credit_rating_informational": inst.credit_rating_informational,
                "credit_risk_assessment": inst.credit_risk_assessment,
                "rule_125_status": inst.rule_125_status,
                "liquidity_evidence_date": inst.liquidity_evidence_date.isoformat(),
                "offering_doc_reviewed": inst.offering_doc_reviewed,
                "embedded_derivative_check": inst.embedded_derivative_check,
                "statutory_rule": "17 CFR § 1.25(a)(1) Permitted",
                "is_permitted": True
            }
            for inst in get_standard_universe(as_of)
        ],
        "prohibited_securities": [
            {
                "name": "Corporate Equities / Stocks (e.g. S&P 500, AAPL, NVDA)",
                "statutory_status": "STRICTLY PROHIBITED",
                "citation": "17 CFR § 1.25(a)(2)",
                "reason": "Equity securities are explicitly barred. Customer segregated funds can only be invested in CFTC-enumerated debt instruments designed for capital preservation."
            },
            {
                "name": "Corporate Bonds, Corporate Notes & Commercial Paper (e.g. Apple, Google, Microsoft)",
                "statutory_status": "STRICTLY PROHIBITED",
                "citation": "17 CFR § 1.25(a)(1)(v)-(vi)",
                "reason": "All corporate bonds, corporate notes, and private commercial paper were removed and banned under post-2011 CFTC rulemaking (76 FR 78776)."
            },
            {
                "name": "Bank Certificates of Deposit (CDs)",
                "statutory_status": "STRICTLY PROHIBITED",
                "citation": "17 CFR § 1.25(a)(1)(iv)",
                "reason": "Negotiable and time Certificates of Deposit (CDs) are no longer permitted investments under post-2011 Rule 1.25."
            },
            {
                "name": "Treasury Inflation-Protected Securities (TIPS)",
                "statutory_status": "STRICTLY PROHIBITED",
                "citation": "17 CFR § 1.25(b)(2)(iii)",
                "reason": "CPI and inflation index-linked principal or interest payments are barred under § 1.25(b)(2)(iii) adjustable-rate restrictions."
            },
            {
                "name": "Term Repurchase Agreements > 1 Business Day (e.g. 7-Day Fixed Repo)",
                "statutory_status": "STRICTLY PROHIBITED",
                "citation": "17 CFR § 1.25(d)(5)",
                "reason": "Repurchase agreements must be terminable and demand-reversible by the FCM within one business day."
            },
            {
                "name": "Municipal Revenue & Lease-Revenue Bonds",
                "statutory_status": "STRICTLY PROHIBITED",
                "citation": "17 CFR § 1.25(a)(1)(ii)",
                "reason": "Only general obligation (UTGO) bonds backed by the full faith, credit, and taxing power of a state or municipality qualify."
            },
            {
                "name": "Foreign Sovereign Debt (Without Currency Matching or CFTC Order)",
                "statutory_status": "STRICTLY PROHIBITED",
                "citation": "17 CFR § 1.25(b)(3)(vi)",
                "reason": "Foreign sovereign debt is prohibited unless held strictly to the extent of customer liabilities in that exact currency with CDS <= 45 bps."
            },
            {
                "name": "Cryptocurrencies & Digital Assets (Direct Spot)",
                "statutory_status": "STRICTLY PROHIBITED",
                "citation": "17 CFR § 1.25(a)",
                "reason": "Non-permitted asset class. Only cash and CFTC-enumerated debt instruments qualify for customer segregation."
            }
        ]
    }

def create_custom_portfolio_from_allocations(
    as_of: date,
    total_float: Decimal,
    allocations_map: Dict[str, float],
    firm_ri: Optional[Decimal] = None
) -> TreasuryPortfolio:
    """Constructs a TreasuryPortfolio from user-defined allocations in allowed securities."""
    from ..core.instruments import Position
    from ..core.portfolio import round_money
    
    if firm_ri is None:
        if total_float <= Decimal("25000000.00"):
            firm_ri = Decimal("4688126.00")
        else:
            firm_ri = round_money(total_float * Decimal("0.05"))
    
    universe = {inst.id: inst for inst in get_standard_universe(as_of)}
    positions = []
    total_securities_amt = Decimal("0.00")

    for inst_id, dollar_amt in allocations_map.items():
        if inst_id != "CASH-FED-RESERVE" and inst_id in universe:
            dec_amt = round_money(Decimal(str(dollar_amt)))
            if dec_amt > Decimal("0.00"):
                total_securities_amt += dec_amt
                inst = universe[inst_id]
                par = round_money(dec_amt / (inst.clean_price / Decimal("100.0")))
                positions.append(Position(
                    instrument=inst,
                    par_amount=par,
                    book_cost=dec_amt,
                    accrued_interest=Decimal("0.00")
                ))

    # Customer cash at Fed is total customer float minus securities deployed
    if "CASH-FED-RESERVE" in allocations_map and allocations_map["CASH-FED-RESERVE"] is not None:
        cust_cash = round_money(Decimal(str(allocations_map["CASH-FED-RESERVE"])))
    else:
        cust_cash = max(Decimal("0.00"), total_float - total_securities_amt)

    cash_at_fed = cust_cash + firm_ri

    return TreasuryPortfolio(
        as_of_date=as_of,
        customer_segregated_liability=total_float,
        firm_residual_interest=firm_ri,
        cash_at_fed=cash_at_fed,
        positions=positions
    )

class DashboardRequestHandler(BaseHTTPRequestHandler):
    current_portfolio = PortfolioPresets.get_kalshi_us_treasuries_focused(date.today(), Decimal("11370355.00"))
    yield_shift_bps = 0.0
    margin_call_amount = 2500000.0
    credit_facility = False

    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?") or self.path.startswith("/index"):
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            html_path = os.path.join(project_root, "public", "index.html")
            with open(html_path, "rb") as f:
                self.wfile.write(f.read())
        elif self.path.startswith("/api/data") or self.path.startswith("/api"):
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            payload = build_full_dashboard_payload(
                self.current_portfolio,
                self.yield_shift_bps,
                self.margin_call_amount,
                self.credit_facility
            )
            self.wfile.write(json.dumps(payload, cls=DecimalEncoder).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path.startswith("/api/update") or self.path.startswith("/api"):
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len)
            data = json.loads(body.decode("utf-8")) if body else {}

            preset_name = data.get("preset", "balanced")
            total_float = to_decimal(data.get("total_float", 500000000.0))
            firm_ri_raw = data.get("firm_residual_interest")
            firm_ri = to_decimal(firm_ri_raw) if firm_ri_raw is not None else None
            custom_allocations = data.get("custom_allocations")
            as_of = date.today()

            if custom_allocations and isinstance(custom_allocations, dict):
                DashboardRequestHandler.current_portfolio = create_custom_portfolio_from_allocations(
                    as_of=as_of,
                    total_float=total_float,
                    allocations_map=custom_allocations,
                    firm_ri=firm_ri
                )
            elif preset_name == "balanced":
                DashboardRequestHandler.current_portfolio = PortfolioPresets.get_default_for_float(as_of, total_float)
            elif preset_name == "aggressive":
                DashboardRequestHandler.current_portfolio = PortfolioPresets.get_aggressive_yield_chaser(as_of, total_float)
            elif preset_name == "breached":
                DashboardRequestHandler.current_portfolio = PortfolioPresets.get_breached_mf_global_style(as_of, total_float)
            elif preset_name == "optimized":
                universe = get_standard_universe(as_of)
                DashboardRequestHandler.current_portfolio = TreasuryOptimizer.optimize_allocation(
                    as_of_date=as_of,
                    total_float=total_float,
                    candidate_instruments=universe
                )

            DashboardRequestHandler.yield_shift_bps = float(data.get("yield_shift_bps", 0.0))
            if "margin_call_amount" in data:
                DashboardRequestHandler.margin_call_amount = float(data.get("margin_call_amount"))
            DashboardRequestHandler.credit_facility = bool(data.get("credit_facility", False))

            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            payload = build_full_dashboard_payload(
                DashboardRequestHandler.current_portfolio,
                DashboardRequestHandler.yield_shift_bps,
                DashboardRequestHandler.margin_call_amount,
                DashboardRequestHandler.credit_facility
            )
            self.wfile.write(json.dumps(payload, cls=DecimalEncoder).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

def run_server(port: int = 8080):
    server_address = ("127.0.0.1", port)
    httpd = HTTPServer(server_address, DashboardRequestHandler)
    print(f"[CFTC 1.25 Simulator] Web Dashboard running at http://127.0.0.1:{port}", flush=True)
    httpd.serve_forever()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    run_server(port)
