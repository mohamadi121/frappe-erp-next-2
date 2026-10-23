"""Real rows: leave, mission and overtime executors, direct and through the approval dispatcher."""

import frappe
from frappe.utils import add_days, nowdate

from asoud_erp.api.v1 import forms, workflow_request, workflow_runtime
from asoud_erp.integration_tests.fixtures import APPROVER_USER, APITestCase
from asoud_erp.integration_tests.request_fixtures import make_definition
from asoud_erp.integration_tests.request_helpers import open_task
from asoud_erp.services.form_execution import leave_application, mission, overtime


def rows(doctype, **filters):
    return frappe.get_all(doctype, filters=filters, fields=['*'], limit_page_length=0)


class Base(APITestCase):
    def setUp(self):
        super().setUp()
        self.token = frappe.generate_hash(length=8)
        self.first = add_days(nowdate(), -40)  # past: Attendance may not be in the future
        self.user = frappe.get_doc({'doctype': 'User', 'email': f'lmo-{self.token}@example.test',
            'first_name': 'درخواست‌کننده', 'send_welcome_email': 0,
            'roles': [{'role': 'Employee'}]}).insert().name
        self.hr = frappe.get_doc({'doctype': 'User', 'email': f'lmo-hr-{self.token}@example.test',
            'first_name': 'منابع انسانی', 'send_welcome_email': 0,
            'roles': [{'role': 'HR Manager'}]}).insert().name
        self.holiday_list = self.make_holidays([])
        self.employee = frappe.get_doc({'doctype': 'Employee', 'first_name': 'درخواست‌کننده',
            'company': self.company, 'user_id': self.user, 'gender': 'Male', 'date_of_birth': '1990-01-01',
            'date_of_joining': '2020-01-01', 'status': 'Active', 'create_user_permission': 0,
            'reports_to': self.records['approver'], 'holiday_list': self.holiday_list,
            'leave_approver': APPROVER_USER}).insert().name
        definition = frappe.get_doc({'doctype': 'ASOUD Workflow Definition',
            'workflow_code': 'LMO-' + self.token, 'workflow_title': 'مرخصی', 'company': self.company,
            'module_key': 'HR', 'target_doctype': 'ASOUD Workflow Request'}).insert().name
        request = frappe.get_doc({'doctype': 'ASOUD Workflow Request', 'company': self.company,
            'workflow_definition': definition, 'request_type': 'مرخصی', 'subject': 'درخواست',
            'requester_employee': self.employee, 'status': 'Submitted'}).insert()
        frappe.db.set_value('ASOUD Workflow Request', request.name, 'owner', self.user)
        self.request = frappe.get_doc('ASOUD Workflow Request', request.name)

    def day(self, offset):
        return add_days(self.first, offset)

    def make_holidays(self, dates):
        return frappe.get_doc({'doctype': 'Holiday List', 'holiday_list_name': f'LMO-{self.token}-{len(dates)}',
            'from_date': add_days(nowdate(), -400), 'to_date': add_days(nowdate(), 400),
            'holidays': [{'holiday_date': value, 'description': 'تعطیل'} for value in dates]}).insert().name

    def make_leave_type(self, allocation=5, **extra):
        name = f'LMO {frappe.generate_hash(length=6)}'
        frappe.get_doc({'doctype': 'Leave Type', 'leave_type_name': name, 'max_leaves_allowed': 30,
                        **extra}).insert()
        if allocation:
            frappe.get_doc({'doctype': 'Leave Allocation', 'employee': self.employee, 'leave_type': name,
                'from_date': add_days(nowdate(), -300), 'to_date': add_days(nowdate(), 300),
                'new_leaves_allocated': allocation}).submit()
        return name

    def make_attendance(self, value, status='Present'):
        doc = frappe.get_doc({'doctype': 'Attendance', 'employee': self.employee, 'company': self.company,
                              'attendance_date': value, 'status': status}).insert()
        doc.submit()
        return doc.name


