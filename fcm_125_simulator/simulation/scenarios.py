"""
Historical and Hypothetical Crisis Scenarios for CFTC 1.25 Customer Fund Stress Testing.
"""

from decimal import Decimal
from dataclasses import dataclass
from typing import Dict, List, Any
from ..core.portfolio import TreasuryPortfolio
from ..analytics.mtm_pricing import MTMPricingEngine
from .liquidity_stress import LiquidityStressEngine, MarginCallSimulationResult

@dataclass
class ScenarioDefinition:
    id: str
    name: str
    description: str
    yield_shift_bps: Decimal
    credit_spread_shift_bps: Decimal
    bid_ask_multiplier: Decimal
    dco_margin_call_amount: Decimal
    historical_date_reference: str

@dataclass
class ScenarioStressResult:
    scenario: ScenarioDefinition
    initial_market_value: Decimal
    stressed_market_value: Decimal
    unrealized_mtm_loss: Decimal
    mtm_loss_pct: Decimal
    liquidity_result: MarginCallSimulationResult
    initial_seg_excess: Decimal
    stressed_seg_excess: Decimal
    is_segregation_deficit: bool
    required_firm_ri_injection: Decimal
    fcm_survived_scenario: bool
    post_mortem_summary: str

class StressScenarioLibrary:
    """
    Library of institutional market stress scenarios.
    """

    @staticmethod
    def get_all_scenarios(customer_float: Decimal) -> List[ScenarioDefinition]:
        """
        Returns calibrated scenarios scaled to total customer segregated float.
        """
        call_25pct = customer_float * Decimal("0.25") # 25% intraday margin surge
        call_20pct = customer_float * Decimal("0.20")
        call_15pct = customer_float * Decimal("0.15")
        call_40pct = customer_float * Decimal("0.40")

        return [
            ScenarioDefinition(
                id="march_2020_covid",
                name="2020 March Dash-for-Cash Treasury Liquidity Crisis",
                description="Global rush for USD cash: Off-the-run Treasury bid-ask spreads explode 8x, front-end repo spikes, massive intraday exchange margin calls.",
                yield_shift_bps=Decimal("-75.0"), # Front-end rate collapse
                credit_spread_shift_bps=Decimal("125.0"), # Agency & CP spreads blow out
                bid_ask_multiplier=Decimal("8.0"),
                dco_margin_call_amount=call_25pct,
                historical_date_reference="March 16-23, 2020"
            ),
            ScenarioDefinition(
                id="fed_2022_hikes",
                name="2022 Fed Aggressive 500bps Rate Hike Shock",
                description="Fastest tightening cycle in 40 years: Short and intermediate yields surge by +450 bps, inflicting severe paper MTM drawdowns on 2Y-5Y paper.",
                yield_shift_bps=Decimal("450.0"),
                credit_spread_shift_bps=Decimal("40.0"),
                bid_ask_multiplier=Decimal("1.5"),
                dco_margin_call_amount=call_15pct,
                historical_date_reference="March - December 2022"
            ),
            ScenarioDefinition(
                id="svb_2023_bank_run",
                name="2023 SVB Regional Banking & Uninsured Deposit Panic",
                description="Sudden run on regional bank deposits: Bank CDs face 20% illiquidity haircut, Tier-1 CP market freezes, flight to direct Treasury Bills.",
                yield_shift_bps=Decimal("-120.0"), # Bull steepening flight to safety
                credit_spread_shift_bps=Decimal("250.0"), # Bank credit spreads blow out
                bid_ask_multiplier=Decimal("5.0"),
                dco_margin_call_amount=call_20pct,
                historical_date_reference="March 8-15, 2023"
            ),
            ScenarioDefinition(
                id="mf_global_repo_freeze",
                name="MF Global Sovereign Repo & Duration Liquidity Trap",
                description="Over-leveraged duration and term repo freeze: T+1 MMMF redemptions gated, term paper cannot be liquidated, intraday clearing calls fail.",
                yield_shift_bps=Decimal("200.0"),
                credit_spread_shift_bps=Decimal("300.0"),
                bid_ask_multiplier=Decimal("12.0"),
                dco_margin_call_amount=call_40pct,
                historical_date_reference="October 31, 2011"
            ),
            ScenarioDefinition(
                id="crypto_black_swan_2026",
                name="2026 Crypto Perp Extreme Volatility & DCO Margin Shock",
                description="Instant 35% crypto market crash triggers record liquidation volume and an unprecedented 30% intraday cash margin call by the DCO clearinghouse.",
                yield_shift_bps=Decimal("25.0"),
                credit_spread_shift_bps=Decimal("15.0"),
                bid_ask_multiplier=Decimal("2.0"),
                dco_margin_call_amount=customer_float * Decimal("0.30"),
                historical_date_reference="Hypothetical Extreme Tail Event"
            )
        ]

    @staticmethod
    def run_stress_test(
        portfolio: TreasuryPortfolio,
        scenario: ScenarioDefinition,
        allow_t1_credit_facility: bool = False
    ) -> ScenarioStressResult:
        """
        Executes a complete stress test combining MTM valuation shock and DCO margin call waterfall.
        """
        init_mv = portfolio.total_portfolio_market_value
        customer_par = portfolio.customer_segregated_liability
        firm_ri = portfolio.firm_residual_interest

        # 1. Revalue portfolio under market yield and credit spread shifts
        stressed_mv, mtm_pnl, _ = MTMPricingEngine.revalue_portfolio_under_shock(
            portfolio=portfolio,
            yield_shift_bps=scenario.yield_shift_bps,
            credit_spread_shift_bps=scenario.credit_spread_shift_bps,
            apply_bid_ask_haircut=True
        )

        unrealized_loss = max(Decimal("0.00"), -mtm_pnl)
        loss_pct = (unrealized_loss / init_mv) * Decimal("100.0") if init_mv > 0 else Decimal("0.0")

        # Initial segregation excess
        init_seg_excess = (init_mv + firm_ri) - customer_par

        # Stressed segregation excess before margin call
        stressed_seg_excess = (stressed_mv + firm_ri) - customer_par
        is_seg_deficit = stressed_seg_excess < Decimal("0.00")
        required_ri_injection = max(Decimal("0.00"), -stressed_seg_excess)

        # 2. Run liquidity waterfall on the DCO margin call
        liq_result = LiquidityStressEngine.simulate_dco_margin_call(
            portfolio=portfolio,
            margin_call_amount=scenario.dco_margin_call_amount,
            allow_t1_credit_facility=allow_t1_credit_facility
        )

        # Evaluate survival
        fcm_survived = (not liq_result.is_settlement_default) and (firm_ri >= (unrealized_loss + liq_result.total_liquidation_costs))

        # Generate executive post-mortem summary
        if not fcm_survived:
            reasons = []
            if liq_result.is_settlement_default:
                reasons.append(f"T+0 liquidity shortfall of ${liq_result.shortfall_amount_t0:,.2f} on DCO margin call")
            if is_seg_deficit:
                reasons.append(f"Segregation deficit of ${abs(stressed_seg_excess):,.2f} (firm RI buffer depleted)")
            if not reasons:
                reasons.append(f"Combined MTM loss (${unrealized_loss:,.2f}) and liquidation costs (${liq_result.total_liquidation_costs:,.2f}) exceeded firm RI cushion (${firm_ri:,.2f})")
            post_mortem = f"FAILURE: Firm suffered {' and '.join(reasons)}."
        else:
            post_mortem = f"PASSED: FCM absorbed ${unrealized_loss:,.2f} MTM shock and funded ${scenario.dco_margin_call_amount:,.2f} margin call with ${stressed_seg_excess:,.2f} residual cushion remaining."

        return ScenarioStressResult(
            scenario=scenario,
            initial_market_value=init_mv,
            stressed_market_value=stressed_mv,
            unrealized_mtm_loss=unrealized_loss,
            mtm_loss_pct=loss_pct.quantize(Decimal("0.01")),
            liquidity_result=liq_result,
            initial_seg_excess=init_seg_excess,
            stressed_seg_excess=stressed_seg_excess,
            is_segregation_deficit=is_seg_deficit,
            required_firm_ri_injection=required_ri_injection,
            fcm_survived_scenario=fcm_survived,
            post_mortem_summary=post_mortem
        )
