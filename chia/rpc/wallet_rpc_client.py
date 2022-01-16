from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from chia.pools.pool_wallet_info import PoolWalletInfo
from chia.rpc.rpc_client import RpcClient
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint32, uint64
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.transaction_sorting import SortKey


class WalletRpcClient(RpcClient):
    """
    Client to Chia RPC, connects to a local wallet. Uses HTTP/JSON, and converts back from
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

    async def get_logged_in_fingerprint(self) -> int:
        return (await self.fetch("get_logged_in_fingerprint", {}))["fingerprint"]

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
        return TransactionRecord.from_json_dict_convenience(res["transaction"])

    async def get_transactions(
        self,
        wallet_id: str,
        start: int = None,
        end: int = None,
        sort_key: SortKey = None,
        reverse: bool = False,
    ) -> List[TransactionRecord]:
        request: Dict[str, Any] = {"wallet_id": wallet_id}

        if start is not None:
            request["start"] = start
        if end is not None:
            request["end"] = end
        if sort_key is not None:
            request["sort_key"] = sort_key.name
        request["reverse"] = reverse

        res = await self.fetch(
            "get_transactions",
            request,
        )
        return [TransactionRecord.from_json_dict_convenience(tx) for tx in res["transactions"]]

    async def get_transaction_count(
        self,
        wallet_id: str,
    ) -> List[TransactionRecord]:
        res = await self.fetch(
            "get_transaction_count",
            {"wallet_id": wallet_id},
        )
        return res["count"]

    async def get_next_address(self, wallet_id: str, new_address: bool) -> str:
        return (await self.fetch("get_next_address", {"wallet_id": wallet_id, "new_address": new_address}))["address"]

    async def send_transaction(
        self, wallet_id: str, amount: uint64, address: str, fee: uint64 = uint64(0), memos: Optional[List[str]] = None
    ) -> TransactionRecord:
        if memos is None:
            send_dict: Dict = {"wallet_id": wallet_id, "amount": amount, "address": address, "fee": fee}
        else:
            send_dict = {
                "wallet_id": wallet_id,
                "amount": amount,
                "address": address,
                "fee": fee,
                "memos": memos,
            }
        res = await self.fetch("send_transaction", send_dict)
        return TransactionRecord.from_json_dict_convenience(res["transaction"])

    async def send_transaction_multi(
        self, wallet_id: str, additions: List[Dict], coins: List[Coin] = None, fee: uint64 = uint64(0)
    ) -> TransactionRecord:
        # Converts bytes to hex for puzzle hashes
        additions_hex = []
        for ad in additions:
            additions_hex.append({"amount": ad["amount"], "puzzle_hash": ad["puzzle_hash"].hex()})
            if "memos" in ad:
                additions_hex[-1]["memos"] = ad["memos"]
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

        return TransactionRecord.from_json_dict_convenience(response["transaction"])

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
        self,
        additions: List[Dict],
        coins: List[Coin] = None,
        fee: uint64 = uint64(0),
        coin_announcements: Optional[List[Announcement]] = None,
        puzzle_announcements: Optional[List[Announcement]] = None,
    ) -> TransactionRecord:
        # Converts bytes to hex for puzzle hashes
        additions_hex = []
        for ad in additions:
            additions_hex.append({"amount": ad["amount"], "puzzle_hash": ad["puzzle_hash"].hex()})
            if "memos" in ad:
                additions_hex[-1]["memos"] = ad["memos"]

        request: Dict[str, Any] = {
            "additions": additions_hex,
            "fee": fee,
        }

        if coin_announcements is not None and len(coin_announcements) > 0:
            request["coin_announcements"] = [
                {
                    "coin_id": ann.origin_info.hex(),
                    "message": ann.message.hex(),
                    "morph_bytes": ann.morph_bytes.hex() if ann.morph_bytes is not None else b"".hex(),
                }
                for ann in coin_announcements
            ]

        if puzzle_announcements is not None and len(puzzle_announcements) > 0:
            request["puzzle_announcements"] = [
                {
                    "puzzle_hash": ann.origin_info.hex(),
                    "message": ann.message.hex(),
                    "morph_bytes": ann.morph_bytes.hex() if ann.morph_bytes is not None else b"".hex(),
                }
                for ann in puzzle_announcements
            ]

        if coins is not None and len(coins) > 0:
            coins_json = [c.to_json_dict() for c in coins]
            request["coins"] = coins_json

        response: Dict = await self.fetch("create_signed_transaction", request)
        return TransactionRecord.from_json_dict_convenience(response["signed_tx"])

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

    # CATS
    async def create_new_cat_and_wallet(self, amount: uint64) -> Dict:
        request: Dict[str, Any] = {
            "wallet_type": "cat_wallet",
            "mode": "new",
            "amount": amount,
            "host": f"{self.hostname}:{self.port}",
        }
        return await self.fetch("create_new_wallet", request)

    async def create_wallet_for_existing_cat(self, asset_id: bytes) -> Dict:
        request: Dict[str, Any] = {
            "wallet_type": "cat_wallet",
            "asset_id": asset_id.hex(),
            "mode": "existing",
            "host": f"{self.hostname}:{self.port}",
        }
        return await self.fetch("create_new_wallet", request)

    async def get_cat_asset_id(self, wallet_id: str) -> bytes:
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
        }
        return bytes.fromhex((await self.fetch("cat_get_asset_id", request))["asset_id"])

    async def cat_asset_id_to_name(self, asset_id: bytes32) -> Optional[Tuple[uint32, str]]:
        request: Dict[str, Any] = {
            "asset_id": asset_id.hex(),
        }
        try:
            res = await self.fetch("cat_asset_id_to_name", request)
            return uint32(int(res["wallet_id"])), res["name"]
        except Exception:
            return None

    async def get_cat_name(self, wallet_id: str) -> str:
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
        }
        return (await self.fetch("cat_get_name", request))["name"]

    async def set_cat_name(self, wallet_id: str, name: str) -> None:
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
            "name": name,
        }
        await self.fetch("cat_set_name", request)

    async def cat_spend(
        self,
        wallet_id: str,
        amount: uint64,
        inner_address: str,
        fee: uint64 = uint64(0),
        memos: Optional[List[str]] = None,
    ) -> TransactionRecord:
        send_dict = {
            "wallet_id": wallet_id,
            "amount": amount,
            "inner_address": inner_address,
            "fee": fee,
            "memos": memos if memos else [],
        }
        res = await self.fetch("cat_spend", send_dict)
        return TransactionRecord.from_json_dict_convenience(res["transaction"])

    # Offers
    async def create_offer_for_ids(
        self, offer_dict: Dict[uint32, int], fee=uint64(0), validate_only: bool = False
    ) -> Tuple[Optional[Offer], TradeRecord]:
        send_dict: Dict[str, int] = {}
        for key in offer_dict:
            send_dict[str(key)] = offer_dict[key]

        res = await self.fetch("create_offer_for_ids", {"offer": send_dict, "validate_only": validate_only, "fee": fee})
        offer: Optional[Offer] = None if validate_only else Offer.from_bytes(hexstr_to_bytes(res["offer"]))
        return offer, TradeRecord.from_json_dict_convenience(res["trade_record"], res["offer"])

    async def get_offer_summary(self, offer: Offer) -> Dict[str, Dict[str, int]]:
        res = await self.fetch("get_offer_summary", {"offer": bytes(offer).hex()})
        return res["summary"]

    async def check_offer_validity(self, offer: Offer) -> bool:
        res = await self.fetch("check_offer_validity", {"offer": bytes(offer).hex()})
        return res["valid"]

    async def take_offer(self, offer: Offer, fee=uint64(0)) -> TradeRecord:
        res = await self.fetch("take_offer", {"offer": bytes(offer).hex(), "fee": fee})
        return TradeRecord.from_json_dict_convenience(res["trade_record"])

    async def get_offer(self, trade_id: bytes32, file_contents: bool = False) -> TradeRecord:
        res = await self.fetch("get_offer", {"trade_id": trade_id.hex(), "file_contents": file_contents})
        offer_str = res["offer"] if file_contents else ""
        return TradeRecord.from_json_dict_convenience(res["trade_record"], offer_str)

    async def get_all_offers(
        self, start: int = 0, end: int = 50, sort_key: str = None, reverse: bool = False, file_contents: bool = False
    ) -> List[TradeRecord]:
        res = await self.fetch(
            "get_all_offers",
            {
                "start": start,
                "end": end,
                "sort_key": sort_key,
                "reverse": reverse,
                "file_contents": file_contents,
            },
        )

        records = []
        optional_offers = res["offers"] if file_contents else ([""] * len(res["trade_records"]))
        for record, offer in zip(res["trade_records"], optional_offers):
            records.append(TradeRecord.from_json_dict_convenience(record, offer))

        return records

    async def cancel_offer(self, trade_id: bytes32, fee=uint64(0), secure: bool = True):
        await self.fetch("cancel_offer", {"trade_id": trade_id.hex(), "secure": secure, "fee": fee})
