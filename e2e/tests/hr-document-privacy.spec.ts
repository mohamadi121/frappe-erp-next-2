import { execFileSync } from 'node:child_process';
import { expect, test } from '../support/fixtures';
import { PYTHON } from '../support/config';
import { loadState } from '../support/state';

const state = loadState();

test('HR snapshot reads and print mask payroll and enforce office scope over HTTP', async ({ api }) => {
  const fixture = `${__dirname}/hr_document_privacy_fixture.py`;
  const output = execFileSync(PYTHON, [fixture, 'setup', state.company, state.second_company],
    { encoding: 'utf8', env: process.env });
  const line = output.split('\n').find(value => value.startsWith('@@PRIVACY_JSON@@'));
  if (!line) throw new Error('Missing snapshot reservation');
  const rows = JSON.parse(line.slice('@@PRIVACY_JSON@@'.length)) as Array<{name: string; company: string; kind: string}>;
  try {
    const admin = await api.login('admin');
    const hr = await api.login('hr');
    const employee = await api.login('employee');
    for (const row of rows) {
      const hiring = row.kind === 'ASOUD Hiring Order';
      const certificate = row.kind === 'ASOUD Employment Certificate';
      const prefix = `asoud_erp.api.v1.${certificate ? 'employment_certificates' : hiring ? 'hiring_orders' : 'salary_change_orders'}.`;
      const detail = certificate ? 'get_certificate' : hiring ? 'get_hiring_order' : 'get_salary_change_order';
      const print = certificate ? detail : hiring ? 'print_hiring_order' : 'print_salary_change_order';
      // The administrator session has no Employee and still sees authorized payroll data.
      expect(JSON.stringify(await admin.read(prefix + detail, { name: row.name }))).toContain('987654321');
      for (const method of new Set([detail, print])) {
        expect((await employee.post(prefix + method, { name: row.name })).status).toBe(403);
        const response = await hr.post(prefix + method, { name: row.name });
        if (row.company !== state.company) {
          expect(response.status).toBe(403);
        } else {
          expect(response.status).toBe(200);
          expect(response.envelope.ok).toBe(true);
          const text = JSON.stringify(response.envelope.data);
          expect(text).not.toContain('987654321');
          expect(text).not.toContain('۹۸۷');
        }
      }
    }
  } finally {
    execFileSync(PYTHON, [fixture, 'cleanup', ...rows.map(row => row.name)],
      { encoding: 'utf8', env: process.env });
  }
});
