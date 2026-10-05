/**
 * A logged-in Frappe session over real HTTP.
 *
 * Each session owns its own cookie jar (a Playwright `APIRequestContext`), so a
 * session cookie set by `login` and dropped by `logout` is exercised exactly the
 * way a phone exercises it. Envelope helpers unwrap `{"message": {"ok", "data"}}`.
 */

import type { APIRequestContext, APIResponse } from '@playwright/test';
import { expect } from '@playwright/test';

export interface FrappeResponse<T = unknown> {
  status: number;
  /** Parsed JSON body, or undefined when the body was not JSON. */
  body: Record<string, unknown>;
  /** The `ok`/`data` envelope of an `asoud_erp` method, when present. */
  envelope: { ok: boolean; data: T; meta?: Record<string, unknown>; error?: { code: string; message: string } };
  response: APIResponse;
}

export async function parse<T>(response: APIResponse): Promise<FrappeResponse<T>> {
  const text = await response.text();
  let body: Record<string, unknown> = {};
  try {
    body = text ? (JSON.parse(text) as Record<string, unknown>) : {};
  } catch {
    body = { raw: text };
  }
  const message = body.message;
  const envelope = (message && typeof message === 'object' ? message : body) as FrappeResponse<T>['envelope'];
  return { status: response.status(), body, envelope, response };
}

/** The server's own error text, useful when asserting a refusal reason. */
export function errorText(result: FrappeResponse): string {
  const messages = result.body._server_messages;
  if (typeof messages === 'string') {
    try {
      const parsed = JSON.parse(messages) as { message?: string }[];
      if (parsed[0]?.message) return parsed[0].message as string;
    } catch {
      return messages;
    }
  }
  if (typeof result.body.message === 'string') return result.body.message;
  if (typeof result.body.exception === 'string') return result.body.exception;
  return JSON.stringify(result.body);
}

export class ApiSession {
  private csrfToken: string | null = null;

  private constructor(
    readonly context: APIRequestContext,
    readonly email: string,
  ) {}

  static async login(
    request: APIRequestContext,
    email: string,
    password: string,
  ): Promise<ApiSession> {
    const session = new ApiSession(request, email);
    const response = await request.post('/api/method/login', {
      form: { usr: email, pwd: password },
    });
    const result = await parse(response);
    expect(result.status, `login for ${email}: ${errorText(result)}`).toBe(200);
    expect(result.body.message).toBe('Logged In');
    return session;
  }

  /** A session that has not logged in at all (no cookie in the jar). */
  static anonymous(context: APIRequestContext): ApiSession {
    return new ApiSession(context, 'Guest');
  }

  /**
   * The session's CSRF token, fetched the way Desk does: `/app` embeds it in the
   * boot payload. Frappe skips its CSRF check only while a session has no token
   * at all, so priming it here is what makes the refusal test meaningful.
   */
  async csrf(): Promise<string> {
    if (!this.csrfToken) {
      const page = await this.context.get('/app');
      expect(page.status(), '/app must render for a logged-in session').toBe(200);
      const html = await page.text();
      const match = /frappe\.csrf_token = "([a-f0-9]+)"/.exec(html);
      expect(match, 'the Desk boot payload must carry a csrf token').toBeTruthy();
      this.csrfToken = match![1];
    }
    return this.csrfToken;
  }

  /** A GET call, the read path a phone uses. */
  async get<T = unknown>(method: string, params: Record<string, string> = {}): Promise<FrappeResponse<T>> {
    const query = new URLSearchParams(params).toString();
    const url = `/api/method/${method}${query ? `?${query}` : ''}`;
    return parse<T>(await this.context.get(url));
  }

  /**
   * A POST call. `csrf: false` deliberately omits the token to prove the server
   * refuses an unsafe request that only carries a session cookie.
   */
  async post<T = unknown>(
    method: string,
    form: Record<string, string> = {},
    options: { csrf?: boolean } = {},
  ): Promise<FrappeResponse<T>> {
    const headers: Record<string, string> = {};
    if (options.csrf !== false) headers['X-Frappe-CSRF-Token'] = await this.csrf();
    return parse<T>(
      await this.context.post(`/api/method/${method}`, {
        form,
        headers,
        failOnStatusCode: false,
      }),
    );
  }

  /** GET + envelope unwrap; fails the test when the envelope is not `ok`. */
  async read<T = unknown>(method: string, params: Record<string, string> = {}): Promise<T> {
    const result = await this.get<T>(method, params);
    expect(result.status, `${method}: ${errorText(result)}`).toBe(200);
    expect(result.envelope.ok, `${method} envelope`).toBe(true);
    expect(result.envelope.meta?.api_version).toBe('v1');
    return result.envelope.data as T;
  }

  /** POST + CSRF token + envelope unwrap. */
  async mutate<T = unknown>(
    method: string,
    form: Record<string, string> = {},
  ): Promise<T> {
    const result = await this.post<T>(method, form);
    expect(result.status, `${method}: ${errorText(result)}`).toBe(200);
    expect(result.envelope.ok, `${method} envelope`).toBe(true);
    return result.envelope.data as T;
  }

  async logout(): Promise<FrappeResponse> {
    const response = await this.post('logout');
    this.csrfToken = null;
    return response;
  }

  async cookie(name: string): Promise<string | undefined> {
    const state = await this.context.storageState();
    return state.cookies.find((cookie) => cookie.name === name)?.value;
  }
}

export const ASOUD = 'asoud_erp.api.v1';

export const METHOD = {
  currentUser: `${ASOUD}.auth.current_user`,
  requestOptions: `${ASOUD}.workflow_request.request_options`,
  createRequest: `${ASOUD}.workflow_request.create_request`,
  updateRequest: `${ASOUD}.workflow_request.update_request`,
  cancelRequest: `${ASOUD}.workflow_request.cancel_request`,
  getRequest: `${ASOUD}.workflow_request.get_request`,
  getAttachment: `${ASOUD}.workflow_request.get_attachment`,
  listMyRequests: `${ASOUD}.workflow_request.list_my_requests`,
  listMyTasks: `${ASOUD}.workflow_runtime.list_my_workflow_tasks`,
  completeTask: `${ASOUD}.workflow_runtime.complete_workflow_task`,
  getInstance: `${ASOUD}.workflow_runtime.get_workflow_instance`,
  listWorkflows: `${ASOUD}.workflow.list_workflows`,
  createWorkflowDraft: `${ASOUD}.workflow.create_workflow_draft`,
  addWorkflowStage: `${ASOUD}.workflow.add_workflow_stage`,
  saveStartSettings: `${ASOUD}.workflow.save_start_settings`,
  saveStageSettings: `${ASOUD}.workflow.save_stage_settings`,
  saveStageRoutes: `${ASOUD}.workflow.save_stage_routes`,
  updateRequestTypeInfo: `${ASOUD}.workflow.update_request_type_info`,
  setWorkflowStatus: `${ASOUD}.workflow.set_workflow_status`,
  documentTemplateOptions: `${ASOUD}.document_templates.document_template_options`,
  documentTemplateLinkOptions: `${ASOUD}.document_templates.document_template_link_options`,
  saveDocumentTemplate: `${ASOUD}.document_templates.save_document_template`,
  listDocumentTemplates: `${ASOUD}.document_templates.list_document_templates`,
  getDocumentTemplate: `${ASOUD}.document_templates.get_document_template`,
  clientGet: 'frappe.client.get_value',
  clientGetDoc: 'frappe.client.get',
} as const;
