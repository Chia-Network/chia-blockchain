import asyncio
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from blspy import PrivateKey, G1Element

from chives.cmds.init_funcs import check_keys
from chives.consensus.block_rewards import calculate_base_community_reward, calculate_base_farmer_reward, calculate_pool_reward
from chives.protocols.protocol_message_types import ProtocolMessageTypes
from chives.server.outbound_message import NodeType, make_msg
from chives.simulator.simulator_protocol import FarmNewBlockProtocol
from chives.types.blockchain_format.coin import Coin
from chives.types.blockchain_format.sized_bytes import bytes32
from chives.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from chives.util.byte_types import hexstr_to_bytes
from chives.util.ints import uint32, uint64
from chives.util.keychain import bytes_to_mnemonic, generate_mnemonic
from chives.util.path import path_from_root
from chives.util.ws_message import WsRpcMessage, create_payload_dict
from chives.wallet.cc_wallet.cc_wallet import CCWallet
from chives.wallet.rl_wallet.rl_wallet import RLWallet
from chives.wallet.derive_keys import master_sk_to_farmer_sk, master_sk_to_pool_sk
from chives.wallet.did_wallet.did_wallet import DIDWallet
from chives.wallet.trade_record import TradeRecord
from chives.wallet.transaction_record import TransactionRecord
from chives.wallet.util.backup_utils import download_backup, get_backup_info, upload_backup
from chives.wallet.util.trade_utils import trade_record_to_dict
from chives.wallet.util.transaction_type import TransactionType
from chives.wallet.util.wallet_types import WalletType
from chives.wallet.wallet_info import WalletInfo
from chives.wallet.wallet_node import WalletNode

# Timeout for response from wallet/full node for sending a transaction
TIMEOUT = 30

log = logging.getLogger(__name__)


