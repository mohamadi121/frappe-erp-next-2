"""Optional preview examples filtered through the real installed catalogue."""

ACCOUNTANT_DAILY = frozenset({'Journal Entry', 'Payment Entry', 'Purchase Order',
    'Purchase Invoice', 'Quotation', 'Sales Order', 'Sales Invoice', 'Expense Claim'})
ACCOUNTANT_MASTERS = frozenset({'Account', 'Fiscal Year'})


def accountant_example(catalog):
    grants = {}
    for row in catalog:
        doctype = row['doctype']
        wanted = {'read', 'create', 'write'} if doctype in ACCOUNTANT_DAILY else (
            {'read'} if doctype in ACCOUNTANT_MASTERS or row.get('read_only_report') else set())
        actions = sorted(wanted.intersection(row['actions']))
        if 'read' in actions:
            grants[doctype] = actions
    return {'title': 'حسابدار', 'description': 'ثبت و ویرایش عملیات مالی؛ بدون حذف یا تأیید نهایی اسناد.',
        'grants': grants}
