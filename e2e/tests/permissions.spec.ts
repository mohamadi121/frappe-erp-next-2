/**
 * End-to-end verification of cross-user and cross-company permissions.
 *
 * Verifies that:
 * 1. An outsider employee in the same company cannot read someone else's request,
 *    its attachments, or its workflow instance.
 * 2. The direct manager assigned to review the request can read the request,
 *    its workflow instance, and its attachments.
 * 3. An operation scoped to a company the user has no access to is refused by
 *    `require_company` with 403 "Company access denied".
 */

import { expect, test } from '../support/fixtures';
import type { ApiSession } from '../support/api';
import { METHOD, errorText } from '../support/api';
import { requestId, subject } from '../support/config';
import { loadState, sitePrep } from '../support/state';

const state = loadState();

interface CreatedRequest {
  name: string;
  status: string;
  workflow_instance: string;
}

interface AttachmentInfo {
  name: string;
  file_url: string;
}

test.describe('cross-user and cross-company permissions', () => {
  test("another employee cannot read someone else's request, its attachments or its instance", async ({
    api,
  }) => {
    const employee = await api.login('employee');
    const outsider = await api.login('outsider');
    const tag = 'cross-user';

    // 1. Employee creates a request
    const created = await employee.mutate<CreatedRequest>(METHOD.createRequest, {
      company: state.company,
      workflow_definition: state.request_type,
      subject: subject('درخواست محرمانه', tag),
      values: JSON.stringify({ amount: 2000, reason: `e2e-${tag}` }),
      request_id: requestId('PERM', tag),
    });
    expect(created.name).toMatch(/^REQ-\d+$/);

    // 2. Attach a private document to the request
    const attachment = sitePrep<AttachmentInfo>('attach', {
      request: created.name,
      filename: `doc-${tag}.txt`,
      content: `confidential content for ${tag}`,
    });
    expect(attachment.name).toBeTruthy();

    // 3. Outsider employee attempts to read the request
    const requestRead = await outsider.get(METHOD.getRequest, { name: created.name });
    expect(requestRead.status, 'outsider reading request must be 403').toBe(403);
    expect(errorText(requestRead)).toMatch(/Not permitted to view this request|PermissionError/i);

    // 4. Outsider employee attempts to read the workflow instance
    const instanceRead = await outsider.get(METHOD.getInstance, {
      instance: created.workflow_instance,
    });
    expect(instanceRead.status, 'outsider reading workflow instance must be 403').toBe(403);
    expect(errorText(instanceRead)).toMatch(/Not permitted to (access this request workflow|view this workflow instance)|PermissionError/i);

    // 5. Outsider employee attempts to download the private attachment
    const attachmentRead = await outsider.get(METHOD.getAttachment, { name: attachment.name });
    expect(attachmentRead.status, 'outsider reading attachment must be 403').toBe(403);
    expect(errorText(attachmentRead)).toMatch(/Not permitted to view this request|PermissionError/i);
  });

  test('the direct manager can read the request, its instance and its attachments', async ({
    api,
  }) => {
    const employee = await api.login('employee');
    const approver = await api.login('approver');
    const tag = 'manager-read';

    // 1. Employee creates a request
    const created = await employee.mutate<CreatedRequest>(METHOD.createRequest, {
      company: state.company,
      workflow_definition: state.request_type,
      subject: subject('درخواست بررسی مدیر', tag),
      values: JSON.stringify({ amount: 1800, reason: `e2e-${tag}` }),
      request_id: requestId('PERM', tag),
    });

    // 2. Attach a private file
    const attachmentText = `invoice data for ${tag}`;
    const attachment = sitePrep<AttachmentInfo>('attach', {
      request: created.name,
      filename: `invoice-${tag}.txt`,
      content: attachmentText,
    });
    expect(attachment.name).toBeTruthy();

    // 3. Direct manager reads the request they act on
    const requestData = await approver.read<{ name: string; owner: string }>(METHOD.getRequest, {
      name: created.name,
    });
    expect(requestData.name).toBe(created.name);
    expect(requestData.owner).toBe('asoud.employee@example.com');

    // 4. Direct manager reads the workflow instance
    const instanceData = await approver.read<{ name: string; status: string }>(METHOD.getInstance, {
      instance: created.workflow_instance,
    });
    expect(instanceData.name).toBe(created.workflow_instance);
    expect(instanceData.status).toBe('Running');

    // 5. Direct manager downloads the private attachment
    const attachmentData = await approver.read<{ filename: string; content_base64: string }>(
      METHOD.getAttachment,
      {
        name: attachment.name,
      },
    );
    expect(attachmentData.filename).toContain(`invoice-${tag}.txt`);
    const decoded = Buffer.from(attachmentData.content_base64, 'base64').toString('utf8');
    expect(decoded).toBe(attachmentText);
  });

  test('require_company refuses a company the user has no access to', async ({ api }) => {
    const employee = await api.login('employee');
    const accounts = await api.login('accounts');
    const secondCompany = state.second_company;
    expect(secondCompany, 'second company must be present').toBeTruthy();

    // 1. Employee calling request_options for the inaccessible company
    const employeeOptions = await employee.get(METHOD.requestOptions, { company: secondCompany });
    expect(employeeOptions.status, 'employee querying options for foreign company must be 403').toBe(403);
    expect(errorText(employeeOptions)).toContain('Company access denied');

    // 2. Employee calling create_request for the inaccessible company
    const employeeCreate = await employee.post(METHOD.createRequest, {
      company: secondCompany,
      workflow_definition: state.request_type,
      subject: subject('درخواست شرکت دوم', 'foreign-comp'),
      values: JSON.stringify({ amount: 500, reason: 'غیرمجاز' }),
      request_id: requestId('PERM', 'foreign-comp'),
    });
    expect(employeeCreate.status, 'employee creating request in foreign company must be 403').toBe(403);
    expect(errorText(employeeCreate)).toContain('Company access denied');

    // 3. Accounts Manager restricted to first company querying document templates in second company
    const accountsTemplates = await accounts.get(METHOD.listDocumentTemplates, {
      company: secondCompany,
    });
    expect(accountsTemplates.status, 'accounts manager listing templates in foreign company must be 403').toBe(403);
    expect(errorText(accountsTemplates)).toContain('Company access denied');

    // 4. Accounts Manager querying template options in second company
    const accountsOptions = await accounts.get(METHOD.documentTemplateOptions, {
      company: secondCompany,
    });
    expect(accountsOptions.status, 'accounts manager querying options in foreign company must be 403').toBe(403);
    expect(errorText(accountsOptions)).toContain('Company access denied');
  });
});
