import { execFileSync } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { request } from 'playwright';
import { ApiSession, expect, test } from '../support/fixtures';
import { errorText } from '../support/api';
import { PYTHON } from '../support/config';
import { loadState } from '../support/state';

test('only the system administrator grants HR authority through all public paths', async ({ api, baseURL }) => {
  const state = loadState();
  const token = `HG${randomBytes(6).toString('hex').toUpperCase()}`;
  const fixture = (action: string) => execFileSync(PYTHON,
    [`${__dirname}/hr_role_grants_fixture.py`, action, state.company, token],
    { encoding: 'utf8', env: process.env });
  const context = await request.newContext({ baseURL });
  try {
    const line = fixture('setup').split('\n').find(value => value.startsWith('@@HR_GRANT@@'));
    if (!line) throw new Error('Missing HR grant reservation');
    const reserved = JSON.parse(line.slice('@@HR_GRANT@@'.length)) as {
      actor: string; target: string; global: string; office: string;
    };
    const delegate = await ApiSession.login(context, reserved.actor, 'Http-HR-Grant-42');
    const employee = await api.login('employee');
    const admin = await api.login('admin');
    const prefix = 'asoud_erp.api.v1.';
    for (const session of [delegate, employee]) {
      for (const [method, payload] of [
        ['role_access.assign_role', { user: reserved.target, role: reserved.global }],
        ['user_access.apply', { payload: JSON.stringify({ code: reserved.global, user: reserved.target }) }],
        ['hr_onboarding.register_personnel', {
          company: state.company, first_name: 'سارا', last_name: 'رضایی', mobile: '09123456789',
          email: `denied-${token.toLowerCase()}@example.com`, gender: 'Female',
          birth_date: '1995-01-01', date_of_joining: '2024-01-01',
          activation: 'temporary_password', roles: JSON.stringify([reserved.global]),
        }],
      ] as Array<[string, Record<string, string>]>) {
        const denied = await session.post(prefix + method, payload);
        expect(denied.status).toBe(403);
        expect(denied.body.exc_type).toBe('PermissionError');
        expect(errorText(denied)).toMatch(/[آ-ی]/);
      }
    }
    const foreign = await delegate.post(prefix + 'role_access.assign_role', {
      user: reserved.target, role: reserved.office, company: state.second_company,
    });
    expect(foreign.status).toBe(403);
    expect(errorText(foreign)).toMatch(/[آ-ی]/);
    const allowed = await admin.post<{ assigned: boolean }>(prefix + 'role_access.assign_role', {
      user: reserved.target, role: reserved.global,
    });
    expect(allowed.status).toBe(200);
    expect(allowed.envelope.ok).toBe(true);
    expect(allowed.envelope.data.assigned).toBe(true);
  } finally {
    await context.dispose();
    fixture('cleanup');
  }
});