class TestLeaveExecution(Base):
    def params(self, leave_type, **extra):
        return {'leave_type': leave_type, 'from_date': self.day(0), 'to_date': self.day(2), **extra}

    def test_submits_with_ledger_attendance_and_real_approver(self):
        leave_type = self.make_leave_type(5)
        result = leave_application.apply(self.request, self.params(leave_type, description='سفر'))
        self.assertEqual((result.status, result.doctype), ('Created', 'Leave Application'))
        doc = frappe.get_doc('Leave Application', result.name)
        self.assertEqual((doc.docstatus, doc.status, doc.employee, doc.company, doc.leave_type, doc.leave_approver,
                          doc.total_leave_days, doc.half_day, doc.description, str(doc.posting_date)),
                         (1, 'Approved', self.employee, self.company, leave_type, APPROVER_USER, 3, 0, 'سفر',
                          nowdate()))
        ledger = rows('Leave Ledger Entry', transaction_name=doc.name, docstatus=1)
        self.assertEqual([(row.leaves, row.leave_type) for row in ledger], [(-3, leave_type)])
        attendance = rows('Attendance', employee=self.employee, leave_application=doc.name)
        self.assertEqual(sorted((str(row.attendance_date), row.status, row.docstatus) for row in attendance),
                         [(self.day(index), 'On Leave', 1) for index in range(3)])
        self.assertEqual(frappe.db.count('Comment', {'reference_doctype': 'Leave Application',
                                                       'reference_name': doc.name, 'comment_type': 'Comment'}), 1)

    def test_half_day_single_day(self):
        leave_type = self.make_leave_type(5)
        params = self.params(leave_type, to_date=self.day(0), half_day=True)
        doc = frappe.get_doc('Leave Application', leave_application.apply(self.request, params).name)
        self.assertEqual((doc.total_leave_days, doc.half_day, str(doc.half_day_date)), (0.5, 1, self.day(0)))
        status = frappe.db.get_value('Attendance', {'leave_application': doc.name}, 'status')
        self.assertEqual(status, 'Half Day')

    def test_balance_is_read_from_hrms_and_failure_leaves_nothing(self):
        leave_type = self.make_leave_type(2)
        with self.assertRaisesRegex(ValueError, leave_application.INSUFFICIENT):
            leave_application.apply(self.request, self.params(leave_type))
        self.assertEqual(frappe.db.count('Leave Application', {'employee': self.employee}), 0)
        self.assertEqual(frappe.db.count('Leave Ledger Entry', {'employee': self.employee, 'docstatus': 1,
                                                                  'transaction_type': 'Leave Application'}), 0)
        # exactly the balance is enough
        two_days = self.params(leave_type, to_date=self.day(1))
        self.assertEqual(leave_application.apply(self.request, two_days).status, 'Created')

    def test_second_request_sees_the_first_one_consumed(self):
        leave_type = self.make_leave_type(4)
        leave_application.apply(self.request, self.params(leave_type))
        with self.assertRaisesRegex(ValueError, leave_application.INSUFFICIENT):
            leave_application.apply(self.request, self.params(leave_type, from_date=self.day(10),
                                                                to_date=self.day(11)))

    def test_no_allocation_unknown_type_and_balance_free_types(self):
        without = self.make_leave_type(0)
        with self.assertRaisesRegex(ValueError, leave_application.NO_ALLOCATION):
            leave_application.apply(self.request, self.params(without))
        with self.assertRaisesRegex(ValueError, leave_application.UNKNOWN_TYPE):
            leave_application.apply(self.request, self.params('no-such-type'))
        unpaid = self.make_leave_type(0, is_lwp=1)
        self.assertEqual(leave_application.apply(self.request, self.params(unpaid)).status, 'Created')

    def test_overlapping_leave_is_refused(self):
        leave_type = self.make_leave_type(10)
        leave_application.apply(self.request, self.params(leave_type))
        with self.assertRaisesRegex(ValueError, leave_application.OVERLAP):
            leave_application.apply(self.request, self.params(leave_type, from_date=self.day(2),
                                                                to_date=self.day(3)))
        self.assertEqual(frappe.db.count('Leave Application', {'employee': self.employee, 'docstatus': 1}), 1)

    def test_present_attendance_blocks_and_is_untouched(self):
        leave_type = self.make_leave_type(5)
        attendance = self.make_attendance(self.day(1))
        with self.assertRaisesRegex(ValueError, leave_application.NATIVE_ERROR):
            leave_application.apply(self.request, self.params(leave_type))
        self.assertEqual(frappe.db.get_value('Attendance', attendance, ['status', 'docstatus']), ('Present', 1))
        self.assertEqual(frappe.db.count('Leave Application', {'employee': self.employee}), 0)

    def test_only_holidays_requested(self):
        leave_type = self.make_leave_type(5)
        frappe.db.set_value('Employee', self.employee, 'holiday_list', self.make_holidays([self.day(0)]))
        with self.assertRaisesRegex(ValueError, leave_application.ONLY_HOLIDAYS):
            leave_application.apply(self.request, self.params(leave_type, to_date=self.day(0)))

    def test_holiday_inside_the_range_is_not_counted(self):
        leave_type = self.make_leave_type(5)
        frappe.db.set_value('Employee', self.employee, 'holiday_list', self.make_holidays([self.day(1)]))
        doc = frappe.get_doc('Leave Application', leave_application.apply(self.request, self.params(leave_type)).name)
        self.assertEqual(doc.total_leave_days, 2)

    def test_approver_rules_follow_hr_settings(self):
        leave_type = self.make_leave_type(5)
        frappe.db.set_value('Employee', self.employee, 'leave_approver', None)
        settings = frappe.get_single('HR Settings')
        settings.leave_approver_mandatory_in_leave_application = 1
        settings.save()
        with self.assertRaisesRegex(ValueError, leave_application.NO_APPROVER):
            leave_application.apply(self.request, self.params(leave_type))
        settings.leave_approver_mandatory_in_leave_application = 0
        settings.save()
        doc = frappe.get_doc('Leave Application', leave_application.apply(self.request, self.params(leave_type)).name)
        self.assertIsNone(doc.leave_approver)
        self.assertEqual(doc.docstatus, 1)

    def test_department_approver_is_used_when_employee_has_none(self):
        leave_type = self.make_leave_type(5)
        department = frappe.get_doc({'doctype': 'Department', 'department_name': 'LMO' + self.token,
            'company': self.company, 'parent_department': 'All Departments',
            'leave_approvers': [{'approver': APPROVER_USER}]}).insert().name
        frappe.db.set_value('Employee', self.employee, {'leave_approver': None, 'department': department})
        doc = frappe.get_doc('Leave Application', leave_application.apply(self.request, self.params(leave_type)).name)
        self.assertEqual(doc.leave_approver, APPROVER_USER)

    def test_requester_must_be_the_active_employee_of_the_owner(self):
        leave_type = self.make_leave_type(5)
        frappe.db.set_value('Employee', self.employee, 'status', 'Inactive')
        with self.assertRaisesRegex(ValueError, 'فعال نیست'):
            leave_application.apply(self.request, self.params(leave_type))
        frappe.db.set_value('Employee', self.employee, 'status', 'Active')
        frappe.db.set_value('ASOUD Workflow Request', self.request.name, 'owner', self.hr)
        self.request.reload()
        with self.assertRaisesRegex(ValueError, 'ثبت نشده'):
            leave_application.apply(self.request, self.params(leave_type))
        self.assertEqual(frappe.db.count('Leave Application', {'employee': self.employee}), 0)


