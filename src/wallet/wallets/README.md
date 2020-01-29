# Chia Wallets

The Chia Wallets are designed to show off Chia's approach to transactions, and our new language ChiaLisp.
At the moment this project is uses a local server which simulates the full network. This allows us to test the wallet functionality in isolation.

The local server which handles transactions in Chia is called [ledger_sim](https://github.com/Chia-Network/ledger_sim).

We have a tutorial for writing smart transactions, and other documentation available [here](./docs).

## Setup


To install this repository, and all requirements, clone this repository and then run:

```
$ python3 -m venv .venv
$ . .venv/bin/activate
$ pip install -r requirements.txt
$ pip install -e .
```

**(Note: at the moment [blspy](https://github.com/Chia-Network/bls-signatures) may require you to have [CMake](https://cmake.org/install/) installed as well, though this dependency should be temporary)**

### QR Code Setup

To use the QR codes you will also need to support [pyzbar](https://pypi.org/project/pyzbar/).

On Windows this requires no extra effort.

On Linux, run:

```
$ sudo apt-get install libzbar0
$ pip install pyzbar[scripts]
```

On Mac, run:

```
$ brew install zbar
$ pip install pyzbar[scripts]
```

# The Standard Wallet

The standard command-line wallet contains the default functionality for a wallet.
It can send and receive transactions as well as generate QR codes and a few other 'smart' features.

## Using the Command-line Interface

### How to launch

In a terminal window, run:
```
$ . .venv/bin/activate
```

And then launch an instance of ledger-sim with:
```
$ ledger-sim
```

Then to start a new standard wallet, in a new terminal window, run:
```
$ . .venv/bin/activate
```

And then launch the standard wallet with:
```
$ wallet
```

Feel free to run more than one instance of the wallet to test sending money between them.

### The Menu

The options available in a standard wallet are:
* **Make Payment** - This will take ask you for an amount to send, and a string of wallet information to generate the address.
* **Get Update** - This will poll the ledger_sim network and find out if there have been any new transactions that concern your wallet.
* **Commit Block / Get Money** - This will create a new block, therefore committing all the pending transactions and also giving your wallet 1000000000 Chia.
* **Print My Details** - This will output a string of information that another wallet can use to send money to you.
* **Set Wallet Name** - This will change how your wallet self-identifies when communicating with other wallets.
* **Make Smart Contract** - This will allow you to communicate with the Authorised Payees wallet, and send a coin that can only be spent in approved ways. For more information read the [documentation here](./docs/authorised_payees.md).
* **Make QR code** - This will create a QR code image in the installed folder.
* **Payment to QR code** - This acts the same way as 'Make Payment' but instead of a string storing the information, it reads in a QR image.
* **Quit** - Closes the wallet program.

# Smart Wallets

The Smart Transactions currently available are:
* **Atomic Swaps** - `$ as_wallet` - [guide](./docs/atomic_swaps.md)
* **Authorised Payees** - `$ ap_wallet` - [guide](./docs/authorised_payees.md)
* **Recoverable Wallets** - `$ recoverable_wallet` - [guide](./docs/recoverable_wallet.md)
* **Multi-sig Wallet** - `$ multisig_wallet` - [guide](./multisig/README.org)
* **Rate-Limited Wallet** - `$ rl_wallet` - [guide](./docs/rate_limited_wallet.md)

For more information about the smart wallets, check out our **[docs](./docs).**

# Tests

Firstly, make sure pytest is installed with

```
$ pip install pytest
```

Then you can run our tests with

```
$ py.test tests
```
