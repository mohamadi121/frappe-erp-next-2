import { execFileSync } from 'node:child_process';
import { expect, test } from '../support/fixtures';
import { PYTHON } from '../support/config';

function fixture<T>(action: string, options = {}): T {
  const output = execFileSync(PYTHON, [`${__dirname}/confidential_fixture.py`, action, JSON.stringify(options)], {
    encoding: 'utf8', env: process.env,
  });
  const line = output.split('\n').find(value => value.startsWith('@@CONFIDENTIAL_JSON@@'));
  if (!line) throw new Error(`Missing confidential fixture output for ${action}`);
  return JSON.parse(line.slice('@@CONFIDENTIAL_JSON@@'.length));
}

type Prepared = { form: string; revision: string; definition: string };
type Request = { company: string; name: string; workflow_instance: string; values: { reason: string } };
const forms = 'asoud_erp.api.v1.forms.';
const requests = 'asoud_erp.api.v1.workflow_request.';
const runtime = 'asoud_erp.api.v1.workflow_runtime.';
const SECRET = 'درمان بیماری خاص e2e';
let prepared: Prepared;

test.beforeAll(() => { prepared = fixture<Prepared>('prepare'); });
test.afterAll(() => { if (prepared) fixture('cleanup', { form: prepared.form, definition: prepared.definition }); });

test('a confidential form field is readable by the requester, the approver and HR only', async ({ api }) => {
  const employee = await api.login('employee');
  const approver = await api.login('approver');
  const admin = await api.login('admin');
  const outsider = await api.login('accountant');
  const entry = await employee.mutate<{ reference_name: string }>(forms + 'submit_form', {
    name: prepared.form, revision_name: prepared.revision, subject: 'درخواست محرمانه آزمون',
    values: JSON.stringify({ why: SECRET }), request_key: `confidential-${Date.now()}`,
  });
  const name = entry.reference_name;

  for (const session of [employee, approver, admin]) {
    const detail = await session.read<Request>(requests + 'get_request', { name });
    expect(detail.values.reason).toBe(SECRET);
  }

  // A user of the same company without a task gets neither the value nor the request.
  const read = await outsider.get(requests + 'get_request', { name });
  expect(read.status).toBe(403);
  expect(JSON.stringify(read)).not.toContain(SECRET);
  const request = await employee.read<Request>(requests + 'get_request', { name });
  const instance = await outsider.get(runtime + 'get_workflow_instance', { instance: request.workflow_instance });
  expect(instance.status).toBe(403);
  const tasks = await outsider.read<Array<{ workflow_instance: string }>>(runtime + 'list_my_workflow_tasks', {});
  expect(tasks.find(item => item.workflow_instance === request.workflow_instance)).toBeUndefined();
  expect(JSON.stringify(tasks)).not.toContain(SECRET);
  const notices = await outsider.read<unknown>(runtime + 'list_my_workflow_notifications', {});
  expect(JSON.stringify(notices)).not.toContain(SECRET);

  // The approver's task preview shows the value; the search index never holds it.
  const open = await approver.read<Array<{ name: string; workflow_instance: string }>>(runtime + 'list_my_workflow_tasks', {});
  const task = open.find(item => item.workflow_instance === request.workflow_instance);
  expect(task).toBeTruthy();
  const preview = await approver.read<{ request_values: { reason: string } }>(runtime + 'get_workflow_task', { task: task!.name });
  expect(preview.request_values.reason).toBe(SECRET);
  const found = await employee.read<Array<{ name: string }>>(requests + 'list_my_requests', { company: request.company, search: 'درمان بیماری' });
  expect(found.find(item => item.name === name)).toBeUndefined();
});