class TestMissionExecution(Base):
    def params(self, **extra):
        return {'from_date': self.day(0), 'to_date': self.day(2), 'destination': 'تبریز',
                'purpose': 'بازدید', **extra}

    def test_submits_attendance_request_with_present_rows(self):
        result = mission.apply(self.request, self.params(notes='هماهنگی'))
        self.assertEqual((result.status, result.doctype), ('Created', 'Attendance Request'))
        doc = frappe.get_doc('Attendance Request', result.name)
        self.assertEqual((doc.docstatus, doc.reason, doc.include_holidays, doc.employee, doc.company,
                          doc.explanation), (1, 'On Duty', 0, self.employee, self.company,
                                             'مقصد: تبریز\nهدف: بازدید\nتوضیحات: هماهنگی'))
        attendance = rows('Attendance', attendance_request=doc.name)
        self.assertEqual(sorted((str(row.attendance_date), row.status, row.docstatus) for row in attendance),
                         [(self.day(index), 'Present', 1) for index in range(3)])

    def test_half_day_marks_half_day_attendance(self):
        doc = frappe.get_doc('Attendance Request', mission.apply(self.request, self.params(
            half_day=True, half_day_date=self.day(1))).name)
        statuses = {str(row.attendance_date): row.status for row in rows('Attendance', attendance_request=doc.name)}
        self.assertEqual(statuses, {self.day(0): 'Present', self.day(1): 'Half Day', self.day(2): 'Present'})

    def assert_review_and_nothing_written(self, expected_days, requests=0):
        before = frappe.db.count('Attendance', {'employee': self.employee})
        result = mission.apply(self.request, self.params())
        self.assertEqual((result.status, result.doctype, result.name), ('needs_review', None, None))
        self.assertEqual(result.reason, mission.review_reason(expected_days))
        self.assertEqual(frappe.db.count('Attendance Request', {'employee': self.employee}), requests)
        self.assertEqual(frappe.db.count('Attendance', {'employee': self.employee}), before)

    def test_week_over_a_weekend_is_submitted_with_attendance_on_working_days_only(self):
        weekend = [self.day(2), self.day(3)]
        frappe.db.set_value('Employee', self.employee, 'holiday_list', self.make_holidays(weekend))
        params = self.params(to_date=self.day(6))
        result = mission.apply(self.request, params)
        self.assertEqual((result.status, result.doctype), ('Created', 'Attendance Request'))
        doc = frappe.get_doc('Attendance Request', result.name)
        self.assertEqual((doc.docstatus, doc.include_holidays), (1, 0))
        days = sorted(str(row.attendance_date) for row in rows('Attendance', attendance_request=doc.name))
        self.assertEqual(days, [self.day(index) for index in (0, 1, 4, 5, 6)])

    def test_holiday_as_start_or_end_needs_review(self):
        frappe.db.set_value('Employee', self.employee, 'holiday_list', self.make_holidays([self.day(0)]))
        self.assert_review_and_nothing_written([self.day(0)])
        frappe.db.set_value('Employee', self.employee, 'holiday_list', self.make_holidays([self.day(2), self.day(1)]))
        self.assert_review_and_nothing_written([self.day(2)])

    def test_attendance_on_a_holiday_inside_the_range_is_not_a_conflict(self):
        frappe.db.set_value('Employee', self.employee, 'holiday_list', self.make_holidays([self.day(1)]))
        self.make_attendance(self.day(1), 'Absent')
        self.assertEqual(mission.apply(self.request, self.params()).status, 'Created')

    def test_existing_attendance_is_never_overwritten(self):
        name = self.make_attendance(self.day(2), 'Absent')
        self.assert_review_and_nothing_written([self.day(2)])
        self.assertEqual(frappe.db.get_value('Attendance', name, ['status', 'docstatus']), ('Absent', 1))

    def test_cancelled_attendance_is_not_a_conflict(self):
        name = self.make_attendance(self.day(2), 'Absent')
        frappe.get_doc('Attendance', name).cancel()
        self.assertEqual(mission.apply(self.request, self.params()).status, 'Created')

    def test_leave_in_the_range_needs_review(self):
        leave_type = f'LMO {frappe.generate_hash(length=6)}'
        frappe.get_doc({'doctype': 'Leave Type', 'leave_type_name': leave_type, 'is_lwp': 1}).insert()
        frappe.get_doc({'doctype': 'Leave Application', 'employee': self.employee, 'company': self.company,
            'leave_type': leave_type, 'from_date': self.day(1), 'to_date': self.day(5), 'status': 'Open',
            'posting_date': nowdate()}).insert()
        self.assert_review_and_nothing_written([self.day(1), self.day(2)])

    def test_overlapping_attendance_request_needs_review(self):
        frappe.get_doc({'doctype': 'Attendance Request', 'employee': self.employee, 'company': self.company,
            'from_date': self.day(2), 'to_date': self.day(4), 'reason': 'Work From Home'}).insert()
        self.assert_review_and_nothing_written([self.day(2)], requests=1)

    def test_shift_must_be_assigned_to_the_person(self):
        shift = frappe.get_doc({'doctype': 'Shift Type', 'name': 'LMO' + self.token, 'start_time': '08:00:00',
                                'end_time': '16:00:00'}).insert().name
        with self.assertRaisesRegex(ValueError, mission.SHIFT_NOT_ALLOWED):
            mission.apply(self.request, self.params(shift=shift))
        # an open-ended assignment (no end date) covers the range
        frappe.get_doc({'doctype': 'Shift Assignment', 'employee': self.employee, 'company': self.company,
                        'shift_type': shift, 'start_date': add_days(self.first, -10), 'status': 'Active'}
                       ).insert().submit()
        doc = frappe.get_doc('Attendance Request', mission.apply(self.request, self.params(shift=shift)).name)
        self.assertEqual(doc.shift, shift)

    def test_failed_submit_keeps_no_partial_result(self):
        original = mission.build

        def broken(params, ctx):
            return {**original(params, ctx), 'shift': 'no-such-shift'}
        mission.build = broken
        try:
            with self.assertRaises(ValueError):
                mission.apply(self.request, self.params())
        finally:
            mission.build = original
        self.assertEqual(frappe.db.count('Attendance Request', {'employee': self.employee}), 0)
        self.assertEqual(frappe.db.count('Attendance', {'employee': self.employee}), 0)


