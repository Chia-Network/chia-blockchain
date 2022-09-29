import { ElectronApplication, Page, _electron as electron } from 'playwright'
import { test, expect } from '@playwright/test';
import { dialog } from 'electron';
import { LoginPage } from '../data_object_model/passphrase_login';
import { isWalletSynced, getWalletBalance } from '../utils/wallet';

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


//Failures due to Elements changing attributes
test('Confirm Error Dialog when wrong data is entered on Send Page for 1922132445 ID', async () => {
  
  let funded_wallet = '1922132445'

   // Given I enter correct credentials in Passphrase dialog
   await new LoginPage(page).login('password2022!@')

    // And I navigate to a wallet with funds
  await page.locator('[data-testid="LayoutDashboard-log-out"]').click();
  await page.locator(`text=${funded_wallet}`).click();

  // Begin: Wait for Wallet to Sync
  while (!isWalletSynced(funded_wallet)) {
    console.log('Waiting for wallet to sync...');
    await page.waitForTimeout(1000);
  }

  console.log(`Wallet ${funded_wallet} is now fully synced`);

  const balance = getWalletBalance(funded_wallet);

  console.log(`XCH Balance: ${balance}`);
  // End: Wait for Wallet to Sync

  // And I click on Send Page
  await page.locator('[data-testid="WalletHeader-tab-send"]').click();

  // When I enter an invalid address in address field
  await page.locator('[data-testid="WalletSend-address"]').fill('$$%R*(%^&%&&^%');

  
  // And I enter a valid Amount 
  await page.locator('[data-testid="WalletSend-amount"]').fill('.0005');

  // And I enter a valid Fee
  await page.locator('[data-testid="WalletSend-fee"]').fill('.00000005');
  //await page.locator('text=Fee *TXCH >> input[type="text"]').fill('.00000005');

  //And I click Send button 
  await page.locator('[data-testid="WalletSend-send"]').click();

  //Then I receive an informative error message
  await expect(page.locator('div[role="dialog"]')).toHaveText('ErrorUnexpected Address PrefixOK' || "ErrorPlease finish syncing before making a transactionOK" );
  await page.locator('div[role="dialog"] >> text=OK').click();


});






