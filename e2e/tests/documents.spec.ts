/**
 * End-to-end verification of document templates («الگوهای سند») and ERPNext
 * document generation.
 *
 * Exercises the path where an Accounts Manager configures a Journal Entry template
 * using account choices from link options, the workflow automatic stage uses it,
 * and after approval a real Journal Entry is created in ERPNext and verifiable
 * by the accountant over the API.
 */

import { writeFileSync } from 'node:fs';
import { expect, test } from '../support/fixtures';
import type { ApiSession } from '../support/api';
import { METHOD, errorText } from '../support/api';
import { requestId, subject, type UserKey } from '../support/config';
import { loadState } from '../support/state';

const state = loadState();
const LAST_JE_FILE = `${__dirname}/../test-results/last-journal-entry.json`;

interface LinkOption {
  value: string;
  label: string;
}

interface TemplatePayload {
  name: string;
  title: string;
  module: string;
  document_type: string;
  status: string;
  create_as_draft: boolean;
  mapping: Record<string, { source: string; value: string }>;
}

interface CreatedRequest {
  name: string;
  status: string;
  workflow_instance: string;
}

interface Task {
  name: string;
  workflow_instance: string;
  task_title: string;
  status: string;
}

interface Instance {
  name: string;
  status: string;
  current_stage_title: string;
  activities?: { action: string; actor: string; stage_title?: string; reference_doctype?: string; reference_name?: string }[];
}

interface JournalEntryAccountRow {
  account: string;
  debit_in_account_currency: number;
  credit_in_account_currency: number;
}

interface JournalEntryDoc {
  name: string;
  docstatus: number;
  company: string;
  posting_date: string;
  title: string;
  user_remark: string;
  total_debit: number;
  total_credit: number;
  accounts: JournalEntryAccountRow[];
}

