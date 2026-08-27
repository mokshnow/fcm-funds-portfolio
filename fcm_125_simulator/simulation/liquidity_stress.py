"""
Intraday Clearinghouse (DCO) Margin Call & Liquidity Waterfall Simulator.
Evaluates T+0 immediate liquidity vs. T+1 redemption delays and calculates liquidation costs.
"""

from decimal import Decimal
from dataclasses import dataclass, field
from typing import List, Dict, Any, Tuple
import copy
from ..core.types import (
    AssetClass,
    LiquidityTier,
    to_decimal,
    round_money,
    round_bps
)
from ..core.portfolio import TreasuryPortfolio
from ..core.instruments import Position

@dataclass
class LiquidityStepResult:
    step_number: int
    source_name: str
    asset_class: str
    liquidity_tier: str
    amount_drawn: Decimal
    liquidation_cost: Decimal
    settlement_horizon: str
    is_immediate_t0: bool
    remaining_call_balance: Decimal
    notes: str

@dataclass
class MarginCallSimulationResult:
    call_amount: Decimal
    funded_amount_t0: Decimal
    funded_amount_t1: Decimal
    total_liquidation_costs: Decimal
    is_fully_funded_t0: bool
    is_settlement_default: bool
    shortfall_amount_t0: Decimal
    steps: List[LiquidityStepResult]
    post_stress_cash_at_fed: Decimal
    post_stress_total_value: Decimal
    fcm_residual_interest_consumed: Decimal

