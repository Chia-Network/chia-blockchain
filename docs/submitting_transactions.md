
# Overview

A client needs to be able to specify a key for operations like signing a transaction. This can currently be set on the command like with the `--fingerprint` flag on the command line, or by choosing the key at startup in the GUI.

To work with an external HSM, we must be able to allow signing by an entity other than the wallet. This means we need to

A Transaction, for the Mempool's point of view, is a SpendBundle, which is a list of CoinSpends, and an optional signature.

A TransactionRecord, in the source code, is a SpendBundle, plus extra metadata.

# RPCs

## Create Transaction: `create_unsigned_transaction`

```
{
"key_fingerprint": YOUR_INT_FINGERPRINT_HERE,
"wallet_id": 1,
"spend_amount": 22,
"receiver_puzzlehash": "0b267e00169bbd2962623ba3820733048e15a5efbd15f17b81e4481e5ef8282e"
}
```


## Sign Transaction : `blind_sign_transaction`


## Submit Transaction: `push_tx`

# Example

```bash
cd chia-blockchain/examples
./send_transaction.sh
```
