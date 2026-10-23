from datetime import datetime, timedelta

from asoud_erp.services import record_labels as labels


def test_attendance_label_full_and_partial():
    row = {"attendance_date": "2026-10-20", "status": "Present",
           "in_time": "2026-10-20T08:01:00", "out_time": datetime(2026, 10, 20, 16, 30)}
    assert labels.attendance_label(row) == "۱۴۰۵/۰۷/۲۸ · حاضر · ورود ۰۸:۰۱ · خروج ۱۶:۳۰"
    row.update(status="Absent", in_time=None, out_time="")
    assert labels.attendance_label(row) == "۱۴۰۵/۰۷/۲۸ · غایب"
    for english, persian in (("On Leave", "مرخصی"), ("Half Day", "نیم‌روز"), ("Work From Home", "دورکاری")):
        assert labels.attendance_label({"attendance_date": "2026-10-20", "status": english}).endswith(persian)


def test_shift_event_and_asset_labels():
    assert labels.shift_label({"name": "صبح", "start_time": "08:00:00", "end_time": timedelta(hours=16)}) == "صبح · ۰۸:۰۰ تا ۱۶:۰۰"
    assert labels.shift_label({"name": "صبح", "start_time": None, "end_time": None}) == "صبح"
    assert labels.training_event_label({"name": "TE-1", "label": "ایمنی", "start_time": "2026-10-20T09:00:00"}) == "ایمنی · ۱۴۰۵/۰۷/۲۸"
    assert labels.asset_label({"name": "AST-1", "label": "لپ‌تاپ"}) == "لپ‌تاپ (AST-1)"
