# CFTC Rule 1.25 Customer Fund Investing & Liquidity Simulator

An institutional-grade, fully auditable **FCM Customer Fund Treasury & Liquidity Simulator** built in strict compliance with **CFTC Regulation § 1.25** (17 CFR § 1.25), **CFTC § 1.32** (Daily Segregation Schedule Form 1-FR-FCM), and **CFTC § 1.22 / § 1.11** (Targeted Residual Interest Adequacy).

---

## 🏛️ Regulatory Background & The FCM Treasury Dilemma

A Futures Commission Merchant (FCM) holds customer segregated funds (often \$500M to \$10B+) representing liabilities owed to customers on demand at **$100\%$ Par**. Under CFTC rules, customer funds cannot be used for firm proprietary speculation, but can be invested in low-risk, highly liquid instruments to generate **Net Interest Income (NII)**.

However, Treasury investing presents three major operational and regulatory constraints:
1. **Statutory Concentration Caps (§ 1.25(b)(3))**: Strict limits on asset classes (e.g., 50% MMMFs, 25% Agencies/CDs/CP, 10% Munis) and single-issuer caps (5%).
2. **Weighted Average Maturity (§ 1.25(b)(5))**: Portfolio dollar-weighted average maturity (WAM) must not exceed **24 months (2.0 years)**.
3. **Daily Segregation & MTM Drawdowns (§ 1.32 & § 1.22)**: Customer obligations remain at par. If market rates surge and 1.25 investments suffer paper MTM losses, the segregated pool instantly falls into a **Segregation Deficit**, which the FCM must immediately fund from its own **Firm Residual Interest**.
4. **Intraday DCO Margin Call Liquidity Waterfall**: Sudden exchange margin calls from clearinghouses (CME, ICE, Kalshi Klear) must be funded in **$T+0$ cash within 60 minutes**, creating critical bottlenecks for $T+1$ settling assets like Money Market Mutual Funds.

---

## 📐 Quantitative & Regulatory Framework

### 1. Statutory Concentration Limits (17 CFR § 1.25(b)(3))
- **Direct U.S. Government Obligations (Treasuries)**: $100\%$ (Exempt from caps under § 1.25(b)(3)(v))
- **Central Bank Deposits / Segregated Cash (§ 1.20)**: $100\%$ (Exempt from investment caps)
- **Treasury-backed Reverse Repos (§ 1.25(a)(2) & § 1.25(d))**: $100\%$ aggregate via central clearing / $25\%$ single bilateral counterparty limit
- **Rule 2a-7 Government Money Market Mutual Funds (MMMFs)**: Max $50\%$ aggregate (§ 1.25(b)(3)(i)(D)) (Max $10\%$ per fund family, max $10\%$ of fund total AUM)
- **U.S. Agency / GSE Securities**: Max $50\%$ aggregate (§ 1.25(b)(3)(i)(B)) (Max $25\%$ single GSE issuer)
- **Municipal Obligations (General Obligation - UTGO)**: Max $10\%$ aggregate (§ 1.25(b)(3)(i)(C)) (Max $5\%$ single issuer, max 2 years / 730 days maturity)
- **Bank Certificates of Deposit (CDs)**: $0\%$ (**Strictly Prohibited** post-2011 CFTC rulemaking / 76 FR 78776)
- **Treasury Inflation-Protected Securities (TIPS)**: $0\%$ (**Strictly Prohibited** per § 1.25(b)(2)(iii) CPI-index restriction)
- **Corporate Bonds & Commercial Paper**: $0\%$ (**Strictly Prohibited** post-2011 CFTC rulemaking)
- **Fixed-Term Non-Demand Repurchase Agreements (>1 Business Day)**: $0\%$ (**Strictly Prohibited** per § 1.25(d)(5))

### 2. Portfolio Weighted Average Maturity (17 CFR § 1.25(b)(5))
$$\text{WAM} = \frac{\sum_i \text{MarketValue}_i \times \text{DaysToMaturity}_i}{\sum_i \text{MarketValue}_i \times 365.0} \le 2.000 \text{ Years (730 Days)}$$

### 3. Fixed Income Risk & Valuation
- **Modified Duration ($D_{\text{mod}}$) & Convexity ($C$):**
  $$\Delta P \approx -D_{\text{mod}} \cdot P \cdot \Delta y + \frac{1}{2} C \cdot P \cdot (\Delta y)^2$$
- **Portfolio DV01 (Dollar Value of a Basis Point):**
  $$\text{DV01} = D_{\text{mod}} \times \text{Portfolio Market Value} \times 0.0001$$

### 4. CFTC § 1.32 Segregation Statement (Form 1-FR-FCM Schedule)
$$\text{Line 3 (Customer Net Par Liability)} = \$500{,}000{,}000$$
$$\text{Line 8 (Total Funds in Segregation at MTM)} = \text{Cash} + \text{Securities MTM} + \text{Repos} + \text{Firm RI}$$
$$\text{Line 9 (Excess / Deficiency in Segregation)} = \text{Line 8} - \text{Line 3}$$

