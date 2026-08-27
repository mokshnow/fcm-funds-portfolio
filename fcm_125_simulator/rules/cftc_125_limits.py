"""
CFTC Regulation § 1.25 Statutory and Regulatory Limits.
Source: 17 CFR § 1.25 - Investment of customer funds.
"""

from decimal import Decimal
from typing import Dict, Optional
from ..core.types import AssetClass

class CFTC125Limits:
    """
    Statutory concentration and maturity limits codified under 17 CFR § 1.25.
    """
    # Asset Class Concentration Caps (§ 1.25(b)(3)(i))
    ASSET_CLASS_CAPS: Dict[AssetClass, Optional[Decimal]] = {
        AssetClass.US_TREASURY: None,                   # No Rule 1.25 limit (§ 1.25(b)(3)(v))
        AssetClass.CASH_CENTRAL_BANK: None,             # No Rule 1.25 limit (Depository rules § 1.20)
        AssetClass.US_AGENCY: Decimal("0.50"),          # 50% aggregate (§ 1.25(b)(3)(i)(B))
        AssetClass.MUNICIPAL: Decimal("0.10"),          # 10% aggregate (§ 1.25(b)(3)(i)(C))
        AssetClass.MMMF_GOVT_LARGE: Decimal("0.50"),    # 50% aggregate for large qualifying MMFs (>= $1B AUM)
        AssetClass.MMMF_GOVT_SMALL: Decimal("0.10"),    # 10% aggregate for smaller MMFs (< $1B AUM)
        AssetClass.MMMF_GOVT: Decimal("0.50"),          # 50% aggregate (default qualifying)
        AssetClass.REVERSE_REPO: None,                  # Underlying-security limits apply
        AssetClass.COMMERCIAL_PAPER: Decimal("0.00"),   # 0% - Prohibited
        AssetClass.BANK_CD: Decimal("0.00"),            # 0% - Prohibited
    }

    # Agency GSE Issuer Cap (§ 1.25(b)(3)(ii)): 25% per issuer
    SINGLE_GSE_ISSUER_CAP: Decimal = Decimal("0.25")

    # Municipal Issuer Cap (§ 1.25(b)(3)(ii)): 5% per issuer
    SINGLE_MUNI_ISSUER_CAP: Decimal = Decimal("0.05")

    # Large Qualifying MMF Limits (§ 1.25(b)(3)(i)(G) & § 1.25(c)(1))
    LARGE_MMMF_AGGREGATE_CAP: Decimal = Decimal("0.50")   # 50% aggregate
    LARGE_MMMF_SINGLE_FUND_CAP: Decimal = Decimal("0.10") # 10% per fund
    LARGE_MMMF_FAMILY_CAP: Decimal = Decimal("0.25")      # 25% per fund family

    # Smaller MMF Limits
    SMALL_MMMF_AGGREGATE_CAP: Decimal = Decimal("0.10")   # 10% aggregate
    SMALL_MMMF_SINGLE_FUND_CAP: Decimal = Decimal("0.10") # 10% per fund
    SMALL_MMMF_FAMILY_CAP: Decimal = Decimal("0.25")      # 25% per family

    # Combined MMF / Family Limits
    COMBINED_MMMF_CAP: Decimal = Decimal("0.50")
    MMMF_SINGLE_FUND_CAP: Decimal = Decimal("0.10")       # 10% per fund
    MMMF_FAMILY_CAP: Decimal = Decimal("0.25")            # 25% per fund family

    # Single Counterparty Group Limit for Reverse Repo (§ 1.25(d)(2)): 25%
    SINGLE_REPO_COUNTERPARTY_GROUP_CAP: Decimal = Decimal("0.25")
    SINGLE_REPO_COUNTERPARTY_CAP: Decimal = Decimal("0.25")

    # General Single Issuer Cap (§ 1.25(b)(3)(ii))
    SINGLE_ISSUER_CAP: Decimal = Decimal("0.05")

    # Fund Size / AUM Cap (§ 1.25(b)(3)(iii))
    MMMF_MAX_PCT_OF_FUND_AUM: Decimal = Decimal("0.10")   # Max 10% of external fund AUM

    # Maturity / Duration Limits (§ 1.25(b)(5))
    PORTFOLIO_MAX_WAM_DAYS: Decimal = Decimal("730")      # 24 months (2.0 years = 730 days)
    PORTFOLIO_MAX_WAM_YEARS: Decimal = Decimal("2.000")   # 2.0 years

    # Individual Security Tenor Caps
    COMMERCIAL_PAPER_MAX_DAYS: int = 180
    MUNICIPAL_MAX_DAYS: int = 730                         # Max 2 years for Munis
    FLOATING_RATE_MAX_DAYS: int = 397                     # Max 397 days for floating rate paper
