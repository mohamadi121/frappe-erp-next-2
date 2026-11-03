"""Additive user-action configuration; legacy stage configs are untouched."""
from asoud_erp.services.workflow_submission_policy import normalize


def normalize_action(raw):
    if raw.get('action_contract_version') is None:
        return {}
    if type(raw['action_contract_version']) is not int or raw['action_contract_version'] != 1:
        raise ValueError('نسخهٔ تنظیمات اقدام پشتیبانی نمی‌شود؛ برنامه را به‌روز کنید.')
    mode = raw.get('result_mode', 'Simple')
    if mode not in ('Simple', 'Form'):
        raise ValueError('روش ثبت اطلاعات اقدام معتبر نیست.')
    form = normalize(raw.get('result_form')) if mode == 'Form' else None
    if mode == 'Form' and not form:
        raise ValueError('فرم منتشرشدهٔ ثبت نتیجه را انتخاب کنید.')
    rule = raw.get('assignment_rule')
    if not isinstance(rule, dict) or rule.get('basis') not in ('Unit', 'Subject Unit', 'Subject', 'Manager', 'Role'):
        raise ValueError('مبنای تعیین مسئول اقدام را انتخاب کنید.')
    basis = rule['basis']
    result = {'basis': basis}
    if basis == 'Role':
        result.update(role=required(rule, 'role'), scope=rule.get('scope', 'Company'), delivery='Shared')
        if result['role'] in ('Guest', 'All'):
            raise ValueError('یک نقش واقعی و فعال انتخاب کنید.')
        if result['scope'] not in ('Company', 'Department'):
            raise ValueError('محدودهٔ نقش معتبر نیست.')
        if result['scope'] == 'Department':
            result['department'] = required(rule, 'department')
    elif basis == 'Unit':
        result.update(department=required(rule, 'department'), delivery=rule.get('delivery', 'Shared'))
        if result['delivery'] not in ('Shared', 'Direct'):
            raise ValueError('روش ارجاع معتبر نیست.')
        if result['delivery'] == 'Direct':
            result['person'] = required(rule, 'person')
    else:
        subject = rule.get('subject', 'Initiator')
        if subject not in ('Initiator', 'Form Employee'):
            raise ValueError('شخص مبنا معتبر نیست.')
        result.update(subject=subject, delivery='Shared' if basis == 'Subject Unit' else 'Direct')
        if subject == 'Form Employee':
            result['employee_field'] = required(rule, 'employee_field')
    attachments = raw.get('allow_add_attachments', False)
    if type(attachments) is not bool:
        raise ValueError('تنظیم پیوست باید روشن یا خاموش باشد.')
    style = raw.get('simple_result_style', 'Outcomes')
    if style not in ('Outcomes', 'Report'):
        raise ValueError('روش ثبت گزارش اقدام معتبر نیست.')
    access = raw.get('document_access', 'Read Only')
    if access not in ('Read Only', 'Edit', 'Limited Edit'):
        raise ValueError('سطح دسترسی به درخواست اصلی معتبر نیست.')
    capabilities = {}
    for key, default in [('allow_original_access', True), ('allow_draft', True), ('allow_reassign', False)]:
        value = raw.get(key, default)
        if type(value) is not bool:
            raise ValueError('تنظیمات تکمیلی باید روشن یا خاموش باشند.')
        capabilities[key] = value
    return {'action_contract_version': 1, 'result_mode': mode, 'result_form': form,
        'assignment_rule': result, 'allow_add_attachments': attachments,
        'simple_result_style': style, 'document_access': access, **capabilities}


def required(rule, key):
    value = rule.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > 140:
        raise ValueError('یکی از انتخاب‌های مسئول انجام کامل و معتبر نیست.')
    return value.strip()


def simple_schema(attachments, style='Outcomes'):
    fields = [
        {'key': 'action_result', 'type': 'Select', 'label': 'نتیجه اقدام', 'required': True, 'default': 'done',
         'options': [{'id': 'done', 'label': 'انجام شد'}, {'id': 'follow_up', 'label': 'نیازمند پیگیری'},
                     {'id': 'blocked', 'label': 'امکان انجام وجود ندارد'}]},
        {'key': 'action_note', 'type': 'LongText', 'label': 'شرح نتیجه اقدام', 'max_length': 5000},
    ]
    if style == 'Report':
        fields = [{'key': 'action_note', 'type': 'LongText', 'label': 'گزارش انجام اقدام',
            'required': True, 'max_length': 5000}]
    if attachments:
        fields.append({'key': 'action_files', 'type': 'File', 'label': 'پیوست مستندات', 'max_files': 10,
            'extensions': ['pdf', 'jpg', 'jpeg', 'png', 'xlsx', 'docx'], 'max_mb': 10})
    return {'kind': 'Request', 'title': 'ثبت نتیجه اقدام', 'sections': [{'id': 'result', 'fields': fields}], 'rules': []}


def condition_fields(config):
    """Expose existing saved result scalars to the existing Canvas condition picker."""
    if config.get('action_contract_version') != 1:
        return []
    types = {'Text': 'Data', 'Integer': 'Int', 'Decimal': 'Float', 'Money': 'Currency',
        'Formula': 'Float', 'Date': 'Date', 'DateTime': 'Datetime', 'Time': 'Data',
        'Select': 'Select', 'Boolean': 'Check', 'Checkbox': 'Check', 'Link': 'Link'}
    return [{'fieldname': field['key'], 'label': field['label'], 'fieldtype': types[field['type']], 'source': 'Form'}
        for section in (config.get('result_schema') or {}).get('sections', [])
        for field in section.get('fields', []) if field.get('type') in types and not field.get('sensitive')]
