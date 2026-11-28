"""Pure tests for the API manifest builder and the stale-manifest guard.

No ``frappe`` import and no bench: the manifest is derived from the source AST and
the classification registry, so these run in the lightweight CI.
"""

from pathlib import Path

from asoud_erp.services import api_manifest

_API_DIR = Path(__file__).resolve().parent.parent / "api" / "v1"
_MANIFEST = Path(__file__).resolve().parent.parent.parent / "docs" / "api" / "manifest.json"


def test_build_covers_every_whitelisted_method():
    # Every non-guest, non-protocol whitelisted method appears exactly once.
    manifest = api_manifest.build_from_dir(_API_DIR)
    specs = api_manifest.collect_specs(_API_DIR)
    expected = {
        s["name"] for s in specs if not s["allow_guest"] and s["name"] != "asoud_erp.api.v1.sync.execute_mutation"
    }
    assert set(manifest["methods"]) == expected
    assert manifest["method_count"] == len(manifest["methods"])


def test_guest_and_protocol_methods_are_excluded():
    manifest = api_manifest.build_from_dir(_API_DIR)
    # The four allow_guest account-security methods and the outbox protocol method are not tools.
    for name in (
        "asoud_erp.api.v1.account_security.recovery_status",
        "asoud_erp.api.v1.account_security.request_password_reset",
        "asoud_erp.api.v1.account_security.confirm_password_reset",
        "asoud_erp.api.v1.account_security.activate_account",
        "asoud_erp.api.v1.sync.execute_mutation",
    ):
        assert name not in manifest["methods"], name


def test_every_method_is_classified_and_flagged():
    manifest = api_manifest.build_from_dir(_API_DIR)
    for name, entry in manifest["methods"].items():
        assert entry["kind"] in ("read", "write"), name
        assert entry["effectful"] is (entry["kind"] == "write" and api_manifest.registry.is_impactful(name)), name
        assert entry["pilot"] is (name in api_manifest.PILOT_METHODS), name
        assert entry["http"], name


def test_pilot_methods_are_complete_and_flagged():
    manifest = api_manifest.build_from_dir(_API_DIR)
    flagged = {name for name, entry in manifest["methods"].items() if entry["pilot"]}
    assert flagged == api_manifest.PILOT_METHODS
    # The pilot set is 16 methods: 15 reads plus the one self-service write.
    assert len(flagged) == 16
    assert manifest["methods"]["asoud_erp.api.v1.support.create_issue"]["kind"] == "write"


def test_parameter_schema_shape():
    manifest = api_manifest.build_from_dir(_API_DIR)
    entry = manifest["methods"]["asoud_erp.api.v1.selling.list_sales_invoices"]
    params = entry["parameters"]
    assert params["company"]["required"] is True
    assert params["company"]["type"] == "str"
    assert params["limit_start"]["required"] is False
    assert params["limit_start"]["default"] == 0
    assert params["limit_page_length"]["default"] == 20
    # An optional, un-annotated parameter is not required and has no type.
    assert params["status"]["required"] is False


def test_http_methods_reflect_the_decorator():
    manifest = api_manifest.build_from_dir(_API_DIR)
    # A POST-only method.
    assert manifest["methods"]["asoud_erp.api.v1.support.create_issue"]["http"] == ["POST"]
    # A method with no methods= accepts both.
    assert manifest["methods"]["asoud_erp.api.v1.selling.list_sales_invoices"]["http"] == ["GET", "POST"]


def test_committed_manifest_is_not_stale():
    # The committed docs/api/manifest.json must equal a fresh build; the failure message
    # tells the developer how to regenerate it.
    fresh = api_manifest.manifest_to_json(api_manifest.build_from_dir(_API_DIR))
    committed = _MANIFEST.read_text(encoding="utf-8")
    assert committed == fresh, (
        "docs/api/manifest.json is out of date. Regenerate it with:\n"
        "    PYTHONPATH=. python3 scripts/gen_api_manifest.py\n"
        "and commit the result."
    )


def test_manifest_serialization_is_stable():
    manifest = api_manifest.build_from_dir(_API_DIR)
    # Re-serializing the same manifest is byte-identical (sorted keys, trailing newline).
    assert api_manifest.manifest_to_json(manifest) == api_manifest.manifest_to_json(manifest)
    assert api_manifest.manifest_to_json(manifest).endswith("\n")
