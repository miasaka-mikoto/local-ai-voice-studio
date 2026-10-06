import { expect, test } from '@playwright/test';

test.beforeEach(async ({page}) => {
  await page.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.hostname !== '127.0.0.1' || url.port !== '4317') {
      throw new Error(`Unexpected external request blocked: ${url.origin}`);
    }
    await route.continue();
  });
  await page.goto('/e2e/companion.html');
});

test('real browser renders all five companion states', async ({page}) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  for (const [state,label] of [['idle','待机'],['listening','正在听'],['thinking','整理回应'],['speaking','正在说'],['error','需要重试']]) {
    await page.getByRole('button',{name:`Fixture ${state}`,exact:true}).click();
    await expect(page.getByLabel('数字伙伴陪聊舞台')).toHaveAttribute('data-companion-state',state);
    await expect(page.locator('.companion-state')).toHaveText(label);
    await expect(page.locator('.studio-avatar').first()).toBeVisible();
  }
  expect(errors).toEqual([]);
});

test('suggestion click reaches the composer callback', async ({page}) => {
  await page.getByRole('button',{name:'おすすめは何ですか？',exact:true}).click();
  await expect(page.getByLabel('Selected suggestion')).toHaveText('おすすめは何ですか？');
});

test('VRM permission gate protects file selection and unavailable connector stays disabled', async ({page}) => {
  await page.getByText('形象 Provider',{exact:true}).click();
  await page.getByRole('button',{name:/VRM 连接位/}).click();
  await expect(page.getByLabel('选择本机 .vrm')).toBeDisabled();
  await expect(page.getByRole('button',{name:/Live2D 外部连接位/})).toBeDisabled();
  await page.getByRole('checkbox',{name:'我有使用、扮演、再分发所需授权'}).check();
  await expect(page.getByLabel('选择本机 .vrm')).toBeEnabled();
  await page.getByRole('checkbox',{name:'我有使用、扮演、再分发所需授权'}).uncheck();
  await expect(page.getByLabel('选择本机 .vrm')).toBeDisabled();
});
