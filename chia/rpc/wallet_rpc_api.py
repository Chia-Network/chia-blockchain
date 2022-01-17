import asyncio
import logging
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Set, Any

from blspy import PrivateKey, G1Element

from chia.consensus.block_rewards import calculate_base_farmer_reward
from chia.pools.pool_wallet import PoolWallet
from chia.pools.pool_wallet_info import create_pool_state, FARMING_TO_POOL, PoolWalletInfo, PoolState
from chia.protocols.protocol_message_types import ProtocolMessageTypes
from chia.server.outbound_message import NodeType, make_msg
from chia.simulator.simulator_protocol import FarmNewBlockProtocol
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint32, uint64
from chia.util.keychain import KeyringIsLocked, bytes_to_mnemonic, generate_mnemonic
from chia.util.path import path_from_root
from chia.util.ws_message import WsRpcMessage, create_payload_dict
from chia.wallet.cat_wallet.cat_constants import DEFAULT_CATS
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.derive_keys import master_sk_to_singleton_owner_sk, master_sk_to_wallet_sk_unhardened
from chia.wallet.rl_wallet.rl_wallet import RLWallet
from chia.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_pool_sk, master_sk_to_wallet_sk
from chia.wallet.did_wallet.did_wallet import DIDWallet
from chia.wallet.trade_record import TradeRecord
from chia.wallet.trading.offer import Offer
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import AmountWithPuzzlehash, WalletType
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_node import WalletNode
from chia.util.config import load_config
from chia.consensus.coinbase import create_puzzlehash_for_pk

# Timeout for response from wallet/full node for sending a transaction
TIMEOUT = 30

log = logging.getLogger(__name__)


