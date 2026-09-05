import pytest
from asoud_erp.services.organization_contract import validate_rows

def test_hierarchy():
    assert len(validate_rows([{"code": "CEO", "title": "CEO"}, {"code": "ACC", "title": "Accountant", "parent": "CEO"}])) == 2

@pytest.mark.parametrize("rows", [
    [{"code": "A", "title": "A", "parent": "A"}],
    [{"code": "A", "title": "A", "parent": "B"}, {"code": "B", "title": "B", "parent": "A"}],
    [{"code": "A", "title": "A", "parent": "missing"}],
    [{"code": "A", "title": "A"}, {"code": "A", "title": "B"}],
    [{"code": "A", "title": "A", "employee": "E"}, {"code": "B", "title": "B", "employee": "E"}],
])
def test_invalid_hierarchy(rows):
    with pytest.raises(ValueError):
        validate_rows(rows)

