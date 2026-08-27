"""
Core types, enumerations, and data classes for the CFTC Rule 1.25 Simulator.
Enforces Decimal precision for all financial quantities.
"""

from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import date, datetime

def to_decimal(val: Any) -> Decimal:
    """Safely converts float/int/str to Decimal."""
    if isinstance(val, Decimal):
        return val
    return Decimal(str(val))

def round_money(val: Decimal) -> Decimal:
    """Rounds to nearest cent ($0.01)."""
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def round_bps(val: Decimal) -> Decimal:
    """Rounds basis points/percentages to 4 decimal places."""
    return val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)

class YieldType(str, Enum):
    AUCTION_INVESTMENT_RATE = "AUCTION_INVESTMENT_RATE"  # U.S. Treasury Bill auction investment rate
    YTM = "YTM"                                          # Yield to Maturity (Fixed Rate Notes/Bonds)
    INDEX_EFFECTIVE = "INDEX_EFFECTIVE"                  # Floating Rate Note (e.g. 13W T-Bill index + spread / SOFR + spread)
    SEC_7DAY = "SEC_7DAY"                                # SEC 7-Day Current Yield (Rule 2a-7 MMF)
    FED_IORB = "FED_IORB"                                # Federal Reserve Interest on Reserve Balances
    CONTRACT_CUSTODY = "CONTRACT_CUSTODY"                # Contractual Commercial Bank Custodial Rate
    REPO_RATE = "REPO_RATE"                              # Overnight Collateralized Repurchase Rate (SOFR O/N)

class AssetClass(str, Enum):
    US_TREASURY = "US_TREASURY"          # Direct US Obligations (Bills, Notes, Bonds) - No Rule 1.25 limit
    US_AGENCY = "US_AGENCY"              # GSE / Agency Debentures (FHLB, FNMA, FHLMC) - 50% cap
    MMMF_GOVT_LARGE = "MMMF_GOVT_LARGE"  # Large Qualifying Govt MMFs/Treasury ETFs (>= $1B AUM) - 50% cap
    MMMF_GOVT_SMALL = "MMMF_GOVT_SMALL"  # Smaller Govt MMFs/Treasury ETFs (< $1B AUM) - 10% cap
    MMMF_GOVT = "MMMF_GOVT"              # Rule 2a-7 Government Money Market Fund (Generic/Large default) - 50% cap
    MMMF_PRIME = "MMMF_PRIME"            # Rule 2a-7 Prime Money Market Fund (Deprecated/Prohibited)
    REVERSE_REPO = "REVERSE_REPO"        # Reverse Repurchase Agreements (Underlying limits apply; 25% counterparty group)
    COMMERCIAL_PAPER = "COMMERCIAL_PAPER"# Prime CP - Prohibited (0% cap)
    BANK_CD = "BANK_CD"                  # Certificates of Deposit - Prohibited (0% cap)
    MUNICIPAL = "MUNICIPAL"              # General Obligation Munis - 10% cap, max 2 yr maturity, 5% issuer cap
    CASH_CENTRAL_BANK = "CASH_CENTRAL_BANK" # Cash on deposit at Federal Reserve / Commercial Bank Custody (§ 1.20)

class CreditRating(str, Enum):
    AAA = "AAA"
    AA_PLUS = "AA+"
    AA = "AA"
    AA_MINUS = "AA-"
    A_PLUS = "A+"
    A = "A"
    A_1_P_1 = "A-1/P-1" # Short-term CP/CD Tier 1
    SUB_INVESTMENT = "SUB_INVESTMENT"

class LiquidityTier(str, Enum):
    TIER_0_INSTANT = "TIER_0_INSTANT"     # T+0 Cash at Fed / Maturing O/N Repo (0-60 min)
    TIER_1_SAME_DAY = "TIER_1_SAME_DAY"   # T+0 On-The-Run T-Bills liquidable within 2-4 hours
    TIER_2_NEXT_DAY = "TIER_2_NEXT_DAY"   # T+1 MMMF redemptions / Off-the-run notes
    TIER_3_TERM = "TIER_3_TERM"           # Term CDs / Term Agencies / CP (requires secondary sale / break fee)

class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    WARNING = "WARNING"
    BREACH = "BREACH"

@dataclass
class ComplianceRuleResult:
    rule_name: str
    citation: str
    status: ComplianceStatus
    current_value: Decimal
    limit_value: Decimal
    unit: str
    message: str
    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class SegregationStatement:
    as_of_date: date
    customer_net_equity_par: Decimal   # Total customer net liquidating equity (liabilities at 100% par)
    cash_at_banks: Decimal             # Cash in segregated accounts
    market_value_securities: Decimal   # Marked-to-market value of 1.25 investments
    reverse_repo_receivables: Decimal  # Reverse repo principal + accrued
    total_segregated_funds: Decimal    # Sum of actual segregated assets at MTM
    excess_or_deficit: Decimal         # total_segregated_funds - customer_net_equity_par
    is_deficit: bool
    firm_residual_interest_required: Decimal # Amount firm must inject to cover under-margin & MTM losses
    firm_residual_interest_actual: Decimal   # Firm's own cash buffer in seg pool
    net_excess_segregation: Decimal          # Excess after applying firm RI
