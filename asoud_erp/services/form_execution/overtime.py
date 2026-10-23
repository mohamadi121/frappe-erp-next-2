"""Approved overtime ends as Needs Review: HRMS v15 has no overtime document and no policy exists yet."""

KIND = 'overtime'
LABEL = 'درخواست اضافه‌کار'
PARAMETERS = {
    'work_date': {'label': 'تاریخ اضافه‌کار', 'types': ['Date'], 'required': True},
    'start_time': {'label': 'ساعت شروع', 'types': ['Time'], 'required': True},
    'end_time': {'label': 'ساعت پایان', 'types': ['Time'], 'required': True},
    'purpose': {'label': 'شرح کار', 'types': ['Text', 'LongText'], 'required': True},
    'notes': {'label': 'توضیحات تکمیلی', 'types': ['Text', 'LongText'], 'required': False},
}
DAY = 24 * 60


def _absolute(params: dict, key: str, message: str) -> tuple[int, str]:
    """Minutes from the start of the work date and the shown clock."""
    from . import period

    minutes = period.clock_minutes(params.get(key), message)
    next_day = params.get(f'{key}__next_day')
    if next_day is not None and next_day != '' and not isinstance(next_day, bool):
        raise ValueError('گزینه روز بعد معتبر نیست.')
    return minutes + (DAY if next_day else 0), params[key][:5]


def build(params: dict, ctx: dict) -> dict:
    """``{'needs_review': reason}`` naming the approved date and duration. Pure."""
    from asoud_erp.services.digits import to_persian_digits
    from asoud_erp.services.record_labels import jalali_date

    from . import period

    if not isinstance(params, dict):
        raise ValueError('اطلاعات درخواست اضافه‌کار معتبر نیست.')
    if not isinstance(ctx, dict) or not isinstance(ctx.get('employee'), str) or not ctx['employee'].strip():
        raise ValueError(period.NO_EMPLOYEE)
    work_date = period.day(params.get('work_date'), 'تاریخ اضافه‌کار معتبر نیست.')
    start, start_text = _absolute(params, 'start_time', 'ساعت شروع معتبر نیست.')
    end, end_text = _absolute(params, 'end_time', 'ساعت پایان معتبر نیست.')
    period.clean_text(params.get('purpose'), 'شرح کار اضافه‌کار را وارد کنید.', required=True,
                      too_long='شرح کار اضافه‌کار حداکثر ۲۰۰۰ نویسه است.')
    period.clean_text(params.get('notes'), 'توضیحات اضافه‌کار باید متن باشد.',
                      too_long='توضیحات اضافه‌کار حداکثر ۲۰۰۰ نویسه است.')
    if end <= start:
        raise ValueError('ساعت پایان باید پس از ساعت شروع باشد.')
    if end - start > DAY:
        raise ValueError('مدت اضافه‌کار باید بیش از صفر و حداکثر ۲۴ ساعت باشد.')
    hours, minutes = divmod(end - start, 60)
    length = f'{hours} ساعت' + (f' و {minutes} دقیقه' if minutes else '')
    end_label = to_persian_digits(end_text) + (' روز بعد' if end >= DAY else '')
    return {'needs_review': (
        f'نیاز به اقدام HR؛ اضافه‌کار تأییدشده در تاریخ {jalali_date(work_date)} از ساعت '
        f'{to_persian_digits(start_text)} تا ساعت {end_label} به مدت {to_persian_digits(length)} است؛ '
        'ثبت کارکرد و محاسبه مالی باید توسط منابع انسانی انجام شود.')}


def apply(request, params: dict):
    from asoud_erp.services.request_templates.base import NativeResult

    from . import period

    filters = {'user_id': request.owner, 'company': request.company}
    if request.get('requester_employee'):
        filters['name'] = request.requester_employee
    employee = period.lock_employee(filters)
    payload = build(params, {'company': request.company, 'employee': employee})
    return NativeResult(status='needs_review', reason=payload['needs_review'])
