# Recoverable Wallets

## Background

A Chia recoverable wallet is a wallet whose funds can be recovered in the event that the wallet is lost by providing a recovery string to another wallet. In contrast to a BIP 39 backup seed, a Chia recovery string is a low security piece of information. A thief who finds the string can't use it to steal funds from a wallet they don't own. This is accomplished by the recovery process locking up the funds in escrow along with some mandatory staking funds. If the recovery process was initiated by an attacker, the attacker will lose the staking funds as the original wallet has the ability to clawback the escrow coins during the escrow period. If the recovery process was legitimate however, the owner can retrieve their funds from escrow at the end of the escrow period, along with the staking funds. In this demonstration the staking amount is 10% and the escrow period is 3 blocks.

## Usage

Run a version of `ledger-sim` in a background terminal window.

### Commands
- 1: View Coins
- 2: Spend Coins
- 3: Get Updates
- 4: Farm Block
- 5: Generate Puzzle Hash
- 6: Print Backup
- 7: Recover Coins
- 8: Recover Escrow Coins
- q: Quit


### Recovery Process Demonstration
- Open three terminals and run `$ recoverable_wallet` Accept the default parameters. Terminal 1 will run the wallet that will be recovered. Terminal 2 will run the wallet that recovers the funds. Terminal 3 will just be used to farm blocks to move time forward.

- **Terminal 1**
    - Enter **4** to add funds to this wallet
    - Enter **6** to view the recovery string for this wallet. After you copy the recovery string you can close this terminal as this wallet will be considered lost.
- **Terminal 2**
    - Enter **4** to add funds to this wallet
    - Enter **7** to begin the recovery process. The wallet will ask you for a recovery string
    - Enter the recovery string you received from the wallet in Terminal 1. A recovery transaction will be submitted for inclusion in the next farmed block
- **Terminal 3**
    - Enter **4** to farm a new block
- **Terminal 2**
    - Enter **3** to sync the current blockchain
    - Enter **1** to view your current coins. You will see that your coin balance has decreased by the staking amount and the escrow coins balance is equal to the value of the wallet being recovered plus the staking amount. You will also see how many additional blocks need to be farmed before the escrow funds can be retrieved. 
- **Terminal 3**
    - Enter **4** to farm a new block
    - Do this an appropriate number of times for the escrow period to conclude
- **Terminal 2**
    - Enter **3** to sync the blockchain
    - Enter **1** to verify that the escrow period is over
    - Enter **8** to submit a transaction moving the escrow coins into your wallet in the next farmed block
- **Terminal 3**
    - Enter **4** to farm a new block
- **Terminal 2**
    - Enter **3** to sync the blockchain
    - Enter **1** to verify that the recovered coins and staking funds have been moved out of escrow and into this wallet


### Clawback Demonstration
- Open three terminal windows and run `$ recoverable_wallet` Accept the default parameters. Terminal 1 will run a wallet with some funds in it. Terminal 2 will run the wallet of the attacker attempting to steal the funds from the wallet in Terminal 1 using the recovery string. Terminal 3 will just be used to farm blocks to move time forward.

- **Terminal 1**
    - Enter **4** to add funds to this wallet
    - Enter **6** to view the recovery string for this wallet
- **Terminal 2**
    - Enter **4** to add funds to this wallet
    - Enter **7** to begin the illegitimate recovery process. The wallet will ask you for a recovery string
    - Enter the recovery string you received from the wallet in Terminal 1. A recovery transaction will be submitted for addition to next farmed block
- **Terminal 3**
    - Enter **4** to farm a new block
- **Terminal 2**
    - Enter **3** to sync the current blockchain
    - Enter **1** to view your current coins. You will see that your coin balance has decreased by the staking amount and the escrow coins balance is equal to the value of the wallet being recovered plus the staking amount. Note that the escrow period has not yet concluded.
- **Terminal 1**
    - Enter **3** to sync the blockchain. You will see a warning that your funds have been moved to escrow. Because this wallet is still running, it will automatically submit a clawback transaction for inclusion in the next farmed block.
    - Enter **1** to see that your coins are currently gone because the wallet in Terminal 2 moved them to escrow
- **Terminal 3**
    - Enter **4** to farm a new block
- **Terminal 1**
    - Enter **3** to sync the blockchain
    - Enter **1** to verify that the original amount plus the staking amount was returned to this wallet by the clawback transaction
- **Terminal 2**
    - Enter **3** to sync the blockchain
    - Enter **1** to verify that the coins have left escrow and that the attacker lost the staking funds