# Wallet API

A csr wallet API with endpoints:

## Endpoints

#### `创建wallet`

```sh
POST /wallet

BODY
{
  "userId": USER_ID
}
```

```js
# response
{
  "address": WALLET_ADDRESS,
  "privateKey": PRIVATE_KEY
}
```

#### `获取wallet余额`

```sh
GET /getBalance/{WALLET_ADDRESS}
```

```js
# response
{
  "address": WALLET_ADDRESS,
  "balance": BALANCE
}
```

#### `通过TX_HASH获得transaction的详细信息`

```sh
GET /transaction/{TX_HASH}
```

```js
# response
{
  "txHash": TRANSACTION_HASH,
  ...: // other fields, define it later
}
```

#### `提交一个transfer transaction（提交到链上）`

```sh
POST to /transfer

BODY
{
	"privateKey": YOUR_PRIVATE_KEY,
	"amount": AMOUNT,
	"destination": DESTINATION_WALLET
}
```

```js
# response
{
  "txHash": TRANSACTION_HASH
}
```

#### `在链上释放csr token`

```sh
POST to /mint
BODY
{
	"privateKey": YOUR_PRIVATE_KEY,
	"amount": AMOUNT,
	"destination": DESTINATION_WALLET
}
```

```js
# response
{
  "txHash": TRANSACTION_HASH
}
```

#### `在链上销毁csr token`

```sh
POST to /burn
BODY
{
	"privateKey": YOUR_PRIVATE_KEY,
	"amount": AMOUNT,
	"source": SOURCE_WALLET
}
```

```js
# response
{
  "txHash": TRANSACTION_HASH
}
```


#### `获得钱包的交易信息`

```sh
GET /getTransactions/{WALLET_ADDRESS}/{FROM}/{TO}

FROM: timestamps
TO: timestamps
```

```js
# response
{
  "address": WALLET_ADDRESS,
  "transactions": [
      {
          tx: tx_hash,
          ... // other fields, need to define later
      }
  ]
}
```

## License

NONE