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
test('Confirm that User can Send TXCH to another Wallet', async () => {
  
    let receive_wallet = 'txch1u237ltq0pp4348ppwv6cge7fks87mn4wz3c0ywvgswvpwhkqqn8qn8jeq6';
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

  // When I enter a valid wallet address in address field
  await page.locator('[data-testid="WalletSend-address"]').fill(receive_wallet);

  // And I enter a valid Amount 
  await page.locator('[data-testid="WalletSend-amount"]').fill('0.01');

  // And I enter a valid Fee
  await page.locator('text=Fee *TXCH >> input[type="text"]').fill('0.000005');

  //And I click Send button 
  await page.locator('[data-testid="WalletSend-send"]').click();

  //Then I receive a success message
  await expect(page.locator('div[role="dialog"]')).toHaveText("SuccessTransaction has successfully been sent to a full node and included in the mempool.OK" );
  await page.locator('div[role="dialog"] >> text=OK').click();
  
  // And I navigate to Summary page 
  await page.locator('[data-testid="WalletHeader-tab-summary"]').click();

  // Then Transactions section display the correct wallet, amount and fee
  await expect(page.locator(`text=${receive_wallet} >> nth=0`)).toBeVisible();

});






