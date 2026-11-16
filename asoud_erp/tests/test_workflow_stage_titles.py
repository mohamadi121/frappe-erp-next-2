"""PA-063 regression: the backend User Task stage title must match the app.

The Flutter app renders the User Task node on the designer canvas with the label
``بررسی یا ویرایش سند`` (``workflowStageVisual`` in
``flutter-asoud-erp/lib/features/workflows/presentation/widgets/workflow_graph_canvas.dart``).
The backend ``STAGE_TITLES`` dictionary used to store ``اقدام کاربر`` for the same
stage, so a freshly inserted stage showed a different name than the canvas.

The backend is the side that changes (the app is the reference), so this test pins
``STAGE_TITLES["User Task"]`` to the app's canvas label. It fails on the old value
(``اقدام کاربر``) and passes once the backend is aligned.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "asoud_erp/api/v1/workflow.py"

# The app's canvas label for the User Task stage (workflowStageVisual, userTask).
APP_USER_TASK_LABEL = "بررسی یا ویرایش سند"


def _stage_titles() -> dict:
    tree = ast.parse(WORKFLOW.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "STAGE_TITLES":
                    return ast.literal_eval(node.value)
    raise AssertionError("STAGE_TITLES not found in workflow.py")


def test_user_task_title_matches_app_canvas_label():
    titles = _stage_titles()
    assert titles["User Task"] == APP_USER_TASK_LABEL


def test_all_stage_types_have_persian_titles():
    titles = _stage_titles()
    expected_keys = {"User Task", "Approval", "Condition", "System Action", "Wait", "End"}
    assert set(titles) == expected_keys
    for key, value in titles.items():
        assert any(ch.isalpha() and ord(ch) > 0x0600 for ch in value), f"{key} title is not Persian"