class TestOvertimeExecution(Base):
    def test_needs_review_with_approved_date_and_hours_and_no_document(self):
        counts = {name: frappe.db.count(name) for name in ('Additional Salary', 'Leave Application',
                                                           'Attendance Request', 'Employee Checkin')}
        params = {'work_date': self.day(0), 'start_time': '22:00', 'end_time': '01:30',
                  'end_time__next_day': True, 'purpose': 'پروژه'}
        result = overtime.apply(self.request, params)
        self.assertEqual((result.status, result.doctype, result.name), ('needs_review', None, None))
        self.assertIn('از ساعت ۲۲:۰۰ تا ساعت ۰۱:۳۰ روز بعد به مدت ۳ ساعت و ۳۰ دقیقه', result.reason)
        self.assertEqual(counts, {name: frappe.db.count(name) for name in counts})

    def test_invalid_period_and_missing_employee(self):
        params = {'work_date': self.day(0), 'start_time': '10:00', 'end_time': '09:00', 'purpose': 'x'}
        with self.assertRaisesRegex(ValueError, 'ساعت پایان باید پس از ساعت شروع باشد.'):
            overtime.apply(self.request, params)
        frappe.db.set_value('Employee', self.employee, 'status', 'Inactive')
        with self.assertRaisesRegex(ValueError, 'فعال نیست'):
            overtime.apply(self.request, {**params, 'end_time': '12:00'})


