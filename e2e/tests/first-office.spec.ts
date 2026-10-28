import { execFileSync } from 'node:child_process';
import { expect, test } from '../support/fixtures';
import { PYTHON } from '../support/config';
import { errorText, METHOD } from '../support/api';
import { loadState } from '../support/state';

const state = loadState();
const method = 'asoud_erp.api.v1.first_office_setup.create_hr_lead';

test('first HR account reports Persian fields and enforces administrator access over HTTP', async ({ api }) => {
  const fixture = `${__dirname}/first_office_fixture.py`;
  const output = execFileSync(PYTHON, [fixture, 'setup', state.company], { encoding: 'utf8', env: process.env });
  const line = output.split('\n').find(value => value.startsWith('@@FIRST_OFFICE@@'));
  if (!line) throw new Error('Missing first-office reservation');
  const reservation = JSON.parse(line.slice('@@FIRST_OFFICE@@'.length));
  try {
    const admin = await api.login('admin');
    const identity = await admin.read<{ employee: unknown }>(METHOD.currentUser);
    expect(identity.employee).toBeNull();
    const status = await admin.post('asoud_erp.api.v1.first_office_setup.status', { company: state.company });
    expect(status.status).toBe(200);
    expect(status.envelope.ok).toBe(true);
    expect(status.envelope.data.hr_lead).toBeNull();
    const args = { company: state.company, full_name: 'علی رضایی', username: reservation.username,
      contact: 'lead-contact@example.com', temporary_password: 'Secure-Lead-Password-42' };
    for (const [overrides, message] of [
      [{ username: '1invalid' }, 'نام کاربری'],
      [{}, 'نام کاربری قبلاً'],
      [{ username: 'new_lead', contact: '' }, 'شماره موبایل یا ایمیل'],
      [{ username: 'new_lead', temporary_password: '12345678' }, 'رمز موقت'],
    ] as const) {
      const response = await admin.post(method, { ...args, ...overrides });
      expect(response.status).toBe(417);
      expect(errorText(response)).toContain(message);
    }
    const { contact, ...withoutContact } = { ...args, username: 'new_lead' };
    const missing = await admin.post(method, withoutContact);
    expect(missing.status).toBe(417);
    expect(errorText(missing)).toContain('شماره موبایل یا ایمیل');
    for (const user of ['employee', 'outsider', 'hr'] as const) {
      const denied = await (await api.login(user)).post(method, args);
      expect(denied.status).toBe(403);
      expect(errorText(denied)).toContain('فقط برای مدیر سیستم');
    }
  } finally {
    execFileSync(PYTHON, [fixture, 'cleanup', JSON.stringify(reservation)], { encoding: 'utf8', env: process.env });
  }
});
