import { execFileSync } from 'node:child_process';
import { expect, test } from '../support/fixtures';
import { PYTHON } from '../support/config';
import { loadState } from '../support/state';

function fixture<T>(action: string, options = {}): T {
  const output = execFileSync(PYTHON, [`${__dirname}/request_void_fixture.py`, action, JSON.stringify(options)], {
    encoding: 'utf8', env: process.env,
  });
  const line = output.split('\n').find(value => value.startsWith('@@VOID_JSON@@'));
  if (!line) throw new Error(`Missing void fixture output for ${action}`);
  return JSON.parse(line.slice('@@VOID_JSON@@'.length));
}

type Native = { status: string; name: string; doctype: string };
type Execution = { state: string; label: string; can_void: boolean; can_reissue: boolean; void?: { reason: string } };
type Request = { name: string; workflow_instance: string; native: Native; execution: Execution };
const forms = 'asoud_erp.api.v1.forms.';
const requests = 'asoud_erp.api.v1.workflow_request.';
const runtime = 'asoud_erp.api.v1.workflow_runtime.';
let prepared: { form: string; revision: string; definition: string; restore: string | null };
let foreign = '';
const REASON = 'سند به اشتباه صادر شده است.';

test.beforeAll(() => {
  prepared = fixture('prepare');
  foreign = fixture<{ name: string }>('foreign', { company: loadState().second_company }).name;
});
test.afterAll(() => {
  if (prepared) fixture('cleanup', { form: prepared.form, definition: prepared.definition, restore: prepared.restore, foreign });
});

async function executed(api: any): Promise<Request> {
  const employee = await api.login('employee');
  const approver = await api.login('approver');
  const admin = await api.login('admin');
  const entry = await employee.mutate<{ reference_name: string }>(forms + 'submit_form', {
    name: prepared.form, revision_name: prepared.revision, subject: 'مساعده آزمون ابطال',
    values: JSON.stringify({ asked: 900, why: 'E2E-void' }), request_key: `void-${Date.now()}-${Math.random()}`,
  });
  const request = await employee.read<Request>(requests + 'get_request', { name: entry.reference_name });
  const tasks = await approver.read<Array<{ name: string; workflow_instance: string }>>(runtime + 'list_my_workflow_tasks', {});
  const task = tasks.find(item => item.workflow_instance === request.workflow_instance);
  await approver.mutate(runtime + 'complete_workflow_task', { task: task!.name, action: 'Approve' });
  const detail = await admin.read<Request>(requests + 'get_request', { name: request.name });
  expect(detail.native.status).toBe('Created');
  return detail;
}

test('HR Manager voids with a reason and reissues once; the history is kept', async ({ api }) => {
  const request = await executed(api);
  const hr = await api.login('hr');
  const before = await hr.read<Request>(requests + 'get_request', { name: request.name });
  expect(before.execution.can_void).toBe(true);
  const empty = await hr.post(requests + 'void_native_document', { name: request.name, reason: '  ' });
  expect(empty.status).toBe(417);
  const voided = await hr.mutate<Request>(requests + 'void_native_document', { name: request.name, reason: REASON });
  expect(voided.native.status).toBe('Voided');
  expect(voided.execution).toMatchObject({ state: 'voided', label: 'سند ابطال شد', can_void: false, can_reissue: true });
  expect(voided.execution.void?.reason).toBe(REASON);
  expect(fixture<{ docstatus: number }>('inspect', { name: request.native.name }).docstatus).toBe(0);
  const again = await hr.post(requests + 'void_native_document', { name: request.name, reason: REASON });
  expect(again.status).toBe(417);
  const reissued = await hr.mutate<Request>(requests + 'reissue_native_document', { name: request.name });
  expect(reissued.native.status).toBe('Created');
  expect(reissued.native.name).not.toBe(request.native.name);
  const repeat = await hr.mutate<Request>(requests + 'reissue_native_document', { name: request.name });
  expect(repeat.native.name).toBe(reissued.native.name);
  const instance = await (await api.login('admin')).read<{ activities: Array<{ action: string; comment: string }> }>(
    runtime + 'get_workflow_instance', { instance: request.workflow_instance });
  const marks = instance.activities.filter(row => ['Voided', 'Reissued'].includes(row.action));
  expect(marks.map(row => row.action)).toEqual(['Voided', 'Reissued']);
  expect(marks[0].comment).toBe(REASON);
});

test('a plain employee, the requester, a System Manager and another company are refused', async ({ api }) => {
  const request = await executed(api);
  for (const key of ['employee', 'outsider', 'approver', 'admin'] as const) {
    const session = await api.login(key);
    const voidResult = await session.post(requests + 'void_native_document', { name: request.name, reason: REASON });
    expect(voidResult.status, `${key} void`).toBe(403);
    const reissueResult = await session.post(requests + 'reissue_native_document', { name: request.name });
    expect(reissueResult.status, `${key} reissue`).toBe(403);
    const detail = await session.get(requests + 'get_request', { name: request.name });
    if (detail.status === 200) {
      const execution = (detail.envelope.data as Request).execution;
      expect(execution.can_void, `${key} sees the action`).toBe(false);
    }
  }
  const hr = await api.login('hr');
  const other = await hr.post(requests + 'void_native_document', { name: foreign, reason: REASON });
  expect(other.status).toBe(403);
  const still = await (await api.login('admin')).read<Request>(requests + 'get_request', { name: request.name });
  expect(still.native.status).toBe('Created');
});
