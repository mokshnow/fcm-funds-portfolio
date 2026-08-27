"""
Unit tests for CFTC 1.32 Segregation Statement and CFTC 1.22 Residual Interest Adequacy.
"""

import unittest
from decimal import Decimal
from datetime import date

from fcm_125_simulator.core.portfolio import TreasuryPortfolio
from fcm_125_simulator.core.presets import PortfolioPresets
from fcm_125_simulator.regulatory.cftc_1_32_seg import CFTC132SegregationEngine
from fcm_125_simulator.regulatory.cftc_1_22_ri import CFTC122ResidualInterestEngine
from fcm_125_simulator.analytics.mtm_pricing import MTMPricingEngine

class TestMTMAndSegregation(unittest.TestCase):

    def setUp(self):
        self.as_of = date(2026, 8, 27)
        self.float_val = Decimal("500000000.00") # $500M

    def test_daily_segregation_statement_schedule(self):
        portfolio = PortfolioPresets.get_balanced_institutional_fcm(self.as_of, self.float_val)
        statement = CFTC132SegregationEngine.generate_daily_statement(portfolio)

        self.assertEqual(statement.line_1_customer_ledger_balance, self.float_val)
        self.assertEqual(statement.line_3_total_segregation_requirement, self.float_val)
        # Total funds must equal customer par + firm residual interest
        expected_total = self.float_val + portfolio.firm_residual_interest
        self.assertAlmostEqual(float(statement.line_8_total_segregated_funds), float(expected_total), delta=10.0)
        self.assertAlmostEqual(float(statement.line_9_excess_or_deficit), float(portfolio.firm_residual_interest), delta=10.0)
        self.assertGreater(statement.line_9_excess_or_deficit, Decimal("0.00"))

    def test_mtm_rate_shock_creates_seg_deficit_when_ri_insufficient(self):
        # Create a portfolio with high duration and low firm RI
        portfolio = PortfolioPresets.get_breached_mf_global_style(self.as_of, self.float_val)
        # Firm RI is $5M
        init_statement = CFTC132SegregationEngine.generate_daily_statement(portfolio)
        self.assertAlmostEqual(float(init_statement.line_9_excess_or_deficit), float(Decimal("5000000.00")), delta=5.0)

        # Apply +450 bps yield hike (such as 2022 shock)
        stressed_mv, pnl, _ = MTMPricingEngine.revalue_portfolio_under_shock(
            portfolio, yield_shift_bps=Decimal("450.0")
        )
        unrealized_loss = -pnl
        # Loss on 5Y notes will be > $30M, easily wiping out $5M RI
        self.assertGreater(unrealized_loss, Decimal("20000000.00"))

        stressed_excess = (stressed_mv + portfolio.firm_residual_interest) - self.float_val
        self.assertLess(stressed_excess, Decimal("0.00")) # Deficit occurs!

    def test_targeted_residual_interest_adequacy(self):
        portfolio = PortfolioPresets.get_balanced_institutional_fcm(self.as_of, self.float_val)
        ri_report = CFTC122ResidualInterestEngine.calculate_residual_interest_target(
            portfolio,
            customer_under_margin_sum=Decimal("5000000.00"),
            operational_buffer_pct=Decimal("0.02")
        )
        self.assertTrue(ri_report.is_adequate)
        self.assertGreater(ri_report.actual_firm_ri_deposited, ri_report.targeted_residual_interest)
        self.assertEqual(ri_report.deadline_hour_et, "6:00 PM Eastern")

if __name__ == "__main__":
    unittest.main()
