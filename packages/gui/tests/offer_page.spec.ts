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
test('Create an Offer', async () => {

  // Given I log into Wallet 
  await page.locator('[data-testid="SelectKeyItem-fingerprint-1922132445"]').click();

  // And I navigate to Offers 
  await page.locator('[data-testid="DashboardSideBar-offers"]').click();

 
  // When I click Confirmed under status
  await page.locator('text=Confirmed').click();

  // Then Viewing Offer page displays a section for Summary 
  await expect(page.locator('text=Summary')).toBeVisible()

  // And Viewing Offer page displays a section for Details
  await expect(page.locator('text=Details')).toBeVisible()

  // And Viewing Offer page displays a section for Coins
  await expect(page.locator('text=Coins')).toBeVisible()

  // When I click Viewing offer back button
  await page.locator('text=Viewing offercreated August 26, 2022 6:16 PMYou created this offerSummaryIn exch >> button').click();

  // And I click miniMenu
  await page.locator('[aria-label="more"]').click();

  // And I click Show Details 
  await page.locator('text=Show Details').click();

  // Then Viewing Offer page re-displays
  await expect(page.locator('text=Viewing Offer')).toBeVisible;
})



