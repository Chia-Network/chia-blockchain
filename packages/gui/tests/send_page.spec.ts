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


//Failures due to Elements changing attributes
test('Confirm Error Dialog when wrong data is entered on Send Page for 1922132445 ID', async () => {
  
  // Given I log into Wallet 1922132445
  await Promise.all([
    page.waitForNavigation(/*{ url: 'file:///Users/jahifaw/Documents/Code/Chia-testnet-playwright/chia-blockchain/chia-blockchain-gui/packages/gui/build/renderer/index.html#/dashboard/wallets/1' }*/),
    page.locator('div[role="button"]:has-text("Private key with public fingerprint 1922132445Can be backed up to mnemonic seed")').click()
  ]);

  // And I click on Send Page
  await page.locator('[data-testid="WalletHeader-tab-send"]').click();

  // When I enter an invalid address in address field
  await page.locator('[data-testid="WalletSend-address"]').fill('$$%R*(%^&%&&^%');

  
  // And I enter a valid Amount 
  await page.locator('[data-testid="WalletSend-amount"]').fill('.0005');


  // And I enter a valid Fee
  await page.locator('[data-testid="WalletSend-fee"]').fill('.00000005');

  //And I click Send button 
  await page.locator('[data-testid="WalletSend-send"]').click();

  //Then I receive an informative error message
  await expect(page.locator('div[role="dialog"]')).toHaveText('ErrorUnexpected Address PrefixOK' || "ErrorPlease finish syncing before making a transactionOK" );
  await page.locator('div[role="dialog"] >> text=OK').click();


});






