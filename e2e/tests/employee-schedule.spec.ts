/**
 * `forms.employee_schedule` must not leak a colleague's schedule: it is readable
 * only with an `exclude_self` Employee link in a form the caller fills, or by
 * HR / System managers.
 */

import { expect, test } from '../support/fixtures';
import { ASOUD, METHOD, errorText } from '../support/api';
import { loadState } from '../support/state';

const state = loadState();
const SCHEDULE = `${ASOUD}.forms.employee_schedule`;
const day = { from_date: '2026-10-23', to_date: '2026-10-23' };

interface Me {
  employee: { name: string } | null;
}

test.describe('employee schedule visibility', () => {
  test('a colleague schedule is refused without an eligible form, and across companies', async ({
    api,
  }) => {
    const employee = await api.login('employee');
    const approver = await api.login('approver');
    const colleague = (await approver.read<Me>(METHOD.currentUser)).employee?.name;
    expect(colleague, 'approver must have an Employee record').toBeTruthy();

    const own = await employee.get(SCHEDULE, { company: state.company, ...day });
    expect(own.status, 'own schedule is readable').toBe(200);

    const bare = await employee.get(SCHEDULE, { company: state.company, employee: colleague!, ...day });
    expect(bare.status, 'colleague without a form must be 403').toBe(403);
    expect(errorText(bare)).toContain('دسترسی به برنامه شیفت');

    const missingForm = await employee.get(SCHEDULE, {
      company: state.company, employee: colleague!, form: 'NO-SUCH-FORM', ...day,
    });
    expect(missingForm.status, 'unknown form must not unlock the colleague').not.toBe(200);

    const otherCompany = await employee.get(SCHEDULE, {
      company: state.second_company, employee: colleague!, ...day,
    });
    expect(otherCompany.status, 'another company must be 403').toBe(403);
  });
});
