import { expect, test } from '../support/fixtures';
import { loadState } from '../support/state';
import { METHOD } from '../support/api';
import { requestId, subject } from '../support/config';

const state = loadState();
const prefix = 'asoud_erp.api.v1.personnel_introduction_letters.';
type Template = { revision: number; clauses: unknown[]; can_manage_template: boolean };

test('introduction templates enforce role and company gates over HTTP', async ({ api }) => {
  const admin = await api.login('admin'); // The fixture administrator has no Employee.
  const employee = await api.login('employee');
  const hr = await api.login('hr');
  const anonymous = await api.anonymous();
  const template = await admin.read<Template>(prefix + 'get_template', { company: state.company });
  expect(template.can_manage_template).toBe(true);
  expect((await employee.post(prefix + 'save_template_draft', {
    company: state.company, revision: template.revision, clauses: JSON.stringify(template.clauses),
  })).status).toBe(403);
  expect((await employee.post(prefix + 'publish_template', {
    company: state.company, revision: template.revision,
  })).status).toBe(403);
  for (const method of ['get_template', 'get_employee_options', 'list_letters']) {
    expect((await hr.get(prefix + method, { company: state.second_company })).status).toBe(403);
  }
  expect([401, 403]).toContain((await anonymous.get(prefix + 'list_letters', { company: state.company })).status);
});

test('a requester starts the existing workflow through an owned request only', async ({ api }) => {
  const employee = await api.login('employee');
  expect((await employee.post('asoud_erp.api.v1.workflow_runtime.start_workflow_instance', {
    definition: state.request_type, subject: 'شروع بدون درخواست مجاز نیست',
  })).status).toBe(403);
  const request = await employee.mutate<{ name: string; workflow_instance: string }>(METHOD.createRequest, {
    company: state.company, workflow_definition: state.request_type,
    subject: subject('بررسی معرفی‌نامه', 'intro-workflow'),
    values: JSON.stringify({ amount: 100, reason: 'بررسی مجوز شروع گردش درخواست' }),
    request_id: requestId('INTRO', 'owned-workflow'),
  });
  expect(request.name).toMatch(/^REQ-\d+$/);
  expect(request.workflow_instance.length).toBeGreaterThan(0);
});
