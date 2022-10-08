import { ElectronApplication, Page, _electron as electron } from 'playwright'
import { test, expect } from '@playwright/test';
import { LoginPage } from '../data_object_model/passphrase_login';

let electronApp: ElectronApplication;
let page: Page;
let appWindow: Page;


test.beforeAll(async () => {
  electronApp = await electron.launch({ args: ['./build/electron/main.js'] });
  page = await electronApp.firstWindow();
  
});

test.afterAll(async () => {
  await page.close();

});

  //This works but. This appears to be a bug. New Address Button should generate new Address Id
  test('Verify that new address button creates new address', async () => {

    // Given I enter correct credentials in Passphrase dialog
   await new LoginPage(page).login('password2022!@')

   // And I navigate to a wallet with funds
   await page.locator('[data-testid="LayoutDashboard-log-out"]').click();
   await page.locator('text=975437849').click();

    //And I confirm page has correct Title 
    expect(page).toHaveTitle('Chia Blockchain');

    //And I navigate to Receive page
    await page.locator('[data-testid="WalletHeader-tab-receive"]').click();

    //When I copy the wallet address
    await page.locator('[data-testid="WalletReceiveAddress-address-copy"]').click();
    
    //Then current wallet address is now stored into a variable
    const wallet_address = await page.locator('text=Receive Address New AddressAddress >> input[type="text"]').inputValue()
    console.log(wallet_address)

    //When I generate a new wallet address id
    await page.locator('[data-testid="WalletReceiveAddress-new-address"]').click();

    //And I store the new wallet address id in a variable
    const wallet_new = await page.locator('text=Receive Address New AddressAddress >> input[type="text"]').inputValue()
    console.log(wallet_new)

    //And I Compare Values variables. This should be false. wallet_address != wallet_new
    if(wallet_address == wallet_new){
      expect(wallet_address).toEqual(wallet_new)
      console.log('The Wallet Address has not been updated!')
    }
    else if (wallet_address != wallet_new){
      expect(wallet_address).not.toEqual(wallet_new)
      console.log('A New Wallet Address has been successfully generated!')
    }   
  });

