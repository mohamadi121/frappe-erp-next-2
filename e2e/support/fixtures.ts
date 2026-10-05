import { test as base } from '@playwright/test';
import { request } from 'playwright';
import { ApiSession } from './api';
import { USERS, type UserKey } from './config';

export interface ApiFixture {
  /** One logged-in session per user, each with its own cookie jar. */
  login: (key: UserKey) => Promise<ApiSession>;
  /** A session that never sent a login request. */
  anonymous: () => Promise<ApiSession>;
  sessions: () => Promise<Record<UserKey, ApiSession>>;
}

/**
 * Per-test API sessions with independent cookie jars.
 *
 * Playwright's built-in `request` fixture shares one jar for the whole worker,
 * which would hide a broken logout (a second login would keep the first
 * session alive), so every user gets its own `APIRequestContext` here.
 */
export const test = base.extend<{ api: ApiFixture }>({
  api: async ({ baseURL }, use) => {
    const contexts: { dispose: () => Promise<void> }[] = [];
    const cache: Partial<Record<UserKey, ApiSession>> = {};

    async function newContext() {
      const context = await request.newContext({ baseURL });
      contexts.push(context);
      return context;
    }

    const api: ApiFixture = {
      async login(key) {
        if (!cache[key]) {
          const user = USERS[key];
          cache[key] = await ApiSession.login(await newContext(), user.email, user.password);
        }
        return cache[key] as ApiSession;
      },
      async anonymous() {
        return ApiSession.anonymous(await newContext());
      },
      async sessions() {
        const result = {} as Record<UserKey, ApiSession>;
        for (const key of Object.keys(USERS) as UserKey[]) result[key] = await api.login(key);
        return result;
      },
    };
    await use(api);
    for (const context of contexts) await context.dispose();
  },
});

export { expect } from '@playwright/test';
export { ApiSession };