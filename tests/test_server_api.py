"""
Unit tests for the Web Dashboard REST API payload generation.
"""

import unittest
from decimal import Decimal
from datetime import date

from fcm_125_simulator.core.presets import PortfolioPresets
from fcm_125_simulator.ui.server import build_full_dashboard_payload, DashboardRequestHandler

class TestServerAPI(unittest.TestCase):

    def setUp(self):
        self.as_of = date(2026, 8, 27)
        self.portfolio = PortfolioPresets.get_balanced_institutional_fcm(self.as_of)

    def test_build_full_dashboard_payload(self):
        payload = build_full_dashboard_payload(
            portfolio=self.portfolio,
            yield_shift_bps=50.0,
            margin_call_amount=75000000.0,
            credit_facility_allowed=True
        )

        self.assertIn("total_customer_float", payload)
        self.assertEqual(payload["total_customer_float"], 500000000.0)
        self.assertIn("annual_nii", payload)
        self.assertIn("compliance_status", payload)
        self.assertEqual(payload["compliance_status"], "COMPLIANT")
        self.assertIn("liquidity_waterfall", payload)
        self.assertTrue(payload["liquidity_waterfall"]["is_fully_funded"])
        self.assertIn("segregation_statement", payload)
        self.assertGreater(payload["segregation_statement"]["excess_or_deficit"], 0)
        self.assertIn("scenario_matrix", payload)
        self.assertEqual(len(payload["scenario_matrix"]), 5)
        self.assertIn("asset_allocations", payload)
        self.assertIn("positions_table", payload)
        self.assertGreater(len(payload["positions_table"]), 0)

    def test_nii_accuracy_kalshi_preset(self):
        kalshi_float = Decimal("11370355.00")
        portfolio = PortfolioPresets.get_balanced_institutional_fcm(self.as_of, kalshi_float)
        payload = build_full_dashboard_payload(portfolio)

        # Total positions sum check
        positions_nii_sum = sum(p["annual_nii"] for p in payload["positions_table"])
        self.assertAlmostEqual(positions_nii_sum, payload["annual_nii"], places=1)
        
        # Portfolio yield check
        expected_yield = (payload["annual_nii"] / payload["total_portfolio_market_value"]) * 100.0
        self.assertAlmostEqual(payload["portfolio_yield_pct"], expected_yield, places=2)

    def test_nii_accuracy_100pct_fed_cash_scenario(self):
        from fcm_125_simulator.ui.server import create_custom_portfolio_from_allocations
        total_float = Decimal("11139675.00")
        firm_ri = Decimal("4642477.00")
        allocations = {"CASH-FED-RESERVE": float(total_float)}
        
        portfolio = create_custom_portfolio_from_allocations(self.as_of, total_float, allocations, firm_ri)
        payload = build_full_dashboard_payload(portfolio)

        total_assets = float(total_float + firm_ri)
        expected_nii = total_assets * 0.0380 # Fed IORB rate = 3.80%

        self.assertAlmostEqual(payload["annual_nii"], expected_nii, places=1)
        self.assertAlmostEqual(payload["portfolio_yield_pct"], 3.80, places=2)
        self.assertEqual(len(payload["positions_table"]), 1)
        self.assertEqual(payload["positions_table"][0]["id"], "CASH-FED-RESERVE")
        self.assertAlmostEqual(payload["positions_table"][0]["market_value"], total_assets, places=1)

    def test_nii_accuracy_partial_allocations_scenario(self):
        from fcm_125_simulator.ui.server import create_custom_portfolio_from_allocations
        total_float = Decimal("10000000.00")
        firm_ri = Decimal("500000.00")
        allocations = {
            "UST-TBILL-13W": 5000000.0
        }
        portfolio = create_custom_portfolio_from_allocations(self.as_of, total_float, allocations, firm_ri)
        payload = build_full_dashboard_payload(portfolio)

        expected_nii = (5000000.0 * 0.03802) + (5500000.0 * 0.0380)
        self.assertAlmostEqual(payload["annual_nii"], expected_nii, delta=100.0)

        # Verify positions table sum equals total NII
        positions_nii_sum = sum(p["annual_nii"] for p in payload["positions_table"])
        self.assertAlmostEqual(positions_nii_sum, payload["annual_nii"], delta=1.0)

    def test_nii_accuracy_fully_diversified_portfolio(self):
        from fcm_125_simulator.ui.server import create_custom_portfolio_from_allocations
        total_float = Decimal("50000000.00") # $50M float
        firm_ri = Decimal("2500000.00")     # $2.5M RI
        allocations = {
            "REPO-ON-SOFR": 10000000.0,         # 3.80% -> 380,000
            "UST-TBILL-13W": 10000000.0,        # 3.802% -> 380,200
            "MMMF-BLK-TREASURY": 5000000.0,     # 3.78% -> 189,000
            "GSE-FNMA-3135G0Q22": 5000000.0,    # 3.95% -> 197,500
            "GSE-FHLB-3130B9RC6": 5000000.0,    # 4.15% -> 207,500
            "GSE-FFCB-3133EWXT2": 2500000.0,    # 4.10% -> 102,500
            "MUNI-NYC-64966Q": 2500000.0,       # 3.70% -> 92,500
            # Total securities = 40,000,000
            # Remaining customer cash at Fed = 10,000,000 + 2,500,000 RI = 12,500,000 @ 3.80% -> 475,000
        }
        portfolio = create_custom_portfolio_from_allocations(self.as_of, total_float, allocations, firm_ri)
        payload = build_full_dashboard_payload(portfolio)

        expected_securities_nii = (
            10000000.0 * 0.0380 +
            10000000.0 * 0.03802 +
            5000000.0 * 0.0378 +
            5000000.0 * 0.0395 +
            5000000.0 * 0.0415 +
            2500000.0 * 0.0410 +
            2500000.0 * 0.0370
        )
        expected_fed_nii = 12500000.0 * 0.0380
        expected_total_nii = expected_securities_nii + expected_fed_nii

        self.assertAlmostEqual(payload["annual_nii"], expected_total_nii, delta=1.0)

        # Reconcile positions table sum with payload annual NII
        positions_nii_sum = sum(p["annual_nii"] for p in payload["positions_table"])
        self.assertAlmostEqual(positions_nii_sum, payload["annual_nii"], delta=1.0)
        
        # Verify portfolio yield equals annual_nii / total_market_value
        expected_yield = (payload["annual_nii"] / payload["total_portfolio_market_value"]) * 100.0
        self.assertAlmostEqual(payload["portfolio_yield_pct"], expected_yield, places=2)

if __name__ == "__main__":
    unittest.main()