test.describe('document templates and ERPNext generation', () => {
  test('an employee is refused access to document templates with 403', async ({ api }) => {
    const employee = await api.login('employee');

    const listAttempt = await employee.get(METHOD.listDocumentTemplates, {
      company: state.company,
    });
    expect(listAttempt.status, 'employee listing document templates must be 403').toBe(403);
    expect(errorText(listAttempt)).toMatch(/Not permitted|PermissionError|Only/i);

    const saveAttempt = await employee.post(METHOD.saveDocumentTemplate, {
      company: state.company,
      template: JSON.stringify({
        title: 'الگوی غیرمجاز کارمند',
        module: 'Finance',
        document_type: 'Journal Entry',
        mapping: {},
      }),
    });
    expect(saveAttempt.status, 'employee saving document template must be 403').toBe(403);
    expect(errorText(saveAttempt)).toMatch(/Not permitted|PermissionError|Only/i);
  });

  test('accounts manager creates a Journal Entry template and workflow generates it in ERPNext', async ({
    api,
  }) => {
    const accountsManager = await api.login('accounts');
    const employee = await api.login('employee');
    const approver = await api.login('approver');
    const accountant = await api.login('accountant');

    const docDefinition = state.doc_request_type;
    const docStage = state.doc_stage;
    expect(docDefinition, 'doc_request_type must be prepared in global setup').toBeTruthy();
    expect(docStage, 'doc_stage must be prepared in global setup').toBeTruthy();

    // 1. Fetch available accounts via document_template_link_options
    const linkOptions = await accountsManager.read<LinkOption[]>(
      METHOD.documentTemplateLinkOptions,
      {
        company: state.company,
        target_type: 'Account',
      },
    );
    expect(linkOptions.length, 'company must have accounts available for templates').toBeGreaterThan(0);

    const values = linkOptions.map((opt) => opt.value);
    const debitAccount =
      values.find((name) => /Cost of Goods Sold|Expense|Cost/i.test(name)) ?? values[0];
    const creditAccount =
      values.find((name) => /Cash|Creditors/i.test(name) && name !== debitAccount) ??
      values.find((name) => name !== debitAccount) ??
      values[0];

    expect(debitAccount, 'debit account should be resolved').toBeTruthy();
    expect(creditAccount, 'credit account should be resolved').toBeTruthy();
    expect(debitAccount).not.toBe(creditAccount);

    // 2. Save a Journal Entry template as Accounts Manager
    const tag = 'doc-je';
    const templateTitle = subject('الگوی سند', tag);
    const templateMapping = {
      posting_date: { source: 'system', value: 'today' },
      title: { source: 'fixed', value: 'هزینه بر اساس درخواست {{RequestNo}}' },
      amount: { source: 'request', value: 'amount' },
      debit_account: { source: 'fixed', value: debitAccount },
      credit_account: { source: 'fixed', value: creditAccount },
    };

    const savedTemplate = await accountsManager.mutate<TemplatePayload>(
      METHOD.saveDocumentTemplate,
      {
        company: state.company,
        template: JSON.stringify({
          title: templateTitle,
          module: 'Finance',
          document_type: 'Journal Entry',
          mapping: templateMapping,
        }),
        source_workflow: docDefinition,
      },
    );

    expect(savedTemplate.name).toBeTruthy();
    expect(savedTemplate.title).toBe(templateTitle);
    expect(savedTemplate.status).toBe('Active');
    expect(savedTemplate.create_as_draft).toBe(true);

    // 3. Configure the System Action stage to use this template
    await accountsManager.mutate(METHOD.saveStageSettings, {
      definition: docDefinition!,
      stage: docStage!,
      config: JSON.stringify({
        title: 'ثبت خودکار سند حسابداری',
        action_type: 'Create Document',
        document_template: savedTemplate.name,
        document_remark: 'ایجاد خودکار بر اساس درخواست {{RequestNo}}',
      }),
    });

    // 4. Employee creates a request for this workflow
    const requestedAmount = 4500;
    const reqTag = 'doc-run';
    const createdReq = await employee.mutate<CreatedRequest>(METHOD.createRequest, {
      company: state.company,
      workflow_definition: docDefinition!,
      subject: subject('درخواست هزینه قطعات', reqTag),
      values: JSON.stringify({ amount: requestedAmount, reason: 'خرید تجهیزات دفتر' }),
      request_id: requestId('DOC', reqTag),
    });

    expect(createdReq.status).toBe('Running');
    expect(createdReq.name).toMatch(/^REQ-\d+$/);

    // 5. Approver approves the workflow task
    const tasks = await approver.read<Task[]>(METHOD.listMyTasks, { status: 'Open' });
    const approvalTask = tasks.find(
      (task) => task.workflow_instance === createdReq.workflow_instance,
    );
    expect(approvalTask, 'approver must have a pending task for the submitted request').toBeTruthy();

    await approver.mutate(METHOD.completeTask, {
      task: approvalTask!.name,
      action: 'Approve',
      comment: 'تأیید خرید',
    });

    // 6. Verify workflow completed and system action created the Journal Entry
    const instance = await employee.read<Instance>(METHOD.getInstance, {
      instance: createdReq.workflow_instance,
    });
    expect(instance.status).toBe('Completed');

    const activities = instance.activities ?? [];
    const sysActionActivity = activities.find(
      (act) => act.action === 'System Action Succeeded',
    );
    expect(sysActionActivity, 'system action must succeed and record reference').toBeTruthy();
    expect(sysActionActivity!.reference_doctype).toBe('Journal Entry');
    const journalEntryName = sysActionActivity!.reference_name as string;
    expect(journalEntryName).toMatch(/^ACC-JV-/);

    // Save for desk.spec.ts
    writeFileSync(
      LAST_JE_FILE,
      JSON.stringify(
        {
          name: journalEntryName,
          title: `هزینه بر اساس درخواست ${createdReq.name}`,
          amount: requestedAmount,
          debit_account: debitAccount,
          credit_account: creditAccount,
        },
        null,
        2,
      ),
    );

    // 7. Read back the Journal Entry as the accountant via frappe.client.get
    const clientResponse = await accountant.get(METHOD.clientGetDoc, {
      doctype: 'Journal Entry',
      name: journalEntryName,
    });
    expect(clientResponse.status, 'accountant reading journal entry via client.get').toBe(200);

    const je = clientResponse.body.message as JournalEntryDoc;
    expect(je, 'Journal Entry document must be returned in message payload').toBeTruthy();
    expect(je.name).toBe(journalEntryName);
    expect(je.docstatus, 'Journal Entry must be draft (docstatus=0)').toBe(0);
    expect(je.company).toBe(state.company);
    expect(je.title).toContain(createdReq.name);
    expect(je.total_debit).toBe(requestedAmount);
    expect(je.total_credit).toBe(requestedAmount);

    const accountsInJe = je.accounts.map((row) => ({
      account: row.account,
      debit: row.debit_in_account_currency,
      credit: row.credit_in_account_currency,
    }));
    expect(accountsInJe).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ account: debitAccount, debit: requestedAmount, credit: 0 }),
        expect.objectContaining({ account: creditAccount, debit: 0, credit: requestedAmount }),
      ]),
    );
  });
});
