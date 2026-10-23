"""Pure validation of the additive form execution contract."""

from asoud_erp.services.form_execution import EXECUTORS


def validate_execution(schema: dict) -> None:
    fields = [field for section in schema.get('sections', []) for field in section.get('fields', [])]
    execution = schema.get('execution')
    mapped = [field for field in fields if 'execution_key' in field]
    if execution is None and not mapped:
        return
    if schema.get('kind') != 'Request':
        raise ValueError('اجرای پس از تأیید فقط برای فرم درخواست مجاز است.')
    if not isinstance(execution, dict) or not isinstance(execution.get('kind'), str):
        raise ValueError('نوع اجرا معتبر نیست.')
    executor = EXECUTORS.get(execution['kind'])
    if executor is None:
        raise ValueError('نوع اجرا معتبر نیست.')
    validate_parameter_fields(fields, execution['kind'], required=True)


def validate_parameter_fields(fields: list[dict], kind: str, *, required: bool = False) -> None:
    executor = EXECUTORS.get(kind)
    if executor is None:
        raise ValueError('نوع اجرا معتبر نیست.')
    mapped = [field for field in fields if 'execution_key' in field]
    used = set()
    for field in mapped:
        key = field['execution_key']
        if not isinstance(key, str) or key not in executor.PARAMETERS:
            raise ValueError('پارامتر اجرای فیلد معتبر نیست.')
        if key in used:
            raise ValueError('پارامتر اجرای فیلد تکراری است.')
        if not compatible_type(field.get('type'), executor.PARAMETERS[key]['types']):
            raise ValueError('نوع فیلد با پارامتر اجرا سازگار نیست.')
        used.add(key)
    missing = [parameter['label'] for key, parameter in executor.PARAMETERS.items()
               if parameter.get('required') and key not in used]
    if required and missing:
        raise ValueError('نگاشت پارامتر الزامی مشخص نشده است: ' + '، '.join(missing))


def compatible_type(field_type: str, allowed: list[str]) -> bool:
    aliases = {'Currency': 'Money', 'Checkbox': 'Check', 'Boolean': 'Check', 'Short Text': 'Text',
               'Long Text': 'LongText', 'Choice': 'Select', 'Number': 'Decimal'}
    return aliases.get(field_type, field_type) in {aliases.get(value, value) for value in allowed}


def validate_stage_parameters(fields: list[dict]) -> None:
    mapped = [field for field in fields if 'execution_key' in field]
    if not mapped:
        return
    keys = [field['execution_key'] for field in mapped]
    if any(not isinstance(key, str) for key in keys):
        raise ValueError('پارامتر اجرای فیلد معتبر نیست.')
    if len(keys) != len(set(keys)):
        raise ValueError('پارامتر اجرای فیلد تکراری است.')
    for kind in EXECUTORS:
        try:
            validate_parameter_fields(mapped, kind)
            return
        except ValueError:
            continue
    raise ValueError('پارامتر اجرا یا نوع فیلدهای مرحله معتبر نیست.')
