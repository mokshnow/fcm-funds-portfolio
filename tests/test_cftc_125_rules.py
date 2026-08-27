"""
Unit tests for CFTC Rule 1.25 Statutory Concentration & Tenor Limits.
"""

import unittest
from decimal import Decimal
from datetime import date, timedelta

from fcm_125_simulator.core.types import (
    AssetClass,
    CreditRating,
    LiquidityTier,
    ComplianceStatus
)
from fcm_125_simulator.core.instruments import Instrument, Position
from fcm_125_simulator.core.portfolio import TreasuryPortfolio
from fcm_125_simulator.core.presets import PortfolioPresets, get_standard_universe
from fcm_125_simulator.rules.compliance import CFTC125ComplianceEngine
from fcm_125_simulator.rules.cftc_125_limits import CFTC125Limits

class TestCFTC125Rules(unittest.TestCase):

    def setUp(self):
        self.as_of = date(2026, 8, 27)
        self.engine = CFTC125ComplianceEngine()
        self.float_val = Decimal("100000000.00") # $100M

    def test_balanced_portfolio_is_fully_compliant(self):
        portfolio = PortfolioPresets.get_balanced_institutional_fcm(self.as_of, self.float_val)
        status, results = self.engine.evaluate_portfolio(portfolio)
        self.assertEqual(status, ComplianceStatus.COMPLIANT)
        self.assertLessEqual(portfolio.weighted_average_maturity_years(), Decimal("2.000"))

    def test_mmmf_concentration_cap_breach(self):
        # 60% in MMMF (exceeds 50% statutory cap)
        insts = {inst.id: inst for inst in get_standard_universe(self.as_of)}
        portfolio = TreasuryPortfolio(
            as_of_date=self.as_of,
            customer_segregated_liability=self.float_val,
            firm_residual_interest=Decimal("5000000.00"),
            cash_at_fed=Decimal("40000000.00"),
            positions=[
                Position(insts["MMMF-BLK-TREASURY"], Decimal("60000000.00"), Decimal("60000000.00"))
            ]
        )
        status, results = self.engine.evaluate_portfolio(portfolio)
        self.assertEqual(status, ComplianceStatus.BREACH)
        mmmf_rule = [r for r in results if "MMMF Aggregate" in r.rule_name][0]
        self.assertEqual(mmmf_rule.status, ComplianceStatus.BREACH)
        self.assertGreater(mmmf_rule.current_value, CFTC125Limits.COMBINED_MMMF_CAP)

    def test_single_issuer_concentration_breach(self):
        # 15% in single municipal issuer (exceeds 5% single municipal issuer cap under § 1.25(b)(3)(ii))
        insts = {inst.id: inst for inst in get_standard_universe(self.as_of)}
        portfolio = TreasuryPortfolio(
            as_of_date=self.as_of,
            customer_segregated_liability=self.float_val,
            firm_residual_interest=Decimal("5000000.00"),
            cash_at_fed=Decimal("85000000.00"),
            positions=[
                Position(insts["MUNI-CA-13063C5D8"], Decimal("15000000.00"), Decimal("15000000.00"))
            ]
        )
        status, results = self.engine.evaluate_portfolio(portfolio)
        self.assertEqual(status, ComplianceStatus.BREACH)
        issuer_rule = [r for r in results if "Single Issuer" in r.rule_name and "STATE_OF_CALIFORNIA" in r.rule_name][0]
        self.assertEqual(issuer_rule.status, ComplianceStatus.BREACH)

    def test_wam_limit_breach(self):
        # Synthetic 5-Year Notes => WAM = 5.0 years (exceeds 2.0 yr / 24 mo limit under § 1.25(b)(5))
        long_note = Instrument(
            id="UST-NOTE-5Y",
            name="US Treasury Note 5-Year",
            asset_class=AssetClass.US_TREASURY,
            issuer="US_TREASURY",
            issuer_family="US_TREASURY",
            maturity_date=self.as_of + timedelta(days=1825),
            coupon_rate=Decimal("0.0425"),
            credit_rating=CreditRating.AAA,
            liquidity_tier=LiquidityTier.TIER_1_SAME_DAY,
            yield_to_maturity=Decimal("0.0425"),
            clean_price=Decimal("100.00"),
            bid_ask_spread_bps=Decimal("2.0"),
            cusip="912828YY2"
        )
        portfolio = TreasuryPortfolio(
            as_of_date=self.as_of,
            customer_segregated_liability=self.float_val,
            firm_residual_interest=Decimal("5000000.00"),
            cash_at_fed=Decimal("0.00"),
            positions=[
                Position(long_note, Decimal("100000000.00"), Decimal("100000000.00"))
            ]
        )
        status, results = self.engine.evaluate_portfolio(portfolio)
        self.assertEqual(status, ComplianceStatus.BREACH)
        wam_rule = [r for r in results if "Portfolio WAM" in r.rule_name][0]
        self.assertEqual(wam_rule.status, ComplianceStatus.BREACH)
        self.assertGreater(portfolio.weighted_average_maturity_years(), Decimal("2.000"))

    def test_municipal_tenor_limit_breach(self):
        # Municipal Bond with 3-year maturity (exceeds 2-year / 730 days limit under § 1.25(b)(5))
        long_muni = Instrument(
            id="MUNI-ILLEGAL-3Y",
            name="Illegal 3-Year Municipal Bond",
            asset_class=AssetClass.MUNICIPAL,
            issuer="STATE_OF_CALIFORNIA",
            issuer_family="CALIFORNIA",
            maturity_date=self.as_of + timedelta(days=1095),
            coupon_rate=Decimal("0.0450"),
            credit_rating=CreditRating.AA,
            liquidity_tier=LiquidityTier.TIER_3_TERM,
            yield_to_maturity=Decimal("0.0450"),
            clean_price=Decimal("100.00"),
            bid_ask_spread_bps=Decimal("15.0")
        )
        portfolio = TreasuryPortfolio(
            as_of_date=self.as_of,
            customer_segregated_liability=self.float_val,
            firm_residual_interest=Decimal("5000000.00"),
            cash_at_fed=Decimal("96000000.00"),
            positions=[
                Position(long_muni, Decimal("4000000.00"), Decimal("4000000.00"))
            ]
        )
        status, results = self.engine.evaluate_portfolio(portfolio)
        self.assertEqual(status, ComplianceStatus.BREACH)
        muni_rule = [r for r in results if "Municipal Tenor Limit" in r.rule_name][0]
        self.assertEqual(muni_rule.status, ComplianceStatus.BREACH)

if __name__ == "__main__":
    unittest.main()
