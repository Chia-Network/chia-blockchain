import asyncio
import json
import logging
import signal
import time
import traceback
from pathlib import Path
from blspy import ExtendedPrivateKey

from typing import List, Optional, Tuple

import aiohttp
from src.util.byte_types import hexstr_to_bytes
from src.util.keychain import Keychain, seed_from_mnemonic, generate_mnemonic
from src.util.path import path_from_root
from src.util.ws_message import create_payload, format_response, pong
from src.wallet.trade_manager import TradeManager

try:
    import uvloop
except ImportError:
    uvloop = None

from src.server.outbound_message import NodeType, OutboundMessage, Message, Delivery
from src.server.server import ChiaServer
from src.simulator.simulator_constants import test_constants
from src.simulator.simulator_protocol import FarmNewBlockProtocol
from src.util.config import load_config_cli, load_config
from src.util.ints import uint64
from src.util.logging import initialize_logging
from src.wallet.util.wallet_types import WalletType
from src.wallet.rl_wallet.rl_wallet import RLWallet
from src.wallet.cc_wallet.cc_wallet import CCWallet
from src.wallet.wallet_info import WalletInfo
from src.wallet.wallet_node import WalletNode
from src.types.mempool_inclusion_status import MempoolInclusionStatus
from src.util.default_root import DEFAULT_ROOT_PATH
from src.util.setproctitle import setproctitle
from src.cmds.init import check_keys

# Timeout for response from wallet/full node for sending a transaction
TIMEOUT = 30

log = logging.getLogger(__name__)


