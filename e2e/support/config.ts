/** Shared configuration and identities for the end-to-end suite. */

export const SITE = process.env.E2E_SITE ?? 'asoud.test';
export const BENCH = process.env.E2E_BENCH_PATH ?? `${process.env.HOME}/frappe-dev/bench`;
export const PYTHON = `${BENCH}/env/bin/python`;

/** Every record this suite creates is prefixed so cleanup and debugging stay safe. */
export const PREFIX = 'E2E-';

/**
 * Users prepared by global setup with `bench add-user` / `bench set-password`.
 * The three `asoud.*` accounts are the integration fixture users.
 */
export const USERS = {
  admin: { email: 'e2e.admin@example.com', password: 'E2e-Pw-Admin-2026' },
  accounts: { email: 'e2e.accounts@example.com', password: 'E2e-Pw-Accounts-2026' },
  outsider: { email: 'e2e.outsider@example.com', password: 'E2e-Pw-Outsider-2026' },
  employee: { email: 'asoud.employee@example.com', password: 'E2e-Pw-Employee-2026' },
  approver: { email: 'asoud.approver@example.com', password: 'E2e-Pw-Approver-2026' },
  accountant: { email: 'asoud.accountant@example.com', password: 'E2e-Pw-Accountant-2026' },
} as const;

export type UserKey = keyof typeof USERS;

/** A short token that makes every request id and subject of one run unique. */
export const RUN_ID = `${Date.now().toString(36)}${Math.floor(Math.random() * 1e4)
  .toString(36)
  .padStart(3, '0')}`;

export function requestId(kind: string, suffix: string): string {
  return `${PREFIX}${RUN_ID}-${kind}-${suffix}`.slice(0, 90);
}

export function subject(kind: string, suffix: string): string {
  return `${PREFIX} ${kind} ${RUN_ID} ${suffix}`;
}

/** Site facts global setup prepares; specs read them instead of hard-coding. */
export interface SiteState {
  site: string;
  company: string;
  abbr: string;
  second_company: string;
  employees: { name: string; employee_name: string; user_id: string; reports_to: string | null }[];
  accounts: { name: string; account_type: string; root_type: string }[];
  definitions: {
    name: string;
    workflow_title: string;
    status: string;
    readiness_status: string;
    frappe_workflow: string;
    company: string;
  }[];
  templates: { name: string; template_title: string; status: string; document_type: string }[];
  fixture_approver?: string;
  fixture_employee?: string;
  /** Written by global setup: the ASOUD Workflow Definition the request tests use. */
  request_type?: string;
  doc_request_type?: string;
  doc_stage?: string;
}