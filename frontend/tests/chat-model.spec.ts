import { test, expect } from '@playwright/test';

test('startup race, specialist labels, saved choice, request model, and visible errors', async ({ page }) => {
  let infoCalls = 0;
  let failSave = false;
  let failChat = false;
  let requestedModel = '';
  let savedModel = '';
  await page.addInitScript(() => {
    sessionStorage.setItem('orion-greeted', '1');
    localStorage.setItem('orion-voice-replies', 'off');
  });
  await page.route('**/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/v1/info') {
      if (++infoCalls <= 2) return route.fulfill({ status: 503, json: {} });
      return route.fulfill({ json: { model: 'qwen3.5:4b', engine: 'ollama', agent: null } });
    }
    if (path === '/v1/models') return route.fulfill({ json: { data: [
      { id: 'moondream:latest', purpose: 'vision' },
      { id: 'qwen3.5:4b', purpose: 'chat' }, { id: 'qwen3.5:2b', purpose: 'chat' },
    ] } });
    if (path === '/v1/config') {
      if (failSave) return route.fulfill({ status: 500, json: {} });
      savedModel = route.request().postDataJSON().model;
      return route.fulfill({ json: { status: 'ok' } });
    }
    if (path === '/v1/chat/completions') {
      requestedModel = route.request().postDataJSON().model;
      if (failChat) return route.fulfill({ status: 502, json: { detail: 'The selected model could not produce a valid reply. Please retry or select another chat model.' } });
      return route.fulfill({ contentType: 'text/event-stream', body: 'data: {"choices":[{"delta":{"content":"Hello! What can I help with?"}}]}\n\ndata: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n' });
    }
    if (path === '/v1/speech/health') return route.fulfill({ json: { available: false } });
    if (path === '/v1/hud/vitals') return route.fulfill({ json: { vitals: [], draw_watts: null } });
    if (path.includes('savings')) return route.fulfill({ json: { per_provider: [], total_calls: 0, total_tokens: 0 } });
    if (path === '/v1/config/tools') return route.fulfill({ json: { tools: [], enabled_count: 0 } });
    return route.fulfill({ status: 503, json: {} });
  });
  await page.route('**/health', (route) => route.fulfill({ json: { status: 'ok' } }));
  await page.goto('/');
  const picker = page.getByLabel('Chat model', { exact: true });
  await expect(picker).toHaveValue('qwen3.5:4b', { timeout: 15000 });
  await expect(picker.locator('option[value="moondream:latest"]')).toBeDisabled();
  await picker.selectOption('qwen3.5:2b');
  await expect.poll(() => savedModel).toBe('qwen3.5:2b');
  await page.reload();
  await expect(picker).toHaveValue('qwen3.5:2b');
  failSave = true;
  await picker.selectOption('qwen3.5:4b');
  await expect(page.getByRole('alert')).toContainText('Could not save');
  await expect(picker).toHaveValue('qwen3.5:2b');
  const input = page.getByPlaceholder('Speak, or set a directive…');
  await input.fill('Hey Orion');
  await page.getByRole('button', { name: 'Commit', exact: true }).click();
  await expect.poll(() => requestedModel).toBe('qwen3.5:2b');
  await expect(page.getByText('Hello! What can I help with?', { exact: true })).toBeVisible();
  failChat = true;
  await input.fill('Hello');
  await page.getByRole('button', { name: 'Commit', exact: true }).click();
  await expect(page.getByRole('alert').filter({ hasText: 'valid reply' })).toBeVisible();
  await page.screenshot({ path: 'test-results/chat-model-picker.png', fullPage: true });
});
