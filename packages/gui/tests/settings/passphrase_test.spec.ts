import { ElectronApplication, Page, _electron as electron } from 'playwright'
import { test, expect } from '@playwright/test';
import { LoginPage } from '../data_object_model/passphrase_login';


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

//Works and Passes
test('Confirm user can add and remove passphrase ', async () => {

  // Given I enter the incorrect credentials in Passphrase dialog
  await new LoginPage(page).incorrectlogin()
  await page.locator('text=OK').click();

  // Given I enter correct credentials in Passphrase dialog
  await new LoginPage(page).login('password2022!@')
 
  // When I navigate to Setting's Page
  await page.locator('div[role="button"]:has-text("Settings")').click();

  // Then I can remove passphrase 
    await page.locator('[data-testid="SettingsPanel-remove-passphrase"]').click();
    // Click text=Cancel
    await page.locator('text=Cancel').click();
  
  // And I can update passphrase
    await page.locator('text=Change Passphrase').click();
    // Click text=Cancel
    await page.locator('text=Cancel').click();
  
});


