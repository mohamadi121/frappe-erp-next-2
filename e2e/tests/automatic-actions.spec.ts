/**
 * Automatic actions, schema 2 (`asoud_erp.api.v1.automatic_actions`).
 *
 * Schema 2 needs `asoud_workflow_service_user` and
 * `asoud_workflow_service_companies` in the site config
 * (docs/automatic-actions-v2.md). This suite never edits site config, so it
 * covers only what works without it: `options`, `save` validation and the
 * saved design, role refusals, and the documented stop of a schema-2 stage:
 * without the service identity a request reaching it ends as a Failed
 * instance (`Automatic Failed`, `ServiceIdentityMissing`).
 *
 * Everything runs on a dedicated request type (`auto_request_type`) so the
 * stage rewrites never touch the definition `requests.spec.ts` relies on.
 */

import { expect, test } from '../support/fixtures';
import type { ApiSession } from '../support/api';
import { ASOUD, METHOD, errorText } from '../support/api';
import { requestId, subject } from '../support/config';
import { loadState } from '../support/state';

const state = loadState();
const definition = state.auto_request_type as string;
const stages = state.auto_stages as Record<string, string>;
const systemStage = stages['System Action'];

const OPTIONS = `${ASOUD}.automatic_actions.options`;
const SAVE = `${ASOUD}.automatic_actions.save`;
const MISSING_IDENTITY = 'Configure a restricted workflow service user and company allowlist first';

const NOTIFICATION = {
  schema_version: 2,
  title: 'اعلان خودکار',
  action_type: 'Send Notification',
  operation: { recipients: ['initiator'], channels: ['in_app'], message: 'اعلان تستی' },
  execution: { extra_attempts: 0, retry_seconds: 60, timeout_seconds: 120 },
};
const ROUTES = { Success: stages['End'], Error: stages['User Task'] };

interface Design {
  stages: { name: string; stage_type: string; stage_title: string; config: Record<string, unknown> }[];
  transitions: { from_stage: string; to_stage: string; condition: { action?: string } }[];
}

interface Options {
  schema_version: number;
  actions: string[];
  channels: string[];
  execution_ready: boolean;
  blocked_reason: string | null;
  users: { id: string; label: string }[];
}

function saveForm(config: unknown, routes: unknown = ROUTES): Record<string, string> {
  return {
    definition,
    stage: systemStage,
    config: JSON.stringify(config),
    routes: JSON.stringify(routes),
  };
}

async function design(session: ApiSession): Promise<Design> {
  return session.read<Design>(`${ASOUD}.workflow.get_workflow_design`, { definition });
}

function systemConfig(value: Design): Record<string, unknown> {
  return value.stages.find((stage) => stage.name === systemStage)!.config;
}

test.describe.configure({ mode: 'serial' });

