import {expect, test} from '../support/fixtures';
import {ASOUD} from '../support/api';
import {loadState, sitePrep} from '../support/state';

const state = loadState();
interface Design {
  stages: {name: string; stage_type: string}[];
  transitions: {name: string; from_stage: string; to_stage: string}[];
  insertion_token?: string;
}

test('native draft path preview, role refusal, cancel, stale guard and safe deletion survive reload', async ({api}) => {
  const admin = await api.login('admin');
  const employee = await api.login('employee');
  const prefix = `${ASOUD}.workflow.`;
  const paths = `${ASOUD}.workflow_paths.`;
  const draft = await admin.mutate<{name: string}>(prefix + 'create_workflow_draft', {
    company: state.company, workflow_title: `E2E-ویرایش مسیر ${Date.now()}`,
    module_key: 'HR', target_doctype: 'ASOUD Workflow Request'});
  try {
    let design = await admin.read<Design>(prefix + 'get_workflow_design', {definition: draft.name});
    const start = design.stages.find(row => row.stage_type === 'Start')!.name;
    await admin.mutate(prefix + 'add_workflow_stage', {definition: draft.name, stage_type: 'End', after_stage: start});
    design = await admin.read<Design>(prefix + 'get_workflow_design', {definition: draft.name});
    const end = design.stages.find(row => row.stage_type === 'End')!.name;
    const original = design.transitions[0];
    expect((await employee.post(prefix + 'insert_workflow_stage', {
      definition: draft.name, transition: original.name, stage_type: 'Approval', draft_edit: 1})).status).toBe(403);
    const inserted = await admin.mutate<Design>(prefix + 'insert_workflow_stage', {
      definition: draft.name, transition: original.name, stage_type: 'Approval', draft_edit: 1});
    const added = inserted.stages.find(row => row.stage_type === 'Approval')!.name;
    expect(inserted.insertion_token).toBeTruthy();
    expect((await employee.post(paths + 'discard_inserted_stage', {
      definition: draft.name, stage: added, original: inserted.insertion_token})).status).toBe(403);
    await admin.mutate(paths + 'discard_inserted_stage', {
      definition: draft.name, stage: added, original: inserted.insertion_token});
    design = await admin.read<Design>(prefix + 'get_workflow_design', {definition: draft.name});
    expect(design.stages.map(row => row.name).sort()).toEqual([start, end].sort());
    expect(design.transitions).toHaveLength(1);
    const edge = design.transitions[0].name;
    expect((await employee.get(paths + 'preview_path_removal', {definition: draft.name, transition: edge})).status).toBe(403);
    const review = await admin.read<{stages: string[]; version: number}>(paths + 'preview_path_removal', {
      definition: draft.name, transition: edge});
    expect(review.stages).toEqual([end]);
    expect((await admin.post(paths + 'remove_path', {
      definition: draft.name, transition: edge, version: Number(review.version) - 1})).status).toBe(417);
    await admin.mutate(paths + 'remove_path', {definition: draft.name, transition: edge, version: review.version});
    design = await admin.read<Design>(prefix + 'get_workflow_design', {definition: draft.name});
    expect(design.stages.map(row => row.name)).toEqual([start]);
    expect(design.transitions).toEqual([]);
  } finally {
    sitePrep('drop-definition', {definition: draft.name});
  }
});
