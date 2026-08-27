"""
Constrained Treasury Portfolio Optimizer for CFTC Rule 1.25 Customer Funds.
Maximizes Net Interest Income (NII) subject to regulatory concentration caps, WAM limits, and liquidity buffers.
"""

from decimal import Decimal
import numpy as np
from scipy.optimize import linprog
from typing import List, Dict, Any, Tuple
from datetime import date
from ..core.types import (
    AssetClass,
    LiquidityTier,
    to_decimal,
    round_money,
    round_bps
)
from ..core.instruments import Instrument, Position
from ..core.portfolio import TreasuryPortfolio
from ..rules.cftc_125_limits import CFTC125Limits

class TreasuryOptimizer:
    """
    Mathematical linear/quadratic optimizer for CFTC 1.25 customer fund portfolios.
    """

    @staticmethod
    def optimize_allocation(
        as_of_date: date,
        total_float: Decimal,
        candidate_instruments: List[Instrument],
        firm_ri: Decimal = Decimal("25000000.00"),
        min_t0_liquidity_pct: Decimal = Decimal("0.25"), # Minimum 25% in T+0 instant/same-day liquidity
        max_wam_years: Decimal = Decimal("1.75"),         # Conservative WAM cap (<= 2.0 yrs)
        max_single_issuer_pct: Decimal = Decimal("0.05") # 5% single issuer cap
    ) -> TreasuryPortfolio:
        """
        Solves:
            maximize sum(w_i * yield_i)
        subject to:
            sum(w_i) = 1, w_i >= 0
            sum_{MMMF} w_i <= 0.50
            sum_{Agency} w_i <= 0.25
            sum_{CD} w_i <= 0.25
            sum_{CP} w_i <= 0.25
            sum_{Muni} w_i <= 0.10
            w_k <= 0.05 for each non-US-Gov issuer
            sum(w_i * maturity_years_i) <= max_wam_years
            sum_{T0_liquidity} w_i >= min_t0_liquidity_pct
        """
        n = len(candidate_instruments)
        if n == 0:
            return TreasuryPortfolio(as_of_date, total_float, firm_ri, total_float)

        # Objective: minimize -yield
        c = [-float(inst.yield_to_maturity) for inst in candidate_instruments]

        A_ub = []
        b_ub = []

        # 1. WAM constraint: sum(w_i * years_i) <= max_wam_years
        wam_coeffs = [float(inst.years_to_maturity(as_of_date)) for inst in candidate_instruments]
        A_ub.append(wam_coeffs)
        b_ub.append(float(max_wam_years))

        # 2. Min T+0 Liquidity: sum_{T0}(w_i) >= min_t0 => -sum_{T0}(w_i) <= -min_t0
        t0_coeffs = [
            -1.0 if inst.liquidity_tier in (LiquidityTier.TIER_0_INSTANT, LiquidityTier.TIER_1_SAME_DAY) else 0.0
            for inst in candidate_instruments
        ]
        A_ub.append(t0_coeffs)
        b_ub.append(-float(min_t0_liquidity_pct))

        # 3. Asset Class Caps
        # Agency <= 0.25
        agency_coeffs = [1.0 if inst.asset_class == AssetClass.US_AGENCY else 0.0 for inst in candidate_instruments]
        A_ub.append(agency_coeffs)
        b_ub.append(0.25)

        # MMMF <= 0.50
        mmmf_coeffs = [1.0 if inst.asset_class in (AssetClass.MMMF_GOVT, AssetClass.MMMF_PRIME) else 0.0 for inst in candidate_instruments]
        A_ub.append(mmmf_coeffs)
        b_ub.append(0.50)

        # CD <= 0.25
        cd_coeffs = [1.0 if inst.asset_class == AssetClass.BANK_CD else 0.0 for inst in candidate_instruments]
        A_ub.append(cd_coeffs)
        b_ub.append(0.25)

        # CP <= 0.25
        cp_coeffs = [1.0 if inst.asset_class == AssetClass.COMMERCIAL_PAPER else 0.0 for inst in candidate_instruments]
        A_ub.append(cp_coeffs)
        b_ub.append(0.25)

        # Muni <= 0.10
        muni_coeffs = [1.0 if inst.asset_class == AssetClass.MUNICIPAL else 0.0 for inst in candidate_instruments]
        A_ub.append(muni_coeffs)
        b_ub.append(0.10)

        # 4. Single-Issuer Caps (5% for non-Gov, 25% for GSE)
        unique_issuers = set(inst.issuer for inst in candidate_instruments)
        for iss in unique_issuers:
            if iss in ("US_TREASURY", "FEDERAL_RESERVE"):
                continue
            cap = 0.25 if iss in ("FHLB", "FNMA", "FHLMC", "FARMER_MAC") else float(max_single_issuer_pct)
            iss_coeffs = [1.0 if inst.issuer == iss else 0.0 for inst in candidate_instruments]
            A_ub.append(iss_coeffs)
            b_ub.append(cap)

        # 5. Equality: sum(w_i) = 1.0
        A_eq = [[1.0] * n]
        b_eq = [1.0]

        # Bounds: 0 <= w_i <= 1.0
        bounds = [(0.0, 1.0) for _ in range(n)]

        # Solve Linear Program
        res = linprog(
            c=c,
            A_ub=A_ub,
            b_ub=b_ub,
            A_eq=A_eq,
            b_eq=b_eq,
            bounds=bounds,
            method="highs"
        )

        positions: List[Position] = []
        cash_at_fed = firm_ri

        if res.success:
            weights = res.x
            for i, w in enumerate(weights):
                if w > 0.0001:
                    alloc_usd = round_money(total_float * Decimal(str(round(w, 6))))
                    inst = candidate_instruments[i]
                    if inst.asset_class == AssetClass.CASH_CENTRAL_BANK:
                        cash_at_fed += alloc_usd
                    else:
                        par = round_money(alloc_usd / (inst.clean_price / Decimal("100.0")))
                        positions.append(Position(
                            instrument=inst,
                            par_amount=par,
                            book_cost=alloc_usd,
                            accrued_interest=Decimal("0.00")
                        ))
        else:
            # Fallback if unfeasible: 100% Treasury Bills
            tbill = [i for i in candidate_instruments if i.asset_class == AssetClass.US_TREASURY][0]
            positions.append(Position(
                instrument=tbill,
                par_amount=round_money(total_float / (tbill.clean_price / Decimal("100.0"))),
                book_cost=total_float,
                accrued_interest=Decimal("0.00")
            ))

        return TreasuryPortfolio(
            as_of_date=as_of_date,
            customer_segregated_liability=total_float,
            firm_residual_interest=firm_ri,
            cash_at_fed=cash_at_fed,
            positions=positions
        )