### 5. Intraday Liquidity Waterfall Priority
1. **Tier 0**: Cash on deposit at Federal Reserve Bank ($T+0$ instant wire, 0 friction)
2. **Tier 0**: Maturing Overnight SOFR Reverse Repurchase Agreements ($T+0$ instant, 0 friction)
3. **Tier 1**: Secondary market sale of on-the-run Treasury Bills ($T+0$ same-day, bid-ask spread cost)
4. **Tier 1**: Secondary market sale of Treasury Notes ($T+0$ same-day, market spread cost)
5. **Tier 2**: Rule 2a-7 Government MMMF Redemptions ($T+1$ next-day settlement; requires committed daylight bank facility for $T+0$)
6. **Tier 3**: Secondary sale of Term Agencies / Breakage of Bank CDs ($T+1/T+2$, 35 bps penalty)

---

## 💻 System Architecture

```
fcm_125_simulator/
├── core/
│   ├── types.py               # Decimal financial primitives, Enums, Segregation structures
│   ├── instruments.py         # 1.25 Instruments (Bills, Notes, Repos, MMMFs, Agencies, CDs, CP)
│   ├── portfolio.py           # TreasuryPortfolio state manager & metric aggregation
│   └── presets.py             # Institutional portfolio archetypes (Balanced, Aggressive, Breached)
├── rules/
│   ├── cftc_125_limits.py     # 17 CFR § 1.25 statutory caps and tenor constants
│   └── compliance.py          # Pre/post-trade compliance validator and breach engine
├── analytics/
│   ├── fixed_income.py        # Yield curves, YTM, Duration, Convexity, DV01
│   ├── mtm_pricing.py         # MTM revaluation under rate shocks and bid-ask haircuts
│   └── optimizer.py           # SciPy-powered Constrained Portfolio Optimizer
├── simulation/
│   ├── yield_curve.py         # Dynamic term structure & curve twist/steepening models
│   ├── liquidity_stress.py    # DCO intraday margin call liquidity waterfall engine
│   └── scenarios.py           # Historical stress library (2020 March, 2022 Hike, 2023 SVB, MF Global)
├── regulatory/
│   ├── cftc_1_32_seg.py       # Form 1-FR-FCM Daily Segregation Statement schedule
│   └── cftc_1_22_ri.py        # Targeted Residual Interest adequacy ($Q_{99\%}$ tail buffer)
└── ui/
    ├── server.py              # Lightweight HTTP server & JSON REST API
    ├── cli.py                 # Terminal dashboard and portfolio inspector
    └── reports.py             # Formal Markdown/HTML Investment Committee report generator
```

The web UI lives in [`public/index.html`](public/index.html) and loads permitted securities from the API (`allowed_universe`).

---

## 🚀 Quickstart & Usage

### 1. Run Automated Test Suite
```bash
PYTHONNOUSERSITE=1 python3 -m unittest discover -s tests -v
```

### 2. Inspect Portfolios via CLI
```bash
# Balanced Institutional FCM Portfolio ($500M Float)
PYTHONNOUSERSITE=1 python3 -m fcm_125_simulator.ui.cli --preset balanced

# Aggressive Yield Chaser
PYTHONNOUSERSITE=1 python3 -m fcm_125_simulator.ui.cli --preset aggressive

# Mathematically Optimized Allocation
PYTHONNOUSERSITE=1 python3 -m fcm_125_simulator.ui.cli --preset optimized

# Non-compliant / Distress Case
PYTHONNOUSERSITE=1 python3 -m fcm_125_simulator.ui.cli --preset breached
```

---

## ☁️ Deploying to Vercel

This repository is configured for **one-click deployment to Vercel**:

### Structure:
- **Frontend**: [`public/index.html`](file:///Users/mokdes/Projects/FCM/public/index.html) (Static HTML5/CSS3/JS with macro-density styling).
- **Serverless API**: [`api/index.py`](file:///Users/mokdes/Projects/FCM/api/index.py) (Vercel Serverless Function running complete Python fixed income & CFTC 1.25 calculation engines).
- **Configuration**: [`vercel.json`](file:///Users/mokdes/Projects/FCM/vercel.json) & [`requirements.txt`](file:///Users/mokdes/Projects/FCM/requirements.txt).

### Option 1: Deploy with Vercel CLI
```bash
# Install Vercel CLI (if not already installed)
npm install -g vercel

# Deploy directly from repository root
vercel
```

### Option 2: Deploy via GitHub
1. Push this repository to GitHub.
2. In the [Vercel Dashboard](https://vercel.com/new), select **Import Repository**.
3. Vercel automatically detects `vercel.json`, installs `requirements.txt`, and deploys the live serverless application instantly.
