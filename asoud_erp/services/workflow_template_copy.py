"""Pure, bounded graph-copy plan; never copies execution data."""
import json
import re


def appearance(title, description, icon, color):
    if not isinstance(title, str) or not 3 <= len(title.strip()) <= 140:
        raise ValueError("عنوان گردش کار باید بین ۳ تا ۱۴۰ نویسه باشد.")
    if not isinstance(description, str) or len(description) > 2000:
        raise ValueError("توضیح گردش کار باید متن و حداکثر ۲۰۰۰ نویسه باشد.")
    if not isinstance(icon, str) or icon not in {"hub", "purchase", "expense", "support", "leave", "hiring"}:
        raise ValueError("آیکن گردش کار معتبر نیست.")
    if not isinstance(color, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
        raise ValueError("رنگ گردش کار معتبر نیست.")
    return title.strip(), description.strip()


def rebind(value, identities):
    if isinstance(value, dict):
        return {key: rebind(item, identities) for key, item in value.items()}
    if isinstance(value, list):
        return [rebind(item, identities) for item in value]
    return identities.get(value, value) if isinstance(value, str) else value


def graph_plan(stages, transitions, identities):
    if not stages or len(stages) > 200 or len(transitions) > 1000:
        raise ValueError("اندازهٔ الگوی گردش کار معتبر نیست.")
    names = {row["name"] for row in stages}
    if len(names) != len(stages) or set(identities) != names or len(set(identities.values())) != len(names):
        raise ValueError("شناسه‌های مراحل الگو معتبر نیستند.")
    if sum(row["stage_type"] == "Start" for row in stages) != 1:
        raise ValueError("الگو باید دقیقاً یک مرحلهٔ شروع داشته باشد.")
    if not any(row["stage_type"] == "End" for row in stages):
        raise ValueError("الگو مرحلهٔ پایان ندارد.")
    try:
        copied_stages = []
        for row in stages:
            config = json.loads(row.get("config_json") or "{}")
            if not isinstance(config, dict):
                raise ValueError
            copied_stages.append({
                **{key: row.get(key) for key in ("stage_type", "stage_subtype", "stage_title",
                    "sequence_no", "position_x", "position_y")},
                "name": identities[row["name"]],
                "config_json": json.dumps(rebind(config, identities), ensure_ascii=False),
                "configuration_status": "Pending",
            })
        copied_edges = []
        for row in transitions:
            condition = json.loads(row.get("condition_json") or "{}")
            if not isinstance(condition, dict) or row["from_stage"] not in names or row["to_stage"] not in names:
                raise ValueError
            copied_edges.append({"from_stage": identities[row["from_stage"]],
                "to_stage": identities[row["to_stage"]], "sequence_no": row["sequence_no"],
                "transition_label": row.get("transition_label"),
                "condition_json": json.dumps(rebind(condition, identities), ensure_ascii=False)})
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError("تنظیمات یا مسیرهای الگو معتبر نیستند.") from error
    return copied_stages, copied_edges
