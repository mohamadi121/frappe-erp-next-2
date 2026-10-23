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


EXECUTORS: dict[str, Executor] = {}

# Executor modules register here; each one imports only its own dependencies lazily.
from . import asset_movement, attendance_correction, employee_advance, shift_request  # noqa: E402

for _module in (employee_advance, attendance_correction, asset_movement, shift_request):
    EXECUTORS[_module.KIND] = _module

__all__ = ['EXECUTORS', 'Executor', 'Result']
