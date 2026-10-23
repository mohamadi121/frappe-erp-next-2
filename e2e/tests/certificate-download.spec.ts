import { execFileSync } from 'node:child_process';
import { request } from 'playwright';
import { ApiSession, ASOUD } from '../support/api';
import { PYTHON } from '../support/config';
import { expect, test } from '../support/fixtures';

const PASSWORD = 'E2e-Pw-Cert-2026';
const FOREIGN_EMPLOYEE = 'e2e.cert.foreign@example.com';
const FOREIGN_HR = 'e2e.cert.foreignhr@example.com';
const NO_EMPLOYEE = 'e2e.cert.noemployee@example.com';

function fixture<T>(action: string, options = {}): T {
  const output = execFileSync(PYTHON, [`${__dirname}/certificate_fixture.py`, action, JSON.stringify(options)], {
    encoding: 'utf8', env: process.env,
  });
  const line = output.split('\n').find(value => value.startsWith('@@CERT_JSON@@'));
  if (!line) throw new Error(`Missing certificate fixture output for ${action}`);
  return JSON.parse(line.slice('@@CERT_JSON@@'.length));
}

type Prepared = { form: string; revision: string; definition: string; head: string; previous_head: string | null; company: string };
type Certificate = { number: string; filename: string; content_type: string; content_base64: string };
const forms = `${ASOUD}.forms.`;
const requests = `${ASOUD}.workflow_request.`;
const runtime = `${ASOUD}.workflow_runtime.`;
let prepared: Prepared;
let requestName: string;
let fileName: string;

test.beforeAll(() => { prepared = fixture<Prepared>('prepare'); });
test.afterAll(() => {
  if (prepared) fixture('cleanup', {
    form: prepared.form, definition: prepared.definition, head: prepared.head,
    previous_head: prepared.previous_head, company: prepared.company,
  });
});

test('approval issues the certificate and each role sees the right thing', async ({ api }) => {
  const employee = await api.login('employee');
  const approver = await api.login('approver');
  const entry = await employee.mutate<{ reference_name: string }>(forms + 'submit_form', {
    name: prepared.form, revision_name: prepared.revision, subject: 'درخواست گواهی اشتغال',
    values: JSON.stringify({ recipient: 'بانک ملی', purpose: 'bank' }), request_key: `cert-${Date.now()}`,
  });
  requestName = entry.reference_name;
  const created = await employee.read<{ workflow_instance: string }>(requests + 'get_request', { name: requestName });
  const tasks = await approver.read<Array<{ name: string; workflow_instance: string }>>(runtime + 'list_my_workflow_tasks', {});
  const task = tasks.find(item => item.workflow_instance === created.workflow_instance);
  expect(task).toBeTruthy();
  await approver.mutate(runtime + 'complete_workflow_task', { task: task!.name, action: 'Approve' });
  const detail = await employee.read<{ native: { status: string; doctype: string; name: string }; certificate: { number: string } | null }>(
    requests + 'get_request', { name: requestName });
  expect(detail.native.status).toBe('Created');
  expect(detail.native.doctype).toBe('File');
  fileName = detail.native.name;
  expect(detail.certificate?.number).toMatch(/^CERT-\d{4}-\d{5}$/);
  // The approver reads the request but never the certificate.
  const approverView = await approver.read<{ certificate: unknown }>(requests + 'get_request', { name: requestName });
  expect(approverView.certificate).toBeNull();
});

for (const user of ['employee', 'hr', 'admin'] as const) {
  test(`${user} downloads the certificate PDF`, async ({ api }) => {
    const session = await api.login(user);
    const data = await session.read<Certificate>(requests + 'get_certificate', { name: requestName });
    expect(data.content_type).toBe('application/pdf');
    expect(data.number).toMatch(/^CERT-\d{4}-\d{5}$/);
    expect(data.filename).toBe(`${data.number}.pdf`);
    expect(Buffer.from(data.content_base64, 'base64').subarray(0, 5).toString()).toBe('%PDF-');
  });
}

for (const user of ['outsider', 'approver', 'accountant'] as const) {
  test(`${user} (another person of the same company) is refused with a Persian error`, async ({ api }) => {
    const session = await api.login(user);
    const result = await session.get(requests + 'get_certificate', { name: requestName });
    expect(result.status).toBe(403);
    expect(JSON.stringify(result.body)).toContain('اجازهٔ دریافت این گواهی');
    const attachment = await session.get(requests + 'get_attachment', { name: fileName });
    expect(attachment.status).toBe(403);
  });
}

test('other company users and a user without Employee are refused', async ({ baseURL }) => {
  for (const email of [FOREIGN_EMPLOYEE, FOREIGN_HR, NO_EMPLOYEE]) {
    const context = await request.newContext({ baseURL });
    try {
      const session = await ApiSession.login(context, email, PASSWORD);
      const result = await session.get(requests + 'get_certificate', { name: requestName });
      expect(result.status, email).toBe(403);
      const attachment = await session.get(requests + 'get_attachment', { name: fileName });
      expect(attachment.status, email).toBe(403);
    } finally {
      await context.dispose();
    }
  }
});

test('anonymous session is refused and a request without certificate says so', async ({ api }) => {
  const anonymous = await api.anonymous();
  expect((await anonymous.get(requests + 'get_certificate', { name: requestName })).status).toBe(403);
  const employee = await api.login('employee');
  const missing = await employee.get(requests + 'get_certificate', { name: `${requestName}-none` });
  expect(missing.status).toBeGreaterThanOrEqual(400);
});
