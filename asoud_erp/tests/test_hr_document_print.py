from asoud_erp.services.hr_document_print import final_letterhead


def test_legacy_final_has_no_header_and_reports_missing_metadata():
    assert final_letterhead({}, "letterhead_snapshot", "letterhead_html") == (None, True)


def test_explicit_empty_snapshot_is_preserved_and_not_marked_legacy():
    assert final_letterhead({"letterhead_snapshot": None}, "letterhead_snapshot") == (None, False)


def test_historical_header_takes_precedence_over_compatibility_key():
    assert final_letterhead({"letterhead_snapshot": "old", "letterhead_html": "other"},
                            "letterhead_snapshot", "letterhead_html") == ("old", False)
