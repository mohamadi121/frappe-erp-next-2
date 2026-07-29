from datetime import date, timedelta


def jalali_to_gregorian(year: int, month: int, day: int) -> date:
    """Convert a valid Solar Hijri date to Gregorian without external packages."""
    jy = int(year) + 1595
    jm = int(month)
    jd = int(day)
    if not 1 <= jm <= 12:
        raise ValueError("Jalali month must be between 1 and 12")
    month_days = 31 if jm <= 6 else 30
    if not 1 <= jd <= month_days:
        raise ValueError("Jalali day is not valid for the selected month")

    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    days += (jm - 1) * 31 if jm < 7 else ((jm - 7) * 30) + 186

    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1

    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365

    gd = days + 1
    leap = gy % 4 == 0 and (gy % 100 != 0 or gy % 400 == 0)
    lengths = (31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    gm = 1
    for length in lengths:
        if gd <= length:
            break
        gd -= length
        gm += 1
    return date(gy, gm, gd)


def jalali_fiscal_period(year: int, month: int, day: int) -> tuple[date, date]:
    start = jalali_to_gregorian(year, month, day)
    end = jalali_to_gregorian(year + 1, month, day) - timedelta(days=1)
    return start, end
