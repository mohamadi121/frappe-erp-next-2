"""Versioned presentation schemas. Never replaces native ERP validation."""
import copy
import json
import re
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

import frappe

TYPES = {"Text", "LongText", "Integer", "Decimal", "Money", "Date", "Time", "DateTime",
         "Select", "MultiSelect", "Boolean", "Checkbox", "Link", "Table", "Formula", "Display", "Rating",
         "File", "Image", "Signature", "Barcode"}
SOURCES = {"Employee", "Customer", "Supplier", "Item", "Warehouse", "Account", "Cost Center",
           "Project", "Department", "Attendance", "Shift Type", "Training Event", "Asset"}
SCOPED_SOURCES = {"Attendance", "Shift Type", "Training Event", "Asset"}
FETCH_ATTRIBUTES = {
    "Attendance": ("in_time", "out_time", "attendance_date", "status", "shift"),
    "Shift Type": ("start_time", "end_time"),
    "Training Event": ("start_time", "end_time", "type", "level", "training_program"),
    "Asset": ("asset_name", "item_code", "location"),
    "Employee": ("department", "designation", "employee_number"),
}
DEFAULT_SOURCES = {'user', 'company', 'today', 'employee', 'department', 'designation', 'joining_date',
                   'employee_number', 'default_shift'}
NOT_EQUAL_TYPES = {"Text", "Integer", "Decimal", "Money", "Date", "Time", "Select"}
NUMBERS = {"Integer", "Decimal", "Money", "Rating", "Formula"}
OPERATORS = {"eq", "ne", "gt", "lt", "ge", "le", "empty", "not_empty", "contains"}
FORMULAS = {"add", "subtract", "multiply", "divide", "percent", "sum", "sum_product", "average", "count", "chain", "if", "round", "min", "max", "expression"}
CHAIN_OPS = {"add", "subtract", "multiply", "divide", "percent"}
LINK_FILTERS = {'Employee': {'department'}, 'Item': {'item_group'}, 'Customer': {'customer_group'},
                'Supplier': {'supplier_group'}, 'Account': {'account_type'}, 'Warehouse': {'parent_warehouse'},
                'Cost Center': {'parent_cost_center'}, 'Project': {'status'}, 'Department': {'parent_department'},
                'Attendance': {'attendance_date'}}


def current_employee(company):
    return frappe.db.get_value(
        'Employee', {'company': company, 'user_id': frappe.session.user, 'status': 'Active'}, 'name')


def scope_filters(source, company, employee):
    """Rows of a scoped source the signed-in user may pick. The scope is the authorization."""
    if source == 'Attendance':
        return {'company': company, 'employee': employee, 'docstatus': 1}
    if source == 'Shift Type':
        return {}
    if source == 'Training Event':
        from frappe.utils import now_datetime
        return {'company': company, 'event_status': 'Scheduled', 'docstatus': ['<', 2],
                'start_time': ['>=', now_datetime()]}
    if source == 'Asset':
        return {'company': company, 'custodian': employee, 'docstatus': 1}
    return {}


