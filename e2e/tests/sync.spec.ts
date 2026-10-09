/**
 * `sync.execute_mutation`: the replay-safe wrapper the offline queue uses.
 *
 * The observable effect is a workflow draft: `create_workflow_draft` makes a
 * new definition on every real execution, so counting definitions with the
 * run's title proves how many times the inner call actually ran. (A request
 * type would not do: `create_request` has its own `request_id` idempotency.)
 */

import { expect, test } from '../support/fixtures';
import type { ApiSession, FrappeResponse } from '../support/api';
import { ASOUD, METHOD, errorText } from '../support/api';
import { PREFIX, RUN_ID } from '../support/config';
import { loadState, sitePrep } from '../support/state';

const state = loadState();
const EXECUTE = `${ASOUD}.sync.execute_mutation`;
const DRAFT = METHOD.createWorkflowDraft;
const titles = new Set<string>();

function title(tag: string): string {
  const value = `${PREFIX} همگام ${RUN_ID} ${tag}`;
  titles.add(value);
  return value;
}

function key(tag: string): string {
  return `${PREFIX}sync-${RUN_ID}-${tag}`;
}

function draftPayload(workflowTitle: string): string {
  return JSON.stringify({
    workflow_title: workflowTitle,
    module_key: 'Support',
    target_doctype: 'ASOUD Workflow Request',
    company: state.company,
  });
}

function run(session: ApiSession, request_key: string, target_method: string, payload: string) {
  return session.post(EXECUTE, { request_key, target_method, payload });
}

async function definitionsTitled(admin: ApiSession, workflowTitle: string) {
  const listed = await admin.read<{ name: string; workflow_title: string }[]>(METHOD.listWorkflows, {
    company: state.company,
    search: workflowTitle,
  });
  return listed.filter((row) => row.workflow_title === workflowTitle);
}

function expectFailure(result: FrappeResponse, code: string) {
  expect(result.status, `a key refusal is an envelope, not an HTTP error: ${errorText(result)}`).toBe(200);
  expect(result.envelope.ok).toBe(false);
  expect(result.envelope.error?.code).toBe(code);
}

test.afterAll(() => {
  // Drafts made by this suite are removed so repeated runs leave nothing behind.
  for (const definition of sitePrep<{ definitions: { name: string; workflow_title: string }[] }>('status')
    .definitions) {
    if (titles.has(definition.workflow_title)) sitePrep('drop-definition', { definition: definition.name });
  }
});

test.describe('sync.execute_mutation request keys', () => {
  test('the same key and payload twice runs once and answers with the same envelope', async ({ api }) => {
    const admin = await api.login('admin');
    const workflowTitle = title('replay');
    const first = await run(admin, key('replay'), DRAFT, draftPayload(workflowTitle));
    expect(first.status, errorText(first)).toBe(200);
    expect(first.envelope.ok).toBe(true);
    const created = (first.envelope.data as { name: string }).name;
    expect(created).toMatch(/^WF-/);

    const second = await run(admin, key('replay'), DRAFT, draftPayload(workflowTitle));
    expect(second.status).toBe(200);
    expect(second.envelope, 'the replay must return the stored envelope').toEqual(first.envelope);
    expect(await definitionsTitled(admin, workflowTitle), 'the inner call must have run exactly once').toHaveLength(1);
  });

  test('the same key with a different payload is REQUEST_KEY_CONFLICT and never runs', async ({ api }) => {
    const admin = await api.login('admin');
    const original = title('conflict-payload');
    const other = title('conflict-payload-other');
    const first = await run(admin, key('conflict-payload'), DRAFT, draftPayload(original));
    expect(first.envelope.ok).toBe(true);

    const clash = await run(admin, key('conflict-payload'), DRAFT, draftPayload(other));
    expectFailure(clash, 'REQUEST_KEY_CONFLICT');
    expect(clash.envelope.data ?? null, 'never the first response').not.toEqual(first.envelope.data);
    expect(await definitionsTitled(admin, other), 'the conflicting payload must not execute').toHaveLength(0);
    expect(await definitionsTitled(admin, original)).toHaveLength(1);

    const again = await run(admin, key('conflict-payload'), DRAFT, draftPayload(original));
    expect(again.envelope, 'the original payload still replays').toEqual(first.envelope);
  });

  test('the same key with a different method is REQUEST_KEY_CONFLICT', async ({ api }) => {
    const admin = await api.login('admin');
    const workflowTitle = title('conflict-method');
    const first = await run(admin, key('conflict-method'), DRAFT, draftPayload(workflowTitle));
    expect(first.envelope.ok).toBe(true);

    const clash = await run(admin, key('conflict-method'), METHOD.createRequest, '{}');
    expectFailure(clash, 'REQUEST_KEY_CONFLICT');
  });

  test("another user's key is INVALID_REQUEST_KEY and never replays the response", async ({ api }) => {
    const admin = await api.login('admin');
    const accounts = await api.login('accounts');
    const workflowTitle = title('foreign');
    const first = await run(admin, key('foreign'), DRAFT, draftPayload(workflowTitle));
    expect(first.envelope.ok).toBe(true);

    const stolen = await run(accounts, key('foreign'), DRAFT, draftPayload(workflowTitle));
    expectFailure(stolen, 'INVALID_REQUEST_KEY');
    expect(JSON.stringify(stolen.body)).not.toContain((first.envelope.data as { name: string }).name);
  });

  test('an inner validation error answers HTTP 417 and is not a key collision', async ({ api }) => {
    const admin = await api.login('admin');
    const result = await run(admin, key('inner-error'), DRAFT, draftPayload('x'));
    expect(result.status).toBe(417);
    expect(errorText(result)).toContain('Workflow title must contain at least 3 characters');
    expect(result.envelope.error?.code).not.toBe('REQUEST_KEY_CONFLICT');

    // The failed attempt rolled back with its key, so a corrected call under the
    // same key is a fresh execution, not a conflict.
    const workflowTitle = title('inner-error-fixed');
    const retry = await run(admin, key('inner-error'), DRAFT, draftPayload(workflowTitle));
    expect(retry.status, errorText(retry)).toBe(200);
    expect(retry.envelope.ok).toBe(true);
    expect(await definitionsTitled(admin, workflowTitle)).toHaveLength(1);
  });

  test('unsafe keys and methods are refused before anything runs', async ({ api }) => {
    const admin = await api.login('admin');
    expectFailure(await run(admin, ' ', DRAFT, '{}'), 'INVALID_REQUEST_KEY');
    expectFailure(await run(admin, 'k'.repeat(141), DRAFT, '{}'), 'INVALID_REQUEST_KEY');
    expectFailure(await run(admin, key('read-only'), METHOD.listWorkflows, '{}'), 'METHOD_NOT_ALLOWED');
    expectFailure(await run(admin, key('foreign-app'), 'frappe.client.insert', '{}'), 'METHOD_NOT_ALLOWED');
    expectFailure(await run(admin, key('recursive'), EXECUTE, '{}'), 'METHOD_NOT_ALLOWED');
  });
});
