/**
 * Return for correction: the manager returns a request with a reason, only the
 * owner can correct it, and the corrected request goes back to the first review.
 */

import { expect, test } from '../support/fixtures';
import type { ApiSession } from '../support/api';
import { METHOD, errorText } from '../support/api';
import { requestId, subject } from '../support/config';
import { loadState } from '../support/state';

const state = loadState();

interface Detail {
  name: string;
  workflow_instance: string;
  status_key: string;
  can_edit: boolean;
  return_reason: string;
  values: Record<string, unknown>;
}

interface Task {
  name: string;
  workflow_instance: string;
}

async function returned(api: { login: (key: 'employee' | 'approver') => Promise<ApiSession> }, tag: string) {
  const employee = await api.login('employee');
  const approver = await api.login('approver');
  const created = await employee.mutate<Detail>(METHOD.createRequest, {
    company: state.company,
    workflow_definition: state.return_request_type,
    subject: subject('درخواست اصلاح', tag),
    request_id: requestId('REQ', tag),
    values: JSON.stringify({ amount: 1500, reason: `e2e-${tag}` }),
  });
  const tasks = await approver.read<Task[]>(METHOD.listMyTasks, { status: 'Open' });
  const task = tasks.find((row) => row.workflow_instance === created.workflow_instance);
  expect(task, 'the manager must own the approval task').toBeTruthy();
  await approver.mutate(METHOD.completeTask, {
    task: task!.name,
    action: 'Return',
    comment: 'مبلغ را اصلاح کنید',
  });
  return { employee, approver, created };
}

test.describe('return for correction over HTTP', () => {
  test('the owner sees the reason, corrects the request and it is reviewed again', async ({ api }) => {
    const { employee, approver, created } = await returned(api, 'resubmit');

    const detail = await employee.read<Detail>(METHOD.getRequest, { name: created.name });
    expect(detail).toMatchObject({
      status_key: 'returned',
      can_edit: true,
      return_reason: 'مبلغ را اصلاح کنید',
    });

    const updated = await employee.mutate<Detail>(METHOD.updateRequest, {
      name: created.name,
      values: JSON.stringify({ amount: 900, reason: 'e2e-resubmit' }),
    });
    expect(updated.values.amount).toBe(900);
    expect(updated.status_key).not.toBe('returned');
    expect(updated.can_edit).toBe(false);

    const again = (await approver.read<Task[]>(METHOD.listMyTasks, { status: 'Open' })).find(
      (row) => row.workflow_instance === created.workflow_instance,
    );
    expect(again, 'the first review stage must be open again').toBeTruthy();

    const twice = await employee.post(METHOD.updateRequest, {
      name: created.name,
      values: JSON.stringify({ amount: 1, reason: 'twice' }),
    });
    expect(twice.status).toBeGreaterThanOrEqual(400);
  });

  test('a stranger and a user of another company cannot correct a returned request', async ({ api }) => {
    const { employee, created } = await returned(api, 'stranger');
    for (const key of ['accountant', 'outsider'] as const) {
      const other = await api.login(key);
      const edit = await other.post(METHOD.updateRequest, {
        name: created.name,
        values: JSON.stringify({ amount: 1, reason: 'x' }),
      });
      expect(edit.status, `${key} must not edit`).toBe(403);
      expect(errorText(edit)).toBeTruthy();
    }
    const still = await employee.read<Detail>(METHOD.getRequest, { name: created.name });
    expect(still.values.amount).toBe(1500);
    expect(still.status_key).toBe('returned');
  });
});