class WalletRpcApi:
    def __init__(self, wallet_node: WalletNode):
        assert wallet_node is not None
        self.service = wallet_node
        self.service_name = "chia_wallet"
        self.balance_cache: Dict[int, Any] = {}

    def get_routes(self) -> Dict[str, Callable]:
        return {
            # Key management
            "/log_in": self.log_in,
            "/get_logged_in_fingerprint": self.get_logged_in_fingerprint,
            "/get_public_keys": self.get_public_keys,
            "/get_private_key": self.get_private_key,
            "/generate_mnemonic": self.generate_mnemonic,
            "/add_key": self.add_key,
            "/delete_key": self.delete_key,
            "/check_delete_key": self.check_delete_key,
            "/delete_all_keys": self.delete_all_keys,
            # Wallet node
            "/get_sync_status": self.get_sync_status,
            "/get_height_info": self.get_height_info,
            "/farm_block": self.farm_block,  # Only when node simulator is running
            # this function is just here for backwards-compatibility. It will probably
            # be removed in the future
            "/get_initial_freeze_period": self.get_initial_freeze_period,
            "/get_network_info": self.get_network_info,
            # Wallet management
            "/get_wallets": self.get_wallets,
            "/create_new_wallet": self.create_new_wallet,
            # Wallet
            "/get_wallet_balance": self.get_wallet_balance,
            "/get_transaction": self.get_transaction,
            "/get_transactions": self.get_transactions,
            "/get_transaction_count": self.get_transaction_count,
            "/get_next_address": self.get_next_address,
            "/send_transaction": self.send_transaction,
            "/send_transaction_multi": self.send_transaction_multi,
            "/get_farmed_amount": self.get_farmed_amount,
            "/create_signed_transaction": self.create_signed_transaction,
            "/delete_unconfirmed_transactions": self.delete_unconfirmed_transactions,
            # Coloured coins and trading
            "/cat_set_name": self.cat_set_name,
            "/cat_asset_id_to_name": self.cat_asset_id_to_name,
            "/cat_get_name": self.cat_get_name,
            "/cat_spend": self.cat_spend,
            "/cat_get_asset_id": self.cat_get_asset_id,
            "/create_offer_for_ids": self.create_offer_for_ids,
            "/get_offer_summary": self.get_offer_summary,
            "/check_offer_validity": self.check_offer_validity,
            "/take_offer": self.take_offer,
            "/get_offer": self.get_offer,
            "/get_all_offers": self.get_all_offers,
            "/cancel_offer": self.cancel_offer,
            "/get_cat_list": self.get_cat_list,
            # DID Wallet
            "/did_update_recovery_ids": self.did_update_recovery_ids,
            "/did_get_pubkey": self.did_get_pubkey,
            "/did_get_did": self.did_get_did,
            "/did_recovery_spend": self.did_recovery_spend,
            "/did_get_recovery_list": self.did_get_recovery_list,
            "/did_create_attest": self.did_create_attest,
            "/did_get_information_needed_for_recovery": self.did_get_information_needed_for_recovery,
            "/did_create_backup_file": self.did_create_backup_file,
            # RL wallet
            "/rl_set_user_info": self.rl_set_user_info,
            "/send_clawback_transaction:": self.send_clawback_transaction,
            "/add_rate_limited_funds:": self.add_rate_limited_funds,
            # Pool Wallet
            "/pw_join_pool": self.pw_join_pool,
            "/pw_self_pool": self.pw_self_pool,
            "/pw_absorb_rewards": self.pw_absorb_rewards,
            "/pw_status": self.pw_status,
        }

    async def _state_changed(self, *args) -> List[WsRpcMessage]:
        """
        Called by the WalletNode or WalletStateManager when something has changed in the wallet. This
        gives us an opportunity to send notifications to all connected clients via WebSocket.
        """
        if len(args) < 2:
            return []

        data = {
            "state": args[0],
        }
        if args[1] is not None:
            data["wallet_id"] = args[1]
        if args[2] is not None:
            data["additional_data"] = args[2]
        return [create_payload_dict("state_changed", data, "chia_wallet", "wallet_ui")]

    async def _stop_wallet(self):
        """
        Stops a currently running wallet/key, which allows starting the wallet with a new key.
        Each key has it's own wallet database.
        """
        if self.service is not None:
            self.service._close()
            peers_close_task: Optional[asyncio.Task] = await self.service._await_closed()
            if peers_close_task is not None:
                await peers_close_task

    ##########################################################################################
    # Key management
    ##########################################################################################

    async def log_in(self, request):
        """
        Logs in the wallet with a specific key.
        """

        fingerprint = request["fingerprint"]
        if self.service.logged_in_fingerprint == fingerprint:
            return {"fingerprint": fingerprint}

        await self._stop_wallet()
        started = await self.service._start(fingerprint)
        if started is True:
            return {"fingerprint": fingerprint}

        return {"success": False, "error": "Unknown Error"}

    async def get_logged_in_fingerprint(self, request: Dict):
        return {"fingerprint": self.service.logged_in_fingerprint}

    async def get_public_keys(self, request: Dict):
        try:
            assert self.service.keychain_proxy is not None  # An offering to the mypy gods
            fingerprints = [
                sk.get_g1().get_fingerprint() for (sk, seed) in await self.service.keychain_proxy.get_all_private_keys()
            ]
        except KeyringIsLocked:
            return {"keyring_is_locked": True}
        except Exception:
            return {"public_key_fingerprints": []}
        else:
            return {"public_key_fingerprints": fingerprints}

    async def _get_private_key(self, fingerprint) -> Tuple[Optional[PrivateKey], Optional[bytes]]:
        try:
            assert self.service.keychain_proxy is not None  # An offering to the mypy gods
            all_keys = await self.service.keychain_proxy.get_all_private_keys()
            for sk, seed in all_keys:
                if sk.get_g1().get_fingerprint() == fingerprint:
                    return sk, seed
        except Exception as e:
            log.error(f"Failed to get private key by fingerprint: {e}")
        return None, None

    async def get_private_key(self, request):
        fingerprint = request["fingerprint"]
        sk, seed = await self._get_private_key(fingerprint)
        if sk is not None:
            s = bytes_to_mnemonic(seed) if seed is not None else None
            return {
                "private_key": {
                    "fingerprint": fingerprint,
                    "sk": bytes(sk).hex(),
                    "pk": bytes(sk.get_g1()).hex(),
                    "farmer_pk": bytes(master_sk_to_farmer_sk(sk).get_g1()).hex(),
                    "pool_pk": bytes(master_sk_to_pool_sk(sk).get_g1()).hex(),
                    "seed": s,
                },
            }
        return {"success": False, "private_key": {"fingerprint": fingerprint}}

    async def generate_mnemonic(self, request: Dict):
        return {"mnemonic": generate_mnemonic().split(" ")}

    async def add_key(self, request):
        if "mnemonic" not in request:
            raise ValueError("Mnemonic not in request")

        # Adding a key from 24 word mnemonic
        mnemonic = request["mnemonic"]
        passphrase = ""
        try:
            sk = await self.service.keychain_proxy.add_private_key(" ".join(mnemonic), passphrase)
        except KeyError as e:
            return {
                "success": False,
                "error": f"The word '{e.args[0]}' is incorrect.'",
                "word": e.args[0],
            }
        except Exception as e:
            return {"success": False, "error": str(e)}

        fingerprint = sk.get_g1().get_fingerprint()
        await self._stop_wallet()

        # Makes sure the new key is added to config properly
        started = False
        try:
            await self.service.keychain_proxy.check_keys(self.service.root_path)
        except Exception as e:
            log.error(f"Failed to check_keys after adding a new key: {e}")
        started = await self.service._start(fingerprint=fingerprint)
        if started is True:
            return {"fingerprint": fingerprint}
        raise ValueError("Failed to start")

    async def delete_key(self, request):
        await self._stop_wallet()
        fingerprint = request["fingerprint"]
        try:
            await self.service.keychain_proxy.delete_key_by_fingerprint(fingerprint)
        except Exception as e:
            log.error(f"Failed to delete key by fingerprint: {e}")
            return {"success": False, "error": str(e)}
        path = path_from_root(
            self.service.root_path,
            f"{self.service.config['database_path']}-{fingerprint}",
        )
        if path.exists():
            path.unlink()
        return {}

    async def _check_key_used_for_rewards(
        self, new_root: Path, sk: PrivateKey, max_ph_to_search: int
    ) -> Tuple[bool, bool]:
        """Checks if the given key is used for either the farmer rewards or pool rewards
        returns a tuple of two booleans
        The first is true if the key is used as the Farmer rewards, otherwise false
        The second is true if the key is used as the Pool rewards, otherwise false
        Returns both false if the key cannot be found with the given fingerprint
        """
        if sk is None:
            return False, False

        config: Dict = load_config(new_root, "config.yaml")
        farmer_target = config["farmer"].get("xch_target_address")
        pool_target = config["pool"].get("xch_target_address")
        found_farmer = False
        found_pool = False
        selected = config["selected_network"]
        prefix = config["network_overrides"]["config"][selected]["address_prefix"]
        for i in range(max_ph_to_search):
            if found_farmer and found_pool:
                break

            phs = [
                encode_puzzle_hash(create_puzzlehash_for_pk(master_sk_to_wallet_sk(sk, uint32(i)).get_g1()), prefix),
                encode_puzzle_hash(
                    create_puzzlehash_for_pk(master_sk_to_wallet_sk_unhardened(sk, uint32(i)).get_g1()), prefix
                ),
            ]
            for ph in phs:
                if ph == farmer_target:
                    found_farmer = True
                if ph == pool_target:
                    found_pool = True

        return found_farmer, found_pool

    async def check_delete_key(self, request):
        """Check the key use prior to possible deletion
        checks whether key is used for either farm or pool rewards
        checks if any wallets have a non-zero balance
        """
        used_for_farmer: bool = False
        used_for_pool: bool = False
        walletBalance: bool = False

        fingerprint = request["fingerprint"]
        sk, _ = await self._get_private_key(fingerprint)
        if sk is not None:
            used_for_farmer, used_for_pool = await self._check_key_used_for_rewards(self.service.root_path, sk, 100)

            if self.service.logged_in_fingerprint != fingerprint:
                await self._stop_wallet()
                await self.service._start(fingerprint=fingerprint)

            wallets: List[WalletInfo] = await self.service.wallet_state_manager.get_all_wallet_info_entries()
            for w in wallets:
                wallet = self.service.wallet_state_manager.wallets[w.id]
                unspent = await self.service.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(w.id)
                balance = await wallet.get_confirmed_balance(unspent)
                pending_balance = await wallet.get_unconfirmed_balance(unspent)

                if (balance + pending_balance) > 0:
                    walletBalance = True
                    break

        return {
            "fingerprint": fingerprint,
            "used_for_farmer_rewards": used_for_farmer,
            "used_for_pool_rewards": used_for_pool,
            "wallet_balance": walletBalance,
        }

    async def delete_all_keys(self, request: Dict):
        await self._stop_wallet()
        try:
            assert self.service.keychain_proxy is not None  # An offering to the mypy gods
            await self.service.keychain_proxy.delete_all_keys()
        except Exception as e:
            log.error(f"Failed to delete all keys: {e}")
            return {"success": False, "error": str(e)}
        path = path_from_root(self.service.root_path, self.service.config["database_path"])
        if path.exists():
            path.unlink()
        return {}

    ##########################################################################################
    # Wallet Node
    ##########################################################################################

    async def get_sync_status(self, request: Dict):
        assert self.service.wallet_state_manager is not None
        syncing = self.service.wallet_state_manager.sync_mode
        synced = await self.service.wallet_state_manager.synced()
        return {"synced": synced, "syncing": syncing, "genesis_initialized": True}

    async def get_height_info(self, request: Dict):
        assert self.service.wallet_state_manager is not None
        height = self.service.wallet_state_manager.blockchain.get_peak_height()
        return {"height": height}

    async def get_network_info(self, request: Dict):
        assert self.service.wallet_state_manager is not None
        network_name = self.service.config["selected_network"]
        address_prefix = self.service.config["network_overrides"]["config"][network_name]["address_prefix"]
        return {"network_name": network_name, "network_prefix": address_prefix}

    async def farm_block(self, request):
        raw_puzzle_hash = decode_puzzle_hash(request["address"])
        request = FarmNewBlockProtocol(raw_puzzle_hash)
        msg = make_msg(ProtocolMessageTypes.farm_new_block, request)

        await self.service.server.send_to_all([msg], NodeType.FULL_NODE)
        return {}

    ##########################################################################################
    # Wallet Management
    ##########################################################################################

    async def get_wallets(self, request: Dict):
        assert self.service.wallet_state_manager is not None

        wallets: List[WalletInfo] = await self.service.wallet_state_manager.get_all_wallet_info_entries()

        return {"wallets": wallets}

    async def create_new_wallet(self, request: Dict):
        assert self.service.wallet_state_manager is not None
        wallet_state_manager = self.service.wallet_state_manager

        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced.")
        main_wallet = wallet_state_manager.main_wallet
        fee = uint64(request.get("fee", 0))

        if request["wallet_type"] == "cat_wallet":
            name = request.get("name", "CAT Wallet")
            if request["mode"] == "new":
                async with self.service.wallet_state_manager.lock:
                    cat_wallet: CATWallet = await CATWallet.create_new_cat_wallet(
                        wallet_state_manager,
                        main_wallet,
                        {"identifier": "genesis_by_id"},
                        uint64(request["amount"]),
                        name,
                    )
                    asset_id = cat_wallet.get_asset_id()
                self.service.wallet_state_manager.state_changed("wallet_created")
                return {"type": cat_wallet.type(), "asset_id": asset_id, "wallet_id": cat_wallet.id()}

            elif request["mode"] == "existing":
                async with self.service.wallet_state_manager.lock:
                    cat_wallet = await CATWallet.create_wallet_for_cat(
                        wallet_state_manager, main_wallet, request["asset_id"]
                    )
                self.service.wallet_state_manager.state_changed("wallet_created")
                return {"type": cat_wallet.type(), "asset_id": request["asset_id"], "wallet_id": cat_wallet.id()}

            else:  # undefined mode
                pass

        elif request["wallet_type"] == "rl_wallet":
            if request["rl_type"] == "admin":
                log.info("Create rl admin wallet")
                async with self.service.wallet_state_manager.lock:
                    rl_admin: RLWallet = await RLWallet.create_rl_admin(wallet_state_manager)
                    success = await rl_admin.admin_create_coin(
                        uint64(int(request["interval"])),
                        uint64(int(request["limit"])),
                        request["pubkey"],
                        uint64(int(request["amount"])),
                        uint64(int(request["fee"])) if "fee" in request else uint64(0),
                    )
                assert rl_admin.rl_info.admin_pubkey is not None
                return {
                    "success": success,
                    "id": rl_admin.id(),
                    "type": rl_admin.type(),
                    "origin": rl_admin.rl_info.rl_origin,
                    "pubkey": rl_admin.rl_info.admin_pubkey.hex(),
                }

            elif request["rl_type"] == "user":
                log.info("Create rl user wallet")
                async with self.service.wallet_state_manager.lock:
                    rl_user: RLWallet = await RLWallet.create_rl_user(wallet_state_manager)
                assert rl_user.rl_info.user_pubkey is not None
                return {
                    "id": rl_user.id(),
                    "type": rl_user.type(),
                    "pubkey": rl_user.rl_info.user_pubkey.hex(),
                }

            else:  # undefined rl_type
                pass

        elif request["wallet_type"] == "did_wallet":
            if request["did_type"] == "new":
                backup_dids = []
                num_needed = 0
                for d in request["backup_dids"]:
                    backup_dids.append(hexstr_to_bytes(d))
                if len(backup_dids) > 0:
                    num_needed = uint64(request["num_of_backup_ids_needed"])
                async with self.service.wallet_state_manager.lock:
                    did_wallet: DIDWallet = await DIDWallet.create_new_did_wallet(
                        wallet_state_manager,
                        main_wallet,
                        uint64(request["amount"]),
                        backup_dids,
                        uint64(num_needed),
                    )
                my_did = did_wallet.get_my_DID()
                return {
                    "success": True,
                    "type": did_wallet.type(),
                    "my_did": my_did,
                    "wallet_id": did_wallet.id(),
                }

            elif request["did_type"] == "recovery":
                async with self.service.wallet_state_manager.lock:
                    did_wallet = await DIDWallet.create_new_did_wallet_from_recovery(
                        wallet_state_manager, main_wallet, request["filename"]
                    )
                assert did_wallet.did_info.temp_coin is not None
                assert did_wallet.did_info.temp_puzhash is not None
                assert did_wallet.did_info.temp_pubkey is not None
                my_did = did_wallet.get_my_DID()
                coin_name = did_wallet.did_info.temp_coin.name().hex()
                coin_list = did_wallet.did_info.temp_coin.as_list()
                newpuzhash = did_wallet.did_info.temp_puzhash
                pubkey = did_wallet.did_info.temp_pubkey
                return {
                    "success": True,
                    "type": did_wallet.type(),
                    "my_did": my_did,
                    "wallet_id": did_wallet.id(),
                    "coin_name": coin_name,
                    "coin_list": coin_list,
                    "newpuzhash": newpuzhash.hex(),
                    "pubkey": pubkey.hex(),
                    "backup_dids": did_wallet.did_info.backup_ids,
                    "num_verifications_required": did_wallet.did_info.num_of_backup_ids_needed,
                }
            else:  # undefined did_type
                pass

        elif request["wallet_type"] == "pool_wallet":
            if request["mode"] == "new":
                owner_puzzle_hash: bytes32 = await self.service.wallet_state_manager.main_wallet.get_puzzle_hash(True)

                from chia.pools.pool_wallet_info import initial_pool_state_from_dict

                async with self.service.wallet_state_manager.lock:
                    last_wallet: Optional[
                        WalletInfo
                    ] = await self.service.wallet_state_manager.user_store.get_last_wallet()
                    assert last_wallet is not None

                    next_id = last_wallet.id + 1
                    owner_sk: PrivateKey = master_sk_to_singleton_owner_sk(
                        self.service.wallet_state_manager.private_key, uint32(next_id)
                    )
                    owner_pk: G1Element = owner_sk.get_g1()

                    initial_target_state = initial_pool_state_from_dict(
                        request["initial_target_state"], owner_pk, owner_puzzle_hash
                    )
                    assert initial_target_state is not None

                    try:
                        delayed_address = None
                        if "p2_singleton_delayed_ph" in request:
                            delayed_address = bytes32.from_hexstr(request["p2_singleton_delayed_ph"])
                        tr, p2_singleton_puzzle_hash, launcher_id = await PoolWallet.create_new_pool_wallet_transaction(
                            wallet_state_manager,
                            main_wallet,
                            initial_target_state,
                            fee,
                            request.get("p2_singleton_delay_time", None),
                            delayed_address,
                        )
                    except Exception as e:
                        raise ValueError(str(e))
                    return {
                        "total_fee": fee * 2,
                        "transaction": tr,
                        "launcher_id": launcher_id.hex(),
                        "p2_singleton_puzzle_hash": p2_singleton_puzzle_hash.hex(),
                    }
            elif request["mode"] == "recovery":
                raise ValueError("Need upgraded singleton for on-chain recovery")

        else:  # undefined wallet_type
            pass

        return None

    ##########################################################################################
    # Wallet
    ##########################################################################################

    async def get_wallet_balance(self, request: Dict) -> Dict:
        assert self.service.wallet_state_manager is not None
        wallet_id = uint32(int(request["wallet_id"]))
        wallet = self.service.wallet_state_manager.wallets[wallet_id]

        # If syncing return the last available info or 0s
        syncing = self.service.wallet_state_manager.sync_mode
        if syncing:
            if wallet_id in self.balance_cache:
                wallet_balance = self.balance_cache[wallet_id]
            else:
                wallet_balance = {
                    "wallet_id": wallet_id,
                    "confirmed_wallet_balance": 0,
                    "unconfirmed_wallet_balance": 0,
                    "spendable_balance": 0,
                    "pending_change": 0,
                    "max_send_amount": 0,
                    "unspent_coin_count": 0,
                    "pending_coin_removal_count": 0,
                }
        else:
            async with self.service.wallet_state_manager.lock:
                unspent_records = await self.service.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(
                    wallet_id
                )
                balance = await wallet.get_confirmed_balance(unspent_records)
                pending_balance = await wallet.get_unconfirmed_balance(unspent_records)
                spendable_balance = await wallet.get_spendable_balance(unspent_records)
                pending_change = await wallet.get_pending_change_balance()
                max_send_amount = await wallet.get_max_send_amount(unspent_records)

                unconfirmed_removals: Dict[
                    bytes32, Coin
                ] = await wallet.wallet_state_manager.unconfirmed_removals_for_wallet(wallet_id)
                wallet_balance = {
                    "wallet_id": wallet_id,
                    "confirmed_wallet_balance": balance,
                    "unconfirmed_wallet_balance": pending_balance,
                    "spendable_balance": spendable_balance,
                    "pending_change": pending_change,
                    "max_send_amount": max_send_amount,
                    "unspent_coin_count": len(unspent_records),
                    "pending_coin_removal_count": len(unconfirmed_removals),
                }
                self.balance_cache[wallet_id] = wallet_balance

        return {"wallet_balance": wallet_balance}

    async def get_transaction(self, request: Dict) -> Dict:
        assert self.service.wallet_state_manager is not None
        transaction_id: bytes32 = bytes32(hexstr_to_bytes(request["transaction_id"]))
        tr: Optional[TransactionRecord] = await self.service.wallet_state_manager.get_transaction(transaction_id)
        if tr is None:
            raise ValueError(f"Transaction 0x{transaction_id.hex()} not found")

        return {
            "transaction": tr.to_json_dict_convenience(self.service.config),
            "transaction_id": tr.name,
        }

    async def get_transactions(self, request: Dict) -> Dict:
        assert self.service.wallet_state_manager is not None

        wallet_id = int(request["wallet_id"])

        start = request.get("start", 0)
        end = request.get("end", 50)
        sort_key = request.get("sort_key", None)
        reverse = request.get("reverse", False)

        transactions = await self.service.wallet_state_manager.tx_store.get_transactions_between(
            wallet_id, start, end, sort_key=sort_key, reverse=reverse
        )
        return {
            "transactions": [tr.to_json_dict_convenience(self.service.config) for tr in transactions],
            "wallet_id": wallet_id,
        }

    async def get_transaction_count(self, request: Dict) -> Dict:
        assert self.service.wallet_state_manager is not None

        wallet_id = int(request["wallet_id"])
        count = await self.service.wallet_state_manager.tx_store.get_transaction_count_for_wallet(wallet_id)
        return {
            "count": count,
            "wallet_id": wallet_id,
        }

    # this function is just here for backwards-compatibility. It will probably
    # be removed in the future
    async def get_initial_freeze_period(self, _: Dict):
        # Mon May 03 2021 17:00:00 GMT+0000
        return {"INITIAL_FREEZE_END_TIMESTAMP": 1620061200}

    async def get_next_address(self, request: Dict) -> Dict:
        """
        Returns a new address
        """
        assert self.service.wallet_state_manager is not None

        if request["new_address"] is True:
            create_new = True
        else:
            create_new = False
        wallet_id = uint32(int(request["wallet_id"]))
        wallet = self.service.wallet_state_manager.wallets[wallet_id]
        selected = self.service.config["selected_network"]
        prefix = self.service.config["network_overrides"]["config"][selected]["address_prefix"]
        if wallet.type() == WalletType.STANDARD_WALLET:
            raw_puzzle_hash = await wallet.get_puzzle_hash(create_new)
            address = encode_puzzle_hash(raw_puzzle_hash, prefix)
        elif wallet.type() == WalletType.CAT:
            raw_puzzle_hash = await wallet.standard_wallet.get_puzzle_hash(create_new)
            address = encode_puzzle_hash(raw_puzzle_hash, prefix)
        else:
            raise ValueError(f"Wallet type {wallet.type()} cannot create puzzle hashes")

        return {
            "wallet_id": wallet_id,
            "address": address,
        }

    async def send_transaction(self, request):
        assert self.service.wallet_state_manager is not None

        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced before sending transactions")

        wallet_id = int(request["wallet_id"])
        wallet = self.service.wallet_state_manager.wallets[wallet_id]

        if wallet.type() == WalletType.CAT:
            raise ValueError("send_transaction does not work for CAT wallets")

        if not isinstance(request["amount"], int) or not isinstance(request["fee"], int):
            raise ValueError("An integer amount or fee is required (too many decimals)")
        amount: uint64 = uint64(request["amount"])
        puzzle_hash: bytes32 = decode_puzzle_hash(request["address"])

        memos: List[bytes] = []
        if "memos" in request:
            memos = [mem.encode("utf-8") for mem in request["memos"]]

        if "fee" in request:
            fee = uint64(request["fee"])
        else:
            fee = uint64(0)
        async with self.service.wallet_state_manager.lock:
            tx: TransactionRecord = await wallet.generate_signed_transaction(amount, puzzle_hash, fee, memos=memos)
            await wallet.push_transaction(tx)

        # Transaction may not have been included in the mempool yet. Use get_transaction to check.
        return {
            "transaction": tx.to_json_dict_convenience(self.service.config),
            "transaction_id": tx.name,
        }

    async def send_transaction_multi(self, request) -> Dict:
        assert self.service.wallet_state_manager is not None

        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced before sending transactions")

        wallet_id = uint32(request["wallet_id"])
        wallet = self.service.wallet_state_manager.wallets[wallet_id]

        async with self.service.wallet_state_manager.lock:
            transaction: Dict = (await self.create_signed_transaction(request, hold_lock=False))["signed_tx"]
            tr: TransactionRecord = TransactionRecord.from_json_dict_convenience(transaction)
            await wallet.push_transaction(tr)

        # Transaction may not have been included in the mempool yet. Use get_transaction to check.
        return {"transaction": transaction, "transaction_id": tr.name}

    async def delete_unconfirmed_transactions(self, request):
        wallet_id = uint32(request["wallet_id"])
        if wallet_id not in self.service.wallet_state_manager.wallets:
            raise ValueError(f"Wallet id {wallet_id} does not exist")
        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced.")

        async with self.service.wallet_state_manager.lock:
            async with self.service.wallet_state_manager.tx_store.db_wrapper.lock:
                await self.service.wallet_state_manager.tx_store.db_wrapper.begin_transaction()
                await self.service.wallet_state_manager.tx_store.delete_unconfirmed_transactions(wallet_id)
                if self.service.wallet_state_manager.wallets[wallet_id].type() == WalletType.POOLING_WALLET.value:
                    self.service.wallet_state_manager.wallets[wallet_id].target_state = None
                await self.service.wallet_state_manager.tx_store.db_wrapper.commit_transaction()
                # Update the cache
                await self.service.wallet_state_manager.tx_store.rebuild_tx_cache()
                return {}

    ##########################################################################################
    # Coloured Coins and Trading
    ##########################################################################################

    async def get_cat_list(self, request):
        return {"cat_list": list(DEFAULT_CATS.values())}

    async def cat_set_name(self, request):
        assert self.service.wallet_state_manager is not None
        wallet_id = int(request["wallet_id"])
        wallet: CATWallet = self.service.wallet_state_manager.wallets[wallet_id]
        await wallet.set_name(str(request["name"]))
        return {"wallet_id": wallet_id}

    async def cat_get_name(self, request):
        assert self.service.wallet_state_manager is not None
        wallet_id = int(request["wallet_id"])
        wallet: CATWallet = self.service.wallet_state_manager.wallets[wallet_id]
        name: str = await wallet.get_name()
        return {"wallet_id": wallet_id, "name": name}

    async def cat_asset_id_to_name(self, request):
        assert self.service.wallet_state_manager is not None
        wallet = await self.service.wallet_state_manager.get_wallet_for_asset_id(request["asset_id"])
        if wallet is None:
            raise ValueError("The asset ID specified does not belong to a wallet")
        else:
            return {"wallet_id": wallet.id(), "name": (await wallet.get_name())}

    async def cat_spend(self, request):
        assert self.service.wallet_state_manager is not None

        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced.")
        wallet_id = int(request["wallet_id"])
        wallet: CATWallet = self.service.wallet_state_manager.wallets[wallet_id]

        puzzle_hash: bytes32 = decode_puzzle_hash(request["inner_address"])

        memos: List[bytes] = []
        if "memos" in request:
            memos = [mem.encode("utf-8") for mem in request["memos"]]
        if not isinstance(request["amount"], int) or not isinstance(request["amount"], int):
            raise ValueError("An integer amount or fee is required (too many decimals)")
        amount: uint64 = uint64(request["amount"])
        if "fee" in request:
            fee = uint64(request["fee"])
        else:
            fee = uint64(0)
        async with self.service.wallet_state_manager.lock:
            txs: TransactionRecord = await wallet.generate_signed_transaction(
                [amount], [puzzle_hash], fee, memos=[memos]
            )
            for tx in txs:
                await wallet.standard_wallet.push_transaction(tx)

        return {
            "transaction": tx.to_json_dict_convenience(self.service.config),
            "transaction_id": tx.name,
        }

    async def cat_get_asset_id(self, request):
        assert self.service.wallet_state_manager is not None
        wallet_id = int(request["wallet_id"])
        wallet: CATWallet = self.service.wallet_state_manager.wallets[wallet_id]
        asset_id: str = wallet.get_asset_id()
        return {"asset_id": asset_id, "wallet_id": wallet_id}

    async def get_offer_summary(self, request):
        assert self.service.wallet_state_manager is not None
        offer_hex: str = request["offer"]
        offer = Offer.from_bytes(hexstr_to_bytes(offer_hex))
        offered, requested = offer.summary()

        return {"summary": {"offered": offered, "requested": requested}}

    async def create_offer_for_ids(self, request):
        assert self.service.wallet_state_manager is not None

        offer: Dict[str, int] = request["offer"]
        fee: uint64 = uint64(request.get("fee", 0))
        validate_only: bool = request.get("validate_only", False)

        modified_offer = {}
        for key in offer:
            modified_offer[int(key)] = offer[key]

        async with self.service.wallet_state_manager.lock:
            (
                success,
                trade_record,
                error,
            ) = await self.service.wallet_state_manager.trade_manager.create_offer_for_ids(
                modified_offer, fee=fee, validate_only=validate_only
            )
        if success:
            return {
                "offer": trade_record.offer.hex(),
                "trade_record": trade_record.to_json_dict_convenience(),
            }
        raise ValueError(error)

    async def check_offer_validity(self, request):
        assert self.service.wallet_state_manager is not None
        offer_hex: str = request["offer"]
        offer = Offer.from_bytes(hexstr_to_bytes(offer_hex))

        return {"valid": (await self.service.wallet_state_manager.trade_manager.check_offer_validity(offer))}

    async def take_offer(self, request):
        assert self.service.wallet_state_manager is not None
        offer_hex = request["offer"]
        offer = Offer.from_bytes(hexstr_to_bytes(offer_hex))
        fee: uint64 = uint64(request.get("fee", 0))

        async with self.service.wallet_state_manager.lock:
            (
                success,
                trade_record,
                error,
            ) = await self.service.wallet_state_manager.trade_manager.respond_to_offer(offer, fee=fee)
        if not success:
            raise ValueError(error)
        return {"trade_record": trade_record.to_json_dict_convenience()}

    async def get_offer(self, request: Dict):
        assert self.service.wallet_state_manager is not None

        trade_mgr = self.service.wallet_state_manager.trade_manager

        trade_id = bytes32.from_hexstr(request["trade_id"])
        file_contents: bool = request.get("file_contents", False)
        trade_record: Optional[TradeRecord] = await trade_mgr.get_trade_by_id(bytes32(trade_id))
        if trade_record is None:
            raise ValueError(f"No trade with trade id: {trade_id.hex()}")

        offer_to_return: bytes = trade_record.offer if trade_record.taken_offer is None else trade_record.taken_offer
        offer_value: Optional[str] = offer_to_return.hex() if file_contents else None
        return {"trade_record": trade_record.to_json_dict_convenience(), "offer": offer_value}

    async def get_all_offers(self, request: Dict):
        assert self.service.wallet_state_manager is not None

        trade_mgr = self.service.wallet_state_manager.trade_manager

        start: int = request.get("start", 0)
        end: int = request.get("end", 50)
        sort_key: Optional[str] = request.get("sort_key", None)
        reverse: bool = request.get("reverse", False)
        file_contents: bool = request.get("file_contents", False)

        all_trades = await trade_mgr.trade_store.get_trades_between(start, end, sort_key=sort_key, reverse=reverse)
        result = []
        offer_values: Optional[List[str]] = [] if file_contents else None
        for trade in all_trades:
            result.append(trade.to_json_dict_convenience())
            if file_contents and offer_values is not None:
                offer_to_return: bytes = trade.offer if trade.taken_offer is None else trade.taken_offer
                offer_values.append(offer_to_return.hex())

        return {"trade_records": result, "offers": offer_values}

    async def cancel_offer(self, request: Dict):
        assert self.service.wallet_state_manager is not None

        wsm = self.service.wallet_state_manager
        secure = request["secure"]
        trade_id = bytes32.from_hexstr(request["trade_id"])
        fee: uint64 = uint64(request.get("fee", 0))

        async with self.service.wallet_state_manager.lock:
            if secure:
                await wsm.trade_manager.cancel_pending_offer_safely(bytes32(trade_id), fee=fee)
            else:
                await wsm.trade_manager.cancel_pending_offer(bytes32(trade_id))
        return {}

    ##########################################################################################
    # Distributed Identities
    ##########################################################################################

    async def did_update_recovery_ids(self, request):
        wallet_id = int(request["wallet_id"])
        wallet: DIDWallet = self.service.wallet_state_manager.wallets[wallet_id]
        recovery_list = []
        for _ in request["new_list"]:
            recovery_list.append(hexstr_to_bytes(_))
        if "num_verifications_required" in request:
            new_amount_verifications_required = uint64(request["num_verifications_required"])
        else:
            new_amount_verifications_required = len(recovery_list)
        async with self.service.wallet_state_manager.lock:
            update_success = await wallet.update_recovery_list(recovery_list, new_amount_verifications_required)
            # Update coin with new ID info
            spend_bundle = await wallet.create_update_spend()

        success = spend_bundle is not None and update_success
        return {"success": success}

    async def did_get_did(self, request):
        wallet_id = int(request["wallet_id"])
        wallet: DIDWallet = self.service.wallet_state_manager.wallets[wallet_id]
        my_did: str = wallet.get_my_DID()
        async with self.service.wallet_state_manager.lock:
            coins = await wallet.select_coins(1)
        if coins is None or coins == set():
            return {"success": True, "wallet_id": wallet_id, "my_did": my_did}
        else:
            coin = coins.pop()
            return {"success": True, "wallet_id": wallet_id, "my_did": my_did, "coin_id": coin.name()}

    async def did_get_recovery_list(self, request):
        wallet_id = int(request["wallet_id"])
        wallet: DIDWallet = self.service.wallet_state_manager.wallets[wallet_id]
        recovery_list = wallet.did_info.backup_ids
        recover_hex_list = []
        for _ in recovery_list:
            recover_hex_list.append(_.hex())
        return {
            "success": True,
            "wallet_id": wallet_id,
            "recover_list": recover_hex_list,
            "num_required": wallet.did_info.num_of_backup_ids_needed,
        }

    async def did_recovery_spend(self, request):
        wallet_id = int(request["wallet_id"])
        wallet: DIDWallet = self.service.wallet_state_manager.wallets[wallet_id]
        if len(request["attest_filenames"]) < wallet.did_info.num_of_backup_ids_needed:
            return {"success": False, "reason": "insufficient messages"}

        async with self.service.wallet_state_manager.lock:
            (
                info_list,
                message_spend_bundle,
            ) = await wallet.load_attest_files_for_recovery_spend(request["attest_filenames"])

            if "pubkey" in request:
                pubkey = G1Element.from_bytes(hexstr_to_bytes(request["pubkey"]))
            else:
                assert wallet.did_info.temp_pubkey is not None
                pubkey = wallet.did_info.temp_pubkey

            if "puzhash" in request:
                puzhash = hexstr_to_bytes(request["puzhash"])
            else:
                assert wallet.did_info.temp_puzhash is not None
                puzhash = wallet.did_info.temp_puzhash

            success = await wallet.recovery_spend(
                wallet.did_info.temp_coin,
                puzhash,
                info_list,
                pubkey,
                message_spend_bundle,
            )
        return {"success": success}

    async def did_get_pubkey(self, request):
        wallet_id = int(request["wallet_id"])
        wallet: DIDWallet = self.service.wallet_state_manager.wallets[wallet_id]
        pubkey = bytes((await wallet.wallet_state_manager.get_unused_derivation_record(wallet_id)).pubkey).hex()
        return {"success": True, "pubkey": pubkey}

    async def did_create_attest(self, request):
        wallet_id = int(request["wallet_id"])
        wallet: DIDWallet = self.service.wallet_state_manager.wallets[wallet_id]
        async with self.service.wallet_state_manager.lock:
            info = await wallet.get_info_for_recovery()
            coin = hexstr_to_bytes(request["coin_name"])
            pubkey = G1Element.from_bytes(hexstr_to_bytes(request["pubkey"]))
            spend_bundle = await wallet.create_attestment(
                coin, hexstr_to_bytes(request["puzhash"]), pubkey, request["filename"]
            )
        if spend_bundle is not None:
            return {
                "success": True,
                "message_spend_bundle": bytes(spend_bundle).hex(),
                "info": [info[0].hex(), info[1].hex(), info[2]],
            }
        else:
            return {"success": False}

    async def did_get_information_needed_for_recovery(self, request):
        wallet_id = int(request["wallet_id"])
        did_wallet: DIDWallet = self.service.wallet_state_manager.wallets[wallet_id]
        my_did = did_wallet.get_my_DID()
        coin_name = did_wallet.did_info.temp_coin.name().hex()
        return {
            "success": True,
            "wallet_id": wallet_id,
            "my_did": my_did,
            "coin_name": coin_name,
            "newpuzhash": did_wallet.did_info.temp_puzhash,
            "pubkey": did_wallet.did_info.temp_pubkey,
            "backup_dids": did_wallet.did_info.backup_ids,
        }

    async def did_create_backup_file(self, request):
        try:
            wallet_id = int(request["wallet_id"])
            did_wallet: DIDWallet = self.service.wallet_state_manager.wallets[wallet_id]
            did_wallet.create_backup(request["filename"])
            return {"wallet_id": wallet_id, "success": True}
        except Exception:
            return {"wallet_id": wallet_id, "success": False}

    ##########################################################################################
    # Rate Limited Wallet
    ##########################################################################################

    async def rl_set_user_info(self, request):
        assert self.service.wallet_state_manager is not None

        wallet_id = uint32(int(request["wallet_id"]))
        rl_user = self.service.wallet_state_manager.wallets[wallet_id]
        origin = request["origin"]
        async with self.service.wallet_state_manager.lock:
            await rl_user.set_user_info(
                uint64(request["interval"]),
                uint64(request["limit"]),
                origin["parent_coin_info"],
                origin["puzzle_hash"],
                origin["amount"],
                request["admin_pubkey"],
            )
        return {}

    async def send_clawback_transaction(self, request):
        assert self.service.wallet_state_manager is not None

        wallet_id = int(request["wallet_id"])
        wallet: RLWallet = self.service.wallet_state_manager.wallets[wallet_id]

        fee = int(request["fee"])
        async with self.service.wallet_state_manager.lock:
            tx = await wallet.clawback_rl_coin_transaction(fee)
            await wallet.push_transaction(tx)

        # Transaction may not have been included in the mempool yet. Use get_transaction to check.
        return {
            "transaction": tx,
            "transaction_id": tx.name,
        }

    async def add_rate_limited_funds(self, request):
        wallet_id = uint32(request["wallet_id"])
        wallet: RLWallet = self.service.wallet_state_manager.wallets[wallet_id]
        puzzle_hash = wallet.rl_get_aggregation_puzzlehash(wallet.rl_info.rl_puzzle_hash)
        async with self.service.wallet_state_manager.lock:
            await wallet.rl_add_funds(request["amount"], puzzle_hash, request["fee"])
        return {"status": "SUCCESS"}

    async def get_farmed_amount(self, request):
        tx_records: List[TransactionRecord] = await self.service.wallet_state_manager.tx_store.get_farming_rewards()
        amount = 0
        pool_reward_amount = 0
        farmer_reward_amount = 0
        fee_amount = 0
        last_height_farmed = 0
        for record in tx_records:
            if record.wallet_id not in self.service.wallet_state_manager.wallets:
                continue
            if record.type == TransactionType.COINBASE_REWARD:
                if self.service.wallet_state_manager.wallets[record.wallet_id].type() == WalletType.POOLING_WALLET:
                    # Don't add pool rewards for pool wallets.
                    continue
                pool_reward_amount += record.amount
            height = record.height_farmed(self.service.constants.GENESIS_CHALLENGE)
            if record.type == TransactionType.FEE_REWARD:
                fee_amount += record.amount - calculate_base_farmer_reward(height)
                farmer_reward_amount += calculate_base_farmer_reward(height)
            if height > last_height_farmed:
                last_height_farmed = height
            amount += record.amount

        assert amount == pool_reward_amount + farmer_reward_amount + fee_amount
        return {
            "farmed_amount": amount,
            "pool_reward_amount": pool_reward_amount,
            "farmer_reward_amount": farmer_reward_amount,
            "fee_amount": fee_amount,
            "last_height_farmed": last_height_farmed,
        }

    async def create_signed_transaction(self, request, hold_lock=True) -> Dict:
        assert self.service.wallet_state_manager is not None
        if "additions" not in request or len(request["additions"]) < 1:
            raise ValueError("Specify additions list")

        additions: List[Dict] = request["additions"]
        amount_0: uint64 = uint64(additions[0]["amount"])
        assert amount_0 <= self.service.constants.MAX_COIN_AMOUNT
        puzzle_hash_0 = bytes32.from_hexstr(additions[0]["puzzle_hash"])
        if len(puzzle_hash_0) != 32:
            raise ValueError(f"Address must be 32 bytes. {puzzle_hash_0.hex()}")

        memos_0 = None if "memos" not in additions[0] else [mem.encode("utf-8") for mem in additions[0]["memos"]]

        additional_outputs: List[AmountWithPuzzlehash] = []
        for addition in additions[1:]:
            receiver_ph = bytes32.from_hexstr(addition["puzzle_hash"])
            if len(receiver_ph) != 32:
                raise ValueError(f"Address must be 32 bytes. {receiver_ph.hex()}")
            amount = uint64(addition["amount"])
            if amount > self.service.constants.MAX_COIN_AMOUNT:
                raise ValueError(f"Coin amount cannot exceed {self.service.constants.MAX_COIN_AMOUNT}")
            memos = [] if "memos" not in addition else [mem.encode("utf-8") for mem in addition["memos"]]
            additional_outputs.append({"puzzlehash": receiver_ph, "amount": amount, "memos": memos})

        fee = uint64(0)
        if "fee" in request:
            fee = uint64(request["fee"])

        coins = None
        if "coins" in request and len(request["coins"]) > 0:
            coins = set([Coin.from_json_dict(coin_json) for coin_json in request["coins"]])

        coin_announcements: Optional[Set[Announcement]] = None
        if (
            "coin_announcements" in request
            and request["coin_announcements"] is not None
            and len(request["coin_announcements"]) > 0
        ):
            coin_announcements = {
                Announcement(
                    bytes32.from_hexstr(announcement["coin_id"]),
                    hexstr_to_bytes(announcement["message"]),
                    hexstr_to_bytes(announcement["morph_bytes"])
                    if "morph_bytes" in announcement and len(announcement["morph_bytes"]) > 0
                    else None,
                )
                for announcement in request["coin_announcements"]
            }

        puzzle_announcements: Optional[Set[Announcement]] = None
        if (
            "puzzle_announcements" in request
            and request["puzzle_announcements"] is not None
            and len(request["puzzle_announcements"]) > 0
        ):
            puzzle_announcements = {
                Announcement(
                    bytes32.from_hexstr(announcement["puzzle_hash"]),
                    hexstr_to_bytes(announcement["message"]),
                    hexstr_to_bytes(announcement["morph_bytes"])
                    if "morph_bytes" in announcement and len(announcement["morph_bytes"]) > 0
                    else None,
                )
                for announcement in request["puzzle_announcements"]
            }

        if hold_lock:
            async with self.service.wallet_state_manager.lock:
                signed_tx = await self.service.wallet_state_manager.main_wallet.generate_signed_transaction(
                    amount_0,
                    bytes32(puzzle_hash_0),
                    fee,
                    coins=coins,
                    ignore_max_send_amount=True,
                    primaries=additional_outputs,
                    memos=memos_0,
                    coin_announcements_to_consume=coin_announcements,
                    puzzle_announcements_to_consume=puzzle_announcements,
                )
        else:
            signed_tx = await self.service.wallet_state_manager.main_wallet.generate_signed_transaction(
                amount_0,
                bytes32(puzzle_hash_0),
                fee,
                coins=coins,
                ignore_max_send_amount=True,
                primaries=additional_outputs,
                memos=memos_0,
                coin_announcements_to_consume=coin_announcements,
                puzzle_announcements_to_consume=puzzle_announcements,
            )
        return {"signed_tx": signed_tx.to_json_dict_convenience(self.service.config)}

    ##########################################################################################
    # Pool Wallet
    ##########################################################################################
    async def pw_join_pool(self, request) -> Dict:
        if self.service.wallet_state_manager is None:
            return {"success": False, "error": "not_initialized"}
        fee = uint64(request.get("fee", 0))
        wallet_id = uint32(request["wallet_id"])
        wallet: PoolWallet = self.service.wallet_state_manager.wallets[wallet_id]
        pool_wallet_info: PoolWalletInfo = await wallet.get_current_state()
        owner_pubkey = pool_wallet_info.current.owner_pubkey
        target_puzzlehash = None

        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced.")

        if "target_puzzlehash" in request:
            target_puzzlehash = bytes32(hexstr_to_bytes(request["target_puzzlehash"]))
        assert target_puzzlehash is not None
        new_target_state: PoolState = create_pool_state(
            FARMING_TO_POOL,
            target_puzzlehash,
            owner_pubkey,
            request["pool_url"],
            uint32(request["relative_lock_height"]),
        )
        async with self.service.wallet_state_manager.lock:
            total_fee, tx = await wallet.join_pool(new_target_state, fee)
            return {"total_fee": total_fee, "transaction": tx}

    async def pw_self_pool(self, request) -> Dict:
        if self.service.wallet_state_manager is None:
            return {"success": False, "error": "not_initialized"}
        # Leaving a pool requires two state transitions.
        # First we transition to PoolSingletonState.LEAVING_POOL
        # Then we transition to FARMING_TO_POOL or SELF_POOLING
        fee = uint64(request.get("fee", 0))
        wallet_id = uint32(request["wallet_id"])
        wallet: PoolWallet = self.service.wallet_state_manager.wallets[wallet_id]

        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced.")

        async with self.service.wallet_state_manager.lock:
            total_fee, tx = await wallet.self_pool(fee)  # total_fee: uint64, tx: TransactionRecord
            return {"total_fee": total_fee, "transaction": tx}

    async def pw_absorb_rewards(self, request) -> Dict:
        """Perform a sweep of the p2_singleton rewards controlled by the pool wallet singleton"""
        if self.service.wallet_state_manager is None:
            return {"success": False, "error": "not_initialized"}
        if await self.service.wallet_state_manager.synced() is False:
            raise ValueError("Wallet needs to be fully synced before collecting rewards")
        fee = uint64(request.get("fee", 0))
        wallet_id = uint32(request["wallet_id"])
        wallet: PoolWallet = self.service.wallet_state_manager.wallets[wallet_id]

        async with self.service.wallet_state_manager.lock:
            transaction: TransactionRecord = await wallet.claim_pool_rewards(fee)
            state: PoolWalletInfo = await wallet.get_current_state()
        return {"state": state.to_json_dict(), "transaction": transaction}

    async def pw_status(self, request) -> Dict:
        """Return the complete state of the Pool wallet with id `request["wallet_id"]`"""
        if self.service.wallet_state_manager is None:
            return {"success": False, "error": "not_initialized"}
        wallet_id = uint32(request["wallet_id"])
        wallet: PoolWallet = self.service.wallet_state_manager.wallets[wallet_id]
        if wallet.type() != WalletType.POOLING_WALLET.value:
            raise ValueError(f"wallet_id {wallet_id} is not a pooling wallet")
        state: PoolWalletInfo = await wallet.get_current_state()
        unconfirmed_transactions: List[TransactionRecord] = await wallet.get_unconfirmed_transactions()
        return {
            "state": state.to_json_dict(),
            "unconfirmed_transactions": unconfirmed_transactions,
        }
