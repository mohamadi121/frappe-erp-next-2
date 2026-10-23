import { execFileSync } from 'node:child_process';
import { request } from 'playwright';
import { expect, test } from '../support/fixtures';
import { ApiSession, errorText } from '../support/api';
import { PYTHON } from '../support/config';

const FOREIGN = { email: 'e2e.receipt.foreign@example.com', password: 'E2e-Pw-Foreign-2026' };
const followup = 'asoud_erp.api.v1.request_followup.';
const runtime = 'asoud_erp.api.v1.workflow_runtime.';

type Case = { request: string; instance: string; movement: string; task: string };
type Prepared = { asset: string; cases: { confirm: Case; reject: Case } };
type Inspected = { docstatus: number; custodian: string | null; employee: string; status: string; comment: string | null;
  notified: string[]; movement_comments: number };

function fixture<T>(action: string, options = {}): T {
  const output = execFileSync(PYTHON, [`${__dirname}/receipt_fixture.py`, action, JSON.stringify(options)], {
    encoding: 'utf8', env: process.env,
  });
  const line = output.split('\n').find(value => value.startsWith('@@RECEIPT_JSON@@'));
  if (!line) throw new Error(`Missing receipt fixture output for ${action}`);
  return JSON.parse(line.slice('@@RECEIPT_JSON@@'.length));
}

let prepared: Prepared;
const inspect = (key: 'confirm' | 'reject') => fixture<Inspected>('inspect', {
  asset: prepared.asset, movement: prepared.cases[key].movement, instance: prepared.cases[key].instance,
  task: prepared.cases[key].task });

test.beforeAll(() => { prepared = fixture<Prepared>('prepare'); });
test.afterAll(() => { if (prepared) fixture('cleanup', prepared); });

test('the requester sees the receipt task in the cartable with the asset and the two choices', async ({ api }) => {
  const employee = await api.login('employee');
  const tasks = await employee.read<Array<{ name: string; task_title: string }>>(runtime + 'list_my_workflow_tasks', {});
  const listed = tasks.find(item => item.name === prepared.cases.confirm.task);
  expect(listed?.task_title).toContain('تأیید دریافت تجهیز: ');
  const detail = await employee.read<{ config: { activity_type: string; allow_reject: boolean }; stage_type: string;
    document: { name: string; values: Array<{ key: string; value: string }> } }>(
    runtime + 'get_workflow_task', { task: prepared.cases.confirm.task });
  expect(detail.config.activity_type).toBe('ConfirmReceipt');
  expect(detail.config.allow_reject).toBe(true);
  expect(detail.stage_type).toBe('User Task');
  expect(detail.document.name).toBe(prepared.cases.confirm.movement);
  expect(detail.document.values.find(row => row.key === 'asset')?.value).toContain('لپ‌تاپ E2E');
  const other = await api.login('approver');
  expect((await other.get(runtime + 'get_workflow_task', { task: prepared.cases.confirm.task })).status).toBe(403);
  const generic = await employee.post(runtime + 'complete_workflow_task', { task: prepared.cases.confirm.task, action: 'Complete' });
  expect(generic.status).toBe(403);
  expect(errorText(generic)).toContain('این وظیفه فقط با تأیید یا عدم دریافت تجهیز قابل اقدام است.');
});

test('every other identity is refused and nothing changes', async ({ api, baseURL }) => {
  const task = prepared.cases.confirm.task;
  const foreign = await ApiSession.login(await request.newContext({ baseURL }), FOREIGN.email, FOREIGN.password);
  const sessions = {
    'a colleague of the same company': await api.login('approver'),
    'an HR manager of the same company': await api.login('hr'),
    'a user without an Employee record': await api.login('admin'),
    'a user of another company': foreign,
  };
  for (const [who, session] of Object.entries(sessions)) {
    const confirm = await session.post(followup + 'confirm_receipt', { task });
    expect(confirm.status, `confirm by ${who}`).toBe(403);
    expect(errorText(confirm), who).toContain('فقط درخواست‌دهنده می‌تواند دریافت تجهیز را تأیید کند.');
    const reject = await session.post(followup + 'reject_receipt', { task, reason: 'x' });
    expect(reject.status, `reject by ${who}`).toBe(403);
  }
  const anonymous = await api.anonymous();
  expect([401, 403]).toContain((await anonymous.post(followup + 'confirm_receipt', { task }, { csrf: false })).status);
  const employee = await api.login('employee');
  expect((await employee.get(followup + 'confirm_receipt', { task })).status).toBe(403);
  const unknown = await employee.post(followup + 'confirm_receipt', { task: 'missing-task' });
  expect(unknown.status).toBe(417);
  expect(errorText(unknown)).toContain('وظیفه تأیید دریافت یافت نشد.');
  const state = inspect('confirm');
  expect([state.docstatus, state.status, state.custodian]).toEqual([0, 'Open', '']);
  await foreign.context.dispose();
});

test('the requester confirms once; the second confirmation is refused', async ({ api }) => {
  const employee = await api.login('employee');
  const task = prepared.cases.confirm.task;
  const done = await employee.mutate<{ status: string; movement: { docstatus: number; name: string } }>(
    followup + 'confirm_receipt', { task });
  expect(done.status).toBe('Completed');
  expect(done.movement).toEqual({ doctype: 'Asset Movement', name: prepared.cases.confirm.movement, docstatus: 1 });
  const state = inspect('confirm');
  expect([state.docstatus, state.status, state.custodian]).toEqual([1, 'Completed', state.employee]);
  const again = await employee.post(followup + 'confirm_receipt', { task });
  expect(again.status).toBe(417);
  expect(errorText(again)).toContain('دریافت این تجهیز قبلاً تأیید شده است.');
  expect((await employee.post(followup + 'reject_receipt', { task, reason: 'دیر' })).status).toBe(417);
});

test('non-receipt rejection needs a reason, keeps the draft and alerts HR', async ({ api }) => {
  const employee = await api.login('employee');
  const task = prepared.cases.reject.task;
  for (const reason of ['', '   ']) {
    const empty = await employee.post(followup + 'reject_receipt', { task, reason });
    expect(empty.status).toBe(417);
    expect(errorText(empty)).toContain('علت عدم دریافت را بنویسید.');
  }
  const done = await employee.mutate<{ status: string; movement: { docstatus: number } }>(
    followup + 'reject_receipt', { task, reason: 'تجهیز تحویل داده نشد' });
  expect([done.status, done.movement.docstatus]).toEqual(['Rejected', 0]);
  const state = inspect('reject');
  expect([state.docstatus, state.status, state.comment]).toEqual([0, 'Rejected', 'تجهیز تحویل داده نشد']);
  expect(state.movement_comments).toBe(2);
  expect(state.notified).toContain('e2e.hr@example.com');
  expect(state.notified).not.toContain('asoud.employee@example.com');
  const later = await employee.post(followup + 'confirm_receipt', { task });
  expect(later.status).toBe(417);
  expect(errorText(later)).toContain('عدم دریافت این تجهیز قبلاً ثبت شده است.');
});