test.describe('automatic actions schema 2 without a service user', () => {
  test('options lists the schema and reports the missing service identity', async ({ api }) => {
    const admin = await api.login('admin');
    const options = await admin.read<Options>(OPTIONS, { definition, stage: systemStage });
    expect(options.schema_version).toBe(2);
    expect(options.actions).toEqual(expect.arrayContaining(['Send Notification', 'Create Request', 'Change Status']));
    expect(options.channels).toEqual(['in_app', 'email']);
    test.skip(options.execution_ready, 'this site has a workflow service user configured');
    expect(options.execution_ready).toBe(false);
    expect(options.blocked_reason).toBe(MISSING_IDENTITY);
  });

  test('options and save refuse an Employee with 403', async ({ api }) => {
    const employee = await api.login('employee');
    const listed = await employee.get(OPTIONS, { definition, stage: systemStage });
    expect(listed.status, errorText(listed)).toBe(403);
    const before = JSON.stringify(systemConfig(await design(await api.login('admin'))));
    const saved = await employee.post(SAVE, saveForm(NOTIFICATION));
    expect(saved.status, errorText(saved)).toBe(403);
    expect(JSON.stringify(systemConfig(await design(await api.login('admin'))))).toBe(before);
  });

  test('options on a stage that is not an automatic action is refused with 417', async ({ api }) => {
    const admin = await api.login('admin');
    const result = await admin.get(OPTIONS, { definition, stage: stages['Approval'] });
    expect(result.status).toBe(417);
    expect(errorText(result)).toContain('The selected stage is not an automatic action of this workflow');
  });

  test('invalid configurations are refused with 417 and change nothing', async ({ api }) => {
    const admin = await api.login('admin');
    const before = JSON.stringify(await design(admin));
    const cases: { name: string; config: unknown; routes?: unknown; message: string }[] = [
      {
        name: 'unknown channel',
        config: { ...NOTIFICATION, operation: { ...NOTIFICATION.operation, channels: ['sms'] } },
        message: 'Choose in-app notification and/or email',
      },
      {
        name: 'no recipients',
        config: { ...NOTIFICATION, operation: { ...NOTIFICATION.operation, recipients: [] } },
        message: 'Choose 1..30 recipients',
      },
      {
        name: 'settings from another action',
        config: { ...NOTIFICATION, operation: { ...NOTIFICATION.operation, request_type: 'x' } },
        message: 'Configuration contains fields from another action',
      },
      {
        name: 'unknown action type',
        config: { ...NOTIFICATION, action_type: 'Run Script' },
        message: 'Unsupported automatic action',
      },
      {
        name: 'an unknown message variable',
        config: { ...NOTIFICATION, operation: { ...NOTIFICATION.operation, message: 'سلام {{no_such_field}}' } },
        message: 'Message contains an unknown or non-scalar variable',
      },
      {
        name: 'a missing error route is not enough: both keys are required',
        config: NOTIFICATION,
        routes: { Success: stages['End'] },
        message: 'Configuration and both routes are required',
      },
      {
        name: 'no success route',
        config: NOTIFICATION,
        routes: { Success: '', Error: stages['User Task'] },
        message: 'Choose an existing success stage',
      },
      {
        name: 'an error route to a non-human stage',
        config: NOTIFICATION,
        routes: { Success: stages['End'], Error: stages['End'] },
        message: 'Invalid route: errors may only route to a human task',
      },
    ];
    for (const row of cases) {
      const result = await admin.post(SAVE, saveForm(row.config, row.routes ?? ROUTES));
      expect(result.status, `${row.name}: ${errorText(result)}`).toBe(417);
      expect(errorText(result), row.name).toContain(row.message);
    }
    expect(JSON.stringify(await design(admin)), 'a refused save must not alter the design').toBe(before);
  });

  test('a valid action is saved with both routes and read back through the design', async ({ api }) => {
    const admin = await api.login('admin');
    const result = await admin.post<Design>(SAVE, saveForm(NOTIFICATION));
    expect(result.status, errorText(result)).toBe(200);
    expect(result.envelope.ok).toBe(true);

    const stored = await design(admin);
    const stage = stored.stages.find((row) => row.name === systemStage)!;
    expect(stage.stage_title).toBe('اعلان خودکار');
    expect(stage.config).toMatchObject({
      schema_version: 2,
      action_type: 'Send Notification',
      operation: { recipients: ['initiator'], channels: ['in_app'], message: 'اعلان تستی' },
      execution: { extra_attempts: 0, retry_seconds: 60, timeout_seconds: 120 },
    });
    const exits = stored.transitions.filter((row) => row.from_stage === systemStage);
    expect(exits.map((row) => row.to_stage).sort()).toEqual([stages['End'], stages['User Task']].sort());
    expect(result.envelope.data.stages.find((row) => row.name === systemStage)!.config).toEqual(stage.config);
  });

  test('a request reaching the stage without a service user ends as a Failed instance', async ({ api }) => {
    const admin = await api.login('admin');
    const options = await admin.read<Options>(OPTIONS, { definition, stage: systemStage });
    test.skip(options.execution_ready, 'this site has a workflow service user configured');
    // Global setup resets the stage to its legacy action on every run, so this test
    // installs the schema-2 action itself instead of relying on the test before it.
    const saved = await admin.post(SAVE, saveForm(NOTIFICATION));
    expect(saved.status, errorText(saved)).toBe(200);

    const employee = await api.login('employee');
    const approver = await api.login('approver');
    const created = await employee.mutate<{ name: string; workflow_instance: string }>(METHOD.createRequest, {
      company: state.company,
      workflow_definition: definition,
      subject: subject('اقدام خودکار', 'no-identity'),
      values: JSON.stringify({ amount: 10, reason: 'e2e-auto' }),
      request_id: requestId('AUTO', 'no-identity'),
    });
    const task = (await approver.read<{ name: string; workflow_instance: string }[]>(METHOD.listMyTasks, {
      status: 'Open',
    })).find((row) => row.workflow_instance === created.workflow_instance);
    expect(task, 'the direct manager owns the approval task').toBeTruthy();
    await approver.mutate(METHOD.completeTask, { task: task!.name, action: 'Approve', comment: 'تأیید شد' });

    const instance = await employee.read<{
      status: string;
      activities: { action: string; comment?: string }[];
    }>(METHOD.getInstance, { instance: created.workflow_instance });
    expect(instance.status).toBe('Failed');
    const failure = instance.activities.find((row) => row.action === 'Automatic Failed');
    expect(failure, 'the failure must be audited').toBeTruthy();
    expect(failure!.comment).toContain('Send Notification');
    expect(failure!.comment).toContain(MISSING_IDENTITY);
    expect(instance.activities.map((row) => row.action)).not.toContain('System Action Succeeded');

    const request = await employee.read<{ status: string }>(METHOD.getRequest, { name: created.name });
    expect(request.status, 'a Failed instance must not read as a finished request').not.toBe('Completed');
  });
});
