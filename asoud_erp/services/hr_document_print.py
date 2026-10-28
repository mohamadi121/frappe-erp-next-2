"""Resolve only historical letterhead metadata for finalized HR documents."""


def final_letterhead(snapshot: dict, *keys: str) -> tuple[str | None, bool]:
    """An explicit empty snapshot is valid; absent metadata renders without a header."""
    for key in keys:
        if key in snapshot:
            return snapshot[key], False
    return None, True
