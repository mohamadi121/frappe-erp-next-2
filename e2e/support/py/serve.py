"""Start the Frappe development web server for the ASOUD ERP test site.

    ~/frappe-dev/bench/env/bin/python e2e/support/py/serve.py [port]

The site is pinned in code, so no ``/etc/hosts`` entry and no ``Host`` header
are required: every request on this port is served by ``E2E_SITE``
(``asoud.test`` by default). The port is passed as an argument, never 8000, so
a run never disturbs a bench web server another worker is using.
"""

import logging  # noqa: E402
import os
import sys

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
frappe.app.serve(
    port=PORT,
    site=SITE,
    sites_path=os.path.join(BENCH, "sites"),
    no_reload=True,
)