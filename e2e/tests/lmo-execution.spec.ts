import { execFileSync } from 'node:child_process';
import { expect, test } from '../support/fixtures';
import { PYTHON } from '../support/config';
import { loadState } from '../support/state';

function fixture<T>(action: string, options = {}): T {
  const output = execFileSync(PYTHON, [`${__dirname}/lmo_fixture.py`, action, JSON.stringify(options)], {
    encoding: 'utf8', env: process.env,
  });
  const line = output.split('\n').find(value => value.startsWith('@@LMO_JSON@@'));
  if (!line) throw new Error(`Missing fixture output for ${action}`);
  return JSON.parse(line.slice('@@LMO_JSON@@'.length));
}

type Prepared = {
  leave_type: string; optional_type: string; start: string; definitions: string[];
  forms: Record<string, { form: string; revision: string }>;
};
type Request = { name: string; workflow_instance: string; native: { status: string; name: string; doctype: string; error: string } };
const forms = 'asoud_erp.api.v1.forms.';
const requests = 'asoud_erp.api.v1.workflow_request.';
const runtime = 'asoud_erp.api.v1.workflow_runtime.';
let prepared: Prepared;
const state = loadState();

function offset(day: string, days: number): string {
  const value = new Date(`${day}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

test.beforeAll(() => { prepared = fixture<Prepared>('prepare'); });
test.afterAll(() => {
  if (!prepared) return;
  fixture('cleanup', {
    forms: Object.values(prepared.forms).map(item => item.form), definitions: prepared.definitions,
    leave_type: prepared.leave_type, optional_type: prepared.optional_type,
  });
});

test('catalog lists the three kinds with their parameters behind the designer role gate', async ({ api }) => {
  const admin = await api.login('admin');
  const catalog = await admin.read<Array<{kind: string; label: string; parameters: Record<string, {required: boolean}>}>>(
    forms + 'execution_kinds');
  const byKind = Object.fromEntries(catalog.map(item => [item.kind, item]));
  expect(byKind.leave_application.label).toBe('درخواست مرخصی');
  expect(Object.keys(byKind.leave_application.parameters)).toEqual([
    'leave_type', 'from_date', 'to_date', 'half_day', 'half_day_date', 'description']);
  expect(byKind.mission.label).toBe('درخواست مأموریت');
  expect(Object.keys(byKind.mission.parameters)).not.toContain('include_holidays');
  expect(byKind.overtime.label).toBe('درخواست اضافه‌کار');
  expect(byKind.overtime.parameters.work_date.required).toBe(true);
  const employee = await api.login('employee');
  expect((await employee.get(forms + 'execution_kinds')).status).toBe(403);
});

test('Leave Type options: employee reads them without optional leave; anonymous and another company are refused', async ({ api }) => {
  const employee = await api.login('employee');
  const options = await employee.read<Array<{name: string}>>(forms + 'get_link_options', {
    company: state.company, source: 'Leave Type', query: 'E2E-LMO', form: prepared.forms.leave_application.form });
  const names = options.map(row => row.name);
  expect(names).toContain(prepared.leave_type);
  expect(names).not.toContain(prepared.optional_type);
  // A user without an Employee record may read the list (it is not person bound); execution refuses later.
  const outsider = await api.login('outsider');
  const outsiderOptions = await outsider.get(forms + 'get_link_options', {
    company: state.company, source: 'Leave Type', form: prepared.forms.leave_application.form });
  expect(outsiderOptions.status).toBe(200);
  const anonymous = await api.anonymous();
  expect((await anonymous.get(forms + 'get_link_options', {
    company: state.company, source: 'Leave Type', form: prepared.forms.leave_application.form })).status).toBe(403);
  const other = await employee.get(forms + 'get_link_options', {
    company: state.second_company, source: 'Leave Type', form: prepared.forms.leave_application.form });
  expect(other.status).toBe(403);
});

async function approve(api: any, kind: string, values: Record<string, unknown>): Promise<Request> {
  const employee = await api.login('employee');
  const approver = await api.login('approver');
  const admin = await api.login('admin');
  const item = prepared.forms[kind];
  const entry = await employee.mutate<{reference_name: string}>(forms + 'submit_form', {
    name: item.form, revision_name: item.revision, subject: `درخواست ${kind}`,
    values: JSON.stringify(values), request_key: `lmo-${Date.now()}-${kind}`,
  });
  const request = await employee.read<Request>(requests + 'get_request', {name: entry.reference_name});
  const tasks = await approver.read<Array<{name: string; workflow_instance: string}>>(runtime + 'list_my_workflow_tasks', {});
  const task = tasks.find(value => value.workflow_instance === request.workflow_instance);
  expect(task).toBeTruthy();
  await approver.mutate(runtime + 'complete_workflow_task', {task: task!.name, action: 'Approve'});
  return admin.read<Request>(requests + 'get_request', {name: request.name});
}

test('leave: approval submits the Leave Application with the real balance; a second one over the balance fails in Persian', async ({ api }) => {
  const start = prepared.start;
  const detail = await approve(api, 'leave_application', {
    kind: prepared.leave_type, start, end: offset(start, 1), note: 'گواهی' });
  expect(detail.native.status).toBe('Created');
  expect(detail.native.doctype).toBe('Leave Application');
  const native = fixture<any>('inspect', {kind: 'Leave Application', name: detail.native.name});
  expect(native).toMatchObject({docstatus: 1, status: 'Approved', ledger: 1, attendance: 2});
  expect(native.text).toBe(`محرمانه؛ جزئیات در درخواست ${detail.name} است.`);
  const over = await approve(api, 'leave_application', {
    kind: prepared.leave_type, start: offset(start, 20), end: offset(start, 31) });
  expect(over.native.status).toBe('Failed');
  expect(over.native.error).toBe('مانده قابل مصرف برای این مرخصی کافی نیست.');
});

test('mission: approval submits an On Duty Attendance Request with attendance rows', async ({ api }) => {
  const start = offset(prepared.start, 40);
  const detail = await approve(api, 'mission', { start, end: offset(start, 1), where: 'اصفهان', why: 'نصب' });
  expect(detail.native.status).toBe('Created');
  expect(detail.native.doctype).toBe('Attendance Request');
  const native = fixture<any>('inspect', {kind: 'Attendance Request', name: detail.native.name});
  expect(native).toMatchObject({docstatus: 1, reason: 'On Duty', attendance: 2, text: 'مقصد: اصفهان\nهدف: نصب'});
  const again = await approve(api, 'mission', { start, end: offset(start, 1), where: 'اصفهان', why: 'نصب' });
  expect(again.native.status).toBe('Needs Review');
  expect(again.native.error).toContain('نیاز به اقدام HR');
});

test('overtime: approval ends as Needs Review with the approved hours and creates no document', async ({ api }) => {
  const detail = await approve(api, 'overtime', {
    day: offset(prepared.start, 80), from: '22:00', to: '01:00', to__next_day: true, job: 'استقرار' });
  expect(detail.native.status).toBe('Needs Review');
  expect(detail.native.error).toContain('از ساعت ۲۲:۰۰ تا ساعت ۰۱:۰۰ روز بعد به مدت ۳ ساعت است');
  expect(detail.native.name).toBe('');
});
