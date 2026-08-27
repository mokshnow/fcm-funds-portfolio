"""
Unit tests for Fixed Income Quantitative Pricing and Sensitivity Math.
"""

import unittest
from decimal import Decimal
from datetime import date, timedelta

from fcm_125_simulator.core.types import AssetClass, CreditRating, LiquidityTier
from fcm_125_simulator.core.instruments import Instrument, Position
from fcm_125_simulator.core.portfolio import TreasuryPortfolio
from fcm_125_simulator.analytics.fixed_income import FixedIncomeAnalytics
from fcm_125_simulator.analytics.mtm_pricing import MTMPricingEngine

class TestFixedIncomeMath(unittest.TestCase):

    def setUp(self):
        self.as_of = date(2026, 8, 27)

    def test_tbill_duration_calculation(self):
        # 1-Year (365 days) zero-coupon T-Bill at 5% YTM
        tbill = Instrument(
            id="UST-TBILL-1Y-TEST",
            name="1Y T-Bill",
            asset_class=AssetClass.US_TREASURY,
            issuer="US_TREASURY",
            issuer_family="US_TREASURY",
            maturity_date=self.as_of + timedelta(days=365),
            coupon_rate=Decimal("0.00"),
            credit_rating=CreditRating.AAA,
            liquidity_tier=LiquidityTier.TIER_1_SAME_DAY,
            yield_to_maturity=Decimal("0.0500"),
            clean_price=Decimal("95.2381"),
            bid_ask_spread_bps=Decimal("1.0")
        )
        mac_dur, mod_dur, conv = FixedIncomeAnalytics.calculate_instrument_duration_convexity(tbill, self.as_of)
        
        # For 1Y zero coupon: Macaulay duration is exactly 1.0 years
        self.assertAlmostEqual(float(mac_dur), 1.0, places=3)
        # Modified duration = 1.0 / (1 + 0.05) = ~0.9524 years
        self.assertAlmostEqual(float(mod_dur), 1.0 / 1.05, places=3)
        self.assertGreater(conv, Decimal("0.0"))

    def test_overnight_repo_duration_is_zero(self):
        repo = Instrument(
            id="REPO-TEST",
            name="Overnight Repo",
            asset_class=AssetClass.REVERSE_REPO,
            issuer="BNY",
            issuer_family="BNY",
            maturity_date=self.as_of + timedelta(days=1),
            coupon_rate=Decimal("0.00"),
            credit_rating=CreditRating.AAA,
            liquidity_tier=LiquidityTier.TIER_0_INSTANT,
            yield_to_maturity=Decimal("0.0530"),
            clean_price=Decimal("100.00"),
            bid_ask_spread_bps=Decimal("0.0")
        )
        mac_dur, mod_dur, conv = FixedIncomeAnalytics.calculate_instrument_duration_convexity(repo, self.as_of)
        self.assertEqual(mac_dur, Decimal("0.0"))
        self.assertEqual(mod_dur, Decimal("0.0"))
        self.assertEqual(conv, Decimal("0.0"))

    def test_dv01_revaluation_accuracy(self):
        # $100M in 2Y Note with modified duration ~ 1.85 yrs
        # DV01 ~ 1.85 * $100M * 0.0001 = $18,500
        note = Instrument(
            id="NOTE-2Y-TEST",
            name="2Y Note",
            asset_class=AssetClass.US_TREASURY,
            issuer="US_TREASURY",
            issuer_family="US_TREASURY",
            maturity_date=self.as_of + timedelta(days=730),
            coupon_rate=Decimal("0.0450"),
            credit_rating=CreditRating.AAA,
            liquidity_tier=LiquidityTier.TIER_1_SAME_DAY,
            yield_to_maturity=Decimal("0.0450"),
            clean_price=Decimal("100.00"),
            bid_ask_spread_bps=Decimal("1.5")
        )
        pos = Position(note, Decimal("100000000.00"), Decimal("100000000.00"))
        dv01 = FixedIncomeAnalytics.calculate_position_dv01(pos, self.as_of)
        self.assertGreater(dv01, Decimal("15000.00"))
        self.assertLess(dv01, Decimal("22000.00"))

        # Test +100 bps shift: price should drop roughly 100 * DV01
        portfolio = TreasuryPortfolio(
            as_of_date=self.as_of,
            customer_segregated_liability=Decimal("100000000.00"),
            firm_residual_interest=Decimal("5000000.00"),
            cash_at_fed=Decimal("0.00"),
            positions=[pos]
        )
        new_mv, pnl, _ = MTMPricingEngine.revalue_portfolio_under_shock(
            portfolio, yield_shift_bps=Decimal("100.0")
        )
        expected_drop = dv01 * Decimal("100.0")
        actual_drop = -pnl
        # Within 10% due to convexity offset
        self.assertAlmostEqual(float(actual_drop), float(expected_drop), delta=float(expected_drop * Decimal("0.10")))

if __name__ == "__main__":
    unittest.main()
