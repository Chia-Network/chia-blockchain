import { ElectronApplication, _electron as electron } from 'playwright';
import { test, expect } from '@playwright/test';

let electronApp: ElectronApplication;

test.beforeAll(async () => {
  electronApp = await electron.launch({
    args: ['./build/electron/main.js'],
  });

  electronApp.on('window', async (page) => {
    const filename = page.url()?.split('/').pop();
    console.log(`Window opened: ${filename}`);

    // capture errors
    page.on('pageerror', (error) => {
      console.error(error);
    });
    // capture console messages
    page.on('console', (msg) => {
      console.log(msg.text());
    });
  });
});

test.afterAll(async () => {
  await electronApp.close();
});

test('renders the first page', async () => {
  const page = await electronApp.firstWindow();
  await page.waitForSelector('h1');
  const text = await page.$eval('h1', (el) => el.textContent);
  expect(text).toBe('Select Your Client Mode');
  const title = await page.title();
  expect(title).toBe('Chia Blockchain');
});
