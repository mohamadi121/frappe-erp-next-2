from decimal import Decimal, InvalidOperation
from typing import Any


def evaluate_condition(operator: str, actual: Any, expected: Any = None) -> bool:
    if operator == "Is Set":
        return actual not in (None, "", [])
    if operator == "Equals":
        return str(actual) == str(expected)
    if operator == "Not Equals":
        return str(actual) != str(expected)
    if operator == "Contains":
        return str(expected) in str(actual or "")
    if operator in {"Greater Than", "Less Than"}:
        try:
            left, right = Decimal(str(actual)), Decimal(str(expected))
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValueError("Condition values must be numeric") from error
        return left > right if operator == "Greater Than" else left < right
    raise ValueError("Invalid condition operator")


def select_boolean_transition(transitions: list[dict[str, Any]], result: bool) -> str:
    matches = [
        str(item.get("to_stage") or "")
        for item in transitions
        if isinstance(item.get("condition"), dict)
        and item["condition"].get("result") is result
    ]
    if len(matches) != 1 or not matches[0]:
        raise ValueError("Condition stage must have exactly one transition for each result")
    return matches[0]
