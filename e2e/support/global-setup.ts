/**
 * Site preparation, run once before the whole suite.
 *
 * 1. `bench add-user` / `bench set-password` create the E2E logins (bench only,
 *    never real data) and give the three shared fixture users a known password.
 * 2. `support/py/site_prep.py ensure` runs the integration fixtures, adds the
 *    Employee records the E2E-only logins need and creates a second company.
 * 3. The request type `requests.spec.ts` and `permissions.spec.ts` use is
 *    designed here through the real `workflow.*` endpoints as a System Manager
 *    over HTTP. Only the native Frappe Workflow link that no API exposes is
 *    written by the helper; activation still goes through `set_workflow_status`.
 *
 * Every step is idempotent, so a second run reuses what the first run created.
 */

import { execFileSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { request } from '@playwright/test';
import { ApiSession, METHOD } from './api';
import { PYTHON, BENCH, USERS, PREFIX, type SiteState } from './config';

const STATE_FILE = `${__dirname}/../test-results/site-state.json`;
const REQUEST_TYPE_TITLE = `${PREFIX} درخواست تستی گردش کار`;
const DOC_REQUEST_TYPE_TITLE = `${PREFIX} گردش کار صدور سند تستی`;

const FORM_FIELDS = [
  { key: 'amount', label: 'مبلغ درخواست', type: 'Number', required: true },
  { key: 'reason', label: 'دلیل درخواست', type: 'Short Text', required: true },
];

function bench(args: string[]): void {
  try {
    execFileSync('bench', ['--site', process.env.E2E_SITE ?? 'asoud.test', ...args], {
      cwd: BENCH,
      encoding: 'utf8',
      stdio: ['ignore', 'pipe', 'pipe'],
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    // An existing user is not a failure: set-password below fixes the password.
    if (!/DuplicateEntryError|already exists/i.test(message)) throw error;
  }
}

function sitePrep(action: string, options: Record<string, string> = {}): SiteState {
  const args = [action, ...Object.entries(options).map(([key, value]) => `${key}=${value}`)];
  const output = execFileSync(PYTHON, [`${__dirname}/py/site_prep.py`, ...args], {
    cwd: BENCH,
    encoding: 'utf8',
    maxBuffer: 32 * 1024 * 1024,
  });
  const line = output.split('\n').find((value) => value.startsWith('@@E2E_JSON@@'));
  if (!line) throw new Error(`site_prep.py ${action} printed no state:\n${output}`);
  return JSON.parse(line.slice('@@E2E_JSON@@'.length)) as SiteState;
}

interface Stage {
  name: string;
  stage_type: string;
  configuration_status: string;
  config: Record<string, unknown>;
}

const STAGE_PLAN = ['Start', 'User Task', 'Approval', 'System Action', 'End'];

async function readDesign(
  session: ApiSession,
  definition: string,
): Promise<{ stages: Stage[] }> {
  return session.read<{ stages: Stage[] }>('asoud_erp.api.v1.workflow.get_workflow_design', {
    definition,
  });
}

/** A definition is reusable only when it holds the full stage plan, configured. */
function designIsUsable(design: { stages: Stage[] }): boolean {
  const stages = design.stages;
  if (stages.length !== STAGE_PLAN.length) return false;
  return STAGE_PLAN.every((stageType, index) => {
    const stage = stages[index];
    return (
      stage.stage_type === stageType &&
      stage.configuration_status === 'Complete' &&
      Object.keys(stage.config ?? {}).length > 0
    );
  });
}

async function designRequestType(
  admin: ApiSession,
  company: string,
  title: string = REQUEST_TYPE_TITLE,
): Promise<string> {
  const draft = await admin.mutate<{ name: string }>(METHOD.createWorkflowDraft, {
    workflow_title: title,
    module_key: 'Support',
    target_doctype: 'ASOUD Workflow Request',
    company,
    process_description: 'گردش کار آزمون سرتاسری',
    creation_mode: 'Custom',
  });
  const design = await readDesign(admin, draft.name);
  const start = design.stages.find((stage) => stage.stage_type === 'Start') as Stage;

  await admin.mutate(METHOD.saveStartSettings, {
    definition: draft.name,
    trigger_type: 'Manual',
    initiator_roles: '["Employee"]',
    subject_source: 'General Subject',
    pass_mode: 'Direct',
  });

  const stages: Record<string, string> = {};
  let previous = start;
  for (const stageType of STAGE_PLAN.slice(1)) {
    const payload = await admin.mutate<{ stages: Stage[] }>(METHOD.addWorkflowStage, {
      definition: draft.name,
      stage_type: stageType,
      after_stage: previous.name,
    });
    previous = payload.stages.find((row) => row.stage_type === stageType) as Stage;
    stages[stageType] = previous.name;
  }

  await admin.mutate(METHOD.saveStageSettings, {
    definition: draft.name,
    stage: stages['User Task'],
    config: JSON.stringify({
      title: 'ثبت درخواست',
      activity_type: 'Data Entry',
      assignment_type: 'Initiator',
      form_fields: FORM_FIELDS,
      require_all_fields: true,
    }),
  });
  await admin.mutate(METHOD.saveStageSettings, {
    definition: draft.name,
    stage: stages['Approval'],
    config: JSON.stringify({
      title: 'تأیید مدیر مستقیم',
      assignment_type: 'Direct Manager',
      approval_mode: 'Any',
      allow_reject: true,
      allow_return: false,
      reject_comment_required: true,
    }),
  });
  await admin.mutate(METHOD.saveStageSettings, {
    definition: draft.name,
    stage: stages['System Action'],
    config: JSON.stringify({
      title: 'ثبت وضعیت خودکار',
      action_type: 'Change Status',
      request_status: 'در حال بررسی خودکار',
    }),
  });
  await admin.mutate(METHOD.saveStageSettings, {
    definition: draft.name,
    stage: stages['End'],
    config: JSON.stringify({ title: 'پایان', outcome: 'Completed' }),
  });

  await admin.mutate(METHOD.updateRequestTypeInfo, {
    name: draft.name,
    workflow_title: title,
    short_title: 'درخواست تستی',
    process_description: 'گردش کار آزمون سرتاسری',
    request_category: 'General',
    show_in_request_list: '1',
    allow_user_submission: '1',
  });
  return draft.name;
}

export default async function globalSetup(): Promise<void> {
  for (const [key, user] of Object.entries(USERS)) {
    if (key === 'admin' || key === 'accounts' || key === 'outsider') {
      const role = key === 'admin' ? 'System Manager' : key === 'accounts' ? 'Accounts Manager' : 'Employee';
      bench(['add-user', user.email, '--first-name', `E2E ${key}`, '--password', user.password, '--add-role', role]);
    }
    bench(['set-password', user.email, user.password]);
  }

  const state = sitePrep('ensure');
  if (!state.second_company) throw new Error('site_prep did not create the second company');

  const apiRequest = await request.newContext({
    baseURL: process.env.E2E_BASE_URL ?? `http://127.0.0.1:${process.env.E2E_PORT ?? 8010}`,
  });
  try {
    const admin = await ApiSession.login(apiRequest, USERS.admin.email, USERS.admin.password);

    async function ensureDefinition(title: string): Promise<{ name: string; systemStage: string }> {
      let def = state.definitions.find((row) => row.workflow_title === title);
      // A definition left half-designed by an earlier interrupted run is dropped,
      // never patched: the suite always designs through the real endpoints.
      if (def && !designIsUsable(await readDesign(admin, def.name))) {
        sitePrep('drop-definition', { definition: def.name });
        def = undefined;
      }
      if (!def) {
        def = {
          name: await designRequestType(admin, state.company, title),
          workflow_title: title,
          status: 'Inactive',
          readiness_status: 'Pending',
          frappe_workflow: '',
          company: state.company,
        };
      }
      const design = await readDesign(admin, def.name);
      if (!designIsUsable(design)) {
        throw new Error(`request type ${def.name} is not fully configured`);
      }
      if (def.status !== 'Active') {
        sitePrep('activate', { definition: def.name });
        await admin.mutate(METHOD.setWorkflowStatus, { name: def.name, status: 'Active' });
      }
      const currentStatus =
        sitePrep('status').definitions.find((row) => row.name === def!.name)?.status ?? 'Active';
      if (currentStatus !== 'Active') throw new Error(`request type ${def.name} is not Active`);

      const systemStage = design.stages.find((stage) => stage.stage_type === 'System Action')!.name;
      return { name: def.name, systemStage };
    }

    const mainDef = await ensureDefinition(REQUEST_TYPE_TITLE);
    const docDef = await ensureDefinition(DOC_REQUEST_TYPE_TITLE);

    mkdirSync(`${__dirname}/../test-results`, { recursive: true });
    writeFileSync(
      STATE_FILE,
      JSON.stringify(
        {
          ...sitePrep('status'),
          request_type: mainDef.name,
          doc_request_type: docDef.name,
          doc_stage: docDef.systemStage,
        },
        null,
        2,
      ),
    );
  } finally {
    await apiRequest.dispose();
  }
}