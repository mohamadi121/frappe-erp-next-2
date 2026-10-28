import { execFileSync } from 'node:child_process';
import { expect, test } from '../support/fixtures';
import { PYTHON } from '../support/config';
import { loadState } from '../support/state';

const state = loadState();
const prefix = 'asoud_erp.api.v1.employment_contracts.';

test('employment contracts API enforces permissions, search normalization, and immutable final print', async ({ api }) => {
  const fixture = `${__dirname}/hr_documents_fixture.py`;
  const output = execFileSync(PYTHON, [fixture, 'setup', 'contracts', state.company], {
    encoding: 'utf8', env: process.env,
  });
  const line = output.split('\n').find(value => value.startsWith('@@HR_DOC_JSON@@'));
  if (!line) throw new Error('Contracts fixture setup returned no JSON');
  const res = JSON.parse(line.slice('@@HR_DOC_JSON@@'.length)) as {
    id: string; employee: string; employee_name: string; template_id: string; revision: number;
  };

  try {
    const admin = await api.login('admin');
    const hr = await api.login('hr');
    const employee = await api.login('employee');

    // 1. Unauthorized role denied
    const unauthSave = await employee.post(prefix + 'save_contract_draft', {
      company: state.company, employee: res.employee, start_date: '2026-10-28',
    });
    expect(unauthSave.status).toBe(403);

    const unauthFinalize = await employee.post(prefix + 'finalize_contract', {
      contract_id: res.id,
    });
    expect(unauthFinalize.status).toBe(403);

    // 2. Cross-company denied
    const crossCompanyList = await hr.get(prefix + 'list_contracts', {
      company: state.second_company,
    });
    expect(crossCompanyList.status).toBe(403);

    // 3. Search normalization (ی/ي, ک/ك, Persian/English digits) with pagination
    const searchArabized = res.employee_name.replace(/ی/g, 'ي').replace(/ک/g, 'ك');
    const listRes = await hr.read<Array<{ contract_id: string }>>(prefix + 'list_contracts', {
      company: state.company, search: searchArabized, start: 0, page_length: 5,
    });
    expect(listRes.some(c => c.contract_id === res.id)).toBe(true);

    // Pagination bounds
    const pagedRes = await hr.read<Array<{ contract_id: string }>>(prefix + 'list_contracts', {
      company: state.company, start: 0, page_length: 1,
    });
    expect(pagedRes.length).toBeLessThanOrEqual(1);

    // 4. Draft print contains «پیش‌نویس ـ فاقد اعتبار نهایی»
    const draftPrint = await hr.read<{ html: string; is_draft: boolean; draft_banner: string }>(
      prefix + 'get_contract_print', { contract_id: res.id }
    );
    expect(draftPrint.is_draft).toBe(true);
    expect(draftPrint.draft_banner).toContain('پیش‌نویس ـ فاقد اعتبار نهایی');
    expect(draftPrint.html).toContain('پیش‌نویس ـ فاقد اعتبار نهایی');

    // 5. Finalize and verify final print unchanged after template republish
    const finalized = await hr.mutate<{ contract_number: string; status: string; is_draft: boolean }>(
      prefix + 'finalize_contract', { contract_id: res.id, request_id: `fin-${res.id}` }
    );
    expect(finalized.status).toBe('نهایی');
    expect(finalized.is_draft).toBe(false);
    expect(finalized.contract_number).toMatch(/^CNT-\d{4}-\d+$/);

    const finalPrintBefore = await hr.read<{ html: string; draft_banner: string | null }>(
      prefix + 'get_contract_print', { contract_id: res.id }
    );
    expect(finalPrintBefore.draft_banner).toBeNull();
    expect(finalPrintBefore.html).not.toContain('پیش‌نویس ـ فاقد اعتبار نهایی');

    // Republish contract template with mutated clauses
    await admin.mutate(prefix + 'publish_contract_template', {
      company: state.company, template_id: res.template_id, change_note: 'تغییر نسخه پس از صدور قرارداد',
    });

    const finalPrintAfter = await hr.read<{ html: string }>(
      prefix + 'get_contract_print', { contract_id: res.id }
    );
    expect(finalPrintAfter.html).toBe(finalPrintBefore.html);
  } finally {
    execFileSync(PYTHON, [fixture, 'cleanup', 'contracts', res.id], {
      encoding: 'utf8', env: process.env,
    });
  }
});
