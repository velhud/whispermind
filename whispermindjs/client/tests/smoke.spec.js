const { test, expect } = require('@playwright/test');

test('WhisperMind UI stays connected and handles common states', async ({ page, context }) => {
  const consoleFailures = [];

  page.on('console', (message) => {
    if (['error', 'warning'].includes(message.type())) {
      consoleFailures.push(`${message.type()}: ${message.text()}`);
    }
  });
  page.on('pageerror', (error) => {
    consoleFailures.push(`pageerror: ${error.message}`);
  });

  await context.grantPermissions(['microphone']);
  await page.goto('/', { waitUntil: 'networkidle' });
  await page.waitForTimeout(15000);

  await expect(page.locator('body')).not.toContainText('Disconnected from backend');
  await expect(page.locator('body')).toContainText('Ready');
  await page.screenshot({ path: '/tmp/whispermind-ui-ready.png', fullPage: false });

  await page.getByRole('button', { name: 'Generate Suggestions' }).click();
  await expect(page.locator('body')).toContainText('No recent conversation to generate suggestions from.', { timeout: 8000 });

  await page.getByLabel('Mode').selectOption({ label: 'OpenAI Realtime Translation' });
  await page.getByRole('button', { name: 'Start Recording' }).click();
  await expect(page.locator('body')).toContainText('OPENAI_API_KEY is required for OpenAI realtime translation', { timeout: 10000 });
  await expect(page.getByRole('button', { name: 'Start Recording' })).toBeVisible();
  await page.screenshot({ path: '/tmp/whispermind-ui-realtime-error.png', fullPage: false });

  await page.getByLabel('Mode').selectOption({ label: 'Legacy Groq Whisper + Groq Translate' });
  await page.getByRole('checkbox', { name: 'Settings' }).click();
  await expect(page.locator('body')).not.toContainText('Backend & Languages');
  await page.getByRole('checkbox', { name: 'Settings' }).click();
  await expect(page.locator('body')).toContainText('Backend & Languages');

  expect(consoleFailures.filter((line) => line.startsWith('error') || line.startsWith('pageerror'))).toEqual([]);
});
