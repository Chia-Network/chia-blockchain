from typing import Dict, List
from pathlib import Path
from src.rpc.rpc_client import RpcClient
from src.wallet.transaction_record import TransactionRecord
from src.util.ints import uint64, uint32
from src.types.blockchain_format.sized_bytes import bytes32
from src.util.bech32m import decode_puzzle_hash


class WalletRpcClient(RpcClient):
    """
    Client to Chia RPC, connects to a local wallet. Uses HTTP/JSON, and converts back from
    JSON into native python objects before returning. All api calls use POST requests.
    Note that this is not the same as the peer protocol, or wallet protocol (which run Chia's
    protocol on top of TCP), it's a separate protocol on top of HTTP thats provides easy access
    to the full node.
    """

    # Key Management APIs
    async def log_in(self, fingerprint: int) -> Dict:
        try:
            return await self.fetch(
                "log_in",
                {"host": "https://backup.chia.net", "fingerprint": fingerprint, "type": "start"},
            )

        except ValueError as e:
            return e.args[0]

    async def log_in_and_restore(self, fingerprint: int, file_path) -> Dict:
        try:
            return await self.fetch(
                "log_in",
                {
                    "host": "https://backup.chia.net",
                    "fingerprint": fingerprint,
                    "type": "restore_backup",
                    "file_path": file_path,
                },
            )
        except ValueError as e:
            return e.args[0]

    async def log_in_and_skip(self, fingerprint: int) -> Dict:
        try:
            return await self.fetch(
                "log_in",
                {"host": "https://backup.chia.net", "fingerprint": fingerprint, "type": "skip"},
            )
        except ValueError as e:
            return e.args[0]

    async def get_public_keys(self) -> List[int]:
        return (await self.fetch("get_public_keys", {}))["public_key_fingerprints"]

    async def get_private_key(self, fingerprint: int) -> Dict:
        return (await self.fetch("get_private_key", {"fingerprint": fingerprint}))["private_key"]

    async def generate_mnemonic(self) -> List[str]:
        return (await self.fetch("generate_mnemonic", {}))["mnemonic"]

    async def add_key(self, mnemonic: List[str], request_type: str = "new_wallet") -> None:
        return await self.fetch("add_key", {"mnemonic": mnemonic, "type": request_type})

    async def delete_key(self, fingerprint: int) -> None:
        return await self.fetch("delete_key", {"fingerprint": fingerprint})

    async def delete_all_keys(self) -> None:
        return await self.fetch("delete_all_keys", {})

    # Wallet Node APIs
    async def get_sync_status(self) -> bool:
        return (await self.fetch("get_sync_status", {}))["syncing"]

    async def get_height_info(self) -> uint32:
        return (await self.fetch("get_height_info", {}))["height"]

    async def farm_block(self, address: str) -> None:
        return await self.fetch("farm_block", {"address": address})

    # Wallet Management APIs
    async def get_wallets(self) -> Dict:
        return (await self.fetch("get_wallets", {}))["wallets"]

    # Wallet APIs
    async def get_wallet_balance(self, wallet_id: str) -> Dict:
        return (await self.fetch("get_wallet_balance", {"wallet_id": wallet_id}))["wallet_balance"]

    async def get_transaction(self, wallet_id: str, transaction_id: bytes32) -> TransactionRecord:
        res = await self.fetch(
            "get_transaction",
            {"walled_id": wallet_id, "transaction_id": transaction_id.hex()},
        )
        return TransactionRecord.from_json_dict(res["transaction"])

    async def get_transactions(
        self,
        wallet_id: str,
    ) -> List[TransactionRecord]:
        res = await self.fetch(
            "get_transactions",
            {"wallet_id": wallet_id},
        )
        reverted_tx: List[TransactionRecord] = []
        for modified_tx in res["transactions"]:
            # Server returns address instead of ph, but TransactionRecord requires ph
            modified_tx["to_puzzle_hash"] = decode_puzzle_hash(modified_tx["to_address"]).hex()
            del modified_tx["to_address"]
            reverted_tx.append(TransactionRecord.from_json_dict(modified_tx))
        return reverted_tx

    async def get_next_address(self, wallet_id: str) -> str:
        return (await self.fetch("get_next_address", {"wallet_id": wallet_id}))["address"]

    async def send_transaction(
        self, wallet_id: str, amount: uint64, address: str, fee: uint64 = uint64(0)
    ) -> TransactionRecord:

        res = await self.fetch(
            "send_transaction",
            {"wallet_id": wallet_id, "amount": amount, "address": address, "fee": fee},
        )
        return TransactionRecord.from_json_dict(res["transaction"])

    async def create_backup(self, file_path: Path) -> None:
        return await self.fetch("create_backup", {"file_path": str(file_path.resolve())})


# TODO: add APIs for coloured coins and RL wallet
