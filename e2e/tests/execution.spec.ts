/**
 * The execution lane of a request: approval and execution are separate states,
 * and the raw execution error is never sent to an ordinary user.
 */

import { expect, test } from '../support/fixtures';
import { METHOD } from '../support/api';
import { requestId, subject } from '../support/config';
import { loadState, sitePrep } from '../support/state';

const state = loadState();
const ERROR = 'LEAVE_BALANCE: e2e-secret-execution-error';

interface Execution {
  state: string;
  label: string;
  error: string;
  reference: string;
}

interface Task {
  name: string;
  workflow_instance: string;
}

test.describe('request execution block', () => {
  test('a failed execution is shown to an owner without its error text', async ({ api }) => {
    const employee = await api.login('employee');
    const approver = await api.login('approver');
    const tag = 'exec-failed';
    const created = await employee.mutate<{ name: string; workflow_instance: string }>(METHOD.createRequest, {
      company: state.company,
      workflow_definition: state.request_type as string,
      subject: subject('درخواست اجرا', tag),
      values: JSON.stringify({ amount: 900, reason: `e2e-${tag}` }),
      request_id: requestId('REQ', tag),
    });
    const tasks = await approver.read<Task[]>(METHOD.listMyTasks, { status: 'Open' });
    const task = tasks.find((row) => row.workflow_instance === created.workflow_instance);
    expect(task, 'the approver must hold the open task').toBeDefined();
    await approver.mutate(METHOD.completeTask, { task: (task as Task).name, action: 'Approve' });
    sitePrep('mark-native-failed', { request: created.name, error: ERROR });

    const asOwner = await employee.read<{ execution: Execution }>(METHOD.getRequest, { name: created.name });
    expect(asOwner.execution.state, JSON.stringify(asOwner)).toBe('failed');
    expect(asOwner.execution.error, 'the owner is not privileged').toBe('');
    expect(JSON.stringify(asOwner)).not.toContain('e2e-secret-execution-error');

    const asApprover = await approver.read<{ execution: Execution }>(METHOD.getRequest, {
      name: created.name,
    });
    expect(asApprover.execution.error).toBe('');
    expect(JSON.stringify(asApprover)).not.toContain('e2e-secret-execution-error');

    const asAdmin = await (await api.login('admin')).read<{ execution: Execution }>(METHOD.getRequest, {
      name: created.name,
    });
    expect(asAdmin.execution.error).toBe(ERROR);
  });
});
