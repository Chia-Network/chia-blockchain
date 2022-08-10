from typing import Dict, List, Optional, Any, Tuple, Union

from chia.pools.pool_wallet_info import PoolWalletInfo
from chia.rpc.rpc_client import RpcClient
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.ints import uint32, uint64
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.transaction_sorting import SortKey
from chia.wallet.util.wallet_types import WalletType


def parse_result_transactions(result: Dict[str, Any]) -> Dict[str, Any]:
    result["transaction"] = TransactionRecord.from_json_dict(result["transaction"])
    if result["fee_transaction"]:
        result["fee_transaction"] = TransactionRecord.from_json_dict(result["fee_transaction"])
    return result


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
                {"fingerprint": fingerprint, "type": "start"},
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

    async def add_key(self, mnemonic: List[str], request_type: str = "new_wallet") -> Dict[str, Any]:
        return await self.fetch("add_key", {"mnemonic": mnemonic, "type": request_type})

    async def delete_key(self, fingerprint: int) -> Dict[str, Any]:
        return await self.fetch("delete_key", {"fingerprint": fingerprint})

    async def check_delete_key(self, fingerprint: int, max_ph_to_search: int = 100) -> Dict[str, Any]:
        return await self.fetch("check_delete_key", {"fingerprint": fingerprint, "max_ph_to_search": max_ph_to_search})

    async def delete_all_keys(self) -> Dict[str, Any]:
        return await self.fetch("delete_all_keys", {})

    # Wallet Node APIs
    async def get_sync_status(self) -> bool:
        return (await self.fetch("get_sync_status", {}))["syncing"]

    async def get_synced(self) -> bool:
        return (await self.fetch("get_sync_status", {}))["synced"]

    async def get_height_info(self) -> uint32:
        return (await self.fetch("get_height_info", {}))["height"]

    async def push_tx(self, spend_bundle):
        return await self.fetch("push_tx", {"spend_bundle": bytes(spend_bundle).hex()})

    async def farm_block(self, address: str) -> Dict[str, Any]:
        return await self.fetch("farm_block", {"address": address})

    # Wallet Management APIs
    async def get_wallets(self, wallet_type: Optional[WalletType] = None) -> Dict:
        request: Dict[str, Any] = {}
        if wallet_type is not None:
            request["type"] = wallet_type
        return (await self.fetch("get_wallets", request))["wallets"]

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
        to_address: Optional[str] = None,
    ) -> List[TransactionRecord]:
        request: Dict[str, Any] = {"wallet_id": wallet_id}

        if start is not None:
            request["start"] = start
        if end is not None:
            request["end"] = end
        if sort_key is not None:
            request["sort_key"] = sort_key.name
        request["reverse"] = reverse

        if to_address is not None:
            request["to_address"] = to_address

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
        self,
        wallet_id: str,
        amount: uint64,
        address: str,
        fee: uint64 = uint64(0),
        memos: Optional[List[str]] = None,
        min_coin_amount: uint64 = uint64(0),
    ) -> TransactionRecord:
        if memos is None:
            send_dict: Dict = {
                "wallet_id": wallet_id,
                "amount": amount,
                "address": address,
                "fee": fee,
                "min_coin_amount": min_coin_amount,
            }
        else:
            send_dict = {
                "wallet_id": wallet_id,
                "amount": amount,
                "address": address,
                "fee": fee,
                "memos": memos,
                "min_coin_amount": min_coin_amount,
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

    async def get_current_derivation_index(self) -> str:
        return (await self.fetch("get_current_derivation_index", {}))["index"]

    async def extend_derivation_index(self, index: int) -> str:
        return (await self.fetch("extend_derivation_index", {"index": index}))["index"]

    async def get_farmed_amount(self) -> Dict:
        return await self.fetch("get_farmed_amount", {})

    async def create_signed_transaction(
        self,
        additions: List[Dict],
        coins: List[Coin] = None,
        fee: uint64 = uint64(0),
        coin_announcements: Optional[List[Announcement]] = None,
        puzzle_announcements: Optional[List[Announcement]] = None,
        min_coin_amount: uint64 = uint64(0),
        exclude_coins: Optional[List[Coin]] = None,
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
            "min_coin_amount": min_coin_amount,
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

        if exclude_coins is not None and len(exclude_coins) > 0:
            exclude_coins_json = [exclude_coin.to_json_dict() for exclude_coin in exclude_coins]
            request["exclude_coins"] = exclude_coins_json

        response: Dict = await self.fetch("create_signed_transaction", request)
        return TransactionRecord.from_json_dict_convenience(response["signed_tx"])

    async def select_coins(
        self,
        *,
        amount: int,
        wallet_id: int,
        excluded_coins: Optional[List[Coin]] = None,
        min_coin_amount: uint64 = uint64(0),
    ) -> List[Coin]:
        if excluded_coins is None:
            excluded_coins = []
        request = {
            "amount": amount,
            "wallet_id": wallet_id,
            "min_coin_amount": min_coin_amount,
            "excluded_coins": [excluded_coin.to_json_dict() for excluded_coin in excluded_coins],
        }
        response: Dict[str, List[Dict]] = await self.fetch("select_coins", request)
        return [Coin.from_json_dict(coin) for coin in response["coins"]]

    # DID wallet
    async def create_new_did_wallet(
        self,
        amount: int,
        fee: int = 0,
        name: Optional[str] = "DID Wallet",
        backup_ids: List[str] = [],
        required_num: int = 0,
    ) -> Dict:
        request: Dict[str, Any] = {
            "wallet_type": "did_wallet",
            "did_type": "new",
            "backup_dids": backup_ids,
            "num_of_backup_ids_needed": required_num,
            "amount": amount,
            "fee": fee,
            "wallet_name": name,
        }
        response = await self.fetch("create_new_wallet", request)
        return response

    async def get_did_id(self, wallet_id: int) -> Dict:
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
        }
        response = await self.fetch("did_get_did", request)
        return response

    async def create_did_backup_file(self, wallet_id: int, filename: str) -> Dict:
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
            "filename": filename,
        }
        response = await self.fetch("did_create_backup_file", request)
        return response

    async def update_did_recovery_list(self, wallet_id: int, recovery_list: List[str], num_verification: int) -> Dict:
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
            "new_list": recovery_list,
            "num_verifications_required": num_verification,
        }
        response = await self.fetch("did_update_recovery_ids", request)
        return response

    async def get_did_recovery_list(self, wallet_id: int) -> Dict:
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
        }
        response = await self.fetch("did_get_recovery_list", request)
        return response

    async def update_did_metadata(self, wallet_id: int, metadata: Dict) -> Dict:
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
            "metadata": metadata,
        }
        response = await self.fetch("did_update_metadata", request)
        return response

    async def get_did_metadata(self, wallet_id: int) -> Dict:
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
        }
        response = await self.fetch("did_get_metadata", request)
        return response

    async def create_new_did_wallet_from_recovery(self, filename: str) -> Dict:
        request: Dict[str, Any] = {
            "wallet_type": "did_wallet",
            "did_type": "recovery",
            "filename": filename,
        }
        response = await self.fetch("create_new_wallet", request)
        return response

    async def did_create_attest(
        self, wallet_id: int, coin_name: str, pubkey: str, puzhash: str, file_name: str
    ) -> Dict:
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
            "coin_name": coin_name,
            "pubkey": pubkey,
            "puzhash": puzhash,
            "filename": file_name,
        }
        response = await self.fetch("did_create_attest", request)
        return response

    async def did_recovery_spend(self, wallet_id: int, attest_filenames: str) -> Dict:
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
            "attest_filenames": attest_filenames,
        }
        response = await self.fetch("did_recovery_spend", request)
        return response

    async def did_transfer_did(self, wallet_id: int, address: str, fee: int, with_recovery: bool) -> Dict:
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
            "inner_address": address,
            "fee": fee,
            "with_recovery_info": with_recovery,
        }
        response = await self.fetch("did_transfer_did", request)
        return response

    async def did_set_wallet_name(self, wallet_id: int, name: str) -> Dict:
        request = {"wallet_id": wallet_id, "name": name}
        response = await self.fetch("did_set_wallet_name", request)
        return response

    async def did_get_wallet_name(self, wallet_id: int) -> Dict:
        request = {"wallet_id": wallet_id}
        response = await self.fetch("did_get_wallet_name", request)
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

    async def pw_self_pool(self, wallet_id: str, fee: uint64) -> Dict:
        reply = await self.fetch("pw_self_pool", {"wallet_id": wallet_id, "fee": fee})
        reply = parse_result_transactions(reply)
        return reply

    async def pw_join_pool(
        self, wallet_id: str, target_puzzlehash: bytes32, pool_url: str, relative_lock_height: uint32, fee: uint64
    ) -> Dict:
        request = {
            "wallet_id": int(wallet_id),
            "target_puzzlehash": target_puzzlehash.hex(),
            "relative_lock_height": relative_lock_height,
            "pool_url": pool_url,
            "fee": fee,
        }

        reply = await self.fetch("pw_join_pool", request)
        reply = parse_result_transactions(reply)
        return reply

    async def pw_absorb_rewards(
        self, wallet_id: str, fee: uint64 = uint64(0), max_spends_in_tx: Optional[int] = None
    ) -> Dict:
        reply = await self.fetch(
            "pw_absorb_rewards", {"wallet_id": wallet_id, "fee": fee, "max_spends_in_tx": max_spends_in_tx}
        )
        reply["state"] = PoolWalletInfo.from_json_dict(reply["state"])
        reply = parse_result_transactions(reply)
        return reply

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
        }
        return await self.fetch("create_new_wallet", request)

    async def create_wallet_for_existing_cat(self, asset_id: bytes) -> Dict:
        request: Dict[str, Any] = {
            "wallet_type": "cat_wallet",
            "asset_id": asset_id.hex(),
            "mode": "existing",
        }
        return await self.fetch("create_new_wallet", request)

    async def get_cat_asset_id(self, wallet_id: str) -> bytes32:
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
        }
        return bytes32.from_hexstr((await self.fetch("cat_get_asset_id", request))["asset_id"])

    async def get_stray_cats(self) -> Dict:
        response = await self.fetch("get_stray_cats", {})
        return response["stray_cats"]

    async def cat_asset_id_to_name(self, asset_id: bytes32) -> Optional[Tuple[Optional[uint32], str]]:
        request: Dict[str, Any] = {
            "asset_id": asset_id.hex(),
        }
        try:
            res = await self.fetch("cat_asset_id_to_name", request)
        except ValueError:
            return None

        wallet_id: Optional[uint32] = None if res["wallet_id"] is None else uint32(int(res["wallet_id"]))
        return wallet_id, res["name"]

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
        min_coin_amount: uint64 = uint64(0),
    ) -> TransactionRecord:
        send_dict = {
            "wallet_id": wallet_id,
            "amount": amount,
            "inner_address": inner_address,
            "fee": fee,
            "memos": memos if memos else [],
            "min_coin_amount": min_coin_amount,
        }
        res = await self.fetch("cat_spend", send_dict)
        return TransactionRecord.from_json_dict_convenience(res["transaction"])

    # Offers
    async def create_offer_for_ids(
        self,
        offer_dict: Dict[Union[uint32, str], int],
        driver_dict: Dict[str, Any] = None,
        fee=uint64(0),
        validate_only: bool = False,
        min_coin_amount: uint64 = uint64(0),
    ) -> Tuple[Optional[Offer], TradeRecord]:
        send_dict: Dict[str, int] = {}
        for key in offer_dict:
            send_dict[str(key)] = offer_dict[key]

        req = {
            "offer": send_dict,
            "validate_only": validate_only,
            "fee": fee,
            "min_coin_amount": min_coin_amount,
        }
        if driver_dict is not None:
            req["driver_dict"] = driver_dict
        res = await self.fetch("create_offer_for_ids", req)
        offer: Optional[Offer] = None if validate_only else Offer.from_bech32(res["offer"])
        offer_str: str = "" if offer is None else bytes(offer).hex()
        return offer, TradeRecord.from_json_dict_convenience(res["trade_record"], offer_str)

    async def get_offer_summary(self, offer: Offer) -> Dict[str, Dict[str, int]]:
        res = await self.fetch("get_offer_summary", {"offer": offer.to_bech32()})
        return res["summary"]

    async def check_offer_validity(self, offer: Offer) -> bool:
        res = await self.fetch("check_offer_validity", {"offer": offer.to_bech32()})
        return res["valid"]

    async def take_offer(self, offer: Offer, fee=uint64(0), min_coin_amount: uint64 = uint64(0)) -> TradeRecord:
        res = await self.fetch(
            "take_offer", {"offer": offer.to_bech32(), "fee": fee, "min_coin_amount": min_coin_amount}
        )
        return TradeRecord.from_json_dict_convenience(res["trade_record"])

    async def get_offer(self, trade_id: bytes32, file_contents: bool = False) -> TradeRecord:
        res = await self.fetch("get_offer", {"trade_id": trade_id.hex(), "file_contents": file_contents})
        offer_str = bytes(Offer.from_bech32(res["offer"])).hex() if file_contents else ""
        return TradeRecord.from_json_dict_convenience(res["trade_record"], offer_str)

    async def get_all_offers(
        self,
        start: int = 0,
        end: int = 50,
        sort_key: str = None,
        reverse: bool = False,
        file_contents: bool = False,
        exclude_my_offers: bool = False,
        exclude_taken_offers: bool = False,
        include_completed: bool = False,
    ) -> List[TradeRecord]:
        res = await self.fetch(
            "get_all_offers",
            {
                "start": start,
                "end": end,
                "sort_key": sort_key,
                "reverse": reverse,
                "file_contents": file_contents,
                "exclude_my_offers": exclude_my_offers,
                "exclude_taken_offers": exclude_taken_offers,
                "include_completed": include_completed,
            },
        )

        records = []
        if file_contents:
            optional_offers = [bytes(Offer.from_bech32(o)).hex() for o in res["offers"]]
        else:
            optional_offers = [""] * len(res["trade_records"])
        for record, offer in zip(res["trade_records"], optional_offers):
            records.append(TradeRecord.from_json_dict_convenience(record, offer))

        return records

    async def cancel_offer(self, trade_id: bytes32, fee=uint64(0), secure: bool = True):
        await self.fetch("cancel_offer", {"trade_id": trade_id.hex(), "secure": secure, "fee": fee})

    # NFT wallet
    async def create_new_nft_wallet(self, did_id, name=None):
        request: Dict[str, Any] = {
            "wallet_type": "nft_wallet",
            "did_id": did_id,
            "name": name,
        }
        response = await self.fetch("create_new_wallet", request)
        return response

    async def mint_nft(
        self,
        wallet_id,
        royalty_address,
        target_address,
        hash,
        uris,
        meta_hash="",
        meta_uris=[],
        license_hash="",
        license_uris=[],
        edition_total=1,
        edition_number=1,
        fee=0,
        royalty_percentage=0,
        did_id=None,
    ):
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
            "royalty_address": royalty_address,
            "target_address": target_address,
            "hash": hash,
            "uris": uris,
            "meta_hash": meta_hash,
            "meta_uris": meta_uris,
            "license_hash": license_hash,
            "license_uris": license_uris,
            "edition_number": edition_number,
            "edition_total": edition_total,
            "royalty_percentage": royalty_percentage,
            "did_id": did_id,
            "fee": fee,
        }
        response = await self.fetch("nft_mint_nft", request)
        return response

    async def add_uri_to_nft(self, wallet_id, nft_coin_id, key, uri, fee):
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
            "nft_coin_id": nft_coin_id,
            "uri": uri,
            "key": key,
            "fee": fee,
        }
        response = await self.fetch("nft_add_uri", request)
        return response

    async def get_nft_info(self, coin_id: str, latest: bool = True):
        request: Dict[str, Any] = {"coin_id": coin_id, "latest": latest}
        response = await self.fetch("nft_get_info", request)
        return response

    async def transfer_nft(self, wallet_id, nft_coin_id, target_address, fee):
        request: Dict[str, Any] = {
            "wallet_id": wallet_id,
            "nft_coin_id": nft_coin_id,
            "target_address": target_address,
            "fee": fee,
        }
        response = await self.fetch("nft_transfer_nft", request)
        return response

    async def list_nfts(self, wallet_id):
        request: Dict[str, Any] = {"wallet_id": wallet_id}
        response = await self.fetch("nft_get_nfts", request)
        return response

    async def set_nft_did(self, wallet_id, did_id, nft_coin_id, fee):
        request: Dict[str, Any] = {"wallet_id": wallet_id, "did_id": did_id, "nft_coin_id": nft_coin_id, "fee": fee}
        response = await self.fetch("nft_set_nft_did", request)
        return response

    async def get_nft_wallet_did(self, wallet_id):
        request: Dict[str, Any] = {"wallet_id": wallet_id}
        response = await self.fetch("nft_get_wallet_did", request)
        return response
