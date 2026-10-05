import { readFileSync } from 'node:fs';
import type { SiteState } from './config';

/** The site facts global setup wrote; every spec reads them instead of guessing. */
export function loadState(): SiteState & { request_type: string } {
  return JSON.parse(
    readFileSync(`${__dirname}/../test-results/site-state.json`, 'utf8'),
  ) as SiteState & { request_type: string };
}

/** A leaf (non-group) account of the given root type, e.g. an expense account. */
export function leafAccount(state: SiteState, rootType: string): string {
  const row = state.accounts.find((account) => account.root_type === rootType);
  if (!row) throw new Error(`no leaf ${rootType} account in the test company`);
  return row.name;
}