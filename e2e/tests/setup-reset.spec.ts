import { expect, test } from '../support/fixtures';

const prefix = 'asoud_erp.api.v1.setup_reset.';

test('setup reset never grants destructive authority to an employee or guest', async ({api}) => {
  const employee = await api.login('employee');
  const guest = await api.anonymous();
  expect((await employee.post(prefix + 'preview')).status).toBe(403);
  expect((await employee.post(prefix + 'status', {job: 'a'.repeat(40)})).status).toBe(403);
  expect((await employee.post(prefix + 'perform', {token: 'a'.repeat(40),
    password: 'not-a-real-password', confirmation: 'شروع دوباره', backup_confirmed: '1'})).status).toBe(403);
  expect([401, 403]).toContain((await guest.post(prefix + 'preview', {}, {csrf: false})).status);
});

test('an administrator cannot invent a successful reset receipt', async ({api}) => {
  const admin = await api.login('admin');
  expect((await admin.post(prefix + 'status', {job: 'b'.repeat(40)})).status).toBe(417);
});