class WalletRpcApi:
    def __init__(self, wallet_node: WalletNode):
        assert wallet_node is not None
        self.service = wallet_node
        self.service_name = "chives_wallet"

    def get_routes(self) -> Dict[str, Callable]:
        return {
            # Key management
            "/log_in": self.log_in,
            "/get_public_keys": self.get_public_keys,
            "/get_private_key": self.get_private_key,
            "/generate_mnemonic": self.generate_mnemonic,
            "/add_key": self.add_key,
            "/delete_key": self.delete_key,
            "/delete_all_keys": self.delete_all_keys,
            # Wallet node
            "/get_sync_status": self.get_sync_status,
            "/get_height_info": self.get_height_info,
            "/farm_block": self.farm_block,  # Only when node simulator is running
            "/get_initial_freeze_period": self.get_initial_freeze_period,
            "/get_network_info": self.get_network_info,
            # Wallet management
            "/get_wallets": self.get_wallets,
            "/create_new_wallet": self.create_new_wallet,
            # Wallet
            "/get_wallet_balance": self.get_wallet_balance,
            "/get_transaction": self.get_transaction,
            "/get_transactions": self.get_transactions,
            "/get_next_address": self.get_next_address,
            "/send_transaction": self.send_transaction,
            "/create_backup": self.create_backup,
            "/get_transaction_count": self.get_transaction_count,
            "/get_farmed_amount": self.get_farmed_amount,
            "/create_signed_transaction": self.create_signed_transaction,
            # Coloured coins and trading
            "/cc_set_name": self.cc_set_name,
            "/cc_get_name": self.cc_get_name,
            "/cc_spend": self.cc_spend,
            "/cc_get_colour": self.cc_get_colour,
            "/create_offer_for_ids": self.create_offer_for_ids,
            "/get_discrepancies_for_offer": self.get_discrepancies_for_offer,
            "/respond_to_offer": self.respond_to_offer,
            "/get_trade": self.get_trade,
            "/get_all_trades": self.get_all_trades,
            "/cancel_trade": self.cancel_trade,
            # DID Wallet
            "/did_update_recovery_ids": self.did_update_recovery_ids,
            "/did_spend": self.did_spend,
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
        return [create_payload_dict("state_changed", data, "chives_wallet", "wallet_ui")]

    async def _stop_wallet(self):
        """
        Stops a currently running wallet/key, which allows starting the wallet with a new key.
        Each key has it's own wallet database.
        """
        if self.service is not None:
            self.service._close()
            await self.service._await_closed()

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
        log_in_type = request["type"]
        recovery_host = request["host"]
        testing = False

        if "testing" in self.service.config and self.service.config["testing"] is True:
            testing = True
        if log_in_type == "skip":
            started = await self.service._start(fingerprint=fingerprint, skip_backup_import=True)
        elif log_in_type == "restore_backup":
            file_path = Path(request["file_path"])
            started = await self.service._start(fingerprint=fingerprint, backup_file=file_path)
        else:
            started = await self.service._start(fingerprint)

        if started is True:
            return {"fingerprint": fingerprint}
        elif testing is True and self.service.backup_initialized is False:
            response = {"success": False, "error": "not_initialized"}
            return response
        elif self.service.backup_initialized is False:
            backup_info = None
            backup_path = None
            try:
                private_key = self.service.get_key_for_fingerprint(fingerprint)
                last_recovery = await download_backup(recovery_host, private_key)
                backup_path = path_from_root(self.service.root_path, "last_recovery")
                if backup_path.exists():
                    backup_path.unlink()
                backup_path.write_text(last_recovery)
                backup_info = get_backup_info(backup_path, private_key)
                backup_info["backup_host"] = recovery_host
                backup_info["downloaded"] = True
            except Exception as e:
                log.error(f"error {e}")
            response = {"success": False, "error": "not_initialized"}
            if backup_info is not None:
                response["backup_info"] = backup_info
                response["backup_path"] = f"{backup_path}"
            return response

        return {"success": False, "error": "Unknown Error"}

    async def get_public_keys(self, request: Dict):
        fingerprints = [sk.get_g1().get_fingerprint() for (sk, seed) in self.service.keychain.get_all_private_keys()]
        return {"public_key_fingerprints": fingerprints}

    async def _get_private_key(self, fingerprint) -> Tuple[Optional[PrivateKey], Optional[bytes]]:
        for sk, seed in self.service.keychain.get_all_private_keys():
            if sk.get_g1().get_fingerprint() == fingerprint:
                return sk, seed
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
            sk = self.service.keychain.add_private_key(" ".join(mnemonic), passphrase)
        except KeyError as e:
            return {
                "success": False,
                "error": f"The word '{e.args[0]}' is incorrect.'",
                "word": e.args[0],
            }

        fingerprint = sk.get_g1().get_fingerprint()
        await self._stop_wallet()

        # Makes sure the new key is added to config properly
        started = False
        check_keys(self.service.root_path)
        request_type = request["type"]
        if request_type == "new_wallet":
            started = await self.service._start(fingerprint=fingerprint, new_wallet=True)
        elif request_type == "skip":
            started = await self.service._start(fingerprint=fingerprint, skip_backup_import=True)
        elif request_type == "restore_backup":
            file_path = Path(request["file_path"])
            started = await self.service._start(fingerprint=fingerprint, backup_file=file_path)

        if started is True:
            return {"fingerprint": fingerprint}
        raise ValueError("Failed to start")

    async def delete_key(self, request):
        await self._stop_wallet()
        fingerprint = request["fingerprint"]
        self.service.keychain.delete_key_by_fingerprint(fingerprint)
        path = path_from_root(
            self.service.root_path,
            f"{self.service.config['database_path']}-{fingerprint}",
        )
        if path.exists():
            path.unlink()
        return {}

    async def delete_all_keys(self, request: Dict):
        await self._stop_wallet()
        self.service.keychain.delete_all_keys()
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
        peak = self.service.wallet_state_manager.peak
        if peak is None:
            return {"height": 0}
        else:
            return {"height": peak.height}

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

    async def _create_backup_and_upload(self, host) -> None:
        assert self.service.wallet_state_manager is not None
        try:
            if "testing" in self.service.config and self.service.config["testing"] is True:
                return None
            now = time.time()
            file_name = f"backup_{now}"
            path = path_from_root(self.service.root_path, file_name)
            await self.service.wallet_state_manager.create_wallet_backup(path)
            backup_text = path.read_text()
            response = await upload_backup(host, backup_text)
            success = response["success"]
            if success is False:
                log.error("Failed to upload backup to wallet backup service")
            elif success is True:
                log.info("Finished upload of the backup file")
        except Exception as e:
            log.error(f"Exception in upload backup. Error: {e}")

    async def create_new_wallet(self, request: Dict):
        assert self.service.wallet_state_manager is not None

        wallet_state_manager = self.service.wallet_state_manager
        main_wallet = wallet_state_manager.main_wallet
        host = request["host"]
        if request["wallet_type"] == "cc_wallet":
            if request["mode"] == "new":
                async with self.service.wallet_state_manager.lock:
                    cc_wallet: CCWallet = await CCWallet.create_new_cc(
                        wallet_state_manager, main_wallet, request["amount"]
                    )
                    colour = cc_wallet.get_colour()
                    asyncio.create_task(self._create_backup_and_upload(host))
                return {
                    "type": cc_wallet.type(),
                    "colour": colour,
                    "wallet_id": cc_wallet.id(),
                }

            elif request["mode"] == "existing":
                async with self.service.wallet_state_manager.lock:
                    cc_wallet = await CCWallet.create_wallet_for_cc(
                        wallet_state_manager, main_wallet, request["colour"]
                    )
                    asyncio.create_task(self._create_backup_and_upload(host))
                return {"type": cc_wallet.type()}

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
                    asyncio.create_task(self._create_backup_and_upload(host))
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
                    asyncio.create_task(self._create_backup_and_upload(host))
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
                        int(request["amount"]),
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
        async with self.service.wallet_state_manager.lock:
            unspent_records = await self.service.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(wallet_id)
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

        return {"wallet_balance": wallet_balance}

    async def get_transaction(self, request: Dict) -> Dict:
        assert self.service.wallet_state_manager is not None
        transaction_id: bytes32 = bytes32(hexstr_to_bytes(request["transaction_id"]))
        tr: Optional[TransactionRecord] = await self.service.wallet_state_manager.get_transaction(transaction_id)
        if tr is None:
            raise ValueError(f"Transaction 0x{transaction_id.hex()} not found")

        return {
            "transaction": tr,
            "transaction_id": tr.name,
        }

    async def get_transactions(self, request: Dict) -> Dict:
        assert self.service.wallet_state_manager is not None

        wallet_id = int(request["wallet_id"])
        if "start" in request:
            start = request["start"]
        else:
            start = 0
        if "end" in request:
            end = request["end"]
        else:
            end = 50

        transactions = await self.service.wallet_state_manager.tx_store.get_transactions_between(wallet_id, start, end)
        formatted_transactions = []
        selected = self.service.config["selected_network"]
        prefix = self.service.config["network_overrides"]["config"][selected]["address_prefix"]
        for tx in transactions:
            formatted = tx.to_json_dict()
            formatted["to_address"] = encode_puzzle_hash(tx.to_puzzle_hash, prefix)
            formatted_transactions.append(formatted)

        return {
            "transactions": formatted_transactions,
            "wallet_id": wallet_id,
        }

    async def get_initial_freeze_period(self, _: Dict):
        freeze_period = self.service.constants.INITIAL_FREEZE_END_TIMESTAMP
        return {"INITIAL_FREEZE_END_TIMESTAMP": freeze_period}

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
        elif wallet.type() == WalletType.COLOURED_COIN:
            raw_puzzle_hash = await wallet.get_puzzle_hash(create_new)
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

        if int(time.time()) < self.service.constants.INITIAL_FREEZE_END_TIMESTAMP:
            end_date = datetime.fromtimestamp(float(self.service.constants.INITIAL_FREEZE_END_TIMESTAMP))
            raise ValueError(f"No transactions before: {end_date}")

        wallet_id = int(request["wallet_id"])
        wallet = self.service.wallet_state_manager.wallets[wallet_id]

        if not isinstance(request["amount"], int) or not isinstance(request["fee"], int):
            raise ValueError("An integer amount or fee is required (too many decimals)")
        amount: uint64 = uint64(request["amount"])
        puzzle_hash: bytes32 = decode_puzzle_hash(request["address"])
        if "fee" in request:
            fee = uint64(request["fee"])
        else:
            fee = uint64(0)
        async with self.service.wallet_state_manager.lock:
            tx: TransactionRecord = await wallet.generate_signed_transaction(amount, puzzle_hash, fee)
            await wallet.push_transaction(tx)

        # Transaction may not have been included in the mempool yet. Use get_transaction to check.
        return {
            "transaction": tx,
            "transaction_id": tx.name,
        }

    async def get_transaction_count(self, request):
        wallet_id = int(request["wallet_id"])
        count = await self.service.wallet_state_manager.tx_store.get_transaction_count_for_wallet(wallet_id)
        return {"wallet_id": wallet_id, "count": count}

    async def create_backup(self, request):
        assert self.service.wallet_state_manager is not None
        file_path = Path(request["file_path"])
        await self.service.wallet_state_manager.create_wallet_backup(file_path)
        return {}

    ##########################################################################################
    # Coloured Coins and Trading
    ##########################################################################################

    async def cc_set_name(self, request):
        assert self.service.wallet_state_manager is not None
        wallet_id = int(request["wallet_id"])
        wallet: CCWallet = self.service.wallet_state_manager.wallets[wallet_id]
        await wallet.set_name(str(request["name"]))
        return {"wallet_id": wallet_id}

    async def cc_get_name(self, request):
        assert self.service.wallet_state_manager is not None
        wallet_id = int(request["wallet_id"])
        wallet: CCWallet = self.service.wallet_state_manager.wallets[wallet_id]
        name: str = await wallet.get_name()
        return {"wallet_id": wallet_id, "name": name}

    async def cc_spend(self, request):
        assert self.service.wallet_state_manager is not None
        wallet_id = int(request["wallet_id"])
        wallet: CCWallet = self.service.wallet_state_manager.wallets[wallet_id]
        puzzle_hash: bytes32 = decode_puzzle_hash(request["inner_address"])

        if not isinstance(request["amount"], int) or not isinstance(request["amount"], int):
            raise ValueError("An integer amount or fee is required (too many decimals)")
        amount: uint64 = uint64(request["amount"])
        if "fee" in request:
            fee = uint64(request["fee"])
        else:
            fee = uint64(0)
        async with self.service.wallet_state_manager.lock:
            tx: TransactionRecord = await wallet.generate_signed_transaction([amount], [puzzle_hash], fee)
            await wallet.push_transaction(tx)

        return {
            "transaction": tx,
            "transaction_id": tx.name,
        }

    async def cc_get_colour(self, request):
        assert self.service.wallet_state_manager is not None
        wallet_id = int(request["wallet_id"])
        wallet: CCWallet = self.service.wallet_state_manager.wallets[wallet_id]
        colour: str = wallet.get_colour()
        return {"colour": colour, "wallet_id": wallet_id}

    async def create_offer_for_ids(self, request):
        assert self.service.wallet_state_manager is not None

        offer = request["ids"]
        file_name = request["filename"]
        async with self.service.wallet_state_manager.lock:
            (
                success,
                spend_bundle,
                error,
            ) = await self.service.wallet_state_manager.trade_manager.create_offer_for_ids(offer, file_name)
        if success:
            self.service.wallet_state_manager.trade_manager.write_offer_to_disk(Path(file_name), spend_bundle)
            return {}
        raise ValueError(error)

    async def get_discrepancies_for_offer(self, request):
        assert self.service.wallet_state_manager is not None
        file_name = request["filename"]
        file_path = Path(file_name)
        async with self.service.wallet_state_manager.lock:
            (
                success,
                discrepancies,
                error,
            ) = await self.service.wallet_state_manager.trade_manager.get_discrepancies_for_offer(file_path)

        if success:
            return {"discrepancies": discrepancies}
        raise ValueError(error)

    async def respond_to_offer(self, request):
        assert self.service.wallet_state_manager is not None
        file_path = Path(request["filename"])
        async with self.service.wallet_state_manager.lock:
            (
                success,
                trade_record,
                error,
            ) = await self.service.wallet_state_manager.trade_manager.respond_to_offer(file_path)
        if not success:
            raise ValueError(error)
        return {}

    async def get_trade(self, request: Dict):
        assert self.service.wallet_state_manager is not None

        trade_mgr = self.service.wallet_state_manager.trade_manager

        trade_id = request["trade_id"]
        trade: Optional[TradeRecord] = await trade_mgr.get_trade_by_id(trade_id)
        if trade is None:
            raise ValueError(f"No trade with trade id: {trade_id}")

        result = trade_record_to_dict(trade)
        return {"trade": result}

    async def get_all_trades(self, request: Dict):
        assert self.service.wallet_state_manager is not None

        trade_mgr = self.service.wallet_state_manager.trade_manager

        all_trades = await trade_mgr.get_all_trades()
        result = []
        for trade in all_trades:
            result.append(trade_record_to_dict(trade))

        return {"trades": result}

    async def cancel_trade(self, request: Dict):
        assert self.service.wallet_state_manager is not None

        wsm = self.service.wallet_state_manager
        secure = request["secure"]
        trade_id = hexstr_to_bytes(request["trade_id"])

        async with self.service.wallet_state_manager.lock:
            if secure:
                await wsm.trade_manager.cancel_pending_offer_safely(trade_id)
            else:
                await wsm.trade_manager.cancel_pending_offer(trade_id)
        return {}

    async def get_backup_info(self, request: Dict):
        file_path = Path(request["file_path"])
        sk = None
        if "words" in request:
            mnemonic = request["words"]
            passphrase = ""
            try:
                sk = self.service.keychain.add_private_key(" ".join(mnemonic), passphrase)
            except KeyError as e:
                return {
                    "success": False,
                    "error": f"The word '{e.args[0]}' is incorrect.'",
                    "word": e.args[0],
                }
        elif "fingerprint" in request:
            sk, seed = await self._get_private_key(request["fingerprint"])

        if sk is None:
            raise ValueError("Unable to decrypt the backup file.")
        backup_info = get_backup_info(file_path, sk)
        return {"backup_info": backup_info}

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
            updated_puz = await wallet.get_new_puzzle()
            spend_bundle = await wallet.create_spend(updated_puz.get_tree_hash())

        success = spend_bundle is not None and update_success
        return {"success": success}

    async def did_spend(self, request):
        wallet_id = int(request["wallet_id"])
        async with self.service.wallet_state_manager.lock:
            wallet: DIDWallet = self.service.wallet_state_manager.wallets[wallet_id]
            spend_bundle = await wallet.create_spend(request["puzzlehash"])

        success = spend_bundle is not None
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
        community_reward_amount = 0
        fee_amount = 0
        last_height_farmed = 0
        for record in tx_records:
            height = record.height_farmed(self.service.constants.GENESIS_CHALLENGE)
            if height > last_height_farmed:
                last_height_farmed = height
            # Chives Network Code
            # Do not need to calculate the Community Rewards Amount To Wallet Card
            if( uint64(calculate_base_community_reward(height)) != uint64(record.amount) ):
                if record.type == TransactionType.COINBASE_REWARD:
                    pool_reward_amount += record.amount
                if record.type == TransactionType.FEE_REWARD:
                    fee_amount += record.amount - calculate_base_farmer_reward(height)
                    farmer_reward_amount += calculate_base_farmer_reward(height)
                amount += record.amount
            # log.warning("############for record in tx_records:")
            # log.warning(record.amount)
            # log.warning(calculate_base_farmer_reward(height))

        assert amount == pool_reward_amount + farmer_reward_amount + fee_amount
        return {
            "farmed_amount": amount,
            "pool_reward_amount": pool_reward_amount,
            "farmer_reward_amount": farmer_reward_amount,
            "community_reward_amount": community_reward_amount,
            "fee_amount": fee_amount,
            "last_height_farmed": last_height_farmed,
        }

    async def create_signed_transaction(self, request):
        if "additions" not in request or len(request["additions"]) < 1:
            raise ValueError("Specify additions list")

        additions: List[Dict] = request["additions"]
        amount_0: uint64 = uint64(additions[0]["amount"])
        assert amount_0 <= self.service.constants.MAX_COIN_AMOUNT
        puzzle_hash_0 = hexstr_to_bytes(additions[0]["puzzle_hash"])
        if len(puzzle_hash_0) != 32:
            raise ValueError(f"Address must be 32 bytes. {puzzle_hash_0}")

        additional_outputs = []
        for addition in additions[1:]:
            receiver_ph = hexstr_to_bytes(addition["puzzle_hash"])
            if len(receiver_ph) != 32:
                raise ValueError(f"Address must be 32 bytes. {receiver_ph}")
            amount = uint64(addition["amount"])
            if amount > self.service.constants.MAX_COIN_AMOUNT:
                raise ValueError(f"Coin amount cannot exceed {self.service.constants.MAX_COIN_AMOUNT}")
            additional_outputs.append({"puzzlehash": receiver_ph, "amount": amount})

        fee = uint64(0)
        if "fee" in request:
            fee = uint64(request["fee"])

        coins = None
        if "coins" in request and len(request["coins"]) > 0:
            coins = set([Coin.from_json_dict(coin_json) for coin_json in request["coins"]])

        async with self.service.wallet_state_manager.lock:
            signed_tx = await self.service.wallet_state_manager.main_wallet.generate_signed_transaction(
                amount_0, puzzle_hash_0, fee, coins=coins, ignore_max_send_amount=True, primaries=additional_outputs
            )
        return {"signed_tx": signed_tx}
