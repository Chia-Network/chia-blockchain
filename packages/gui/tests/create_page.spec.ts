import { ElectronApplication, Page, _electron as electron } from 'playwright'
import { test, expect } from '@playwright/test';
import { LoginPage } from './data_object_model/passphrase_login';
import { isWalletSynced, getWalletBalance } from './utils/wallet';

let electronApp: ElectronApplication;
let page: Page;


test.beforeAll(async () => {
  electronApp = await electron.launch({ args: ['./build/electron/main.js'] });
  //electronApp = await electron.launch({ headless: true });
  page = await electronApp.firstWindow();
  
});

test.beforeEach(async () => {
    // Given I enter correct credentials in Passphrase dialog
    await new LoginPage(page).login('password2022!@')

   // Logout of the wallet_new
   await page.locator('[data-testid="ExitToAppIcon"]').click();

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

  // Grab the Wallet ID of the newest wallet just created
  const deleteWallet = await page.$eval('[data-testid="LayoutDashboard-fingerprint"]', (el) => el.textContent);
  console.log(deleteWallet)

  // Call CLI on new wallet to check status
  await getWalletBalance(deleteWallet)
  
  // Logout of the wallet_new
  await page.locator('[data-testid="ExitToAppIcon"]').click();

  // Click Delete button on Wallet that was just created
  await page.locator(`[data-testid="SelectKeyItem-delete-${deleteWallet}"]`).click()

  // Click back button on Delete dialog
  await page.locator('button:has-text("Back")').click();

  // Click Delete button on Wallet that was just created
  await page.locator(`[data-testid="SelectKeyItem-delete-${deleteWallet}"]`).click()

  // Click the Delete button on confirmation dialog
  await page.locator('button:has-text("Delete"):right-of(:has-text("Back"))').click();

});

 

 




