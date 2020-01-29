# Authorised Payees

An Authorised Payee smart contract means that Wallet A can give Wallet B some money that can only be spent in ways that Wallet A has approved of.

## Overview
The Authorised Payee smart transaction works in the following way.

1. Wallet A asks Wallet B for its public key.
2. Wallet A creates a new Authorised Payee puzzle using Wallet B's public key and locks a new coin up with the puzzle.
3. Wallet A sends Wallet B some information off the blockchain, so that Wallet B is able to detect and use the new coin.
4. Wallet A sends Wallet B some puzzlehashes and as well as a signature for each of the puzzlehashes
5. Wallet B can only spend the coin if it uses one of the approved puzzlehashes and presents the signature in Aggsig.
6. Any change generated to Wallet B will be locked up with the Authorised Payee puzzle.
7. Any wallet can send Wallet B some more money that can only be aggregated into the Authorised Payee coin by using an aggregation puzzle.
8. Wallet A can send additional signatures to Wallet B off the chain at any time it likes.


## Contacts

The AP wallet uses a contacts system to remember who it is approved to send to.
A contact is comprised of:
1. A human readable name
2. A puzzlehash
3. A signature of that puzzlehash from the authoriser

## Usage

One of the unique qualities of the Authorised Payees smart contract is that it is started by a standard wallet, and uses a special wallet to manage the Authorised Payee coin.

Follow the [README](../README.md) to install the dependencies and setup a standard wallet and ledger-sim.
As always, make sure you have ledger-sim running in a terminal window before trying to use the wallets.


1. Launch your authorised payees wallet by running `$ ap_wallet`.
Your public key will be shown, and you will be asked for some setup information.

2. In another terminal window launch a standard wallet with `$ wallet`.
Press `3` to get some money.

3. Then from the menu, still in the standard wallet, select `6: Initiate Authorised Payee`.
Paste the AP wallet's public key into the terminal and enter an amount of Chia to send to the AP wallet.
You should then see the initialization string for the Authorised Payee wallet.

4. Paste the initialization string into the AP wallet, and you'll be asked to add an authorised payee as an approved contact.
You can cancel this and do it letter by pressing `q`. Otherwise, we're going to need a 3rd runnable wallet.

5. Start a second standard wallet and from the main menu press `5: Set My Name`, and enter a new name for the wallet.
Then from the menu press `4: Print My Details`.
This should print out some information about the wallet, including a single string, which is used for receiving payments.

6. Paste this single string into the first standard wallet, which we used to create the smart contract.
It should return a `Single string for AP Wallet`. Copy this and paste it into the AP Wallet.

* You can repeat steps 5 and 6 for multiple contacts, but for now we will move on.

7. In one of the wallets you must select `Commit Block` to commit the send to the AP Wallet to the chain.
Then select `4: Get Update` from the AP Wallet's menu.

8. From the main menu in the Authorised Payee wallet, select `2: Make Payment`.
You should see a list of authorised recipients. Enter the name of the recipient you would like to send to.
Then enter the amount you would like to send.

9. Select `Commit Block` from one of the wallets.
Then select `2: Get Update` from the recipient wallet's menu.
Your new funds should now appear in the recipient wallet's UTXO set.
