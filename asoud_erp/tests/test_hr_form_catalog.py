from asoud_erp.services.hr_form_catalog import builtin_key, catalog, catalog_rows, form_name


def test_catalog_contains_exact_existing_hr_presets():
    assert set(catalog()) == {
        'traffic_correction', 'employment_certificate', 'shift_change', 'training',
        'equipment', 'leave', 'mission', 'overtime', 'salary_advance', 'settlement',
    }
    assert all(item['kind'] == 'Request' for item in catalog().values())


def test_identity_is_stable_and_scoped():
    names = {form_name('A', key) for key in catalog()}
    assert len(names) == 10
    assert names.isdisjoint({form_name('B', key) for key in catalog()})
    for key in catalog():
        assert builtin_key('A', form_name('A', key)) == key
    assert builtin_key('B', form_name('A', 'leave')) is None


def test_existing_including_disabled_tombstone_never_reappears():
    existing = [form_name('A', 'leave')]
    rows = catalog_rows('A', existing)
    assert len(rows) == 9
    assert all(row['name'] not in existing for row in rows)
    assert all(row['builtin_pending'] for row in rows)


def test_callers_cannot_mutate_trusted_schemas():
    original = catalog()['leave']['title']
    changed = catalog()
    changed['leave']['title'] = 'changed'
    assert catalog()['leave']['title'] == original
