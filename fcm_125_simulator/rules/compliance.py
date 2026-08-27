"""
CFTC Rule 1.25 Compliance and Concentration Engine.
Audits and validates an FCM customer fund investment portfolio against 17 CFR § 1.25.
"""

from decimal import Decimal
from typing import List, Tuple, Dict
from ..core.types import (
    AssetClass,
    ComplianceStatus,
    ComplianceRuleResult,
    CreditRating,
    to_decimal,
    round_bps,
    round_money
)
from ..core.portfolio import TreasuryPortfolio
from ..core.instruments import Position
from .cftc_125_limits import CFTC125Limits

class CFTC125ComplianceEngine:
    """
    Evaluates all statutory rules under 17 CFR § 1.25.
    """

    def __init__(self, warning_buffer: Decimal = Decimal("0.02")):
        """
        warning_buffer: e.g. 0.02 (200 bps). If cap is 25%, warning triggers at 23%.
        """
        self.warning_buffer = warning_buffer

    def evaluate_portfolio(self, portfolio: TreasuryPortfolio) -> Tuple[ComplianceStatus, List[ComplianceRuleResult]]:
        """
        Performs a full audit of the portfolio against CFTC Rule 1.25.
        Returns overall status and list of rule-by-rule results.
        """
        results: List[ComplianceRuleResult] = []
        tot_val = portfolio.total_portfolio_market_value

        if tot_val == Decimal("0"):
            return ComplianceStatus.COMPLIANT, results

        # 1. Asset Class Concentration Limits (§ 1.25(b)(3)(i))
        bd = portfolio.asset_class_breakdown()
        
        # Check combined MMMF cap (50% aggregate under § 1.25(b)(3)(i)(G))
        large_mmmf_val = bd.get(AssetClass.MMMF_GOVT_LARGE, Decimal("0")) + bd.get(AssetClass.MMMF_GOVT, Decimal("0"))
        small_mmmf_val = bd.get(AssetClass.MMMF_GOVT_SMALL, Decimal("0"))
        total_mmmf_val = large_mmmf_val + small_mmmf_val + bd.get(AssetClass.MMMF_PRIME, Decimal("0"))
        
        total_mmmf_pct = round_bps(total_mmmf_val / tot_val)
        mmmf_cap = CFTC125Limits.COMBINED_MMMF_CAP
        status = self._get_status(total_mmmf_pct, mmmf_cap)
        results.append(ComplianceRuleResult(
            rule_name="MMMF Aggregate Concentration (Combined Government MMFs)",
            citation="17 CFR § 1.25(b)(3)(i)(G)",
            status=status,
            current_value=total_mmmf_pct,
            limit_value=mmmf_cap,
            unit="ratio",
            message=f"Government MMF aggregate holding is {total_mmmf_pct * 100:.2f}% (Limit: {mmmf_cap * 100:.1f}%)",
            details={"market_value": total_mmmf_val}
        ))

        # Check Smaller MMF aggregate cap (10% under § 1.25(b)(3)(i)(G) if fund size < $1B)
        if small_mmmf_val > Decimal("0"):
            small_pct = round_bps(small_mmmf_val / tot_val)
            small_cap = CFTC125Limits.SMALL_MMMF_AGGREGATE_CAP
            status = self._get_status(small_pct, small_cap)
            results.append(ComplianceRuleResult(
                rule_name="Smaller Government MMF Aggregate (< $1B AUM)",
                citation="17 CFR § 1.25(b)(3)(i)(G)",
                status=status,
                current_value=small_pct,
                limit_value=small_cap,
                unit="ratio",
                message=f"Smaller MMF holdings are {small_pct * 100:.2f}% (Limit: {small_cap * 100:.1f}%)",
                details={"market_value": small_mmmf_val}
            ))

        # Check US Agency aggregate cap (50% under § 1.25(b)(3)(i)(B))
        agency_val = bd.get(AssetClass.US_AGENCY, Decimal("0"))
        agency_pct = round_bps(agency_val / tot_val)
        agency_cap = CFTC125Limits.ASSET_CLASS_CAPS[AssetClass.US_AGENCY]
        status = self._get_status(agency_pct, agency_cap)
        results.append(ComplianceRuleResult(
            rule_name="U.S. Agency/GSE Concentration",
            citation="17 CFR § 1.25(b)(3)(i)(B)",
            status=status,
            current_value=agency_pct,
            limit_value=agency_cap,
            unit="ratio",
            message=f"Agency GSE holdings are {agency_pct * 100:.2f}% (Limit: {agency_cap * 100:.1f}%)",
            details={"market_value": agency_val}
        ))

        # Check Prohibited Asset Classes: Commercial Paper & Bank CDs
        cp_val = bd.get(AssetClass.COMMERCIAL_PAPER, Decimal("0"))
        if cp_val > Decimal("0"):
            results.append(ComplianceRuleResult(
                rule_name="Prohibited Commercial Paper Holding",
                citation="17 CFR § 1.25(a)(1)(v)",
                status=ComplianceStatus.BREACH,
                current_value=round_bps(cp_val / tot_val),
                limit_value=Decimal("0.00"),
                unit="ratio",
                message=f"Commercial Paper is prohibited under Rule 1.25 (Current: ${cp_val:,.2f})",
                details={"market_value": cp_val}
            ))

        cd_val = bd.get(AssetClass.BANK_CD, Decimal("0"))
        if cd_val > Decimal("0"):
            results.append(ComplianceRuleResult(
                rule_name="Prohibited Bank CD Holding",
                citation="17 CFR § 1.25(a)(1)(iv)",
                status=ComplianceStatus.BREACH,
                current_value=round_bps(cd_val / tot_val),
                limit_value=Decimal("0.00"),
                unit="ratio",
                message=f"Bank Certificates of Deposit are prohibited under Rule 1.25 (Current: ${cd_val:,.2f})",
                details={"market_value": cd_val}
            ))

        # Check Municipal Obligations cap (10% under § 1.25(b)(3)(i)(C))
        muni_val = bd.get(AssetClass.MUNICIPAL, Decimal("0"))
        muni_pct = round_bps(muni_val / tot_val)
        muni_cap = CFTC125Limits.ASSET_CLASS_CAPS[AssetClass.MUNICIPAL]
        status = self._get_status(muni_pct, muni_cap)
        results.append(ComplianceRuleResult(
            rule_name="Municipal GO Obligations Concentration",
            citation="17 CFR § 1.25(b)(3)(i)(C)",
            status=status,
            current_value=muni_pct,
            limit_value=muni_cap,
            unit="ratio",
            message=f"Municipal GO holding is {muni_pct * 100:.2f}% (Limit: {muni_cap * 100:.1f}%)",
            details={"market_value": muni_val}
        ))

        # 2. Single-Issuer & Single-GSE Concentration Limits (§ 1.25(b)(3)(ii))
        # Direct US Government obligations and Fed Cash are exempt (§ 1.25(b)(3)(v)).
        # GSE issuers (FHLB, FNMA, FHLMC, FFCB, FARMER_MAC) have 25% statutory cap per issuer.
        # Municipal issuers have 5% statutory cap per issuer.
        non_exempt_issuers: Dict[str, Decimal] = {}
        gse_issuers = {"FHLB", "FNMA", "FHLMC", "FFCB", "FARMER_MAC"}
        muni_issuers = {"STATE_OF_CALIFORNIA", "CITY_OF_NEW_YORK", "STATE_OF_TEXAS"}

        for p in portfolio.positions:
            if p.instrument.asset_class in (
                AssetClass.US_TREASURY,
                AssetClass.CASH_CENTRAL_BANK,
                AssetClass.REVERSE_REPO,
                AssetClass.MMMF_GOVT,
                AssetClass.MMMF_GOVT_LARGE,
                AssetClass.MMMF_GOVT_SMALL,
                AssetClass.MMMF_PRIME
            ):
                continue
            iss = p.instrument.issuer
            non_exempt_issuers[iss] = non_exempt_issuers.get(iss, Decimal("0.00")) + p.market_value

        for iss, iss_val in non_exempt_issuers.items():
            iss_pct = round_bps(iss_val / tot_val)
            if iss in gse_issuers:
                cap = CFTC125Limits.SINGLE_GSE_ISSUER_CAP # 25% per GSE issuer
                rule_desc = "Single Issuer Concentration (GSE)"
            elif iss in muni_issuers or any("MUNI" in iss for _ in [1]):
                cap = CFTC125Limits.SINGLE_MUNI_ISSUER_CAP # 5% per Muni issuer
                rule_desc = "Single Issuer Concentration (Municipal)"
            else:
                cap = CFTC125Limits.SINGLE_ISSUER_CAP # 5% general issuer cap
                rule_desc = "Single Issuer Concentration"

            status = self._get_status(iss_pct, cap)
            if status != ComplianceStatus.COMPLIANT or iss_pct > (cap - self.warning_buffer):
                results.append(ComplianceRuleResult(
                    rule_name=f"{rule_desc}: {iss}",
                    citation="17 CFR § 1.25(b)(3)(ii)",
                    status=status,
                    current_value=iss_pct,
                    limit_value=cap,
                    unit="ratio",
                    message=f"Issuer '{iss}' is {iss_pct * 100:.2f}% (Limit: {cap * 100:.1f}%)",
                    details={"issuer": iss, "market_value": iss_val}
                ))

        # 3. Single-Fund (10%) and Fund Family (25%) Limits for MMFs (§ 1.25(b)(3)(iii))
        mmmf_positions = [
            p for p in portfolio.positions 
            if p.instrument.asset_class in (AssetClass.MMMF_GOVT, AssetClass.MMMF_GOVT_LARGE, AssetClass.MMMF_GOVT_SMALL, AssetClass.MMMF_PRIME)
        ]

        # Single fund cap: 10% per fund
        for p in mmmf_positions:
            fund_pct = round_bps(p.market_value / tot_val)
            fund_cap = CFTC125Limits.MMMF_SINGLE_FUND_CAP # 10%
            status = self._get_status(fund_pct, fund_cap)
            if status != ComplianceStatus.COMPLIANT or fund_pct > (fund_cap - self.warning_buffer):
                results.append(ComplianceRuleResult(
                    rule_name=f"Single MMF Fund Cap: {p.instrument.name}",
                    citation="17 CFR § 1.25(b)(3)(iii)",
                    status=status,
                    current_value=fund_pct,
                    limit_value=fund_cap,
                    unit="ratio",
                    message=f"Fund '{p.instrument.name}' is {fund_pct * 100:.2f}% (Limit: {fund_cap * 100:.1f}%)",
                    details={"fund_id": p.instrument.id, "market_value": p.market_value}
                ))

        # Fund family cap: 25% per fund family
        mmmf_families = set(p.instrument.issuer_family for p in mmmf_positions)
        for fam in mmmf_families:
            fam_mmmf_val = sum((
                p.market_value for p in mmmf_positions if p.instrument.issuer_family == fam
            ), Decimal("0.00"))
            fam_pct = round_bps(fam_mmmf_val / tot_val)
            fam_cap = CFTC125Limits.MMMF_FAMILY_CAP # 25%
            status = self._get_status(fam_pct, fam_cap)
            if status != ComplianceStatus.COMPLIANT or fam_pct > (fam_cap - self.warning_buffer):
                results.append(ComplianceRuleResult(
                    rule_name=f"MMMF Fund Family Concentration: {fam}",
                    citation="17 CFR § 1.25(b)(3)(iii)",
                    status=status,
                    current_value=fam_pct,
                    limit_value=fam_cap,
                    unit="ratio",
                    message=f"MMMF family '{fam}' is {fam_pct * 100:.2f}% (Limit: {fam_cap * 100:.1f}%)",
                    details={"family": fam, "market_value": fam_mmmf_val}
                ))

        # 4. Reverse Repo Counterparty Group Limit (§ 1.25(d)(2)): 25% per counterparty group
        repo_positions = [p for p in portfolio.positions if p.instrument.asset_class == AssetClass.REVERSE_REPO]
        repo_counterparties = set(p.instrument.issuer_family for p in repo_positions)
        for cp in repo_counterparties:
            cp_val = sum((p.market_value for p in repo_positions if p.instrument.issuer_family == cp), Decimal("0.00"))
            cp_pct = round_bps(cp_val / tot_val)
            # Bilateral repos with commercial entities have 25% single counterparty group cap; FICC CCP is central clearing
            if cp != "FICC":
                cp_cap = CFTC125Limits.SINGLE_REPO_COUNTERPARTY_GROUP_CAP # 25%
                status = self._get_status(cp_pct, cp_cap)
                if status != ComplianceStatus.COMPLIANT or cp_pct > (cp_cap - self.warning_buffer):
                    results.append(ComplianceRuleResult(
                        rule_name=f"Repo Counterparty Group Limit: {cp}",
                        citation="17 CFR § 1.25(d)(2)",
                        status=status,
                        current_value=cp_pct,
                        limit_value=cp_cap,
                        unit="ratio",
                        message=f"Reverse repo counterparty group '{cp}' is {cp_pct * 100:.2f}% (Limit: {cp_cap * 100:.1f}%)",
                        details={"counterparty": cp, "market_value": cp_val}
                    ))

        # 5. Money Market Fund % of Fund AUM Cap (§ 1.25(b)(3)(iii)) - Max 10% of external fund AUM
        for p in mmmf_positions:
            if p.instrument.fund_total_aum:
                aum_pct = round_bps(p.market_value / p.instrument.fund_total_aum)
                aum_cap = CFTC125Limits.MMMF_MAX_PCT_OF_FUND_AUM
                status = self._get_status(aum_pct, aum_cap)
                if status != ComplianceStatus.COMPLIANT or aum_pct > (aum_cap - self.warning_buffer):
                    results.append(ComplianceRuleResult(
                        rule_name=f"MMMF Fund AUM Cap: {p.instrument.name}",
                        citation="17 CFR § 1.25(b)(3)(iii)",
                        status=status,
                        current_value=aum_pct,
                        limit_value=aum_cap,
                        unit="ratio",
                        message=f"Holding is {aum_pct * 100:.2f}% of total fund AUM (Limit: {aum_cap * 100:.1f}%)",
                        details={"fund_name": p.instrument.name, "fund_aum": p.instrument.fund_total_aum}
                    ))

        # 6. Portfolio Weighted Average Maturity (WAM) (§ 1.25(b)(5)) - Max 2.0 years (730 days)
        wam_years = portfolio.weighted_average_maturity_years()
        wam_cap = CFTC125Limits.PORTFOLIO_MAX_WAM_YEARS
        status = self._get_status(wam_years, wam_cap)
        results.append(ComplianceRuleResult(
            rule_name="Portfolio WAM (Years)",
            citation="17 CFR § 1.25(b)(5)",
            status=status,
            current_value=wam_years,
            limit_value=wam_cap,
            unit="years",
            message=f"Portfolio WAM is {wam_years:.3f} years ({wam_years * 12:.1f} months) (Limit: 2.000 years)",
            details={"wam_days": portfolio.weighted_average_maturity_days()}
        ))

        # 7. Single Security Tenor Restrictions
        for p in portfolio.positions:
            days = p.instrument.days_to_maturity(portfolio.as_of_date)
            # Commercial Paper: <= 180 days
            if p.instrument.asset_class == AssetClass.COMMERCIAL_PAPER:
                if days > CFTC125Limits.COMMERCIAL_PAPER_MAX_DAYS:
                    results.append(ComplianceRuleResult(
                        rule_name=f"CP Tenor Limit: {p.instrument.name}",
                        citation="17 CFR § 1.25(b)(5)",
                        status=ComplianceStatus.BREACH,
                        current_value=to_decimal(days),
                        limit_value=to_decimal(CFTC125Limits.COMMERCIAL_PAPER_MAX_DAYS),
                        unit="days",
                        message=f"CP '{p.instrument.name}' has maturity of {days} days (Max: 180 days)",
                        details={"instrument_id": p.instrument.id}
                    ))
            # Municipal: <= 730 days (2 years)
            elif p.instrument.asset_class == AssetClass.MUNICIPAL:
                if days > CFTC125Limits.MUNICIPAL_MAX_DAYS:
                    results.append(ComplianceRuleResult(
                        rule_name=f"Municipal Tenor Limit: {p.instrument.name}",
                        citation="17 CFR § 1.25(b)(5)",
                        status=ComplianceStatus.BREACH,
                        current_value=to_decimal(days),
                        limit_value=to_decimal(CFTC125Limits.MUNICIPAL_MAX_DAYS),
                        unit="days",
                        message=f"Municipal bond '{p.instrument.name}' has maturity of {days} days (Max: 730 days)",
                        details={"instrument_id": p.instrument.id}
                    ))

        # 8. Embedded Derivative Check (§ 1.25(b)(2)(ii))
        for p in portfolio.positions:
            if "fail" in p.instrument.embedded_derivative_check.lower() or "breach" in p.instrument.embedded_derivative_check.lower():
                results.append(ComplianceRuleResult(
                    rule_name=f"Embedded Derivative Restriction: {p.instrument.name}",
                    citation="17 CFR § 1.25(b)(2)(ii)",
                    status=ComplianceStatus.BREACH,
                    current_value=Decimal("1"),
                    limit_value=Decimal("0"),
                    unit="flags",
                    message=f"Instrument '{p.instrument.name}' contains prohibited embedded derivatives: {p.instrument.embedded_derivative_check}",
                    details={"instrument_id": p.instrument.id}
                ))

        # 9. Informational Credit Risk Assessment (§ 1.25(b)(1))
        # Note: NRSRO credit ratings are informational only post-Dodd-Frank § 939A.
        for p in portfolio.positions:
            if p.instrument.credit_rating == CreditRating.SUB_INVESTMENT:
                results.append(ComplianceRuleResult(
                    rule_name=f"Credit Risk Assessment: {p.instrument.name}",
                    citation="17 CFR § 1.25(b)(1)",
                    status=ComplianceStatus.BREACH,
                    current_value=Decimal("0"),
                    limit_value=Decimal("1"),
                    unit="rating",
                    message=f"Instrument '{p.instrument.name}' fails minimal credit risk standard ({p.instrument.credit_risk_assessment})",
                    details={"instrument_id": p.instrument.id, "rating_informational": p.instrument.credit_rating_informational}
                ))

        # Determine overall portfolio compliance status
        overall = ComplianceStatus.COMPLIANT
        for r in results:
            if r.status == ComplianceStatus.BREACH:
                overall = ComplianceStatus.BREACH
                break
            elif r.status == ComplianceStatus.WARNING and overall == ComplianceStatus.COMPLIANT:
                overall = ComplianceStatus.WARNING

        return overall, results

    def _get_status(self, current: Decimal, limit: Decimal) -> ComplianceStatus:
        if current > limit:
            return ComplianceStatus.BREACH
        elif current > (limit - self.warning_buffer):
            return ComplianceStatus.WARNING
        return ComplianceStatus.COMPLIANT
