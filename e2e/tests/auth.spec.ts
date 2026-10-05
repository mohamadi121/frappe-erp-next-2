/**
 * The real HTTP identity path: `/api/method/login`, session cookies, CSRF and
 * the `asoud_erp` envelope. The pytest integration tests call API functions
 * in-process, so nothing before this file proved that a phone could log in.
 */

import { expect, test } from '../support/fixtures';
import type { ApiSession } from '../support/api';
import { METHOD, errorText } from '../support/api';
import { USERS, requestId, subject, type UserKey } from '../support/config';
import { loadState } from '../support/state';

const state = loadState();

async function identityOf(api: { login: (key: UserKey) => Promise<ApiSession> }, key: UserKey) {
  return (await api.login(key)).read<{
    user_id: string;
    full_name: string;
    roles: string[];
    employee: { name: string; company: string; employee_name: string } | null;
  }>(METHOD.currentUser);
}

test.describe('authentication over HTTP', () => {
  test('a correct password sets a session cookie and identifies the user with their roles', async ({ api }) => {
    const session = await api.login('employee');
    const sid = await session.cookie('sid');
    expect(sid, 'login must set the sid cookie').toBeTruthy();
    expect(sid!.length).toBeGreaterThanOrEqual(32);

    const loggedUser = await session.get('frappe.auth.get_logged_user');
    expect(loggedUser.status).toBe(200);
    expect(loggedUser.body.message).toBe('asoud.employee@example.com');

    const identity = await identityOf(api, 'employee');
    expect(identity.user_id).toBe('asoud.employee@example.com');
    expect(identity.roles).toContain('Employee');
    expect(identity.roles).not.toContain('System Manager');
    expect(identity.roles).not.toContain('Accounts Manager');
    expect(identity.employee?.company).toBe(state.company);
    expect(identity.employee?.name).toBeTruthy();
  });

  test('every prepared login reports exactly the roles global setup gave it', async ({ api }) => {
    const admin = await identityOf(api, 'admin');
    expect(admin.roles).toContain('System Manager');

    const accounts = await identityOf(api, 'accounts');
    expect(accounts.roles).toContain('Accounts Manager');
    expect(accounts.roles).not.toContain('System Manager');

    const accountant = await identityOf(api, 'accountant');
    expect(accountant.roles).toContain('Accounts User');
    expect(accountant.roles).not.toContain('Accounts Manager');

    const approver = await identityOf(api, 'approver');
    expect(approver.roles).toContain('Leave Approver');
  });

  test('a wrong password is refused with 401 and leaves no session behind', async ({ api }) => {
    const anonymous = await api.anonymous();
    const result = await anonymous.post('login', { usr: USERS.employee.email, pwd: 'not-the-password' }, { csrf: false });
    expect(result.status).toBe(401);
    expect(result.body.message).not.toBe('Logged In');
    expect(errorText(result)).toContain('Invalid login credentials');

    expect(await anonymous.cookie('sid'), 'a failed login must not set sid').toBeUndefined();
    const after = await anonymous.get('frappe.auth.get_logged_user');
    expect(after.status).toBeGreaterThanOrEqual(401);
  });

  test('logout invalidates the session cookie', async ({ api }) => {
    const session = await api.login('approver');
    expect((await session.get('frappe.auth.get_logged_user')).body.message).toBe('asoud.approver@example.com');
    const sid = await session.cookie('sid');
    expect(sid, 'logout must be reachable only with a session').toBeTruthy();

    const out = await session.logout();
    // The message is Frappe's own ("Logged Out" on an installed app, "No App"
    // here); what the suite asserts is that the session stops working.
    expect(out.status).toBe(200);

    const after = await session.get('frappe.auth.get_logged_user');
    expect(after.status).toBeGreaterThanOrEqual(401);
    expect(after.body.message).not.toBe('asoud.approver@example.com');
    if (await session.cookie('sid')) expect(await session.cookie('sid')).not.toBe(sid);
  });

  test('a mutating call without the CSRF token is refused and writes nothing', async ({ api }) => {
    const employee = await api.login('employee');
    const id = requestId('AUTH', 'csrf');
    const form = {
      company: state.company,
      workflow_definition: state.request_type as string,
      subject: subject('درخواست بدون توکن', 'auth'),
      request_id: id,
      values: JSON.stringify({ amount: 100, reason: 'csrf' }),
    };

    // Prime the session's CSRF token the way Desk does; from now on Frappe
    // demands it on every unsafe request.
    expect(await employee.csrf()).toMatch(/^[a-f0-9]{40,}$/);

    const refused = await employee.post(METHOD.createRequest, form, { csrf: false });
    expect(refused.status).toBe(400);
    expect(errorText(refused)).toContain('Invalid Request');

    // The refused call must not have consumed the idempotency key: the same
    // request_id with a token creates the request instead of conflicting.
    const created = await employee.mutate<{ request_id: string; name: string }>(
      METHOD.createRequest,
      form,
    );
    expect(created.request_id).toBe(id);
    expect(created.name).toMatch(/^REQ-\d+$/);
  });

  test('a mutating call without any session is refused', async ({ api }) => {
    const anonymous = await api.anonymous();
    const result = await anonymous.post(
      METHOD.createRequest,
      {
        company: state.company,
        workflow_definition: state.request_type as string,
        subject: subject('درخواست بی‌نشست', 'auth'),
        request_id: requestId('AUTH', 'guest'),
        values: JSON.stringify({ amount: 100, reason: 'guest' }),
      },
      { csrf: false },
    );
    expect(result.status).toBeGreaterThanOrEqual(401);
    expect(result.body.message).not.toBe('Logged In');
  });

  test('an unknown method is reported as 417, not as an outage', async ({ api }) => {
    const session = await api.login('employee');
    const result = await session.get('asoud_erp.api.v1.workflow_request.no_such_method');
    expect(result.status).toBe(417);
    expect(errorText(result)).toContain('Failed to get method');
  });
});