class LiquidityStressEngine:
    """
    Executes the DCO intraday margin call liquidity waterfall.
    """

    @staticmethod
    def simulate_dco_margin_call(
        portfolio: TreasuryPortfolio,
        margin_call_amount: Decimal,
        allow_t1_credit_facility: bool = False,
        credit_facility_fee_bps: Decimal = Decimal("50.0") # 50 bps annualized intraday fee
    ) -> MarginCallSimulationResult:
        """
        Simulates meeting a sudden intraday DCO variation margin call.
        Waterfall order:
        1. T+0 Cash at Central Bank / Federal Reserve
        2. T+0 Maturing Overnight Reverse Repos
        3. T+0 On-The-Run US Treasury Bills (secondary market sale with bid-ask cost)
        4. T+0 Short Treasury Notes (secondary market sale)
        5. T+1 Rule 2a-7 Government MMMF (next-day settlement; needs credit line for T+0)
        6. T+1 / T+3 Term Bank CDs / CP / Agencies (illiquidity haircut / breakage fee)
        """
        remaining_call = margin_call_amount
        total_drawn_t0 = Decimal("0.00")
        total_drawn_t1 = Decimal("0.00")
        total_costs = Decimal("0.00")
        steps: List[LiquidityStepResult] = []
        step_num = 1

        # Deep copy portfolio for post-stress tracking
        stressed_cash = portfolio.cash_at_fed
        stressed_positions: List[Position] = [
            Position(
                instrument=p.instrument,
                par_amount=p.par_amount,
                book_cost=p.book_cost,
                accrued_interest=p.accrued_interest
            )
            for p in portfolio.positions
        ]

        # --- STEP 1: Uninvested Cash at Fed (Instant T+0) ---
        if stressed_cash > Decimal("0.00") and remaining_call > Decimal("0.00"):
            drawn = min(stressed_cash, remaining_call)
            stressed_cash -= drawn
            remaining_call -= drawn
            total_drawn_t0 += drawn
            steps.append(LiquidityStepResult(
                step_number=step_num,
                source_name="Federal Reserve Segregated Cash Deposit",
                asset_class=AssetClass.CASH_CENTRAL_BANK.value,
                liquidity_tier=LiquidityTier.TIER_0_INSTANT.value,
                amount_drawn=drawn,
                liquidation_cost=Decimal("0.00"),
                settlement_horizon="T+0 Instant (Fedwire, < 15 min)",
                is_immediate_t0=True,
                remaining_call_balance=remaining_call,
                notes="Direct wire from central bank account with zero liquidation friction."
            ))
            step_num += 1

        # --- STEP 2: Overnight Reverse Repurchase Agreements (Maturing T+0) ---
        for p in stressed_positions:
            if remaining_call <= Decimal("0.00"):
                break
            if p.instrument.asset_class == AssetClass.REVERSE_REPO and p.instrument.liquidity_tier == LiquidityTier.TIER_0_INSTANT:
                mv = p.market_value
                if mv > Decimal("0.00"):
                    drawn = min(mv, remaining_call)
                    # Reduce position par proportionally
                    pct = drawn / mv
                    p.par_amount = round_money(p.par_amount * (Decimal("1.0") - pct))
                    p.book_cost = round_money(p.book_cost * (Decimal("1.0") - pct))
                    remaining_call -= drawn
                    total_drawn_t0 += drawn
                    steps.append(LiquidityStepResult(
                        step_number=step_num,
                        source_name=f"Maturing O/N Reverse Repo ({p.instrument.name})",
                        asset_class=p.instrument.asset_class.value,
                        liquidity_tier=p.instrument.liquidity_tier.value,
                        amount_drawn=drawn,
                        liquidation_cost=Decimal("0.00"),
                        settlement_horizon="T+0 Instant (SOFR Tri-Party, < 30 min)",
                        is_immediate_t0=True,
                        remaining_call_balance=remaining_call,
                        notes="Overnight repo matures at 100% par upon opening of Fedwire."
                    ))
                    step_num += 1

        # --- STEP 3: US Treasury Bills (T+0 Secondary Market Liquidation) ---
        for p in stressed_positions:
            if remaining_call <= Decimal("0.00"):
                break
            if p.instrument.asset_class == AssetClass.US_TREASURY and p.instrument.coupon_rate == Decimal("0.0"):
                mv = p.market_value
                if mv > Decimal("0.00"):
                    spread_rate = (p.instrument.bid_ask_spread_bps / Decimal("10000.0")) / Decimal("2.0")
                    needed_gross = remaining_call / (Decimal("1.0") - spread_rate)
                    drawn_gross = min(mv, needed_gross)
                    cost = round_money(drawn_gross * spread_rate)
                    net_proceeds = drawn_gross - cost
                    total_costs += cost

                    pct = min(Decimal("1.0"), drawn_gross / mv)
                    p.par_amount = round_money(p.par_amount * (Decimal("1.0") - pct))
                    p.book_cost = round_money(p.book_cost * (Decimal("1.0") - pct))

                    actual_drawn = min(net_proceeds, remaining_call)
                    remaining_call -= actual_drawn
                    total_drawn_t0 += actual_drawn

                    steps.append(LiquidityStepResult(
                        step_number=step_num,
                        source_name=f"Secondary Sale of T-Bills ({p.instrument.name})",
                        asset_class=p.instrument.asset_class.value,
                        liquidity_tier=p.instrument.liquidity_tier.value,
                        amount_drawn=actual_drawn,
                        liquidation_cost=cost,
                        settlement_horizon="T+0 Same-Day (Primary Dealer Desk)",
                        is_immediate_t0=True,
                        remaining_call_balance=remaining_call,
                        notes=f"Sold in deep institutional Treasury market; incurred {p.instrument.bid_ask_spread_bps} bps spread."
                    ))
                    step_num += 1

        # --- STEP 4: US Treasury Notes (T+0 Coupon Paper Sale) ---
        for p in stressed_positions:
            if remaining_call <= Decimal("0.00"):
                break
            if p.instrument.asset_class == AssetClass.US_TREASURY and p.instrument.coupon_rate > Decimal("0.0"):
                mv = p.market_value
                if mv > Decimal("0.00"):
                    spread_rate = (p.instrument.bid_ask_spread_bps / Decimal("10000.0")) / Decimal("2.0")
                    needed_gross = remaining_call / (Decimal("1.0") - spread_rate)
                    drawn_gross = min(mv, needed_gross)
                    cost = round_money(drawn_gross * spread_rate)
                    net_proceeds = drawn_gross - cost
                    total_costs += cost

                    pct = min(Decimal("1.0"), drawn_gross / mv)
                    p.par_amount = round_money(p.par_amount * (Decimal("1.0") - pct))
                    p.book_cost = round_money(p.book_cost * (Decimal("1.0") - pct))

                    actual_drawn = min(net_proceeds, remaining_call)
                    remaining_call -= actual_drawn
                    total_drawn_t0 += actual_drawn

                    steps.append(LiquidityStepResult(
                        step_number=step_num,
                        source_name=f"Secondary Sale of T-Notes ({p.instrument.name})",
                        asset_class=p.instrument.asset_class.value,
                        liquidity_tier=p.instrument.liquidity_tier.value,
                        amount_drawn=actual_drawn,
                        liquidation_cost=cost,
                        settlement_horizon="T+0 Same-Day (Subject to duration MTM)",
                        is_immediate_t0=True,
                        remaining_call_balance=remaining_call,
                        notes=f"Coupon note liquidated; incurred {p.instrument.bid_ask_spread_bps} bps market spread."
                    ))
                    step_num += 1

        # --- STEP 5: Government Money Market Funds (MMMFs) (T+1 Next-Day Delay Risk) ---
        for p in stressed_positions:
            if remaining_call <= Decimal("0.00"):
                break
            if p.instrument.asset_class in (AssetClass.MMMF_GOVT, AssetClass.MMMF_GOVT_LARGE, AssetClass.MMMF_GOVT_SMALL, AssetClass.MMMF_PRIME):
                mv = p.market_value
                if mv > Decimal("0.00"):
                    drawn_gross = min(mv, remaining_call)
                    if allow_t1_credit_facility:
                        # Day overdraft financing fee
                        facility_fee = round_money(drawn_gross * (credit_facility_fee_bps / Decimal("10000.0")) / Decimal("360.0"))
                        total_costs += facility_fee
                        is_t0 = True
                        total_drawn_t0 += drawn_gross
                        notes = "Bridged via FCM intraday committed bank daylight credit line against T+1 MMMF shares."
                    else:
                        is_t0 = False
                        facility_fee = Decimal("0.00")
                        total_drawn_t1 += drawn_gross
                        notes = "WARNING: Rule 2a-7 MMMF redemptions settle T+1. Cannot fund immediate 60-min DCO call without credit line!"

                    pct = drawn_gross / mv
                    p.par_amount = round_money(p.par_amount * (Decimal("1.0") - pct))
                    p.book_cost = round_money(p.book_cost * (Decimal("1.0") - pct))

                    if is_t0:
                        remaining_call -= drawn_gross

                    steps.append(LiquidityStepResult(
                        step_number=step_num,
                        source_name=f"MMMF Redemption Request ({p.instrument.name})",
                        asset_class=p.instrument.asset_class.value,
                        liquidity_tier=p.instrument.liquidity_tier.value,
                        amount_drawn=drawn_gross,
                        liquidation_cost=facility_fee,
                        settlement_horizon="T+1 Next-Day (Standard) / T+0 (If Bank Line)",
                        is_immediate_t0=is_t0,
                        remaining_call_balance=remaining_call,
                        notes=notes
                    ))
                    step_num += 1

        # --- STEP 6: Term CP, CDs, Agencies (Illiquid / Penalty) ---
        for p in stressed_positions:
            if remaining_call <= Decimal("0.00"):
                break
            if p.instrument.asset_class in (AssetClass.COMMERCIAL_PAPER, AssetClass.BANK_CD, AssetClass.US_AGENCY, AssetClass.MUNICIPAL):
                mv = p.market_value
                if mv > Decimal("0.00"):
                    drawn_gross = min(mv, remaining_call)
                    # CD break penalty or dealer CP bid-ask penalty (~25-50 bps)
                    break_penalty = round_money(drawn_gross * Decimal("0.0035")) # 35 bps
                    total_costs += break_penalty
                    net_drawn = drawn_gross - break_penalty

                    pct = drawn_gross / mv
                    p.par_amount = round_money(p.par_amount * (Decimal("1.0") - pct))
                    p.book_cost = round_money(p.book_cost * (Decimal("1.0") - pct))

                    if allow_t1_credit_facility:
                        is_t0 = True
                        actual_t0 = min(net_drawn, remaining_call)
                        remaining_call -= actual_t0
                        total_drawn_t0 += actual_t0
                        notes = f"Incurred 35 bps break penalty; bridged via intraday bank facility on {p.instrument.name}."
                    else:
                        is_t0 = False
                        total_drawn_t1 += net_drawn
                        notes = f"WARNING: Term instrument '{p.instrument.name}' settles T+1/T+2. Cannot fund 60-min T+0 call without credit line!"

                    steps.append(LiquidityStepResult(
                        step_number=step_num,
                        source_name=f"Early Break/Sale of Term Paper ({p.instrument.name})",
                        asset_class=p.instrument.asset_class.value,
                        liquidity_tier=p.instrument.liquidity_tier.value,
                        amount_drawn=net_drawn,
                        liquidation_cost=break_penalty,
                        settlement_horizon="T+1 Next-Day (Standard) / T+0 (If Bank Line)",
                        is_immediate_t0=is_t0,
                        remaining_call_balance=remaining_call,
                        notes=notes
                    ))
                    step_num += 1

        # Calculate final state
        is_fully_funded = remaining_call <= Decimal("0.00")
        is_default = not is_fully_funded
        shortfall = max(Decimal("0.00"), remaining_call)

        post_stress_mv = stressed_cash + sum((p.market_value for p in stressed_positions), Decimal("0.00"))

        return MarginCallSimulationResult(
            call_amount=margin_call_amount,
            funded_amount_t0=total_drawn_t0,
            funded_amount_t1=total_drawn_t1,
            total_liquidation_costs=total_costs,
            is_fully_funded_t0=is_fully_funded,
            is_settlement_default=is_default,
            shortfall_amount_t0=shortfall,
            steps=steps,
            post_stress_cash_at_fed=stressed_cash,
            post_stress_total_value=post_stress_mv,
            fcm_residual_interest_consumed=total_costs
        )