class TestDispatch(Base):
    """Final approval of a real form request runs the mapped executor."""

    def approve(self, kind, fields, values, stage_fields=None):
        definition, stages = make_definition(self.company, fields=[])
        schema = {'kind': 'Request', 'title': 'اجرای آزمایشی', 'workflow': definition,
                  'execution': {'kind': kind},
                  'sections': [{'id': 'main', 'title': 'اصلی', 'fields': fields}]}
        saved = forms.save_form(self.company, schema, client_id=frappe.generate_hash(length=24))['data']
        revision = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']['active_revision']
        frappe.set_user(self.user)
        entry = forms.submit_form(saved['name'], revision, 'درخواست', values,
                                  frappe.generate_hash(length=24))['data']
        request = workflow_request.get_request(entry['reference_name'])['data']
        task = open_task(request['workflow_instance'])
        frappe.set_user(task.assigned_to)
        workflow_runtime.complete_workflow_task(task.name, 'Approve')
        frappe.set_user('Administrator')
        return workflow_request.get_request(request['name'])['data']

    def leave_fields(self):
        return [
            {'key': 'kind', 'label': 'نوع', 'type': 'Link', 'source': 'Leave Type', 'required': True,
             'execution_key': 'leave_type'},
            {'key': 'start', 'label': 'شروع', 'type': 'Date', 'required': True, 'execution_key': 'from_date'},
            {'key': 'end', 'label': 'پایان', 'type': 'Date', 'required': True, 'execution_key': 'to_date'},
            {'key': 'note', 'label': 'توضیح', 'type': 'LongText', 'sensitive': True,
             'execution_key': 'description'}]

    def test_leave_approval_submits_and_confidential_note_is_a_pointer(self):
        leave_type = self.make_leave_type(5)
        approved = self.approve('leave_application', self.leave_fields(), {
            'kind': leave_type, 'start': self.day(0), 'end': self.day(1), 'note': 'گواهی پزشکی'})
        self.assertEqual((approved['native']['status'], approved['native']['doctype']),
                         ('Created', 'Leave Application'))
        doc = frappe.get_doc('Leave Application', approved['native']['name'])
        self.assertEqual((doc.docstatus, doc.status, doc.total_leave_days, doc.employee),
                         (1, 'Approved', 2, self.employee))
        self.assertEqual(doc.description, f'محرمانه؛ جزئیات در درخواست {approved["name"]} است.')
        self.assertEqual(frappe.db.count('Leave Ledger Entry', {'transaction_name': doc.name, 'docstatus': 1}), 1)

    def test_insufficient_balance_fails_in_persian_keeps_approval_and_retries(self):
        leave_type = self.make_leave_type(1)
        approved = self.approve('leave_application', self.leave_fields(), {
            'kind': leave_type, 'start': self.day(0), 'end': self.day(1)})
        self.assertEqual(approved['native']['status'], 'Failed')
        self.assertEqual(approved['native']['error'], leave_application.INSUFFICIENT)
        self.assertEqual(frappe.db.get_value('ASOUD Workflow Instance', approved['workflow_instance'], 'status'),
                         'Completed')
        self.assertEqual(frappe.db.count('Leave Application', {'employee': self.employee}), 0)
        self.assertEqual(frappe.db.count('Attendance', {'employee': self.employee}), 0)
        frappe.get_doc('Leave Allocation', {'employee': self.employee, 'leave_type': leave_type}).cancel()
        frappe.get_doc({'doctype': 'Leave Allocation', 'employee': self.employee, 'leave_type': leave_type,
            'from_date': add_days(nowdate(), -300), 'to_date': add_days(nowdate(), 300),
            'new_leaves_allocated': 3}).submit()
        retried = workflow_request.create_native_document(approved['name'])['data']
        self.assertEqual(retried['native']['status'], 'Created')
        with self.assertRaisesRegex(frappe.ValidationError, 'قابل تکرار نیست'):
            workflow_request.create_native_document(approved['name'])
        self.assertEqual(frappe.db.count('Leave Application', {'employee': self.employee, 'docstatus': 1}), 1)

    def mission_fields(self):
        return [
            {'key': 'start', 'label': 'شروع', 'type': 'Date', 'required': True, 'execution_key': 'from_date'},
            {'key': 'end', 'label': 'پایان', 'type': 'Date', 'required': True, 'execution_key': 'to_date'},
            {'key': 'where', 'label': 'مقصد', 'type': 'Text', 'required': True, 'execution_key': 'destination'},
            {'key': 'why', 'label': 'هدف', 'type': 'LongText', 'required': True, 'execution_key': 'purpose'},
            {'key': 'extra', 'label': 'توضیحات', 'type': 'LongText', 'sensitive': True,
             'execution_key': 'notes'}]

    def test_mission_approval_submits_attendance_request(self):
        approved = self.approve('mission', self.mission_fields(), {
            'start': self.day(0), 'end': self.day(1), 'where': 'شیراز', 'why': 'جلسه', 'extra': 'محرمانه'})
        self.assertEqual((approved['native']['status'], approved['native']['doctype']),
                         ('Created', 'Attendance Request'))
        doc = frappe.get_doc('Attendance Request', approved['native']['name'])
        self.assertEqual((doc.docstatus, doc.reason), (1, 'On Duty'))
        self.assertIn('مقصد: شیراز\nهدف: جلسه\nتوضیحات: محرمانه؛ جزئیات در درخواست', doc.explanation)
        self.assertNotIn('محرمانه\n', doc.explanation + '\n')
        self.assertEqual(frappe.db.count('Attendance', {'attendance_request': doc.name, 'status': 'Present'}), 2)

    def test_mission_conflict_ends_as_needs_review_and_notifies_hr(self):
        name = self.make_attendance(self.day(1), 'Absent')
        approved = self.approve('mission', self.mission_fields(), {
            'start': self.day(0), 'end': self.day(1), 'where': 'شیراز', 'why': 'جلسه'})
        self.assertEqual(approved['native']['status'], 'Needs Review')
        self.assertEqual(approved['native']['error'], mission.review_reason([self.day(1)]))
        self.assertEqual(frappe.db.count('Attendance Request', {'employee': self.employee}), 0)
        self.assertEqual(frappe.db.get_value('Attendance', name, 'status'), 'Absent')
        logs = frappe.get_all('Notification Log', filters={
            'document_type': 'ASOUD Workflow Instance', 'document_name': approved['workflow_instance'],
            'email_content': approved['native']['error']}, pluck='for_user')
        self.assertIn(self.hr, logs)
        self.assertIn(self.user, logs)

    def overtime_fields(self):
        return [
            {'key': 'day', 'label': 'تاریخ', 'type': 'Date', 'required': True, 'execution_key': 'work_date'},
            {'key': 'from', 'label': 'شروع', 'type': 'Time', 'required': True, 'execution_key': 'start_time'},
            {'key': 'to', 'label': 'پایان', 'type': 'Time', 'required': True, 'next_day_allowed': True,
             'execution_key': 'end_time'},
            {'key': 'job', 'label': 'شرح', 'type': 'LongText', 'required': True, 'execution_key': 'purpose'}]

    def test_overtime_approval_needs_review_with_the_next_day_hours(self):
        counts = {name: frappe.db.count(name) for name in ('Additional Salary', 'Attendance Request')}
        approved = self.approve('overtime', self.overtime_fields(), {
            'day': self.day(0), 'from': '23:00', 'to': '02:00', 'to__next_day': True, 'job': 'استقرار'})
        self.assertEqual(approved['native']['status'], 'Needs Review')
        self.assertIn('از ساعت ۲۳:۰۰ تا ساعت ۰۲:۰۰ روز بعد به مدت ۳ ساعت است', approved['native']['error'])
        self.assertEqual(approved['native']['doctype'], '')
        self.assertEqual(counts, {name: frappe.db.count(name) for name in counts})
        logs = frappe.get_all('Notification Log', filters={
            'document_type': 'ASOUD Workflow Instance', 'document_name': approved['workflow_instance'],
            'email_content': approved['native']['error']}, pluck='for_user')
        self.assertIn(self.hr, logs)


