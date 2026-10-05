/**
 * The request lifecycle a phone drives: submit, replay, edit, approve, reject
 * and cancel. Every step is a real HTTP call with its own session; the only
 * shared fixture is the request type designed by global setup.
 */

import { expect, test } from '../support/fixtures';
import type { ApiSession } from '../support/api';
import { METHOD, errorText } from '../support/api';
import { requestId, subject, type UserKey } from '../support/config';
import { loadState } from '../support/state';

const state = loadState();

interface Api {
  login: (key: UserKey) => Promise<ApiSession>;
}

interface Task {
  name: string;
  workflow_instance: string;
  workflow_stage: string;
  task_title: string;
  status: string;
  assigned_to?: string;
}

interface Instance {
  name: string;
  status: string;
  current_stage_title: string;
  current_assignees: string[];
  reference_name: string;
  activities?: { action: string; actor: string; stage_title?: string; comment?: string }[];
}

interface Created {
  name: string;
  request_id: string;
  status: string;
  subject: string;
  workflow_instance: string;
  values: Record<string, unknown>;
  display_status: string;
  owner: string;
}

function form(tag: string, amount = 1500): Record<string, string> {
  return {
    company: state.company,
    workflow_definition: state.request_type as string,
    subject: subject('درخواست آزمون', tag),
    values: JSON.stringify({ amount, reason: `e2e-${tag}` }),
  };
}

async function submit(
  session: ApiSession,
  tag: string,
  overrides: Record<string, string> = {},
): Promise<Created> {
  return session.mutate<Created>(METHOD.createRequest, {
    ...form(tag),
    request_id: requestId('REQ', tag),
    ...overrides,
  });
}

async function openTasks(api: Api, key: UserKey): Promise<Task[]> {
  return (await api.login(key)).read<Task[]>(METHOD.listMyTasks, { status: 'Open' });
}

/** Waits for nothing: each call below is synchronous in the request lifecycle. */
async function instanceOf(session: ApiSession, name: string): Promise<Instance> {
  return session.read<Instance>(METHOD.getInstance, { instance: name });
}

