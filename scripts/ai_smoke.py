#!/usr/bin/env python
"""Manual smoke test for the Gemloy client (NOT run in CI, NOT run automatically).

It does a single ``count_tokens`` and one tiny ``create_message`` against the
configured Gemloy endpoint, but ONLY when the site config has both
``gemloy_base_url`` and ``gemloy_api_key``. If either is missing it prints a
Persian notice and exits 0 without touching the network.

Run it from a bench site (it needs ``frappe.init`` / ``frappe.conf``):

    bench --site <site> execute scripts.ai_smoke.run

or, from the app directory with a site already initialised:

    python scripts/ai_smoke.py

There is no key in the repo, so this is a manual check only.
"""

import sys


def run() -> int:
    import frappe

    base_url = str(frappe.conf.get("gemloy_base_url") or "").strip()
    api_key = str(frappe.conf.get("gemloy_api_key") or "").strip()
    if not base_url or not api_key:
        print("دستیار هوشمند پیکربندی نشده است؛ کلید یا آدرس در تنظیمات سایت نیست.")
        return 0

    from asoud_erp.services.ai import gemloy_client

    client = gemloy_client.GemloyClient(base_url, api_key)
    try:
        tokens = client.count_tokens([{"role": "user", "content": "سلام"}])
        print(f"count_tokens: {tokens}")
        response = client.create_message(
            [{"role": "user", "content": "سلام"}],
            max_tokens=64, temperature=0.2, thinking={"type": "disabled"})
        print("answer:", gemloy_client.extract_text(response.get("content") or []))
    except gemloy_client.GemloyError as exc:
        print(f"خطا: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(run())