class TestLeaveTypeSource(Base):
    def test_options_are_non_optional_leave_types_and_submit_checks_the_scope(self):
        normal = self.make_leave_type(0)
        optional = self.make_leave_type(0, is_optional_leave=1)
        definition, _ = make_definition(self.company, fields=[])
        fields = [{'key': 'kind', 'label': 'نوع', 'type': 'Link', 'source': 'Leave Type', 'required': True}]
        schema = {'kind': 'Request', 'title': 'نمونه', 'workflow': definition,
                  'sections': [{'id': 'main', 'title': 'اصلی', 'fields': fields}]}
        saved = forms.save_form(self.company, schema, client_id=frappe.generate_hash(length=24))['data']
        revision = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']['active_revision']
        frappe.set_user(self.user)
        names = [row['name'] for row in forms.get_link_options(
            self.company, 'Leave Type', query='LMO', form=saved['name'])['data']]
        self.assertIn(normal, names)
        self.assertNotIn(optional, names)
        with self.assertRaisesRegex(frappe.ValidationError, 'محدوده مجاز'):
            forms.submit_form(saved['name'], revision, 'مرخصی', {'kind': optional}, frappe.generate_hash(length=24))
        entry = forms.submit_form(saved['name'], revision, 'مرخصی', {'kind': normal}, frappe.generate_hash(length=24))
        frappe.set_user('Administrator')
        self.assertTrue(entry['data']['reference_name'])


