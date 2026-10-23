"""Registry contract for native documents created from approved form requests."""

from typing import Any, Protocol, runtime_checkable

from asoud_erp.services.request_templates.base import NativeResult as Result


@runtime_checkable
class Executor(Protocol):
    """An executor module separates pure payload construction from native writes."""

    KIND: str
    LABEL: str
    PARAMETERS: dict[str, dict[str, Any]]

    def build(self, params: dict, ctx: dict) -> dict:
        """Build a native document payload without importing Frappe."""
        ...

    def apply(self, request: Any, params: dict) -> Result:
        """Resolve native defaults, insert the document and return its outcome."""
        ...

    # Optional: validate_submit(params: dict, ctx: dict) -> None raises ValueError (Persian
    # reason) to refuse a request at submit time. ctx = {company, employee, user}.


EXECUTORS: dict[str, Executor] = {}

# Executor modules register here; each one imports only its own dependencies lazily.
from . import (  # noqa: E402
    asset_movement,
    attendance_correction,
    certificate_issue,
    employee_advance,
    shift_request,
    training_enrollment,
)
from . import exit as exit_settlement  # noqa: E402

for _module in (employee_advance, attendance_correction, asset_movement, shift_request, exit_settlement,
                training_enrollment, certificate_issue):
    EXECUTORS[_module.KIND] = _module

__all__ = ['EXECUTORS', 'Executor', 'Result']
