"""
Vercel Serverless Function entry point for CFTC Rule 1.25 Simulator API.
"""

import os
import sys
import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from decimal import Decimal
from datetime import date

# Ensure root directory is on sys.path
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from fcm_125_simulator.ui.server import (
    build_full_dashboard_payload,
    DecimalEncoder,
    create_custom_portfolio_from_allocations
)
from fcm_125_simulator.core.presets import PortfolioPresets, get_standard_universe
from fcm_125_simulator.analytics.optimizer import TreasuryOptimizer
from fcm_125_simulator.core.types import to_decimal

class handler(BaseHTTPRequestHandler):
    """
    Vercel serverless request handler.
    """

    def _set_headers(self, status_code=200, content_type="application/json"):
        self.send_response(status_code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_OPTIONS(self):
        self._set_headers(200)

    def do_GET(self):
        parsed_url = urlparse(self.path)
        params = parse_qs(parsed_url.query)

        preset_name = params.get("preset", ["balanced"])[0]
        total_float = to_decimal(float(params.get("float", [500000000.0])[0]))
        yield_shift = float(params.get("yield_shift", [0.0])[0])
        margin_call = float(params.get("margin_call", [50000000.0])[0])
        credit_facility = params.get("credit_facility", ["false"])[0].lower() == "true"

        as_of = date.today()

        if preset_name == "balanced":
            portfolio = PortfolioPresets.get_default_for_float(as_of, total_float)
        elif preset_name == "aggressive":
            portfolio = PortfolioPresets.get_aggressive_yield_chaser(as_of, total_float)
        elif preset_name == "breached":
            portfolio = PortfolioPresets.get_breached_mf_global_style(as_of, total_float)
        elif preset_name == "optimized":
            universe = get_standard_universe(as_of)
            portfolio = TreasuryOptimizer.optimize_allocation(as_of, total_float, universe)
        else:
            portfolio = PortfolioPresets.get_default_for_float(as_of, total_float)

        payload = build_full_dashboard_payload(
            portfolio=portfolio,
            yield_shift_bps=yield_shift,
            margin_call_amount=margin_call,
            credit_facility_allowed=credit_facility
        )

        self._set_headers(200, "application/json")
        self.wfile.write(json.dumps(payload, cls=DecimalEncoder).encode("utf-8"))

    def do_POST(self):
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_len)
            data = json.loads(body.decode("utf-8")) if body else {}

            preset_name = data.get("preset", "balanced")
            total_float = to_decimal(data.get("total_float", 500000000.0))
            custom_allocations = data.get("custom_allocations")
            yield_shift = float(data.get("yield_shift_bps", 0.0))
            margin_call = float(data.get("margin_call_amount", 50000000.0))
            credit_facility = bool(data.get("credit_facility", False))

            as_of = date.today()

            if custom_allocations and isinstance(custom_allocations, dict):
                portfolio = create_custom_portfolio_from_allocations(
                    as_of=as_of,
                    total_float=total_float,
                    allocations_map=custom_allocations
                )
            elif preset_name == "balanced":
                portfolio = PortfolioPresets.get_default_for_float(as_of, total_float)
            elif preset_name == "aggressive":
                portfolio = PortfolioPresets.get_aggressive_yield_chaser(as_of, total_float)
            elif preset_name == "breached":
                portfolio = PortfolioPresets.get_breached_mf_global_style(as_of, total_float)
            elif preset_name == "optimized":
                universe = get_standard_universe(as_of)
                portfolio = TreasuryOptimizer.optimize_allocation(as_of, total_float, universe)
            else:
                portfolio = PortfolioPresets.get_default_for_float(as_of, total_float)

            payload = build_full_dashboard_payload(
                portfolio=portfolio,
                yield_shift_bps=yield_shift,
                margin_call_amount=margin_call,
                credit_facility_allowed=credit_facility
            )

            self._set_headers(200, "application/json")
            self.wfile.write(json.dumps(payload, cls=DecimalEncoder).encode("utf-8"))
        except Exception as e:
            self._set_headers(500, "application/json")
            self.wfile.write(json.dumps({"error": str(e)}).encode("utf-8"))