test.describe('request lifecycle over HTTP', () => {
  test('a submission is normalized, echoed back and readable by its requester', async ({ api }) => {
    const employee = await api.login('employee');
    const tag = 'create';
    const created = await submit(employee, tag, { priority: 'High' });

    expect(created.name).toMatch(/^REQ-\d+$/);
    expect(created.request_id).toBe(requestId('REQ', tag));
    expect(created.status).toBe('Running');
    expect(created.subject).toBe(subject('درخواست آزمون', tag));
    expect(created.owner).toBe('asoud.employee@example.com');
    expect(created.values, 'amount must be normalized to a number').toEqual({
      amount: 1500,
      reason: `e2e-${tag}`,
    });
    expect(created.workflow_instance).toMatch(/^WFI-/);

    const fetched = await employee.read<Created>(METHOD.getRequest, { name: created.name });
    expect(fetched).toMatchObject({ name: created.name, status: 'Running', priority: 'High' });
  });

  test('replaying the same request_id returns the same request and a different body conflicts', async ({
    api,
  }) => {
    const employee = await api.login('employee');
    const tag = 'replay';
    const id = requestId('REQ', tag);
    const payload = { ...form(tag), request_id: id };

    const first = await employee.mutate<Created>(METHOD.createRequest, payload);
    const replay = await employee.mutate<Created>(METHOD.createRequest, payload);
    expect(replay.name, 'a replay must not create a second request').toBe(first.name);

    const listed = await employee.read<Created[]>(METHOD.listMyRequests, {
      company: state.company,
    });
    expect(listed.filter((row) => row.request_id === id)).toHaveLength(1);

    const conflict = await employee.post(METHOD.createRequest, {
      ...payload,
      subject: subject('درخواست آزمون', `${tag}-changed`),
    });
    expect(conflict.status).toBe(417);
    expect(errorText(conflict)).toContain('Request ID conflict');
  });

  test('invalid submissions are refused without writing a request', async ({ api }) => {
    const employee = await api.login('employee');
    const cases: { tag: string; form: Record<string, string>; refused: string }[] = [
      {
        tag: 'unknown-definition',
        form: { workflow_definition: 'WF-DOES-NOT-EXIST' },
        // Frappe refuses the read before asoud_erp can report a missing draft.
        refused: 'ASOUD Workflow Definition',
      },
      {
        // The employee has no Employee row in the second company, so the
        // company boundary is checked before the definition's own company.
        tag: 'wrong-company',
        form: { company: state.second_company },
        refused: 'Company access denied',
      },
      { tag: 'short-subject', form: { subject: 'ab' }, refused: 'at least 3 characters' },
      {
        tag: 'missing-required',
        form: { values: JSON.stringify({ amount: 10 }) },
        refused: 'Required workflow field is empty',
      },
      {
        tag: 'unknown-field',
        form: { values: JSON.stringify({ amount: 10, reason: 'x', extra: 1 }) },
        refused: 'unknown fields',
      },
      { tag: 'bad-priority', form: { priority: 'Immediate' }, refused: 'priority' },
    ];

    for (const item of cases) {
      const result = await employee.post(METHOD.createRequest, {
        ...form(item.tag),
        request_id: requestId('REQ', item.tag),
        ...item.form,
      });
      expect(result.status, `${item.tag} must be refused`).toBeGreaterThanOrEqual(400);
      expect(errorText(result), item.tag).toContain(item.refused);
    }

    const listed = await employee.read<Created[]>(METHOD.listMyRequests, {
      company: state.company,
    });
    const ids = listed.map((row) => row.request_id);
    for (const item of cases) {
      expect(ids, `${item.tag} must not have been written`).not.toContain(requestId('REQ', item.tag));
    }
  });

  test('the request type is offered to employees and hidden from another company', async ({ api }) => {
    const employee = await api.login('employee');
    const offered = await employee.read<{ name: string; fields: { key: string }[] }[]>(
      METHOD.requestOptions,
      { company: state.company },
    );
    const definition = offered.find((row) => row.name === state.request_type);
    expect(definition, 'the E2E request type must be offered to its employees').toBeTruthy();
    expect(definition!.fields.map((field) => field.key)).toEqual(['amount', 'reason']);

    // The employee has no Employee row in the second company: the request type
    // of their own company is unreachable there.
    const refused = await employee.get(METHOD.requestOptions, { company: state.second_company });
    expect(refused.status).toBe(403);
    expect(errorText(refused)).toContain('Company access denied');
  });

  test('the requester can edit a running request until it is reviewed', async ({ api }) => {
    const employee = await api.login('employee');
    const approver = await api.login('approver');
    const created = await submit(employee, 'edit');

    const updated = await employee.mutate<Created>(METHOD.updateRequest, {
      name: created.name,
      subject: subject('درخواست ویرایش‌شده', 'edit'),
      values: JSON.stringify({ amount: 2500, reason: 'e2e-edit' }),
    });
    expect(updated.subject).toBe(subject('درخواست ویرایش‌شده', 'edit'));
    expect(updated.values.amount).toBe(2500);

    const task = (await openTasks(api, 'approver')).find(
      (row) => row.workflow_instance === created.workflow_instance,
    );
    expect(task, 'the direct manager must own the approval task').toBeTruthy();
    await approver.mutate(METHOD.completeTask, { task: task!.name, action: 'Approve' });

    const tooLate = await employee.post(METHOD.updateRequest, {
      name: created.name,
      subject: subject('درخواست دیرهنگام', 'edit'),
      values: JSON.stringify({ amount: 1, reason: 'late' }),
    });
    expect(tooLate.status).toBeGreaterThanOrEqual(400);
    // The instance is finished, so the request is no longer in progress.
    expect(errorText(tooLate)).toContain('in progress');
  });

  test('a direct manager approves and the system action closes the instance', async ({ api }) => {
    const employee = await api.login('employee');
    const approver = await api.login('approver');
    const created = await submit(employee, 'approve');

    expect((await instanceOf(employee, created.workflow_instance)).status).toBe('Running');

    const task = (await openTasks(api, 'approver')).find(
      (row) => row.workflow_instance === created.workflow_instance,
    );
    expect(task!.task_title).toBe('تأیید مدیر مستقیم');

    // The employee who submitted the request has no approval task.
    expect(
      (await openTasks(api, 'employee')).filter(
        (row) => row.workflow_instance === created.workflow_instance,
      ),
    ).toHaveLength(0);

    // A colleague cannot act on someone else's task.
    const accountant = await api.login('accountant');
    const stolen = await accountant.post(METHOD.completeTask, {
      task: task!.name,
      action: 'Approve',
    });
    expect(stolen.status).toBe(403);
    expect(errorText(stolen)).toContain('permitted');

    await approver.mutate(METHOD.completeTask, { task: task!.name, action: 'Approve', comment: 'تأیید شد' });

    const instance = await instanceOf(employee, created.workflow_instance);
    expect(instance.status).toBe('Completed');
    expect(instance.current_stage_title).toBe('پایان');

    const actions = (instance.activities ?? []).map((row) => row.action);
    expect(actions).toContain('Approve');
    expect(actions).toContain('System Action Succeeded');

    const request = await employee.read<Created>(METHOD.getRequest, { name: created.name });
    expect(request.status).toBe('Completed');
    expect(request.display_status, 'the system action must have set the display status').toBe(
      'در حال بررسی خودکار',
    );

    // The completed task is no longer offered as open work.
    expect(
      (await openTasks(api, 'approver')).filter(
        (row) => row.workflow_instance === created.workflow_instance,
      ),
    ).toHaveLength(0);
  });

  test('a rejection needs a reason and ends the request', async ({ api }) => {
    const employee = await api.login('employee');
    const approver = await api.login('approver');
    const created = await submit(employee, 'reject');
    const task = (await openTasks(api, 'approver')).find(
      (row) => row.workflow_instance === created.workflow_instance,
    );

    const silent = await approver.post(METHOD.completeTask, { task: task!.name, action: 'Reject' });
    expect(silent.status).toBeGreaterThanOrEqual(400);
    expect(errorText(silent)).toContain('rejection reason is required');

    await approver.mutate(METHOD.completeTask, {
      task: task!.name,
      action: 'Reject',
      comment: 'بودجه کافی نیست',
    });

    const instance = await instanceOf(employee, created.workflow_instance);
    expect(instance.status).toBe('Rejected');
    const request = await employee.read<Created>(METHOD.getRequest, { name: created.name });
    expect(request.status).toBe('Rejected');

    const again = await approver.post(METHOD.completeTask, {
      task: task!.name,
      action: 'Approve',
    });
    expect(again.status).toBeGreaterThanOrEqual(400);
    expect(errorText(again)).toContain('already been completed');
  });

  test('the requester can cancel a running request but not a finished one', async ({ api }) => {
    const employee = await api.login('employee');
    const approver = await api.login('approver');

    const cancelled = await submit(employee, 'cancel');
    const result = await employee.mutate<Created>(METHOD.cancelRequest, {
      name: cancelled.name,
      reason: 'انصراف از درخواست',
    });
    expect(result.status).toBe('Cancelled');
    expect((await instanceOf(employee, cancelled.workflow_instance)).status).toBe('Cancelled');

    const edit = await employee.post(METHOD.updateRequest, {
      name: cancelled.name,
      subject: subject('درخواست لغوشده', 'cancel'),
      values: JSON.stringify({ amount: 5, reason: 'late' }),
    });
    expect(edit.status).toBeGreaterThanOrEqual(400);
    expect(errorText(edit)).toContain('in progress');

    const done = await submit(employee, 'cancel-after-approval');
    const task = (await openTasks(api, 'approver')).find(
      (row) => row.workflow_instance === done.workflow_instance,
    );
    await approver.mutate(METHOD.completeTask, { task: task!.name, action: 'Approve' });

    const refused = await employee.post(METHOD.cancelRequest, { name: done.name });
    expect(refused.status).toBeGreaterThanOrEqual(400);
    expect(errorText(refused)).toContain('in progress');
  });

  test('a non-requester cannot read, edit or cancel a request', async ({ api }) => {
    const employee = await api.login('employee');
    const created = await submit(employee, 'ownership');

    for (const key of ['accountant', 'outsider'] as const) {
      const other = await api.login(key);
      const read = await other.get(METHOD.getRequest, { name: created.name });
      expect(read.status, `${key} must not read the request`).toBe(403);
      expect(errorText(read)).toContain('permitted');

      const edit = await other.post(METHOD.updateRequest, {
        name: created.name,
        subject: subject('دستکاری', 'ownership'),
        values: JSON.stringify({ amount: 1, reason: 'x' }),
      });
      expect(edit.status, `${key} must not edit`).toBe(403);

      const cancel = await other.post(METHOD.cancelRequest, { name: created.name });
      expect(cancel.status, `${key} must not cancel`).toBe(403);
    }

    const stillRunning = await employee.read<Created>(METHOD.getRequest, { name: created.name });
    expect(stillRunning.subject).toBe(created.subject);
  });
});