class TestDateUpperBound(Base):
    def test_submit_rejects_a_half_day_after_the_end_and_a_null_end_is_ignored(self):
        definition, _ = make_definition(self.company, fields=[])
        fields = [
            {'key': 'start', 'label': 'شروع', 'type': 'Date', 'required': True},
            {'key': 'end', 'label': 'پایان', 'type': 'Date', 'required': True, 'after_or_equal': 'start'},
            {'key': 'half', 'label': 'نیم‌روز', 'type': 'Date', 'after_or_equal': 'start',
             'before_or_equal': 'end', 'before_or_equal_message': 'تاریخ نیم‌روز باید در بازه درخواست باشد.'}]
        schema = {'kind': 'Request', 'title': 'بازه', 'workflow': definition,
                  'sections': [{'id': 'main', 'title': 'اصلی', 'fields': fields}]}
        saved = forms.save_form(self.company, schema, client_id=frappe.generate_hash(length=24))['data']
        revision = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']['active_revision']
        frappe.set_user(self.user)
        values = {'start': self.day(0), 'end': self.day(2)}
        with self.assertRaisesRegex(frappe.ValidationError, 'تاریخ نیم‌روز باید در بازه درخواست باشد.'):
            forms.submit_form(saved['name'], revision, 'بازه', {**values, 'half': self.day(3)},
                              frappe.generate_hash(length=24))
        entry = forms.submit_form(saved['name'], revision, 'بازه', {**values, 'half': self.day(2)},
                                  frappe.generate_hash(length=24))
        frappe.set_user('Administrator')
        self.assertTrue(entry['data']['reference_name'])