class WebSocketServer:
    def __init__(self, keychain: Keychain, root_path: Path):
        self.config = load_config_cli(root_path, "config.yaml", "wallet")
        initialize_logging("Wallet %(name)-25s", self.config["logging"], root_path)
        self.log = log
        self.keychain = keychain
        self.websocket = None
        self.root_path = root_path
        self.wallet_node: Optional[WalletNode] = None
        self.trade_manager: Optional[TradeManager] = None
        self.shut_down = False
        if self.config["testing"] is True:
            self.config["database_path"] = "test_db_wallet.db"

    async def start(self):
        self.log.info("Starting Websocket Server")

        def master_close_cb():
            asyncio.ensure_future(self.stop())

        try:
            asyncio.get_running_loop().add_signal_handler(
                signal.SIGINT, master_close_cb
            )
            asyncio.get_running_loop().add_signal_handler(
                signal.SIGTERM, master_close_cb
            )
        except NotImplementedError:
            self.log.info("Not implemented")

        await self.start_wallet()

        await self.connect_to_daemon()
        self.log.info("webSocketServer closed")

    async def start_wallet(self, public_key_fingerprint: Optional[int] = None) -> bool:
        private_keys = self.keychain.get_all_private_keys()
        if len(private_keys) == 0:
            self.log.info("No keys")
            return False

        if public_key_fingerprint is not None:
            for sk, _ in private_keys:
                if sk.get_public_key().get_fingerprint() == public_key_fingerprint:
                    private_key = sk
                    break
        else:
            private_key = private_keys[0][0]

        if private_key is None:
            self.log.info("No keys")
            return False

        if self.config["testing"] is True:
            log.info("Websocket server in testing mode")
            self.wallet_node = await WalletNode.create(
                self.config,
                private_key,
                self.root_path,
                override_constants=test_constants,
                local_test=True,
            )
        else:
            log.info("Not Testing")
            self.wallet_node = await WalletNode.create(
                self.config, private_key, self.root_path
            )

        if self.wallet_node is None:
            return False

        self.trade_manager = await TradeManager.create(
            self.wallet_node.wallet_state_manager
        )
        self.wallet_node.wallet_state_manager.set_callback(self.state_changed_callback)

        net_config = load_config(self.root_path, "config.yaml")
        ping_interval = net_config.get("ping_interval")
        network_id = net_config.get("network_id")
        assert ping_interval is not None
        assert network_id is not None

        server = ChiaServer(
            self.config["port"],
            self.wallet_node,
            NodeType.WALLET,
            ping_interval,
            network_id,
            self.root_path,
            self.config,
        )
        self.wallet_node.set_server(server)

        self.wallet_node._start_bg_tasks()

        return True

    async def connection(self, ws):
        data = {"service": "chia-wallet"}
        payload = create_payload("register_service", data, "chia-wallet", "daemon")
        await ws.send_str(payload)

        while True:
            msg = await ws.receive()
            if msg.type == aiohttp.WSMsgType.TEXT:
                message = msg.data.strip()
                # self.log.info(f"received message: {message}")
                await self.safe_handle(ws, message)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                pass
                # self.log.warning("Received binary data")
            elif msg.type == aiohttp.WSMsgType.PING:
                await ws.pong()
            elif msg.type == aiohttp.WSMsgType.PONG:
                self.log.info("Pong received")
            else:
                if msg.type == aiohttp.WSMsgType.CLOSE:
                    print("Closing")
                    await ws.close()
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print("Error during receive %s" % ws.exception())
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    pass

                break

        await ws.close()

    async def connect_to_daemon(self):
        while True:
            session = None
            try:
                if self.shut_down:
                    break
                session = aiohttp.ClientSession()
                async with session.ws_connect(
                    "ws://127.0.0.1:55400", autoclose=False, autoping=True
                ) as ws:
                    self.websocket = ws
                    await self.connection(ws)
                self.log.info("Connection closed")
                self.websocket = None
                await session.close()
            except BaseException as e:
                self.log.error(f"Exception: {e}")
                if session is not None:
                    await session.close()
            await asyncio.sleep(1)

    async def stop(self):
        self.shut_down = True
        if self.wallet_node is not None:
            self.wallet_node.server.close_all()
            self.wallet_node._shutdown()
            await self.wallet_node.wallet_state_manager.close_all_stores()
        self.log.info("closing websocket")
        if self.websocket is not None:
            self.log.info("closing websocket 2")
            await self.websocket.close()
        self.log.info("closied websocket")

    async def get_next_puzzle_hash(self, request):
        """
        Returns a new puzzlehash
        """

        wallet_id = int(request["wallet_id"])
        wallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]

        if wallet.wallet_info.type == WalletType.STANDARD_WALLET:
            puzzle_hash = (await wallet.get_new_puzzlehash()).hex()
        elif wallet.wallet_info.type == WalletType.COLOURED_COIN:
            puzzle_hash = await wallet.get_new_inner_hash()

        response = {
            "wallet_id": wallet_id,
            "puzzle_hash": puzzle_hash,
        }

        return response

    async def send_transaction(self, request):
        wallet_id = int(request["wallet_id"])
        wallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        try:
            tx = await wallet.generate_signed_transaction_dict(request)
        except BaseException as e:
            data = {
                "status": "FAILED",
                "reason": f"Failed to generate signed transaction {e}",
            }
            return data

        if tx is None:
            data = {
                "status": "FAILED",
                "reason": "Failed to generate signed transaction",
            }
            return data
        try:
            await wallet.push_transaction(tx)
        except BaseException as e:
            data = {
                "status": "FAILED",
                "reason": f"Failed to push transaction {e}",
            }
            return data
        self.log.error(tx)
        sent = False
        start = time.time()
        while time.time() - start < TIMEOUT:
            sent_to: List[
                Tuple[str, MempoolInclusionStatus, Optional[str]]
            ] = await self.wallet_node.wallet_state_manager.get_transaction_status(
                tx.name()
            )

            if len(sent_to) == 0:
                await asyncio.sleep(0.1)
                continue
            status, err = sent_to[0][1], sent_to[0][2]
            if status == MempoolInclusionStatus.SUCCESS:
                data = {"status": "SUCCESS"}
                sent = True
                break
            elif status == MempoolInclusionStatus.PENDING:
                assert err is not None
                data = {"status": "PENDING", "reason": err}
                sent = True
                break
            elif status == MempoolInclusionStatus.FAILED:
                assert err is not None
                data = {"status": "FAILED", "reason": err}
                sent = True
                break
        if not sent:
            data = {
                "status": "FAILED",
                "reason": "Timed out. Transaction may or may not have been sent.",
            }

        return data

    async def get_transactions(self, request):
        wallet_id = int(request["wallet_id"])
        transactions = await self.wallet_node.wallet_state_manager.get_all_transactions(
            wallet_id
        )

        response = {"success": True, "txs": transactions, "wallet_id": wallet_id}
        return response

    async def farm_block(self, request):
        puzzle_hash = bytes.fromhex(request["puzzle_hash"])
        request = FarmNewBlockProtocol(puzzle_hash)
        msg = OutboundMessage(
            NodeType.FULL_NODE, Message("farm_new_block", request), Delivery.BROADCAST,
        )

        self.wallet_node.server.push_message(msg)
        return {"success": True}

    async def get_wallet_balance(self, request):
        wallet_id = int(request["wallet_id"])
        wallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        balance = await wallet.get_confirmed_balance()
        pending_balance = await wallet.get_unconfirmed_balance()
        spendable_balance = await wallet.get_spendable_balance()
        pending_change = await wallet.get_pending_change_balance()
        if wallet.wallet_info.type == WalletType.COLOURED_COIN:
            frozen_balance = 0
        else:
            frozen_balance = await wallet.get_frozen_amount()

        response = {
            "wallet_id": wallet_id,
            "success": True,
            "confirmed_wallet_balance": balance,
            "unconfirmed_wallet_balance": pending_balance,
            "spendable_balance": spendable_balance,
            "frozen_balance": frozen_balance,
            "pending_change": pending_change,
        }

        return response

    async def get_sync_status(self):
        syncing = self.wallet_node.wallet_state_manager.sync_mode

        response = {"syncing": syncing}

        return response

    async def get_height_info(self):
        lca = self.wallet_node.wallet_state_manager.lca
        height = self.wallet_node.wallet_state_manager.block_records[lca].height

        response = {"height": height}

        return response

    async def get_connection_info(self):
        connections = (
            self.wallet_node.server.global_connections.get_full_node_peerinfos()
        )

        response = {"connections": connections}

        return response

    async def create_new_wallet(self, request):
        config, wallet_state_manager, main_wallet = self.get_wallet_config()

        if request["wallet_type"] == "cc_wallet":
            if request["mode"] == "new":
                cc_wallet: CCWallet = await CCWallet.create_new_cc(
                    wallet_state_manager, main_wallet, request["amount"]
                )
                response = {"success": True, "type": cc_wallet.wallet_info.type.name}
                return response
            elif request["mode"] == "existing":
                cc_wallet = await CCWallet.create_wallet_for_cc(
                    wallet_state_manager, main_wallet, request["colour"]
                )
                response = {"success": True, "type": cc_wallet.wallet_info.type.name}
                return response

        response = {"success": False}
        return response

    def get_wallet_config(self):
        return (
            self.wallet_node.config,
            self.wallet_node.wallet_state_manager,
            self.wallet_node.wallet_state_manager.main_wallet,
        )

    async def get_wallets(self):
        wallets: List[
            WalletInfo
        ] = await self.wallet_node.wallet_state_manager.get_all_wallets()

        response = {"wallets": wallets, "success": True}

        return response

    async def rl_set_admin_info(self, request):
        wallet_id = int(request["wallet_id"])
        wallet: RLWallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        user_pubkey = request["user_pubkey"]
        limit = uint64(int(request["limit"]))
        interval = uint64(int(request["interval"]))
        amount = uint64(int(request["amount"]))

        success = await wallet.admin_create_coin(interval, limit, user_pubkey, amount)

        response = {"success": success}

        return response

    async def rl_set_user_info(self, request):
        wallet_id = int(request["wallet_id"])
        wallet: RLWallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        admin_pubkey = request["admin_pubkey"]
        limit = uint64(int(request["limit"]))
        interval = uint64(int(request["interval"]))
        origin_id = request["origin_id"]

        success = await wallet.set_user_info(interval, limit, origin_id, admin_pubkey)

        response = {"success": success}

        return response

    async def cc_set_name(self, request):
        wallet_id = int(request["wallet_id"])
        wallet: CCWallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        await wallet.set_name(str(request["name"]))
        response = {"wallet_id": wallet_id, "success": True}
        return response

    async def cc_get_name(self, request):
        wallet_id = int(request["wallet_id"])
        wallet: CCWallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        name: str = await wallet.get_name()
        response = {"wallet_id": wallet_id, "name": name}
        return response

    async def cc_spend(self, request):
        wallet_id = int(request["wallet_id"])
        wallet: CCWallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        puzzle_hash = hexstr_to_bytes(request["innerpuzhash"])
        try:
            tx = await wallet.cc_spend(request["amount"], puzzle_hash)
        except BaseException as e:
            data = {
                "status": "FAILED",
                "reason": f"{e}",
            }
            return data

        if tx is None:
            data = {
                "status": "FAILED",
                "reason": "Failed to generate signed transaction",
            }
            return data

        self.log.error(tx)
        sent = False
        start = time.time()
        while time.time() - start < TIMEOUT:
            sent_to: List[
                Tuple[str, MempoolInclusionStatus, Optional[str]]
            ] = await self.wallet_node.wallet_state_manager.get_transaction_status(
                tx.name()
            )

            if len(sent_to) == 0:
                await asyncio.sleep(0.1)
                continue
            status, err = sent_to[0][1], sent_to[0][2]
            if status == MempoolInclusionStatus.SUCCESS:
                data = {"status": "SUCCESS"}
                sent = True
                break
            elif status == MempoolInclusionStatus.PENDING:
                assert err is not None
                data = {"status": "PENDING", "reason": err}
                sent = True
                break
            elif status == MempoolInclusionStatus.FAILED:
                assert err is not None
                data = {"status": "FAILED", "reason": err}
                sent = True
                break
        if not sent:
            data = {
                "status": "FAILED",
                "reason": "Timed out. Transaction may or may not have been sent.",
            }

        return data

    async def cc_get_colour(self, request):
        wallet_id = int(request["wallet_id"])
        wallet: CCWallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
        colour: str = await wallet.get_colour()
        response = {"colour": colour, "wallet_id": wallet_id}
        return response

    async def get_wallet_summaries(self):
        response = {}
        for wallet_id in self.wallet_node.wallet_state_manager.wallets:
            wallet = self.wallet_node.wallet_state_manager.wallets[wallet_id]
            balance = await wallet.get_confirmed_balance()
            type = wallet.wallet_info.type
            if type == WalletType.COLOURED_COIN:
                name = wallet.cc_info.my_colour_name
                colour = await wallet.get_colour()
                response[wallet_id] = {
                    "type": type,
                    "balance": balance,
                    "name": name,
                    "colour": colour,
                }
            else:
                response[wallet_id] = {"type": type, "balance": balance}
        return response

    async def get_discrepancies_for_offer(self, request):
        file_name = request["filename"]
        file_path = Path(file_name)
        (
            success,
            discrepancies,
            error,
        ) = await self.trade_manager.get_discrepancies_for_offer(file_path)

        if success:
            response = {"success": True, "discrepancies": discrepancies}
        else:
            response = {"success": False, "error": error}

        return response

    async def create_offer_for_ids(self, request):
        offer = request["ids"]
        file_name = request["filename"]
        success, spend_bundle, error = await self.trade_manager.create_offer_for_ids(
            offer
        )
        if success:
            self.trade_manager.write_offer_to_disk(Path(file_name), spend_bundle)
            response = {"success": success}
        else:
            response = {"success": success, "reason": error}

        return response

    async def respond_to_offer(self, request):
        file_path = Path(request["filename"])
        success, reason = await self.trade_manager.respond_to_offer(file_path)
        if success:
            response = {"success": success}
        else:
            response = {"success": success, "reason": reason}
        return response

    async def get_public_keys(self):
        fingerprints = [
            (esk.get_public_key().get_fingerprint(), seed is not None)
            for (esk, seed) in self.keychain.get_all_private_keys()
        ]
        response = {"success": True, "public_key_fingerprints": fingerprints}
        return response

    async def logged_in(self):
        private_key = self.keychain.get_wallet_key()
        if private_key is None:
            response = {"logged_in": False}
        else:
            response = {"logged_in": True}

        return response

    async def log_in(self, request):
        await self.stop_wallet()
        fingerprint = request["fingerprint"]

        started = await self.start_wallet(fingerprint)

        response = {"success": started}
        return response

    async def add_key(self, request):
        await self.stop_wallet()
        mnemonic = request["mnemonic"]
        self.log.info(f"Mnemonic {mnemonic}")
        seed = seed_from_mnemonic(mnemonic)
        self.log.info(f"Seed {seed}")
        fingerprint = (
            ExtendedPrivateKey.from_seed(seed).get_public_key().get_fingerprint()
        )
        self.keychain.add_private_key_seed(seed)
        check_keys(self.root_path)

        started = await self.start_wallet(fingerprint)

        response = {"success": started}
        return response

    async def delete_key(self, request):
        await self.stop_wallet()
        fingerprint = request["fingerprint"]
        self.keychain.delete_key_by_fingerprint(fingerprint)
        response = {"success": True}
        return response

    async def clean_all_state(self):
        self.keychain.delete_all_keys()
        path = path_from_root(self.root_path, self.config["database_path"])
        if path.exists():
            path.unlink()

    async def stop_wallet(self):
        if self.wallet_node is not None:
            if self.wallet_node.server is not None:
                self.wallet_node.server.close_all()
            self.wallet_node._shutdown()
            await self.wallet_node.wallet_state_manager.close_all_stores()
            self.wallet_node = None

    async def delete_all_keys(self):
        await self.stop_wallet()
        await self.clean_all_state()
        response = {"success": True}
        return response

    async def generate_mnemonic(self):
        mnemonic = generate_mnemonic()
        response = {"success": True, "mnemonic": mnemonic}
        return response

    async def safe_handle(self, websocket, payload):
        message = None
        try:
            message = json.loads(payload)
            response = await self.handle_message(message)
            if response is not None:
                # self.log.info(f"message: {message}")
                # self.log.info(f"response: {response}")
                # self.log.info(f"payload: {format_response(message, response)}")
                await websocket.send_str(format_response(message, response))

        except BaseException as e:
            tb = traceback.format_exc()
            self.log.error(f"Error while handling message: {tb}")
            error = {"success": False, "error": f"{e}"}
            if message is None:
                return
            await websocket.send_str(format_response(message, error))

    async def handle_message(self, message):
        """
        This function gets called when new message is received via websocket.
        """

        command = message["command"]
        if message["ack"]:
            return None

        data = None
        if "data" in message:
            data = message["data"]
        if command == "ping":
            return pong()
        elif command == "get_wallet_balance":
            return await self.get_wallet_balance(data)
        elif command == "send_transaction":
            return await self.send_transaction(data)
        elif command == "get_next_puzzle_hash":
            return await self.get_next_puzzle_hash(data)
        elif command == "get_transactions":
            return await self.get_transactions(data)
        elif command == "farm_block":
            return await self.farm_block(data)
        elif command == "get_sync_status":
            return await self.get_sync_status()
        elif command == "get_height_info":
            return await self.get_height_info()
        elif command == "get_connection_info":
            return await self.get_connection_info()
        elif command == "create_new_wallet":
            return await self.create_new_wallet(data)
        elif command == "get_wallets":
            return await self.get_wallets()
        elif command == "rl_set_admin_info":
            return await self.rl_set_admin_info(data)
        elif command == "rl_set_user_info":
            return await self.rl_set_user_info(data)
        elif command == "cc_set_name":
            return await self.cc_set_name(data)
        elif command == "cc_get_name":
            return await self.cc_get_name(data)
        elif command == "cc_spend":
            return await self.cc_spend(data)
        elif command == "cc_get_colour":
            return await self.cc_get_colour(data)
        elif command == "create_offer_for_ids":
            return await self.create_offer_for_ids(data)
        elif command == "get_discrepancies_for_offer":
            return await self.get_discrepancies_for_offer(data)
        elif command == "respond_to_offer":
            return await self.respond_to_offer(data)
        elif command == "get_wallet_summaries":
            return await self.get_wallet_summaries()
        elif command == "get_public_keys":
            return await self.get_public_keys()
        elif command == "logged_in":
            return await self.logged_in()
        elif command == "generate_mnemonic":
            return await self.generate_mnemonic()
        elif command == "log_in":
            return await self.log_in(data)
        elif command == "add_key":
            return await self.add_key(data)
        elif command == "delete_key":
            return await self.delete_key(data)
        elif command == "delete_all_keys":
            return await self.delete_all_keys()
        else:
            response = {"error": f"unknown_command {command}"}
            return response

    async def notify_ui_that_state_changed(self, state: str, wallet_id):
        data = {
            "state": state,
        }
        # self.log.info(f"Wallet notify id is: {wallet_id}")
        if wallet_id is not None:
            data["wallet_id"] = wallet_id

        if self.websocket is not None:
            try:
                await self.websocket.send_str(
                    create_payload("state_changed", data, "chia-wallet", "wallet_ui")
                )
            except (BaseException) as e:
                try:
                    self.log.warning(f"Sending data failed. Exception {type(e)}.")
                except BrokenPipeError:
                    pass

    def state_changed_callback(self, state: str, wallet_id: int = None):
        if self.websocket is None:
            return
        asyncio.create_task(self.notify_ui_that_state_changed(state, wallet_id))


async def start_websocket_server():
    """
    Starts WalletNode, WebSocketServer, and ChiaServer
    """

    setproctitle("chia-wallet")
    keychain = Keychain(testing=False)
    websocket_server = WebSocketServer(keychain, DEFAULT_ROOT_PATH)
    await websocket_server.start()
    log.info("Wallet fully closed")


def main():
    if uvloop is not None:
        uvloop.install()
    asyncio.run(start_websocket_server())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        tb = traceback.format_exc()
        log = logging.getLogger(__name__)
        log.error(f"Error in wallet. {tb}")
        raise
