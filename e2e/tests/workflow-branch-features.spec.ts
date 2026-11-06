import { expect, test } from '../support/fixtures';
import { loadState, sitePrep } from '../support/state';
import { errorText } from '../support/api';

const state = loadState();
const prefix = 'asoud_erp.api.v1.workflow.';
const runtimePrefix = 'asoud_erp.api.v1.workflow_runtime.';

test('start_workflow_instance with request_id is idempotent for manual start', async ({ api }) => {
  const admin = await api.login('admin');
  const draft = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
    company: state.company, workflow_title: `E2E شناسه یکتا ${Date.now()}`, module_key: 'HR',
    target_doctype: 'ASOUD Workflow Request'});
  try {
    const payload = {
      definition: draft.name,
      trigger_type: 'Manual',
      initiator_roles: ['System Manager'],
      subject_source: 'General Subject',
      settings: JSON.stringify({
        trigger_type: 'Manual',
        initiator_roles: ['System Manager'],
        allow_manager_restart: false,
        require_manual_reason: true
      })
    };
    await admin.mutate(prefix + 'save_start_settings', payload);
    await admin.mutate(prefix + 'set_workflow_status', {name: draft.name, status: 'Active'});

    const requestId = `reqid${Date.now()}`;
    const res1 = await admin.mutate<{name: string; status: string}>(runtimePrefix + 'start_workflow_instance', {
      definition: draft.name,
      subject: 'تست شناسه یکتا ۱',
      reason: 'علت شروع اول',
      request_id: requestId
    });
    const res2 = await admin.mutate<{name: string; status: string}>(runtimePrefix + 'start_workflow_instance', {
      definition: draft.name,
      subject: 'تست شناسه یکتا ۲',
      reason: 'علت شروع دوم',
      request_id: requestId
    });
    expect(res2.name).toBe(res1.name);

    // Invalid request_id format
    const badRes = await admin.post(runtimePrefix + 'start_workflow_instance', {
      definition: draft.name,
      subject: 'تست شناسه نامعتبر',
      reason: 'علت',
      request_id: 'bad id!'
    });
    expect(badRes.status).toBe(417);
  } finally {
    sitePrep('drop-definition', {definition: draft.name});
  }
});

test('workflow.delete_workflow success for unused workflow, rejection for plain employee and foreign manager', async ({ api }) => {
  const admin = await api.login('admin');
  const employee = await api.login('employee');
  const accounts = await api.login('accounts');

  const draft = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
    company: state.company, workflow_title: `E2E حذف گردش‌کار ${Date.now()}`, module_key: 'HR',
    target_doctype: 'ASOUD Workflow Request'});
  const foreignDraft = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
    company: state.second_company, workflow_title: `E2E حذف دفتر دیگر ${Date.now()}`, module_key: 'HR',
    target_doctype: 'ASOUD Workflow Request'});

  try {
    const missingName = await admin.post(prefix + 'delete_workflow', {});
    expect(missingName.status).toBe(417);
    expect(errorText(missingName)).toContain('شناسهٔ گردش‌کار معتبر نیست');

    // 1. Plain employee cannot delete
    const empDel = await employee.post(prefix + 'delete_workflow', {name: draft.name});
    expect(empDel.status).toBe(403);

    // 2. Foreign manager cannot delete workflow of another company
    const foreignDel = await accounts.post(prefix + 'delete_workflow', {name: foreignDraft.name});
    expect(foreignDel.status).toBe(403);

    // 3. Real HTTP edits create native Version rows. Edit history alone must
    // not prevent an unused workflow's deletion (issue #47).
    await admin.mutate(prefix + 'update_request_type_info', {
      name: draft.name, workflow_title: `E2E ویرایش پیش از حذف ${Date.now()}`});
    const history = {doctype: 'Version', filters: {
      ref_doctype: 'ASOUD Workflow Definition', docname: draft.name}};
    const before = await admin.get('frappe.client.get_count', history);
    expect(before.status).toBe(200);
    expect(Number(before.body.message)).toBeGreaterThan(0);
    const adminDel = await admin.mutate<{name: string; deleted: boolean}>(prefix + 'delete_workflow', {name: draft.name});
    expect(adminDel).toEqual({name: draft.name, deleted: true});
    const after = await admin.get('frappe.client.get_count', history);
    expect(after.status).toBe(200);
    expect(Number(after.body.message)).toBe(0);
  } finally {
    sitePrep('drop-definition', {definition: foreignDraft.name});
  }
});

test('manager restart of closed form entry submitted by employee', async ({ api }) => {
  const admin = await api.login('admin');
  const employee = await api.login('employee');

  const formRes = sitePrep<{name: string; revision: string; definition: string}>('form-workflow', {
    company: state.company, title: 'E2E فرم شروع مجدد مدیر'
  });

  try {
    const startPayload = {
      definition: formRes.definition,
      trigger_type: 'Document Event',
      initiator_roles: ['Employee'],
      subject_source: 'Referenced Document',
      settings: JSON.stringify({
        trigger_type: 'Document Event',
        initiator_roles: ['Employee'],
        allow_manager_restart: true,
        require_manual_reason: false,
        submission_source: {form: formRes.name, revision: formRes.revision}
      })
    };
    await admin.mutate(prefix + 'save_start_settings', startPayload);
    await admin.mutate(prefix + 'set_workflow_status', {name: formRes.definition, status: 'Active'});

    const entry = await employee.mutate<{reference_name: string; workflow_instance: string}>(
      'asoud_erp.api.v1.forms.submit_form', {
        name: formRes.name,
        revision_name: formRes.revision,
        subject: 'درخواست کارمند برای شروع مجدد',
        values: JSON.stringify({note: 'اطلاعات اولیه'}),
        request_key: `restart-${Date.now()}`
      }
    );
    const instanceName = entry.workflow_instance;

    const tasks = await employee.read<Array<{name: string; workflow_instance: string}>>(
      runtimePrefix + 'list_my_workflow_tasks', {}
    );
    const task = tasks.find(t => t.workflow_instance === instanceName);
    if (task) {
      await employee.mutate(runtimePrefix + 'complete_workflow_task', {
        task: task.name,
        action: 'Complete',
        response: JSON.stringify({})
      });
    }

    // Plain employee cannot restart
    const empRestart = await employee.post(runtimePrefix + 'start_workflow_instance', {
      definition: formRes.definition,
      subject: 'شروع مجدد توسط کارمند',
      reference_doctype: 'ASOUD Form Entry',
      reference_name: entry.reference_name,
      reason: 'تست',
      restart: 1
    });
    expect(empRestart.status).toBe(417);

    // Admin (manager) can restart
    const restartRes = await admin.mutate<{name: string; status: string}>(
      runtimePrefix + 'start_workflow_instance', {
        definition: formRes.definition,
        subject: 'شروع مجدد توسط مدیر',
        reference_doctype: 'ASOUD Form Entry',
        reference_name: entry.reference_name,
        reason: 'بازبینی مدیریتی',
        restart: 1
      }
    );
    expect(restartRes.name).toBeTruthy();
    expect(restartRes.name).not.toBe(instanceName);
  } finally {
    sitePrep('drop-definition', {definition: formRes.definition});
  }
});