class TestTimeOrder(Base):
    def test_submit_rejects_an_end_not_after_the_start_unless_it_is_the_next_day(self):
        definition, _ = make_definition(self.company, fields=[])
        fields = [
            {'key': 'from', 'label': 'شروع', 'type': 'Time', 'required': True},
            {'key': 'to', 'label': 'پایان', 'type': 'Time', 'required': True, 'next_day_allowed': True,
             'time_after': 'from', 'time_after_message': 'ساعت پایان باید پس از ساعت شروع باشد.'}]
        schema = {'kind': 'Request', 'title': 'ساعت', 'workflow': definition,
                  'sections': [{'id': 'main', 'title': 'اصلی', 'fields': fields}]}
        saved = forms.save_form(self.company, schema, client_id=frappe.generate_hash(length=24))['data']
        revision = forms.transition(saved['name'], 'publish', saved['draft_version'])['data']['active_revision']
        frappe.set_user(self.user)
        with self.assertRaisesRegex(frappe.ValidationError, 'ساعت پایان باید پس از ساعت شروع باشد.'):
            forms.submit_form(saved['name'], revision, 'ساعت', {'from': '22:00', 'to': '01:00'},
                              frappe.generate_hash(length=24))
        entry = forms.submit_form(saved['name'], revision, 'ساعت',
                                  {'from': '22:00', 'to': '01:00', 'to__next_day': True},
                                  frappe.generate_hash(length=24))
        frappe.set_user('Administrator')
        self.assertTrue(entry['data']['reference_name'])
