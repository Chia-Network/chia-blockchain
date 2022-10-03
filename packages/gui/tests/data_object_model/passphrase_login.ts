//pages/loginpage.ts

import type { Page } from 'playwright';
export class LoginPage {
    readonly page: Page;
constructor(page: Page) {
        this.page = page;
    }

    async login(password: string) {
        // Given I enter the correct credential in Passphrase field 
        await this.page.locator('input[type="password"]').fill(password);
        // Then I click on Unlock
        await this.page.locator('text=Unlock Keyring').click();
    }

    async incorrectlogin() {
        // Click input[type="password"]
        await this.page.locator('input[type="password"]').click();
        // Fill input[type="password"]
        await this.page.locator('input[type="password"]').fill('Wafisimah2022!@');
        // Click text=Unlock Keyring
        await this.page.locator('text=Unlock Keyring').click();
    }

    async changePassphrase(){
      
        // Given I enter my Current Passphrase
        await this.page.locator('text=Current PassphraseCurrent Passphrase >> input[type="password"]').fill('Wafisimah2022!@');

        // And 
       //await this.page.locator('text=New PassphraseNew Passphrase >> input[type="password"]').click();

        // And I enter my New Passphrase 
        await this.page.locator('text=New PassphraseNew Passphrase >> input[type="password"]').fill('Wafisimah2022!#');
        
        // Click text=Confirm New PassphraseConfirm New Passphrase >> input[type="password"]
        //await this.page.locator('text=Confirm New PassphraseConfirm New Passphrase >> input[type="password"]').click();

        // And I enter a 2nd Passphrase
        await this.page.locator('text=Confirm New PassphraseConfirm New Passphrase >> input[type="password"]').fill('Wafisimah2022!#');

        // And I enter a Passphrase hint
        //await this.page.locator('[placeholder="Passphrase Hint"]').click();

        // And I enter a Passphrase hint
        await this.page.locator('[placeholder="Passphrase Hint"]').fill('My Password');

        // And I select the Passphrase Save checkbox
        //await this.page.locator('input[name="cleanupKeyringPostMigration"]').check();

        // And I click Change Passphrase 
        await this.page.locator('div[role="dialog"] button:has-text("Change Passphrase")').click();

        // Click button:has-text("OK")
        await this.page.locator('button:has-text("OK")').click();
    }

    // NEEDS ATTENTION-NOT WORKING!!
    async setPassphrase(){
        // When I set a passphrase 
        await this.page.locator('[data-testid="SettingsPanel-set-passphrase"]').click();
        //await page.locator('[placeholder="Passphrase"]').click();
        await this.page.locator('[placeholder="Passphrase"]').fill('Wafisimah2022!@');
        //await page.locator('[placeholder="Passphrase"]').press('Tab');
        //await page.locator('[data-testid="SetPassphrasePrompt-passphrase"] button').press('Tab');
        await this.page.locator('[placeholder="Confirm Passphrase"]').fill('Wafisimah2022!@');
        //await page.locator('[placeholder="Passphrase Hint"]').click();
        await this.page.locator('[placeholder="Passphrase Hint"]').fill('My password');
        await this.page.locator('[data-testid="SetPassphrasePrompt-set-passphrase"]').click();
        await this.page.locator('button:has-text("OK")').click();
    }

    // NEEDS ATTENTION-NOT WORKING!!
    async disablePassphrase(){
        /*/ Then user is presented with passphrase dialog
        await this.page.locator('input[type="password"]').click();
        await this.page.locator('input[type="password"]').fill('Wafisimah2022!@');
        await this.page.locator('input[type="password"]').press('Enter');*/

        // When I navigate to Settings Dialog page 
        //await this.page.locator('[data-testid="DashboardSideBar-settings"]').click();

        // And I disable Passphrase
        await this.page.locator('[data-testid="SettingsPanel-remove-passphrase"]').click();
        await this.page.locator('input[type="password"]').click();
        await this.page.locator('input[type="password"]').fill('Wafisimah2022!@');
        await this.page.locator('div[role="dialog"] button:has-text("Remove Passphrase")').click();
        await this.page.locator('button:has-text("OK")').click();


      


         /*/ Click [data-testid="DashboardSideBar-settings"]
  await page.locator('[data-testid="DashboardSideBar-settings"]').click();
  await page.waitForURL('file:///Users/jahifaw/Documents/Code/chia-tn-pw-latest/chia-blockchain/chia-blockchain-gui/packages/gui/build/renderer/index.html#/dashboard/settings/general');
  // Click [data-testid="SettingsPanel-remove-passphrase"]
  await page.locator('[data-testid="SettingsPanel-remove-passphrase"]').click();
  // Click input[type="password"]
  await page.locator('input[type="password"]').click();
  // Fill input[type="password"]
  await page.locator('input[type="password"]').fill('password2022!!');
  // Click div[role="dialog"] button:has-text("Remove Passphrase")
  await page.locator('div[role="dialog"] button:has-text("Remove Passphrase")').click();
  // Click button:has-text("OK")
  await page.locator('button:has-text("OK")').click();
  // Click [data-testid="SettingsPanel-set-passphrase"]
  await page.locator('[data-testid="SettingsPanel-set-passphrase"]').click();
  // Click [placeholder="Passphrase"]
  await page.locator('[placeholder="Passphrase"]').click();
  // Fill [placeholder="Passphrase"]
  await page.locator('[placeholder="Passphrase"]').fill('password2022!!');
  // Click [data-testid="SetPassphrasePrompt-passphrase"] button
  await page.locator('[data-testid="SetPassphrasePrompt-passphrase"] button').click();
  // Click [placeholder="Passphrase"]
  await page.locator('[placeholder="Passphrase"]').click();
  // Fill [placeholder="Passphrase"]
  await page.locator('[placeholder="Passphrase"]').fill('password2022!@');
  // Click [placeholder="Passphrase"]
  await page.locator('[placeholder="Passphrase"]').click();
  // Click [placeholder="Confirm Passphrase"]
  await page.locator('[placeholder="Confirm Passphrase"]').click();
  // Fill [placeholder="Confirm Passphrase"]
  await page.locator('[placeholder="Confirm Passphrase"]').fill('password2022!!');
  // Click [data-testid="SetPassphrasePrompt-confirm-passphrase"] button
  await page.locator('[data-testid="SetPassphrasePrompt-confirm-passphrase"] button').click();
  // Click [placeholder="Confirm Passphrase"]
  await page.locator('[placeholder="Confirm Passphrase"]').click();
  // Fill [placeholder="Confirm Passphrase"]
  await page.locator('[placeholder="Confirm Passphrase"]').fill('password2022!@');
  // Click [placeholder="Passphrase Hint"]
  await page.locator('[placeholder="Passphrase Hint"]').click();
  // Fill [placeholder="Passphrase Hint"]
  await page.locator('[placeholder="Passphrase Hint"]').fill('my passphrase');
  // Click [data-testid="SetPassphrasePrompt-set-passphrase"]
  await page.locator('[data-testid="SetPassphrasePrompt-set-passphrase"]').click();
  // Click button:has-text("OK")
  await page.locator('button:has-text("OK")').click();*/
    }

    /*async dateFunction(){
        let today = new Date();
        let date = today.getFullYear()+ " " + (today.getMonth()+ "" + today.getDate());
        let time = today.getHours()+ " " + today.getMinutes()+ "" + today.getSeconds();
        let currentPassphrase = 'Wafisimah2022!$'
    }*/

}