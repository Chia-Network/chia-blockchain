from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from chia.pools.pool_wallet_info import PoolWalletInfo
from chia.rpc.rpc_client import RpcClient
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.bech32m import decode_puzzle_hash
from chia.util.ints import uint32, uint64
from chia.wallet.transaction_record import TransactionRecord


class WalletRpcClient(RpcClient):
    """
    Client to Silicoin RPC, connects to a local wallet. Uses HTTP/JSON, and converts back from
    JSON into native python objects before returning. All api calls use POST requests.
    Note that this is not the same as the peer protocol, or wallet protocol (which run Chia's
    protocol on top of TCP), it's a separate protocol on top of HTTP that provides easy access
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

    async def check_delete_key(self, fingerprint: int) -> None:
        return await self.fetch("check_delete_key", {"fingerprint": fingerprint})

    async def delete_all_keys(self) -> None:
        return await self.fetch("delete_all_keys", {})

    # Wallet Node APIs
    async def get_sync_status(self) -> bool:
        return (await self.fetch("get_sync_status", {}))["syncing"]

    async def get_synced(self) -> bool:
        return (await self.fetch("get_sync_status", {}))["synced"]

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

    async def get_next_address(self, wallet_id: str, new_address: bool) -> str:
        return (await self.fetch("get_next_address", {"wallet_id": wallet_id, "new_address": new_address}))["address"]

    async def send_transaction(
        self, wallet_id: str, amount: uint64, address: str, fee: uint64 = uint64(0)
    ) -> TransactionRecord:

        res = await self.fetch(
            "send_transaction",
            {"wallet_id": wallet_id, "amount": amount, "address": address, "fee": fee},
        )
        return TransactionRecord.from_json_dict(res["transaction"])

    async def send_transaction_multi(
        self, wallet_id: str, additions: List[Dict], coins: List[Coin] = None, fee: uint64 = uint64(0)
    ) -> TransactionRecord:
        # Converts bytes to hex for puzzle hashes
        additions_hex = [{"amount": ad["amount"], "puzzle_hash": ad["puzzle_hash"].hex()} for ad in additions]
        if coins is not None and len(coins) > 0:
            coins_json = [c.to_json_dict() for c in coins]
            response: Dict = await self.fetch(
                "send_transaction_multi",
                {"wallet_id": wallet_id, "additions": additions_hex, "coins": coins_json, "fee": fee},
            )
        else:
            response = await self.fetch(
                "send_transaction_multi", {"wallet_id": wallet_id, "additions": additions_hex, "fee": fee}
            )
        return TransactionRecord.from_json_dict(response["transaction"])

    async def delete_unconfirmed_transactions(self, wallet_id: str) -> None:
        await self.fetch(
            "delete_unconfirmed_transactions",
            {"wallet_id": wallet_id},
        )
        return None

    async def create_backup(self, file_path: Path) -> None:
        return await self.fetch("create_backup", {"file_path": str(file_path.resolve())})

    async def get_farmed_amount(self) -> Dict:
        return await self.fetch("get_farmed_amount", {})

    async def create_signed_transaction(
        self, additions: List[Dict], coins: List[Coin] = None, fee: uint64 = uint64(0)
    ) -> TransactionRecord:
        # Converts bytes to hex for puzzle hashes
        additions_hex = [{"amount": ad["amount"], "puzzle_hash": ad["puzzle_hash"].hex()} for ad in additions]
        if coins is not None and len(coins) > 0:
            coins_json = [c.to_json_dict() for c in coins]
            response: Dict = await self.fetch(
                "create_signed_transaction", {"additions": additions_hex, "coins": coins_json, "fee": fee}
            )
        else:
            response = await self.fetch("create_signed_transaction", {"additions": additions_hex, "fee": fee})
        return TransactionRecord.from_json_dict(response["signed_tx"])

    async def create_new_did_wallet(self, amount):
        request: Dict[str, Any] = {
            "wallet_type": "did_wallet",
            "did_type": "new",
            "backup_dids": [],
            "num_of_backup_ids_needed": 0,
            "amount": amount,
            "host": f"{self.hostname}:{self.port}",
        }
        response = await self.fetch("create_new_wallet", request)
        return response

    async def create_new_did_wallet_from_recovery(self, filename):
        request: Dict[str, Any] = {
            "wallet_type": "did_wallet",
            "did_type": "recovery",
            "filename": filename,
            "host": f"{self.hostname}:{self.port}",
        }
        response = await self.fetch("create_new_wallet", request)
        return response

    async def did_create_attest(self, wallet_id, coin_name, pubkey, puzhash, file_name):
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
            "coin_name": coin_name,
            "pubkey": pubkey,
            "puzhash": puzhash,
            "filename": file_name,
        }
        response = await self.fetch("did_create_attest", request)
        return response

    async def did_recovery_spend(self, wallet_id, attest_filenames):
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
            "attest_filenames": attest_filenames,
        }
        response = await self.fetch("did_recovery_spend", request)
        return response

    # TODO: test all invocations of create_new_pool_wallet with new fee arg.
    async def create_new_pool_wallet(
        self,
        target_puzzlehash: Optional[bytes32],
        pool_url: Optional[str],
        relative_lock_height: uint32,
        backup_host: str,
        mode: str,
        state: str,
        fee: uint64,
        p2_singleton_delay_time: Optional[uint64] = None,
        p2_singleton_delayed_ph: Optional[bytes32] = None,
    ) -> TransactionRecord:

        request: Dict[str, Any] = {
            "wallet_type": "pool_wallet",
            "mode": mode,
            "host": backup_host,
            "initial_target_state": {
                "target_puzzle_hash": target_puzzlehash.hex() if target_puzzlehash else None,
                "relative_lock_height": relative_lock_height,
                "pool_url": pool_url,
                "state": state,
            },
            "fee": fee,
        }
        if p2_singleton_delay_time is not None:
            request["p2_singleton_delay_time"] = p2_singleton_delay_time
        if p2_singleton_delayed_ph is not None:
            request["p2_singleton_delayed_ph"] = p2_singleton_delayed_ph.hex()
        res = await self.fetch("create_new_wallet", request)
        return TransactionRecord.from_json_dict(res["transaction"])

    async def pw_self_pool(self, wallet_id: str, fee: uint64) -> TransactionRecord:
        return TransactionRecord.from_json_dict(
            (await self.fetch("pw_self_pool", {"wallet_id": wallet_id, "fee": fee}))["transaction"]
        )

    async def pw_join_pool(
        self, wallet_id: str, target_puzzlehash: bytes32, pool_url: str, relative_lock_height: uint32, fee: uint64
    ) -> TransactionRecord:
        request = {
            "wallet_id": int(wallet_id),
            "target_puzzlehash": target_puzzlehash.hex(),
            "relative_lock_height": relative_lock_height,
            "pool_url": pool_url,
            "fee": fee,
        }

        join_reply = await self.fetch("pw_join_pool", request)
        return TransactionRecord.from_json_dict(join_reply["transaction"])

    async def pw_absorb_rewards(self, wallet_id: str, fee: uint64 = uint64(0)) -> TransactionRecord:
        return TransactionRecord.from_json_dict(
            (await self.fetch("pw_absorb_rewards", {"wallet_id": wallet_id, "fee": fee}))["transaction"]
        )

    async def pw_status(self, wallet_id: str) -> Tuple[PoolWalletInfo, List[TransactionRecord]]:
        json_dict = await self.fetch("pw_status", {"wallet_id": wallet_id})
        return (
            PoolWalletInfo.from_json_dict(json_dict["state"]),
            [TransactionRecord.from_json_dict(tr) for tr in json_dict["unconfirmed_transactions"]],
        )

    async def recover_pool_nft(self, launcher_hash: str, contract_hash: str, coins: List[Coin]) -> SpendBundle:
        return (
            await self.fetch(
                "pw_status",
                {
                    "launcher_hash": launcher_hash,
                    "contract_hash": contract_hash,
                    "coins": coins,
                },
            )
        )["spend_bundle"]
