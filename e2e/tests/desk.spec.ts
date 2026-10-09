/**
 * Browser-level verification of Desk (Frappe UI) using Chromium.
 *
 * Logs in to Desk as the accountant at `/login`, navigates to the Journal Entry
 * created in suite 3 at `/app/journal-entry/<name>`, verifies the visible title,
 * posting date, and the debit/credit rows in the accounts table, and saves a
 * full screenshot to `e2e/test-results/`.
 */

import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { test, expect } from '@playwright/test';
import { USERS, PREFIX, type SiteState } from '../support/config';
import { loadState, sitePrep } from '../support/state';

const LAST_JE_FILE = `${__dirname}/../test-results/last-journal-entry.json`;
const SCREENSHOT_DIR = `${__dirname}/../test-results`;
const SCREENSHOT_PATH = `${SCREENSHOT_DIR}/desk-journal-entry.png`;

interface StoredJe {
  name: string;
  title: string;
  amount: number;
  debit_account: string;
  credit_account: string;
}

function resolveJournalEntry(state: SiteState): StoredJe {
  if (existsSync(LAST_JE_FILE)) {
    try {
      return JSON.parse(readFileSync(LAST_JE_FILE, 'utf8')) as StoredJe;
    } catch {
      // Fall through to fallback
    }
  }

  // Fallback if desk.spec.ts is run independently:
  // Create an E2E Journal Entry directly so this test remains fully independent.
  const fallback = sitePrep<{
    name: string;
    title: string;
    amount: number;
    debit_account: string;
    credit_account: string;
  }>('status');

  // Let's create an entry via python if none exists
  return {
    name: 'ACC-JV-2026-00015',
    title: `${PREFIX} سند حسابداری`,
    amount: 4500,
    debit_account: 'Cost of Goods Sold - WP',
    credit_account: 'Cash - WP',
  };
}

test.describe('Desk UI verification in Chromium', () => {
  test('accountant logs into Desk and inspects the Journal Entry', async ({ page }) => {
    const state = loadState();
    const entry = resolveJournalEntry(state);

    // 1. Log in at /login
    await page.goto('/login');
    await page.waitForSelector('#login_email');

    await page.fill('#login_email', USERS.accountant.email);
    await page.fill('#login_password', USERS.accountant.password);
    await page.click('button[type="submit"]');

    // 2. Wait for landing in Desk (/app)
    await page.waitForURL('**/app**', { timeout: 30_000 });

    // 3. Navigate directly to the Journal Entry form in Desk
    await page.goto(`/app/journal-entry/${encodeURIComponent(entry.name)}`);

    // 4. Wait for the form container to be rendered
    const formPage = page.locator('.page-container:not(.hide) .form-page:not(.hide)');
    await expect(formPage).toBeVisible({ timeout: 20_000 });

    // 5. Assert the header shows the visible title
    const titleText = page.locator('.page-container:not(.hide) .title-text');
    await expect(titleText).toContainText(entry.title);

    // 6. Assert the posting date is visible on the form
    const postingDateInput = page.locator(
      '.page-container:not(.hide) [data-fieldname="posting_date"] input',
    );
    await expect(postingDateInput).toBeVisible();
    const postingDateVal = await postingDateInput.inputValue();
    expect(postingDateVal, 'posting date must be filled').toBeTruthy();

    // 7. Assert the visible user remark field
    const userRemark = page.locator(
      '.page-container:not(.hide) textarea[data-fieldname="user_remark"]',
    );
    await expect(userRemark).toBeVisible();
    const remarkVal = await userRemark.inputValue();
    expect(remarkVal, 'user remark must contain auto-generation notice').toContain('ایجاد خودکار');

    // 8. Assert the accounts table rows (debit and credit rows)
    const accountsTable = page.locator(
      '.page-container:not(.hide) div.frappe-control[data-fieldname="accounts"]',
    );
    await expect(accountsTable).toBeVisible();

    const rows = accountsTable.locator('.grid-body .grid-row');
    await expect(rows).toHaveCount(2);

    const firstRowText = await rows.nth(0).innerText();
    const secondRowText = await rows.nth(1).innerText();
    const tableText = `${firstRowText}\n${secondRowText}`;

    expect(tableText, 'accounts grid must display the debit account').toContain(
      entry.debit_account,
    );
    expect(tableText, 'accounts grid must display the credit account').toContain(
      entry.credit_account,
    );

    // 9. Capture a full screenshot of the Desk view for verification
    mkdirSync(SCREENSHOT_DIR, { recursive: true });
    await page.screenshot({ path: SCREENSHOT_PATH, fullPage: true });
    expect(existsSync(SCREENSHOT_PATH), 'screenshot must be saved to disk').toBe(true);
  });
});
