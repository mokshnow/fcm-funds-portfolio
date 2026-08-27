"""
Unit tests for Intraday DCO Margin Call Liquidity Waterfall.
"""

import unittest
from decimal import Decimal
from datetime import date

from fcm_125_simulator.core.portfolio import TreasuryPortfolio
from fcm_125_simulator.core.presets import PortfolioPresets
from fcm_125_simulator.simulation.liquidity_stress import LiquidityStressEngine

class TestLiquidityWaterfall(unittest.TestCase):

    def setUp(self):
        self.as_of = date(2026, 8, 27)
        self.float_val = Decimal("500000000.00")

    def test_moderate_margin_call_satisfied_via_t0_cash_and_repo(self):
        portfolio = PortfolioPresets.get_balanced_institutional_fcm(self.as_of, self.float_val)
        # Cash at Fed = $70M, O/N Repo = $75M => $145M instant T+0
        res = LiquidityStressEngine.simulate_dco_margin_call(
            portfolio=portfolio,
            margin_call_amount=Decimal("100000000.00") # $100M call
        )
        self.assertTrue(res.is_fully_funded_t0)
        self.assertFalse(res.is_settlement_default)
        self.assertEqual(res.shortfall_amount_t0, Decimal("0.00"))
        self.assertEqual(len(res.steps), 2) # Fed Cash ($70M) + O/N Repo ($30M)
        self.assertEqual(res.total_liquidation_costs, Decimal("0.00"))

    def test_heavy_margin_call_uses_tbills_with_spread_friction(self):
        portfolio = PortfolioPresets.get_balanced_institutional_fcm(self.as_of, self.float_val)
        # $150M call: exhausts $25M cash + $75M repo + requires $50M T-Bills
        res = LiquidityStressEngine.simulate_dco_margin_call(
            portfolio=portfolio,
            margin_call_amount=Decimal("150000000.00")
        )
        self.assertTrue(res.is_fully_funded_t0)
        self.assertFalse(res.is_settlement_default)
        # Must have incurred bid-ask spread friction on T-Bills
        self.assertGreater(res.total_liquidation_costs, Decimal("0.00"))

    def test_mmmf_t1_delay_without_credit_facility_creates_shortfall(self):
        # Portfolio with $20M cash and heavy MMMF
        portfolio = PortfolioPresets.get_aggressive_yield_chaser(self.as_of, self.float_val)
        # $300M margin call (exhausts T+0 cash + notes, testing MMMF T+1 bottleneck)
        res_no_credit = LiquidityStressEngine.simulate_dco_margin_call(
            portfolio=portfolio,
            margin_call_amount=Decimal("300000000.00"),
            allow_t1_credit_facility=False
        )
        # MMMF cannot fund intraday T+0 without facility
        self.assertFalse(res_no_credit.is_fully_funded_t0)
        self.assertTrue(res_no_credit.is_settlement_default)
        self.assertGreater(res_no_credit.shortfall_amount_t0, Decimal("0.00"))

        # With credit facility enabled
        res_with_credit = LiquidityStressEngine.simulate_dco_margin_call(
            portfolio=portfolio,
            margin_call_amount=Decimal("300000000.00"),
            allow_t1_credit_facility=True
        )
        self.assertTrue(res_with_credit.is_fully_funded_t0)
        self.assertFalse(res_with_credit.is_settlement_default)

if __name__ == "__main__":
    unittest.main()
