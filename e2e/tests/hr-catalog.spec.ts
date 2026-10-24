import { execFileSync } from 'node:child_process';
import { expect, test } from '../support/fixtures';
import { PYTHON } from '../support/config';
import { loadState } from '../support/state';

const prefix = 'asoud_erp.api.v1.forms.';
const state = loadState();
const key = 'training';
type Row = { name: string; builtin_key?: string; active_revision: string };
let owned = false;
function fixture(action: string) {
  execFileSync(PYTHON, [`${__dirname}/hr_catalog_fixture.py`, action, state.company, key], {
    encoding: 'utf8', env: process.env,
  });
}

test.beforeAll(() => { fixture('reserve'); owned = true; });
test.afterAll(() => { if (owned) fixture('cleanup'); });

test('HR defaults enforce real HTTP company and role gates, preserve removed revisions', async ({ api }) => {
  const admin = await api.login('admin'); // System Manager without Employee
  const employee = await api.login('employee');
  const hr = await api.login('hr');
  const rows = await admin.read<Row[]>(prefix + 'list_forms', {company: state.company, manage: '1'});
  expect(rows.filter(row => row.builtin_key)).toHaveLength(10);
  expect((await employee.post(prefix + 'remove_builtin', {company: state.company, key})).status).toBe(403);
  expect((await hr.post(prefix + 'remove_builtin', {company: state.company, key})).status).toBe(403);
  expect((await employee.post(prefix + 'open_builtin', {company: state.second_company, key})).status).toBe(403);
  expect((await employee.post(prefix + 'open_builtin', {company: state.company, key, manage: '1'})).status).toBe(403);
  const first = await admin.mutate<Row>(prefix + 'open_builtin', {company: state.company, key, manage: 1});
  const second = await admin.mutate<Row>(prefix + 'open_builtin', {company: state.company, key, manage: 1});
  expect(second.name).toBe(first.name);
  expect(second.active_revision).toBe(first.active_revision);
  await employee.mutate(prefix + 'open_builtin', {company: state.company, key});
  await admin.mutate(prefix + 'remove_builtin', {company: state.company, key});
  expect((await admin.read<Row[]>(prefix + 'list_forms', {company: state.company, manage: '1'})).some(row => row.name === first.name)).toBe(false);
  expect((await admin.post(prefix + 'open_builtin', {company: state.company, key})).status).toBe(403);
  const history = await admin.read<Array<{name: string}>>(prefix + 'get_history', {name: first.name});
  expect(history.some(row => row.name === first.active_revision)).toBe(true);
});