def fetch_value(value, field_type=None):
    """Plain JSON value of a database attribute; Time fields take the time part."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if field_type == 'Time':
            return value.time().replace(microsecond=0).isoformat()
        if field_type == 'Date':
            return value.date().isoformat()
        return value.replace(microsecond=0).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, timedelta):
        total = int(value.total_seconds())
        return f'{total // 3600 % 24:02d}:{total // 60 % 60:02d}:{total % 60:02d}'
    return value if isinstance(value, (int, float)) else str(value)


def default_value(field, company):
    source = field.get('default_source')
    if source == 'user':
        return frappe.session.user
    if source == 'company':
        return company
    if source == 'today':
        return date.today().isoformat()
    if source in {'employee', 'department', 'designation', 'joining_date', 'employee_number', 'default_shift'}:
        employee_field = {
            'employee': 'name', 'department': 'department', 'designation': 'designation',
            'joining_date': 'date_of_joining', 'employee_number': 'employee_number',
            'default_shift': 'default_shift',
        }[source]
        value = frappe.db.get_value(
            'Employee',
            {'company': company, 'user_id': frappe.session.user, 'status': 'Active'},
            employee_field,
        )
        if source == 'employee_number' and not value:
            return frappe.db.get_value(
                'Employee', {'company': company, 'user_id': frappe.session.user, 'status': 'Active'}, 'name')
        return value.isoformat() if source == 'joining_date' and value else value
    return field.get('default')


def fail(message):
    frappe.throw(message)


def guard_storage(doc):
    if not doc.flags.form_service:
        fail("تغییر فرم فقط از مسیر مدیریت فرم‌ها مجاز است.")
    if doc.doctype != "ASOUD Form" and not doc.is_new():
        fail("نسخه و ثبت قبلی تغییرناپذیر است.")


def parse(value):
    if isinstance(value, str):
        if len(value) > 250000:
            fail("اندازه اطلاعات فرم بیش از حد مجاز است.")
        try:
            value = json.loads(value)
        except (ValueError, TypeError):
            fail("ساختار اطلاعات معتبر نیست.")
    if not isinstance(value, dict) or len(json.dumps(value)) > 250000:
        fail("ساختار اطلاعات معتبر نیست.")
    return copy.deepcopy(value)


def fields(schema):
    return [f for section in schema.get("sections", []) for f in section.get("fields", [])]


_DIGIT_TRANSLATION = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫", "01234567890123456789.")


def number(value):
    try:
        if isinstance(value, str):
            value = value.strip().translate(_DIGIT_TRANSLATION).replace("٬", "")
        value = Decimal(str(value if value not in (None, "") else 0))
        if not value.is_finite() or abs(value) > Decimal("1e18"):
            raise ValueError()
        return value
    except (InvalidOperation, ValueError, TypeError):
        fail("مقدار عددی معتبر نیست.")


def validate_schema(raw):
    schema = parse(raw)
    version = schema.get("schema_version", 1)
    if version is None:
        version = 1
    if version not in (1, 2) or isinstance(version, bool):
        fail("نسخه ساختار فرم معتبر نیست.")
    if (schema.get("kind") not in {"Request", "Document"}
            or not 1 <= len(str(schema.get("title", "")).strip()) <= 140):
        fail("عنوان و نوع فرم را مشخص کنید.")
    sections = schema.get("sections")
    if not isinstance(sections, list) or not 1 <= len(sections) <= 30:
        fail("فرم باید بین یک تا سی بخش داشته باشد.")
    if any(not isinstance(s, dict) or not isinstance(s.get("id"), str)
           or not re.fullmatch(r"[a-z][a-z0-9_]{0,59}", s["id"])
           or not 1 <= len(str(s.get("title", "")).strip()) <= 140
           or not isinstance(s.get("fields"), list) for s in sections):
        fail("بخش‌ها یا شناسه بخش فرم معتبر نیست.")
    if len({s['id'] for s in sections}) != len(sections):
        fail("شناسه بخش‌ها تکراری است.")
    for section in sections:
        for key in ('description', 'icon', 'color', 'background_color'):
            if key in section and (not isinstance(section[key], str) or len(section[key]) > 500):
                fail('مشخصات نمایشی بخش معتبر نیست.')
        for key in ('collapsible', 'collapsed'):
            if key in section and not isinstance(section[key], bool):
                fail('تنظیمات بخش معتبر نیست.')
    all_fields = fields(schema)
    if not 1 <= len(all_fields) <= 100:
        fail("تعداد فیلدها باید بین یک و صد باشد.")

    def check_fields(items, nested=False):
        keys = set()
        for field in items:
            if not isinstance(field, dict):
                fail('ساختار فیلد معتبر نیست.')
            key = field.get("key", "")
            if not isinstance(key, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,59}", key) or key in keys:
                fail("شناسه فیلد نامعتبر یا تکراری است.")
            keys.add(key)
            kind = field.get("type")
            if not 1 <= len(str(field.get("label", "")).strip()) <= 140 or kind not in TYPES:
                fail("عنوان یا نوع فیلد نامعتبر است.")
            if kind == "Link" and field.get("source") not in SOURCES:
                fail("منبع اطلاعات سیستم معتبر نیست.")
            default_source = field.get('default_source')
            if default_source and default_source not in DEFAULT_SOURCES:
                fail('منبع مقدار پیش‌فرض معتبر نیست.')
            if 'help' in field and (not isinstance(field['help'], str) or len(field['help']) > 1000):
                fail('راهنمای فیلد معتبر نیست.')
            if 'exclude_self' in field and (field['exclude_self'] is not True and field['exclude_self'] is not False
                                            or (field['exclude_self'] and (kind != 'Link' or field.get('source') != 'Employee'))):
                fail('گزینه حذف خود فقط برای فیلد پیوند به کارمند مجاز است.')
            if field.get('fetch_from') is not None:
                fetch = field['fetch_from']
                match = re.fullmatch(r'([a-z][a-z0-9_]{0,59})\.([a-z_]+)', fetch) if isinstance(fetch, str) else None
                target = next((f for f in items if match and f.get('key') == match.group(1)), None)
                if (not match or not target or target.get('type') != 'Link' or target['key'] == key
                        or match.group(2) not in FETCH_ATTRIBUTES.get(target.get('source'), ())):
                    fail('منبع مقدار خودکار فیلد معتبر نیست.')
            if 'not_equal' in field:
                other = next((f for f in items if f.get('key') == field['not_equal']), None) if isinstance(field['not_equal'], str) else None
                if (not other or other['key'] == key or kind not in NOT_EQUAL_TYPES
                        or other.get('type') not in NOT_EQUAL_TYPES):
                    fail('فیلد مقایسه برای شرط یکسان نبودن معتبر نیست.')
            if 'not_equal_message' in field and (not isinstance(field['not_equal_message'], str)
                                                 or not 1 <= len(field['not_equal_message']) <= 500
                                                 or not field.get('not_equal')):
                fail('پیام شرط یکسان نبودن معتبر نیست.')
            if 'unique' in field and (not isinstance(field['unique'], bool) or (field['unique'] and not nested)):
                fail('یکتا بودن فقط برای ستون جدول مجاز است.')
            if field.get('link_filter'):
                rule = field['link_filter']
                if not isinstance(rule, dict) or rule.get('field') not in LINK_FILTERS.get(field.get('source'), set()):
                    fail('فیلتر اطلاعات سیستم مجاز نیست.')
            if kind in {"Select", "MultiSelect"}:
                choices = field.get("options", [])
                if (not isinstance(choices, list) or not choices or len(choices) > 100
                        or any(not isinstance(v, dict)
                               or not isinstance(v.get("id"), str)
                               or not re.fullmatch(r"[a-z][a-z0-9_]{0,59}", v["id"])
                               or not 1 <= len(str(v.get("label", "")).strip()) <= 140
                               for v in choices)
                        or len({v["id"] for v in choices}) != len(choices)):
                    fail("گزینه‌های انتخابی معتبر نیستند.")
            if 'style' in field and (kind != 'Select' or field['style'] not in {'dropdown', 'radio'}):
                fail('شیوه نمایش فهرست انتخابی معتبر نیست.')
            if 'after_or_equal' in field and (kind != 'Date' or not isinstance(field['after_or_equal'], str)
                                              or not field['after_or_equal']):
                fail('وابستگی تاریخ معتبر نیست.')
            if 'after_or_equal_message' in field and (not isinstance(field['after_or_equal_message'], str)
                                                      or not 1 <= len(field['after_or_equal_message']) <= 500
                                                      or not field.get('after_or_equal')):
                fail('پیام وابستگی تاریخ معتبر نیست.')
            for low, high in (("min", "max"), ("min_length", "max_length"), ("min_rows", "max_rows")):
                if field.get(low) is not None and field.get(high) is not None and number(field[low]) > number(field[high]):
                    fail("حداقل نباید از حداکثر بیشتر باشد.")
            for setting in ('min_length', 'max_length', 'min_rows', 'max_rows'):
                if setting in field and (number(field[setting]) < 0 or number(field[setting]) != number(field[setting]).to_integral()):
                    fail('محدودیت طول و تعداد باید عدد صحیح غیرمنفی باشد.')
            if field.get('format') not in (None, '', 'email', 'mobile'):
                fail('قالب اعتبارسنجی مجاز نیست.')
            if kind == "Table":
                columns = field.get("columns", [])
                if nested or not isinstance(columns, list) or not 1 <= len(columns) <= 20:
                    fail("جدول باید یک تا بیست ستون داشته باشد؛ جدول تو در تو مجاز نیست.")
                if not 1 <= int(field.get("max_rows", 100)) <= 100:
                    fail("حداکثر ردیف جدول باید بین یک تا صد باشد.")
                check_fields(columns, True)
            if kind == "Formula":
                formula = field.get("formula")
                if not isinstance(formula, dict):
                    fail("فرمول معتبر نیست.")
                op = formula.get("op", "expression" if formula.get("expression") else None)
                if op not in FORMULAS or not 0 <= int(formula.get("precision", 2)) <= 8:
                    fail("فرمول معتبر نیست.")
                if not isinstance(formula.get('inputs', []), list) or len(formula.get('inputs', [])) > 100:
                    fail('ورودی فرمول معتبر نیست.')
                if formula.get('op') in {'subtract', 'multiply', 'divide', 'percent'} and len(formula.get('inputs', [])) != 2:
                    fail('این فرمول به دو ورودی نیاز دارد.')
                if formula.get('op') == 'add' and not formula.get('inputs'):
                    fail('ورودی جمع را انتخاب کنید.')
                if formula.get('op') == 'chain':
                    ops = formula.get('ops')
                    inputs = formula.get('inputs', [])
                    if not isinstance(ops, list) or len(inputs) < 2 or len(ops) != len(inputs) - 1:
                        fail('تعداد عملگرهای فرمول معتبر نیست.')
                    if any(not isinstance(o, str) or o not in CHAIN_OPS for o in ops):
                        fail('عملگر فرمول معتبر نیست.')
                if formula.get('op') in {'sum', 'sum_product', 'average', 'count', 'min', 'max'} and (nested or (formula.get('table') and not formula.get('table'))):
                    fail('جدول محاسبه را انتخاب کنید؛ محاسبه تجمیعی داخل ستون مجاز نیست.')
                if formula.get('table'):
                    count = len(formula.get('columns', []))
                    if formula.get('op') in {'sum', 'average', 'min', 'max'} and count != 1 or formula.get('op') == 'sum_product' and count != 2:
                        fail('تعداد ستون‌های فرمول معتبر نیست.')
            if kind in {'File', 'Image', 'Signature'}:
                extensions = field.get('extensions', ['pdf', 'jpg', 'jpeg', 'png'])
                if not isinstance(extensions, list) or not extensions or not set(extensions).issubset({'pdf', 'jpg', 'jpeg', 'png', 'xlsx', 'csv', 'docx'}):
                    fail('پسوندهای فایل مجاز نیستند.')
                if not 1 <= int(field.get('max_mb', 10)) <= 10:
                    fail('حجم فایل باید بین یک تا ده مگابایت باشد.')
                if not 1 <= int(field.get('max_files', 1)) <= 10:
                    fail('تعداد فایل باید بین یک تا ده باشد.')
        # Column formulas are evaluated in dependency order, like top-level fields.
        graph = {f['key']: set(f.get('formula', {}).get('inputs', [])) if f['type'] == 'Formula' else set() for f in items}
        kinds = {f['key']: f['type'] for f in items}
        for field in items:
            if field.get('link_filter'):
                graph[field['key']].add(field['link_filter'].get('value_field'))
            if field.get('fetch_from'):
                graph[field['key']].add(field['fetch_from'].split('.')[0])
            for dep in field.get('formula', {}).get('inputs', []) if field['type'] == 'Formula' else []:
                if kinds.get(dep) not in NUMBERS:
                    fail('ورودی محاسبه باید عددی باشد.')
        active, finished = set(), set()
        def visit_column(key):
            if key not in graph:
                fail('ورودی محاسبه وجود ندارد.')
            if key in active:
                fail('چرخه محاسبات وجود دارد.')
            if key in finished:
                return
            active.add(key)
            for dep in graph[key]:
                visit_column(dep)
            active.remove(key)
            finished.add(key)
        for key in graph:
            visit_column(key)
        return keys

    keys = check_fields(all_fields)
    by_key = {f["key"]: f for f in all_fields}
    graph = {key: set() for key in keys}
    for field in all_fields:
        if field.get('after_or_equal'):
            dependency = field['after_or_equal']
            if dependency == field['key'] or by_key.get(dependency, {}).get('type') != 'Date':
                fail('فیلد تاریخ وابسته معتبر نیست.')
            graph[field['key']].add(dependency)
        if field.get('link_filter'):
            dependency = field['link_filter'].get('value_field')
            if dependency not in keys:
                fail('فیلد وابسته منبع اطلاعات وجود ندارد.')
            graph[field['key']].add(dependency)
        formula = field.get("formula") if field["type"] == "Formula" else None
        if formula:
            for key in formula.get("inputs", []):
                if key not in keys:
                    fail("ورودی فرمول وجود ندارد.")
                if by_key[key]['type'] not in NUMBERS:
                    fail('ورودی محاسبه باید عددی باشد.')
                graph[field["key"]].add(key)
            if formula.get("table"):
                table = by_key.get(formula["table"], {})
                if table.get("type") != "Table":
                    fail("جدول محاسبات وجود ندارد.")
                graph[field["key"]].add(formula["table"])
                cols = {c["key"] for c in table.get("columns", [])}
                if any(c not in cols for c in formula.get("columns", [])):
                    fail("ستون محاسبات وجود ندارد.")
    rules = schema.get("rules", [])
    if not isinstance(rules, list) or len(rules) > 100:
        fail("تعداد قوانین بیش از حد مجاز است.")
    for rule in rules:
        if rule.get("target") not in keys or rule.get("action") not in {"visible", "required", "readonly"} or rule.get("join") not in {"and", "or"}:
            fail("قانون نامعتبر است.")
        conditions = rule.get("conditions", [])
        if not isinstance(conditions, list) or not 1 <= len(conditions) <= 20:
            fail("تعداد شرط‌ها معتبر نیست.")
        for condition in conditions:
            key, op = condition.get("field"), condition.get("op")
            if key not in keys or op not in OPERATORS:
                fail("فیلد یا عملگر شرط معتبر نیست.")
            if op in {"gt", "lt", "ge", "le"} and by_key[key]["type"] not in NUMBERS | {"Date", "Time", "DateTime"}:
                fail("عملگر با نوع فیلد سازگار نیست.")
            kind = by_key[key]['type']
            if kind == 'Table' and op not in {'empty', 'not_empty'} or kind == 'MultiSelect' and op not in {'contains', 'empty', 'not_empty'}:
                fail('عملگر با فیلد جدولی یا چندانتخابی سازگار نیست.')
            if op == 'contains' and kind not in {'Text', 'LongText', 'Barcode', 'MultiSelect'}:
                fail('عملگر شامل برای این فیلد مجاز نیست.')
            if op not in {'empty', 'not_empty'} and condition.get('value') is None:
                fail('مقدار شرط را وارد کنید.')
            if kind in NUMBERS and op not in {'empty', 'not_empty'}:
                number(condition.get('value'))
            graph[rule["target"]].add(key)
    visiting, done = set(), set()

    def visit(key):
        if key in visiting:
            fail("چرخه وابستگی بین فیلدها وجود دارد.")
        if key in done:
            return
        visiting.add(key)
        for dependency in graph[key]:
            visit(dependency)
        visiting.remove(key)
        done.add(key)
    for key in graph:
        visit(key)
    access = schema.get("access", {})
    if access.get("mode", "all") not in {"all", "roles", "departments", "and", "or"}:
        fail("روش دسترسی معتبر نیست.")
    for key, doctype in (("roles", "Role"), ("departments", "Department")):
        values = access.get(key, [])
        if not isinstance(values, list) or len(values) > 100 or any(not isinstance(v, str) or not frappe.db.exists(doctype, v) for v in values):
            fail("نقش یا واحد انتخاب‌شده معتبر نیست.")
    mode = access.get('mode', 'all')
    if mode in {'roles', 'and'} and not access.get('roles') or mode in {'departments', 'and'} and not access.get('departments'):
        fail('حداقل یک نقش یا واحد متناسب با روش دسترسی انتخاب کنید.')
    if mode == 'or' and not access.get('roles') and not access.get('departments'):
        fail('حداقل یک نقش یا واحد انتخاب کنید.')
    return schema


def matches(condition, values, field_type=None):
    actual, expected, op = values.get(condition["field"]), condition.get("value"), condition["op"]
    empty = actual is None or actual == "" or actual == []
    if op == "empty":
        return empty
    if op == "not_empty":
        return not empty
    if op in {'eq', 'ne'}:
        equal = number(actual) == number(expected) if field_type in NUMBERS else str(actual).lower() == str(expected).lower()
        return equal if op == 'eq' else not equal
    if op == "contains":
        return expected in actual if isinstance(actual, list) else str(expected) in str(actual or "")
    try:
        left, right = Decimal(str(actual)), Decimal(str(expected))
    except InvalidOperation:
        left, right = str(actual or ""), str(expected or "")
    return {"gt": left > right, "lt": left < right, "ge": left >= right, "le": left <= right}[op]


def flags(field, schema, values):
    result = {"visible": True, "required": bool(field.get("required")), "readonly": bool(field.get("readonly"))}
    for action in result:
        rules = [r for r in schema.get("rules", []) if r.get("enabled", True) and r['target'] == field['key'] and r['action'] == action]
        if rules:
            kinds = {f['key']: f['type'] for f in fields(schema)}
            triggered = any((all if r['join'] == 'and' else any)(matches(c, values, kinds.get(c['field'])) for c in r['conditions']) for r in rules)
            result[action] = triggered if action == 'visible' else result[action] or triggered
    return result


class _ExprParser:
    def __init__(self, expr_str, values):
        self.expr_str = expr_str
        self.values = values
        self.tokens = self.tokenize(expr_str)
        self.pos = 0

    def tokenize(self, s):
        s = str(s).strip().translate(_DIGIT_TRANSLATION).replace("٬", "")
        pattern = r"\s*([0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|[A-Za-z_][A-Za-z0-9_]*|<=|>=|!=|==|[<>=+\-*/%(),«»])"
        raw = re.findall(pattern, s)
        tokens = []
        for t in raw:
            if t not in ("«", "»"):
                tokens.append(t)
        return tokens

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def consume(self, expected=None):
        tok = self.peek()
        if expected and tok != expected:
            fail(f"فرمول معتبر نیست: انتظار {expected} به جای {tok}")
        self.pos += 1
        return tok

    def parse(self):
        return self.parse_expr(True)

    def parse_expr(self, execute):
        return self.parse_comparison(execute)

    def parse_comparison(self, execute):
        left = self.parse_additive(execute)
        while self.peek() in (">", "<", "=", "==", ">=", "<=", "!="):
            op = self.consume()
            right = self.parse_additive(execute)
            if execute:
                if op == ">":
                    left = Decimal(1) if left > right else Decimal(0)
                elif op == "<":
                    left = Decimal(1) if left < right else Decimal(0)
                elif op in ("=", "=="):
                    left = Decimal(1) if left == right else Decimal(0)
                elif op == ">=":
                    left = Decimal(1) if left >= right else Decimal(0)
                elif op == "<=":
                    left = Decimal(1) if left <= right else Decimal(0)
                elif op == "!=":
                    left = Decimal(1) if left != right else Decimal(0)
        return left

    def parse_additive(self, execute):
        left = self.parse_multiplicative(execute)
        while self.peek() in ("+", "-"):
            op = self.consume()
            right = self.parse_multiplicative(execute)
            if execute:
                left = (left + right) if op == "+" else (left - right)
        return left

    def parse_multiplicative(self, execute):
        left = self.parse_unary(execute)
        while self.peek() in ("*", "/", "%"):
            op = self.consume()
            right = self.parse_unary(execute)
            if execute:
                if op == "*":
                    left = left * right
                elif op == "/":
                    if right == 0:
                        fail("تقسیم بر صفر در فرمول مجاز نیست.")
                    left = left / right
                elif op == "%":
                    left = (left * right) / Decimal(100)
        return left

    def parse_unary(self, execute):
        if self.peek() == "-":
            self.consume("-")
            val = self.parse_unary(execute)
            return -val if execute else Decimal(0)
        if self.peek() == "+":
            self.consume("+")
            return self.parse_unary(execute)
        return self.parse_primary(execute)

    def parse_primary(self, execute):
        tok = self.peek()
        if tok is None:
            fail("فرمول خالی است.")
        if tok == "(":
            self.consume("(")
            val = self.parse_expr(execute)
            self.consume(")")
            return val

        try:
            val = Decimal(tok)
            self.consume()
            return val
        except Exception:
            pass

        ident = self.consume()
        if self.peek() == "(":
            self.consume("(")
            fn = ident.upper()
            if fn == "IF":
                cond_val = self.parse_expr(execute)
                cond_bool = (cond_val != Decimal(0)) if execute else False
                self.consume(",")
                true_val = self.parse_expr(execute and cond_bool)
                self.consume(",")
                false_val = self.parse_expr(execute and not cond_bool)
                self.consume(")")
                return true_val if (execute and cond_bool) else (false_val if execute else Decimal(0))
            elif fn == "ROUND":
                x = self.parse_expr(execute)
                digits = 0
                if self.peek() == ",":
                    self.consume(",")
                    d_val = self.parse_expr(execute)
                    if execute:
                        digits = int(d_val)
                self.consume(")")
                if execute:
                    return x.quantize(Decimal(10) ** -digits, rounding=ROUND_HALF_UP)
                return Decimal(0)
            elif fn in ("MAX", "MIN"):
                args = [self.parse_expr(execute)]
                while self.peek() == ",":
                    self.consume(",")
                    args.append(self.parse_expr(execute))
                self.consume(")")
                if execute:
                    return max(args) if fn == "MAX" else min(args)
                return Decimal(0)
            else:
                fail(f"تابع ناشناخته در فرمول: {ident}")
        else:
            if execute:
                return number(self.values.get(ident))
            return Decimal(0)


def _eval_condition(cond, values):
    if isinstance(cond, str):
        return _ExprParser(cond, values).parse() != Decimal(0)
    if isinstance(cond, dict):
        op = cond.get("op", cond.get("cmp", "eq"))
        if "inputs" in cond:
            left_key, right_key = cond["inputs"][0], cond["inputs"][1]
            left = _eval_branch(left_key, values)
            right = _eval_branch(right_key, values)
        else:
            left = _eval_branch(cond.get("left"), values)
            right = _eval_branch(cond.get("right"), values)
        if op in (">", "gt"):
            return left > right
        if op in ("<", "lt"):
            return left < right
        if op in ("=", "==", "eq"):
            return left == right
        if op in (">=", "ge"):
            return left >= right
        if op in ("<=", "le"):
            return left <= right
        if op in ("!=", "ne"):
            return left != right
    return False


def _eval_branch(branch, values):
    if isinstance(branch, dict):
        return Decimal(calculate(branch, values, raw_decimal=True))
    if isinstance(branch, (int, float, Decimal)):
        return Decimal(str(branch))
    if isinstance(branch, str):
        if branch in values:
            return number(values.get(branch))
        try:
            cleaned = branch.strip().translate(_DIGIT_TRANSLATION).replace("٬", "")
            return Decimal(cleaned)
        except Exception:
            return number(values.get(branch))
    return Decimal(0)


def calculate(formula, values, raw_decimal=False):
    if "expression" in formula:
        val = _ExprParser(formula["expression"], values).parse()
        if raw_decimal:
            return val
        prec = int(formula.get("precision", 2))
        return str(val.quantize(Decimal(10) ** -prec, rounding=ROUND_HALF_UP))

    op = formula.get("op")
    rows = values.get(formula.get("table"), []) or []
    columns = formula.get("columns", [])
    args = [number(values.get(key)) for key in formula.get("inputs", [])]
    if op == "count":
        value = Decimal(len(rows))
    elif op in {"sum", "average", "sum_product", "min", "max"} and (formula.get("table") or (rows and columns)):
        nums = [number(row.get(columns[0])) * (number(row.get(columns[1])) if op == 'sum_product' and len(columns) > 1 else 1) for row in rows] if columns else []
        if not nums:
            value = Decimal(0)
        elif op == "min":
            value = min(nums)
        elif op == "max":
            value = max(nums)
        elif op == "average":
            value = sum(nums, Decimal(0)) / len(nums)
        else:
            value = sum(nums, Decimal(0))
    elif op == "add":
        value = sum(args, Decimal(0))
    elif op in {"min", "max"}:
        if not args:
            fail("این محاسبه به ورودی نیاز دارد.")
        value = min(args) if op == "min" else max(args)
    elif op == "round":
        if not args:
            fail("این محاسبه به ورودی نیاز دارد.")
        digits = int(args[1]) if len(args) > 1 else int(formula.get("digits", formula.get("precision", 0)))
        value = args[0].quantize(Decimal(10) ** -digits, rounding=ROUND_HALF_UP)
    elif op == "if":
        cond = _eval_condition(formula.get("condition"), values)
        branch = formula.get("then") if cond else formula.get("else")
        value = _eval_branch(branch, values)
    elif op == "chain" or (isinstance(formula.get("ops"), list) and formula.get("ops")):
        if not args:
            fail("این محاسبه به ورودی نیاز دارد.")
        ops = formula.get("ops")
        if not isinstance(ops, list) or len(args) != len(ops) + 1:
            fail("این محاسبه به دو ورودی نیاز دارد.")
        rem_args = [args[0]]
        rem_ops = []
        for operation, next_val in zip(ops, args[1:]):
            if operation in ("multiply", "divide", "percent"):
                prev_val = rem_args.pop()
                if operation == "multiply":
                    rem_args.append(prev_val * next_val)
                elif operation == "divide":
                    if next_val == Decimal(0):
                        fail("تقسیم بر صفر در فرمول مجاز نیست.")
                    rem_args.append(prev_val / next_val)
                elif operation == "percent":
                    rem_args.append((prev_val * next_val) / Decimal(100))
            elif operation in ("add", "subtract"):
                rem_ops.append(operation)
                rem_args.append(next_val)
            else:
                fail("محاسبه پشتیبانی نمی‌شود.")
        value = rem_args[0]
        for operation, next_val in zip(rem_ops, rem_args[1:]):
            if operation == "add":
                value = value + next_val
            elif operation == "subtract":
                value = value - next_val
    elif len(args) != 2:
        fail("این محاسبه به دو ورودی نیاز دارد.")
    elif op == "subtract":
        value = args[0] - args[1]
    elif op == "multiply":
        value = args[0] * args[1]
    elif op == "percent":
        value = args[0] * args[1] / 100
    elif op == "divide":
        if args[1] == 0:
            fail("تقسیم بر صفر در فرمول مجاز نیست.")
        value = args[0] / args[1]
    else:
        fail("محاسبه پشتیبانی نمی‌شود.")

    if raw_decimal:
        return value
    return str(number(value).quantize(Decimal(10) ** -int(formula.get("precision", 2)), rounding=ROUND_HALF_UP))


def validate_values(schema, raw, company, _file_budget=None):
    file_budget = _file_budget if _file_budget is not None else {'bytes': 0, 'names': set()}
    values = parse(raw)
    definitions = fields(schema)
    known = {f['key'] for f in definitions}
    if set(values) - known:
        fail("اطلاعات شامل فیلد ناشناخته است.")
    calculated, evaluating = set(), set()
    by_key = {f['key']: f for f in definitions}
    for field in definitions:
        if field.get('readonly') or field['type'] == 'Display':
            values[field['key']] = default_value(field, company)
        else:
            values.setdefault(field['key'], default_value(field, company))

    def compute(field):
        if field['key'] in calculated:
            return
        if field['key'] in evaluating:
            fail('چرخه وابستگی معتبر نیست.')
        evaluating.add(field['key'])
        if field.get('link_filter'):
            compute(by_key[field['link_filter']['value_field']])
        if field.get('fetch_from'):
            compute(by_key[field['fetch_from'].split('.')[0]])
        for rule in schema.get('rules', []):
            if rule.get('enabled', True) and rule['target'] == field['key']:
                for condition in rule['conditions']:
                    compute(by_key[condition['field']])
        formula = field.get('formula')
        if field['type'] == 'Formula' and formula:
            for key in formula.get('inputs', []):
                compute(by_key[key])
            if formula.get('table'):
                compute(by_key[formula['table']])
        state = flags(field, schema, values)
        if not state['visible']:
            values.pop(field['key'], None)
        elif field.get('fetch_from'):
            values[field['key']] = check(field, fetched(field), state['required'])
        else:
            value = calculate(formula, values) if field['type'] == 'Formula' else values.get(field['key'])
            if state['readonly'] and field['type'] != 'Formula':
                value = default_value(field, company)
            values[field['key']] = check(field, value, state['required'])
        evaluating.remove(field['key'])
        calculated.add(field['key'])

    def employee():
        if 'employee' not in file_budget:
            file_budget['employee'] = current_employee(company)
        return file_budget['employee']

    def fetched(field):
        """Derived field: always read from the database, never from the client."""
        link_key, attribute = field['fetch_from'].split('.')
        link, record = by_key[link_key], values.get(link_key)
        if not record or not isinstance(record, str):
            return None
        raw = frappe.db.get_value(link['source'], record, attribute)
        return fetch_value(raw, field['type'] if field['type'] in {'Date', 'Time'} else None)

    def check(field, value, required):
        label, kind = field['label'], field['type']
        if kind == 'Table' and value is None:
            value = []
        if kind != 'Table' and (value is None or value == '' or value == []):
            if required:
                fail(f"{label}: تکمیل این فیلد الزامی است.")
            return value
        if kind in NUMBERS:
            n = number(value)
            if kind == 'Integer' and n != n.to_integral():
                fail(f"{label}: عدد صحیح وارد کنید.")
            if field.get('min') is not None and n < number(field['min']):
                fail(f"{label}: کمتر از حداقل است.")
            if field.get('max') is not None and n > number(field['max']):
                fail(f"{label}: بیشتر از حداکثر است.")
            return str(n)
        if kind in {'Boolean', 'Checkbox'} and not isinstance(value, bool):
            fail(f"{label}: مقدار بله یا خیر لازم است.")
        if kind not in {'Boolean', 'Checkbox', 'Table', 'MultiSelect', 'File', 'Image', 'Signature'} | NUMBERS and not isinstance(value, str):
            fail(f"{label}: نوع مقدار معتبر نیست.")
        if kind in {'Select', 'MultiSelect'}:
            chosen = value if kind == 'MultiSelect' else [value]
            option_ids = {option['id'] for option in field['options']}
            if not isinstance(chosen, list) or any(v not in option_ids for v in chosen):
                fail(f"{label}: انتخاب معتبر نیست.")
        if kind in {'Date', 'Time', 'DateTime'}:
            try:
                {'Date': date, 'Time': time, 'DateTime': datetime}[kind].fromisoformat(value)
            except (TypeError, ValueError):
                fail(f"{label}: تاریخ یا ساعت معتبر نیست.")
            if field.get('min_date') and value[:10] < field['min_date'][:10]:
                fail(f"{label}: پیش از بازه مجاز است.")
            if field.get('max_date') and value[:10] > field['max_date'][:10]:
                fail(f"{label}: پس از بازه مجاز است.")
        if kind == 'Link' and field['source'] in SCOPED_SOURCES:
            source = field['source']
            mine = employee()
            if not mine and source in {'Attendance', 'Asset'}:
                fail(f"{label}: پرونده پرسنلی شما ثبت نشده است.")
            if not isinstance(value, str) or not frappe.db.exists(source, {**scope_filters(source, company, mine), 'name': value}):
                fail(f"{label}: رکورد انتخاب‌شده در محدوده مجاز شما نیست.")
            if field.get('link_filter') and source == 'Attendance':
                rule = field['link_filter']
                if str(frappe.db.get_value(source, value, rule['field'])) != str(values.get(rule['value_field'])):
                    fail(f"{label}: رکورد با فیلتر وابسته سازگار نیست.")
        elif kind == 'Link':
            source = field['source']
            if not isinstance(value, str) or not frappe.has_permission(source, 'read', value):
                fail(f"{label}: رکورد انتخاب‌شده در دسترس نیست.")
            if field.get('exclude_self') and value == employee():
                fail('نمی‌توانید خودتان را انتخاب کنید.')
            record = frappe.get_doc(source, value)
            if record.meta.has_field('company') and record.get('company') != company:
                fail(f"{label}: رکورد متعلق به این دفتر نیست.")
            if field.get('link_filter'):
                rule = field['link_filter']
                if record.get(rule['field']) != values.get(rule['value_field']):
                    fail(f"{label}: رکورد با فیلتر وابسته سازگار نیست.")
        if kind in {'File', 'Image', 'Signature'}:
            if isinstance(value, list):
                if len(value) > int(field.get('max_files', 1)) or any(not isinstance(v, str) for v in value):
                    fail(f'{label}: تعداد یا شناسه فایل‌ها معتبر نیست.')
                return [check({**field, 'max_files': 1}, v, False) for v in value]
            if not isinstance(value, str) or not frappe.db.exists('File', value):
                fail(f"{label}: فایل معتبر نیست.")
            file = frappe.get_doc('File', value)
            file.check_permission('read')
            if not file.is_private or file.owner != frappe.session.user:
                fail(f"{label}: فایل خصوصی خود را انتخاب کنید.")
            if int(file.file_size or 0) > min(int(field.get('max_mb', 10)), 10) * 1024 * 1024:
                fail(f"{label}: فایل بیش از حد بزرگ است.")
            if file.name not in file_budget['names']:
                file_budget['names'].add(file.name)
                file_budget['bytes'] += int(file.file_size or 0)
            if file_budget['bytes'] > 25 * 1024 * 1024 or len(file_budget['names']) > 30:
                fail('تعداد یا حجم مجموع پیوست‌ها بیش از حد مجاز است.')
            suffix = (file.file_name or '').rsplit('.', 1)[-1].lower()
            extensions = field.get('extensions', ['pdf', 'jpg', 'jpeg', 'png'])
            if suffix not in extensions or (kind in {'Image', 'Signature'} and suffix not in {'jpg', 'jpeg', 'png'}):
                fail(f"{label}: نوع فایل مجاز نیست.")
        if kind == 'Table':
            minimum = max(int(field.get('min_rows', 0)), 1 if required else 0)
            if not isinstance(value, list) or len(value) > int(field.get('max_rows', 100)):
                fail(f"{label}: تعداد ردیف‌ها مجاز نیست.")
            if len(value) < minimum:
                fail(f"{label}: حداقل {minimum} ردیف لازم است.")
            result = []
            for row in value:
                columns = field['columns']
                if not isinstance(row, dict) or set(row) - {c['key'] for c in columns}:
                    fail(f"{label}: ستون ناشناخته است.")
                result.append(validate_values({'sections': [{'fields': columns}], 'rules': []}, row, company, file_budget))
            for column in field['columns']:
                if column.get('unique'):
                    seen = [str(r[column['key']]) for r in result if r.get(column['key']) not in (None, '', [])]
                    if len(seen) != len(set(seen)):
                        fail(f"ردیف تکراری: {column['label']}")
            return result
        if isinstance(value, str) and kind not in NUMBERS:
            if len(value) < int(field.get('min_length', 0)) or len(value) > int(field.get('max_length', 5000)):
                fail(f"{label}: طول متن مجاز نیست.")
            if field.get('format') == 'email':
                parts = value.split('@')
                if len(parts) != 2 or not parts[0] or '.' not in parts[1] or any(not p for p in parts[1].split('.')) or any(c.isspace() for c in value):
                    fail(field.get('error_message') or f'{label}: ایمیل معتبر نیست.')
            if field.get('format') == 'mobile':
                value = value.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))
                if not re.fullmatch(r'09[0-9]{9}', value):
                    fail(field.get('error_message') or f'{label}: شماره همراه معتبر نیست.')
        return value

    for field in definitions:
        compute(field)
    for field in definitions:
        other = field.get('not_equal')
        if (other and values.get(field['key']) not in (None, '') and values.get(other) not in (None, '')
                and (number(values[field['key']]) == number(values[other]) if field['type'] in NUMBERS
                     and by_key[other]['type'] in NUMBERS else str(values[field['key']]) == str(values[other]))):
            fail(field.get('not_equal_message') or 'مقدار جدید نباید با مقدار فعلی یکسان باشد.')
    for field in definitions:
        dependency = field.get('after_or_equal')
        if not dependency or field['key'] not in values or dependency not in values:
            continue
        if date.fromisoformat(values[field['key']]) < date.fromisoformat(values[dependency]):
            fail(field.get('after_or_equal_message') or 'تاریخ پایان نباید قبل از تاریخ شروع باشد.')
    return values


def migrate_schema(source, values=None):
    schema = copy.deepcopy(source) if isinstance(source, dict) else parse(source)
    labels_by_field = {}

    def migrate_fields(fields_list, path, current_values):
        for index, field in enumerate(fields_list):
            if not isinstance(field, dict):
                continue
            field_path = [*path, index]
            field_type = field.get("type")
            if field_type in ("Select", "MultiSelect"):
                old_options = field.get("options") or []
                if not isinstance(old_options, list):
                    old_options = []
                labels = {}
                options = []
                for option_index, old in enumerate(old_options):
                    if isinstance(old, dict):
                        option = copy.deepcopy(old)
                    else:
                        option = {"label": str(old)}
                    if "id" not in option:
                        option["id"] = f"option_{'_'.join(str(p) for p in [*field_path, option_index])}"
                    if option.get("id") is not None and option.get("label") is not None:
                        options.append(option)
                        labels[str(option["label"])] = str(option["id"])
                field["options"] = options
                field_key = str(field.get("key", ""))
                labels_by_field[field_key] = labels
                if current_values is not None and field_key in current_values:
                    val = current_values[field_key]
                    if isinstance(val, list):
                        current_values[field_key] = [labels.get(str(item), item) for item in val]
                    elif val is not None:
                        current_values[field_key] = labels.get(str(val), val)
            elif field_type == "Table":
                columns = field.get("columns") or []
                if isinstance(columns, list):
                    rows = current_values.get(field.get("key")) if current_values else None
                    if isinstance(rows, list):
                        for row in rows:
                            if isinstance(row, dict):
                                migrate_fields(columns, field_path, row)
                    else:
                        migrate_fields(columns, field_path, None)

    sections = schema.get("sections") or []
    for section_index, section in enumerate(sections):
        if not isinstance(section, dict):
            continue
        sec_fields = section.get("fields") or []
        if isinstance(sec_fields, list):
            migrate_fields(sec_fields, [section_index], values)

    rules = schema.get("rules") or []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        conditions = rule.get("conditions") or []
        for condition in conditions:
            if not isinstance(condition, dict):
                continue
            cond_field = str(condition.get("field", ""))
            option_ids = labels_by_field.get(cond_field)
            if option_ids:
                val = condition.get("value")
                if isinstance(val, list):
                    condition["value"] = [option_ids.get(str(item), item) for item in val]
                elif val is not None:
                    condition["value"] = option_ids.get(str(val), val)

    schema["schema_version"] = 2
    return schema


def migrate_record(record):
    migrated = copy.deepcopy(record)
    values = migrated.get("values") if isinstance(migrated.get("values"), dict) else None
    migrated["schema"] = migrate_schema(migrated.get("schema", {}), values=values)
    if values is not None:
        migrated["values"] = values
    return migrated
