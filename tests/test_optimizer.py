"""
Unit tests for CFTC 1.25 Constrained Treasury Portfolio Optimizer.
"""

import unittest
from decimal import Decimal
from datetime import date

from fcm_125_simulator.core.types import ComplianceStatus, AssetClass
from fcm_125_simulator.core.presets import get_standard_universe
from fcm_125_simulator.analytics.optimizer import TreasuryOptimizer
from fcm_125_simulator.rules.compliance import CFTC125ComplianceEngine
from fcm_125_simulator.rules.cftc_125_limits import CFTC125Limits

class TestOptimizer(unittest.TestCase):

    def setUp(self):
        self.as_of = date(2026, 8, 27)
        self.float_val = Decimal("500000000.00")
        self.universe = get_standard_universe(self.as_of)
        self.compliance_engine = CFTC125ComplianceEngine()

    def test_optimizer_produces_fully_compliant_portfolio(self):
        portfolio = TreasuryOptimizer.optimize_allocation(
            as_of_date=self.as_of,
            total_float=self.float_val,
            candidate_instruments=self.universe,
            min_t0_liquidity_pct=Decimal("0.25"),
            max_wam_years=Decimal("1.75")
        )

        status, results = self.compliance_engine.evaluate_portfolio(portfolio)
        self.assertNotEqual(status, ComplianceStatus.BREACH)
        self.assertIn(status, [ComplianceStatus.COMPLIANT, ComplianceStatus.WARNING])
        
        # Verify WAM <= 1.75 <= 2.0 years
        wam = portfolio.weighted_average_maturity_years()
        self.assertLessEqual(wam, Decimal("1.75"))

        # Verify total market value matches total float + firm residual interest
        expected_mv = self.float_val + portfolio.firm_residual_interest
        self.assertAlmostEqual(
            float(portfolio.total_portfolio_market_value),
            float(expected_mv),
            delta=float(self.float_val * Decimal("0.001"))
        )

        # Verify asset class caps
        bd = portfolio.asset_class_percentages()
        agency_pct = bd.get(AssetClass.US_AGENCY, Decimal("0"))
        self.assertLessEqual(agency_pct, CFTC125Limits.ASSET_CLASS_CAPS[AssetClass.US_AGENCY])

        mmmf_pct = bd.get(AssetClass.MMMF_GOVT, Decimal("0")) + bd.get(AssetClass.MMMF_PRIME, Decimal("0"))
        self.assertLessEqual(mmmf_pct, CFTC125Limits.COMBINED_MMMF_CAP)

if __name__ == "__main__":
    unittest.main()
