# Rate Limited Wallet

## About
  When RL Coin is created, withdrawl limit and time interval are specified. Those two parameters can't be changed and are used to limit how much Chia can be spent per time interval(Blocks).    
  Another paramater that is used for during creation of RL Coin is ID of primary input that's creating it. Before RL Coin can be spent it's puzzle checks if its parent is the Origin coin or if parent coin has the same puzzle hash as itself.     
  This prevents Rate Limited coin owner to create copies of RL coin and spend at **CopyCount * RateLimit**.    

## Setup

To install this repository, and all requirements, clone this repository and then run:

```
$ python3 -m venv .venv
$ . .venv/bin/activate
$ pip install -r requirements.txt
$ pip install -e .
```
## Launch

Before launching rl_wallet, make sure there is an instance of ledger-sim running.   
run:
```
$ ledger-sim
```

## Rate Limited Wallet Usage (step by step)
  1. **RUN**
     - Open two terminal windows and run  ```rl_wallet```

  2. **Get Chia**
     - **Terminal 1**
       - type "**4**" and press Enter (Get 1 Billion Chia)
  3. **Create Rate Limited Coin**
     - **Terminal 1**
       - type "**6**" and press Enter
       - type "**0**" or "**1**" to pick UTXO of Origin
       - type "**100** and press Enter (Coin will be limited to spend 100 Chia per time interval)
       - type "**2**" and press Enter (Time interval will will be 2 blocks)
       - from **Terminal 2** copy **pubkey** and paste it to **Terminal 1**
       - type **10000** and press Enter. (Create coin have 10000 Chia)
     - **Terminal 2**
       - type **5** and press Enter
       - from **Termial 1** copy "Initialization String" and paste it to **Terminal 2**
     - **Terminal 1**
       - press Enter to continue
       - type "**4**" to farm next block
     - **Terminal 2**
       - type "**3**" (Get updated blocks)
       - type "**2**" ("Rate limited balance" should be 10000, and "Available RL Balance" should be 0)
  4. **Interval Time**
     - **Terminal 1** (Mine two blocks to make some funds available in wallet 2)
       - type "**4**" and press Enter
       - type "**4**" and press Enter
     - **Terminal 2**
       - type **3** and press Enter
       - type **2** and press Enter ("Available RL Balance" should be 100 now)
  5. **Spend Rate Limited Funds**
     - **Terminal 2** (Send 100 to wallet 1)
       - type "**7**" and press Enter
     - **Terminal 1** (Show pubkey)
       - type "**1**"
       - from **Terminal 1** copy pubkey and paste it to **Terminal 2**
     - **Terminal 2**
       - type "**100**" and press Enter
     - **Terminal 1**
       - type "**4**" and press Enter
       - type "**2**" and press Enter (there should be UTXO of value 100 in utxo set)
     - **Terminal 2** (Send 100 to wallet 1)
       - type "**3**" and press Enter
       - type "**2**" and press Enter ("Current Rate limited Balance" should be 9900, and "Available RL Balance:" should be 0)
  6. **Add more funds into Rate Limited Wallet**
     - **Terminal 1** (Send 100 to wallet 1)
       - type "**8**" and press Enter
       - from **Terminal 2** copy "RL Coin Puzzlehash" and paste it to **Terminal 1**
       - type "**1000**" and press Enter (Chia amount we are adding to existing coin)
       - type "**4**" and press Enter (Wallet 1 creates aggregation coin)
     - **Terminal 2**
       - type "**3**" and press Enter (Wallet 2 sees aggregation coin on chain, then it creates a spend that consolidates two coins(RL_Coin + AGG_Coin = New_RL_Coin))
     - **Terminal 1**
       - type "**4**" and press Enter (Include latest transaction into block)
     - **Terminal 2**
       - type "**3**" and press Enter
       - type "**2**" and press Enter ("Current Rate limited Balance" should be 10900)
  7. **Retrieve RL Coin (Clawback)**
     - **Terminal 1**
       - type "**9**" and press Enter
       - type "**4**" and press Enter
       - type "**2**" and press Enter (UTXO set should include UTXO of 10900 in value)
     - **Terminal 2**
       - type "**3**" and press Enter
       - type "**2**" and press Enter ("Current rate limited balance" should be 0)
