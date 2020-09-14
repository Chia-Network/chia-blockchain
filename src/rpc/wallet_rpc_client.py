from typing import Dict, List
from src.rpc.rpc_client import RpcClient
from src.wallet.transaction_record import TransactionRecord
from src.util.ints import uint64
from src.types.sized_bytes import bytes32
from src.util.chech32 import decode_puzzle_hash


class WalletRpcClient(RpcClient):
    """
    Client to Chia RPC, connects to a local wallet. Uses HTTP/JSON, and converts back from
    JSON into native python objects before returning. All api calls use POST requests.
    Note that this is not the same as the peer protocol, or wallet protocol (which run Chia's
    protocol on top of TCP), it's a separate protocol on top of HTTP thats provides easy access
    to the full node.
    """

    async def get_wallets(self) -> Dict:
        return (await self.fetch("get_wallets", {}))["wallets"]

    async def get_wallet_balance(self, wallet_id: str) -> Dict:
        return (await self.fetch("get_wallet_balance", {"wallet_id": wallet_id}))["wallet_balance"]

    async def send_transaction(
        self, wallet_id: str, amount: uint64, address: str, fee: uint64 = uint64(0)
    ) -> TransactionRecord:

        res = await self.fetch(
            "send_transaction",
            {
                "wallet_id": wallet_id,
                "amount": amount,
                "puzzle_hash": address,
                "fee": fee,
            },
        )
        return TransactionRecord.from_json_dict(res["transaction"])

    async def get_next_address(self, wallet_id: str) -> str:
        return (await self.fetch("get_next_address", {"wallet_id": wallet_id}))["address"]

    async def get_transaction(self, wallet_id: str, transaction_id: bytes32) -> TransactionRecord:

        res = await self.fetch(
            "get_transaction",
            {"walled_id": wallet_id, "transaction_id": transaction_id.hex()},
        )
        return TransactionRecord.from_json_dict(res["transaction"])

    async def get_transactions(self, wallet_id: str,) -> List[TransactionRecord]:
        res = await self.fetch("get_transactions", {"wallet_id": wallet_id},)
        reverted_tx: List[TransactionRecord] = []
        for modified_tx in res["transactions"]:
            # Server returns address instead of ph, but TransactionRecord requires ph
            modified_tx["to_puzzle_hash"] = decode_puzzle_hash(modified_tx["to_address"]).hex()
            del modified_tx["to_address"]
            reverted_tx.append(TransactionRecord.from_json_dict(modified_tx))
        return reverted_tx

    async def log_in(self, fingerprint) -> Dict:
        return await self.fetch(
            "log_in",
            {
                "host": "https://backup.chia.net",
                "fingerprint": fingerprint,
                "type": "start",
            },
        )

    async def log_in_and_restore(self, fingerprint, file_path) -> Dict:
        return await self.fetch(
            "log_in",
            {
                "host": "https://backup.chia.net",
                "fingerprint": fingerprint,
                "type": "restore_backup",
                "file_path": file_path,
            },
        )

    async def log_in_and_skip(self, fingerprint) -> Dict:
        return await self.fetch(
            "log_in",
            {
                "host": "https://backup.chia.net",
                "fingerprint": fingerprint,
                "type": "skip",
            },
        )

    async def get_public_keys(self) -> List:
        return (await self.fetch("get_public_keys", {}))["public_key_fingerprints"]
