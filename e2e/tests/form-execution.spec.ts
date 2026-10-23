import { execFileSync } from 'node:child_process';
import { expect, test } from '../support/fixtures';
import { PYTHON } from '../support/config';

function fixture<T>(action: string, options = {}): T {
  const output = execFileSync(PYTHON, [`${__dirname}/form_execution_fixture.py`, action, JSON.stringify(options)], {
    encoding: 'utf8', env: process.env,
  });
  const line = output.split('\n').find(value => value.startsWith('@@EXECUTION_JSON@@'));
  if (!line) throw new Error(`Missing execution fixture output for ${action}`);
  return JSON.parse(line.slice('@@EXECUTION_JSON@@'.length));
}

type Prepared = { form: string; revision: string; definition: string };
type Request = { name: string; workflow_instance: string; native: { status: string; name: string; doctype: string; error: string } };
const forms = 'asoud_erp.api.v1.forms.';
const requests = 'asoud_erp.api.v1.workflow_request.';
const runtime = 'asoud_erp.api.v1.workflow_runtime.';
let prepared: Prepared;

test.beforeAll(() => { prepared = fixture<Prepared>('prepare'); });
test.afterAll(() => { if (prepared) fixture('cleanup', { form: prepared.form, definition: prepared.definition }); });

test('catalog uses real HTTP role gates and is available to a designer without Employee', async ({ api }) => {
  const admin = await api.login('admin');
  const catalog = await admin.read<Array<{kind: string; label: string; parameters: object}>>(forms + 'execution_kinds');
  expect(catalog.map(item => item.kind)).toEqual(expect.arrayContaining([
    'employee_advance', 'attendance_correction', 'asset_movement', 'training_enrollment',
  ]));
  expect(catalog).toContainEqual({kind: 'training_enrollment', label: 'ثبت‌نام در دوره آموزشی', parameters: {
    training_event: {label: 'دوره آموزشی', types: ['Link'], required: true},
    notes: {label: 'توضیحات', types: ['Text', 'LongText'], required: false},
  }});
  expect(catalog).toContainEqual({kind: 'e2e_form_execution', label: 'اجرای آزمون گردش‌کار', parameters: {
    amount: {label: 'مبلغ', types: ['Money'], required: true},
    fail_first: {label: 'آزمون تلاش مجدد', types: ['Check'], required: false},
  }});
  const employee = await api.login('employee');
  expect((await employee.get(forms + 'execution_kinds')).status).toBe(403);
});

for (const failFirst of [false, true]) {
  test(`submit, approve and read native draft; retry=${failFirst}`, async ({ api }) => {
    const employee = await api.login('employee');
    const approver = await api.login('approver');
    const admin = await api.login('admin');
    const entry = await employee.mutate<{reference_name: string}>(forms + 'submit_form', {
      name: prepared.form, revision_name: prepared.revision, subject: 'درخواست اجرای آزمون',
      values: JSON.stringify({asked: 125, retry: failFirst}), request_key: `execution-${Date.now()}-${failFirst}`,
    });
    const request = await employee.read<Request>(requests + 'get_request', {name: entry.reference_name});
    const tasks = await approver.read<Array<{name: string; workflow_instance: string}>>(runtime + 'list_my_workflow_tasks', {});
    const task = tasks.find(item => item.workflow_instance === request.workflow_instance);
    expect(task).toBeTruthy();
    await approver.mutate(runtime + 'complete_workflow_task', {task: task!.name, action: 'Approve'});
    let detail = await admin.read<Request>(requests + 'get_request', {name: request.name});
    if (failFirst) {
      expect(detail.native.status).toBe('Failed');
      expect(detail.native.error).toContain('تنظیمات اجرای سند کامل نیست.');
      fixture('ready', {request: request.name});
      detail = await admin.mutate<Request>(requests + 'create_native_document', {name: request.name});
    }
    expect(detail.native.status).toBe('Created');
    expect(detail.native.doctype).toBe('ToDo');
    const native = fixture<{description: string; docstatus: number}>('inspect', {name: detail.native.name});
    expect(native.docstatus).toBe(0);
    expect(native.description).toBe(`E2E-document-${request.name}:125.0`);
  });
}
