"""Start the Frappe development web server for the ASOUD ERP test site.

    ~/frappe-dev/bench/env/bin/python e2e/support/py/serve.py [port]

The site is pinned in code, so no ``/etc/hosts`` entry and no ``Host`` header
are required: every request on this port is served by ``E2E_SITE``
(``asoud.test`` by default). The port is passed as an argument, never 8000, so
a run never disturbs a bench web server another worker is using.
"""

import importlib.util
import logging  # noqa: E402
import os
import sys
from pathlib import Path

BENCH = os.environ.get("E2E_BENCH_PATH", os.path.expanduser("~/frappe-dev/bench"))
SITE = os.environ.get("E2E_SITE", "asoud.test")
PORT = int(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("E2E_PORT", "8010"))

for app in ("frappe", "erpnext", "hrms"):
    sys.path.insert(0, os.path.join(BENCH, "apps", app))
os.chdir(os.path.join(BENCH, "sites"))

import frappe  # noqa: E402
import frappe.app  # noqa: E402

if not os.environ.get("E2E_SERVER_LOG"):
    # Request logs would drown the test output; `E2E_SERVER_LOG=1` keeps them.
    logging.getLogger("werkzeug").setLevel(logging.ERROR)

frappe.init(site=SITE, sites_path=os.path.join(BENCH, "sites"))
# This fixture is confined to the test server; production imports no test executor.
fixture_path = Path(__file__).resolve().parents[2] / 'tests' / 'form_execution_fixture.py'
fixture_spec = importlib.util.spec_from_file_location('form_execution_fixture', fixture_path)
fixture = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixture)
fixture.register()

frappe.app.serve(
    port=PORT,
    site=SITE,
    sites_path=os.path.join(BENCH, "sites"),
    no_reload=True,
)