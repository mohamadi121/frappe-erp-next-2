import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { BENCH, PYTHON, type SiteState } from './config';

/** The site facts global setup wrote; every spec reads them instead of guessing. */
export function loadState(): SiteState & { request_type: string } {
  return JSON.parse(
    readFileSync(`${__dirname}/../test-results/site-state.json`, 'utf8'),
  ) as SiteState & { request_type: string };
}

/** Call site_prep.py with an action and options. */
export function sitePrep<T = Record<string, unknown>>(
  action: string,
  options: Record<string, string> = {},
): T {
  const args = [action, ...Object.entries(options).map(([key, value]) => `${key}=${value}`)];
  const output = execFileSync(PYTHON, [`${__dirname}/py/site_prep.py`, ...args], {
    cwd: BENCH,
    encoding: 'utf8',
    maxBuffer: 32 * 1024 * 1024,
  });
  const line = output.split('\n').find((value) => value.startsWith('@@E2E_JSON@@'));
  if (!line) throw new Error(`site_prep.py ${action} printed no state:\n${output}`);
  return JSON.parse(line.slice('@@E2E_JSON@@'.length)) as T;
}

/** A leaf (non-group) account of the given root type, e.g. an expense account. */
export function leafAccount(state: SiteState, rootType: string): string {
  const row = state.accounts.find((account) => account.root_type === rootType);
  if (!row) throw new Error(`no leaf ${rootType} account in the test company`);
  return row.name;
}