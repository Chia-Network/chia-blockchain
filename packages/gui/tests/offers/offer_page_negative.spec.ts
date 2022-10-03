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
test('Confirm Error message when fields are not completed on Offer Page', async () => {

  // Given I log into Wallet 
  await page.locator('[data-testid="SelectKeyItem-fingerprint-1922132445"]').click();

  // And I navigate to Offers Page
  await page.locator('[data-testid="DashboardSideBar-offers"]').click();

  // And I click on Create an Offer
  await page.locator('button:has-text("Create an Offer")').click();

  // And I select token offer
  await page.locator('li[role="menuitem"]:has-text("NFT Offer")').click();

  // When I enter an Amount 
  await page.locator('text=Amount *TXCH >> input[type="text"]').fill('0.05');

  // And I enter invalid text in Exchange field 
  await page.locator('[placeholder="NFT Identifier"]').fill('hjuyt');

  // And I click Create offer 
  await page.locator('text=Create Offer').click();

  // Then user receives appropriate error message
  await expect(page.locator('div[role="dialog"]')).toHaveText('ErrorInvalid NFT identifierOK');

  // And I click on OK button
  await page.locator('button:has-text("OK")').click();

  // Given I Click Back Button
  await page.locator('text=Create an NFT OfferBuy an NFTSell an NFTYou will offerAmount *TXCH50,000,000,000 >> button').first().click();
  
  // And I click on Create an Offer
  await page.locator('button:has-text("Create an Offer")').click();

  // And I select Token Offer
  await page.locator('text=Token Offer').click();

  // When I complete Amount under heading You will offer
  await page.locator('text=You will offerAsset Type *​Amount *TXCH >> input[type="text"]').fill('0.00000000005');


  // And I complete Amount under heading In exchange for
  await page.locator('text=In exchange forAsset Type *​Amount *TXCH >> input[type="text"]').fill('0.00000000005');

  // And I Click text=Create Offer
  await page.locator('text=Create Offer').click();

  // Then user receives appropriate error message
  await expect(page.locator('div[role="dialog"]')).toHaveText('ErrorPlease select an asset for each rowOK');

  // Click button:has-text("OK")
  await page.locator('button:has-text("OK")').click();

  
})



