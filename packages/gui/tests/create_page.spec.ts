import { ElectronApplication, Page, _electron as electron } from 'playwright'
import { test, expect } from '@playwright/test';
import { dialog } from 'electron';

let electronApp: ElectronApplication;
let page: Page;


test.beforeAll(async () => {
  electronApp = await electron.launch({ args: ['./build/electron/main.js'] });
  //electronApp = await electron.launch({ headless: true });
  page = await electronApp.firstWindow();
  
});

test.afterAll(async () => {
  await page.close();
});

//Works
test('Create new Wallet and logout', async () => {

  // Click text=Create a new private key
  await page.locator('text=Create a new private key').click();
  // assert.equal(page.url(), 'file:///Users/jahifaw/Documents/Code/Chia-testnet-playwright/chia-blockchain/chia-blockchain-gui/packages/gui/build/renderer/index.html#/wallet/add');

  // Click button:has-text("Next")
  await Promise.all([
    page.waitForNavigation(/*{ url: 'file:///Users/jahifaw/Documents/Code/Chia-testnet-playwright/chia-blockchain/chia-blockchain-gui/packages/gui/build/renderer/index.html#/dashboard/wallets/1' }*/),
    page.locator('button:has-text("Next")').click()
  ]);

  // Logout of the wallet_new
  await page.locator('[data-testid="ExitToAppIcon"]').click();


  // Click [aria-label="delete"] >> nth=3
  await page.locator('[aria-label="delete"]').nth(3).click();

  // Click button:has-text("Back")
  await page.locator('button:has-text("Back")').click();

  // Click [aria-label="delete"] >> nth=3
  await page.locator('[aria-label="delete"]').nth(3).click();

  // Click the Delete button on confirmation dialog
  await page.locator('button:has-text("Delete"):right-of(:has-text("Back"))').click();


});

 

 




