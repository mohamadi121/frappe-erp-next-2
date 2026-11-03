import pytest

from asoud_erp.services.organization_contract import reset_revision


@pytest.mark.parametrize('value', [0, 12, '0', '12'])
def test_reset_revision(value):
    assert reset_revision(value) == int(value)


@pytest.mark.parametrize('value', [None, True, False, -1, 1.2, '', ' 1', '1.0', '۱', [], {}, '9' * 19])
def test_reset_revision_rejects_unsafe_inputs(value):
    with pytest.raises(ValueError):
        reset_revision(value)
