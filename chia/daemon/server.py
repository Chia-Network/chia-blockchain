import asyncio
import json
import logging
import os
import signal
import ssl
import subprocess
import sys
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, TextIO, Tuple, cast

from websockets import ConnectionClosedOK, WebSocketException, WebSocketServerProtocol, serve

from chia.cmds.init_funcs import check_keys, chia_init
from chia.cmds.passphrase_funcs import default_passphrase, using_default_passphrase
from chia.daemon.keychain_server import KeychainServer, keychain_commands
from chia.daemon.windows_signal import kill
from chia.plotters.plotters import get_available_plotters
from chia.plotting.util import add_plot_directory
from chia.server.server import ssl_context_for_root, ssl_context_for_server
from chia.ssl.create_ssl import get_mozilla_ca_crt
from chia.util.chia_logging import initialize_logging
from chia.util.config import load_config
from chia.util.json_util import dict_to_json_str
from chia.util.keychain import (
    Keychain,
    KeyringCurrentPassphraseIsInvalid,
    KeyringRequiresMigration,
    passphrase_requirements,
    supports_keyring_passphrase,
    supports_os_passphrase_storage,
)
from chia.util.path import mkdir
from chia.util.service_groups import validate_service
from chia.util.setproctitle import setproctitle
from chia.util.ws_message import WsRpcMessage, create_payload, format_response
from chia import __version__

io_pool_exc = ThreadPoolExecutor()

try:
    from aiohttp import ClientSession, web
except ModuleNotFoundError:
    print("Error: Make sure to run . ./activate from the project folder before starting Chia.")
    quit()

try:
    import fcntl

    has_fcntl = True
except ImportError:
    has_fcntl = False

log = logging.getLogger(__name__)

service_plotter = "chia_plotter"


async def fetch(url: str):
    async with ClientSession() as session:
        try:
            mozilla_root = get_mozilla_ca_crt()
            ssl_context = ssl_context_for_root(mozilla_root, log=log)
            response = await session.get(url, ssl=ssl_context)
            if not response.ok:
                log.warning("Response not OK.")
                return None
            return await response.text()
        except Exception as e:
            log.error(f"Exception while fetching {url}, exception: {e}")
            return None


class PlotState(str, Enum):
    SUBMITTED = "SUBMITTED"
    RUNNING = "RUNNING"
    REMOVING = "REMOVING"
    FINISHED = "FINISHED"


class PlotEvent(str, Enum):
    LOG_CHANGED = "log_changed"
    STATE_CHANGED = "state_changed"


# determine if application is a script file or frozen exe
if getattr(sys, "frozen", False):
    name_map = {
        "chia": "chia",
        "chia_wallet": "start_wallet",
        "chia_full_node": "start_full_node",
        "chia_harvester": "start_harvester",
        "chia_farmer": "start_farmer",
        "chia_introducer": "start_introducer",
        "chia_timelord": "start_timelord",
        "chia_timelord_launcher": "timelord_launcher",
        "chia_full_node_simulator": "start_simulator",
        "chia_seeder": "chia_seeder",
        "chia_seeder_crawler": "chia_seeder_crawler",
        "chia_seeder_dns": "chia_seeder_dns",
    }

    def executable_for_service(service_name: str) -> str:
        application_path = os.path.dirname(sys.executable)
        if sys.platform == "win32" or sys.platform == "cygwin":
            executable = name_map[service_name]
            path = f"{application_path}/{executable}.exe"
            return path
        else:
            path = f"{application_path}/{name_map[service_name]}"
            return path


else:
    application_path = os.path.dirname(__file__)

    def executable_for_service(service_name: str) -> str:
        return service_name


async def ping() -> Dict[str, Any]:
    response = {"success": True, "value": "pong"}
    return response


class WebSocketServer:
    def __init__(
        self,
        root_path: Path,
        ca_crt_path: Path,
        ca_key_path: Path,
        crt_path: Path,
        key_path: Path,
        run_check_keys_on_unlock: bool = False,
    ):
        self.root_path = root_path
        self.log = log
        self.services: Dict = dict()
        self.plots_queue: List[Dict] = []
        self.connections: Dict[str, List[WebSocketServerProtocol]] = dict()  # service_name : [WebSocket]
        self.remote_address_map: Dict[WebSocketServerProtocol, str] = dict()  # socket: service_name
        self.ping_job: Optional[asyncio.Task] = None
        self.net_config = load_config(root_path, "config.yaml")
        self.self_hostname = self.net_config["self_hostname"]
        self.daemon_port = self.net_config["daemon_port"]
        self.daemon_max_message_size = self.net_config.get("daemon_max_message_size", 50 * 1000 * 1000)
        self.websocket_server = None
        self.ssl_context = ssl_context_for_server(ca_crt_path, ca_key_path, crt_path, key_path, log=self.log)
        self.shut_down = False
        self.keychain_server = KeychainServer()
        self.run_check_keys_on_unlock = run_check_keys_on_unlock

    async def start(self):
        self.log.info("Starting Daemon Server")

        if ssl.OPENSSL_VERSION_NUMBER < 0x10101000:
            self.log.warning(
                (
                    "Deprecation Warning: Your version of openssl (%s) does not support TLS1.3. "
                    "A future version of Chia will require TLS1.3."
                ),
                ssl.OPENSSL_VERSION,
            )
        else:
            if self.ssl_context is not None:
                # Daemon is internal connections, so override to TLS1.3 only
                self.ssl_context.minimum_version = ssl.TLSVersion.TLSv1_3

        def master_close_cb():
            asyncio.create_task(self.stop())

        try:
            asyncio.get_running_loop().add_signal_handler(signal.SIGINT, master_close_cb)
            asyncio.get_running_loop().add_signal_handler(signal.SIGTERM, master_close_cb)
        except NotImplementedError:
            self.log.info("Not implemented")

        self.websocket_server = await serve(
            self.safe_handle,
            self.self_hostname,
            self.daemon_port,
            max_size=self.daemon_max_message_size,
            ping_interval=500,
            ping_timeout=300,
            ssl=self.ssl_context,
        )
        self.log.info("Waiting Daemon WebSocketServer closure")

    def cancel_task_safe(self, task: Optional[asyncio.Task]):
        if task is not None:
            try:
                task.cancel()
            except Exception as e:
                self.log.error(f"Error while canceling task.{e} {task}")

    async def stop(self) -> Dict[str, Any]:
        self.shut_down = True
        self.cancel_task_safe(self.ping_job)
        await self.exit()
        if self.websocket_server is not None:
            self.websocket_server.close()
        return {"success": True}

    async def safe_handle(self, websocket: WebSocketServerProtocol, path: str):
        service_name = ""
        try:
            async for message in websocket:
                try:
                    decoded = json.loads(message)
                    if "data" not in decoded:
                        decoded["data"] = {}
                    response, sockets_to_use = await self.handle_message(websocket, decoded)
                except Exception as e:
                    tb = traceback.format_exc()
                    self.log.error(f"Error while handling message: {tb}")
                    error = {"success": False, "error": f"{e}"}
                    response = format_response(decoded, error)
                    sockets_to_use = []
                if len(sockets_to_use) > 0:
                    for socket in sockets_to_use:
                        try:
                            await socket.send(response)
                        except Exception as e:
                            tb = traceback.format_exc()
                            self.log.error(f"Unexpected exception trying to send to websocket: {e} {tb}")
                            self.remove_connection(socket)
                            await socket.close()
        except Exception as e:
            tb = traceback.format_exc()
            service_name = "Unknown"
            if websocket in self.remote_address_map:
                service_name = self.remote_address_map[websocket]
            if isinstance(e, ConnectionClosedOK):
                self.log.info(f"ConnectionClosedOk. Closing websocket with {service_name} {e}")
            elif isinstance(e, WebSocketException):
                self.log.info(f"Websocket exception. Closing websocket with {service_name} {e} {tb}")
            else:
                self.log.error(f"Unexpected exception in websocket: {e} {tb}")
        finally:
            self.remove_connection(websocket)
            await websocket.close()

    def remove_connection(self, websocket: WebSocketServerProtocol):
        service_name = None
        if websocket in self.remote_address_map:
            service_name = self.remote_address_map[websocket]
            self.remote_address_map.pop(websocket)
        if service_name in self.connections:
            after_removal = []
            for connection in self.connections[service_name]:
                if connection == websocket:
                    continue
                else:
                    after_removal.append(connection)
            self.connections[service_name] = after_removal

    async def ping_task(self) -> None:
        restart = True
        await asyncio.sleep(30)
        for remote_address, service_name in self.remote_address_map.items():
            if service_name in self.connections:
                sockets = self.connections[service_name]
                for socket in sockets:
                    if socket.remote_address[1] == remote_address:
                        try:
                            self.log.info(f"About to ping: {service_name}")
                            await socket.ping()
                        except asyncio.CancelledError:
                            self.log.info("Ping task received Cancel")
                            restart = False
                            break
                        except Exception as e:
                            self.log.info(f"Ping error: {e}")
                            self.log.warning("Ping failed, connection closed.")
                            self.remove_connection(socket)
                            await socket.close()
        if restart is True:
            self.ping_job = asyncio.create_task(self.ping_task())

    async def handle_message(
        self, websocket: WebSocketServerProtocol, message: WsRpcMessage
    ) -> Tuple[Optional[str], List[Any]]:
        """
        This function gets called when new message is received via websocket.
        """

        command = message["command"]
        destination = message["destination"]
        if destination != "daemon":
            destination = message["destination"]
            if destination in self.connections:
                sockets = self.connections[destination]
                return dict_to_json_str(message), sockets

            return None, []

        data = message["data"]
        commands_with_data = [
            "start_service",
            "start_plotting",
            "stop_plotting",
            "stop_service",
            "is_running",
            "register_service",
        ]
        if len(data) == 0 and command in commands_with_data:
            response = {"success": False, "error": f'{command} requires "data"'}
        # Keychain commands should be handled by KeychainServer
        elif command in keychain_commands and supports_keyring_passphrase():
            response = await self.keychain_server.handle_command(command, data)
        elif command == "ping":
            response = await ping()
        elif command == "start_service":
            response = await self.start_service(cast(Dict[str, Any], data))
        elif command == "start_plotting":
            response = await self.start_plotting(cast(Dict[str, Any], data))
        elif command == "stop_plotting":
            response = await self.stop_plotting(cast(Dict[str, Any], data))
        elif command == "stop_service":
            response = await self.stop_service(cast(Dict[str, Any], data))
        elif command == "is_running":
            response = await self.is_running(cast(Dict[str, Any], data))
        elif command == "is_keyring_locked":
            response = await self.is_keyring_locked()
        elif command == "keyring_status":
            response = await self.keyring_status()
        elif command == "unlock_keyring":
            response = await self.unlock_keyring(cast(Dict[str, Any], data))
        elif command == "validate_keyring_passphrase":
            response = await self.validate_keyring_passphrase(cast(Dict[str, Any], data))
        elif command == "migrate_keyring":
            response = await self.migrate_keyring(cast(Dict[str, Any], data))
        elif command == "set_keyring_passphrase":
            response = await self.set_keyring_passphrase(cast(Dict[str, Any], data))
        elif command == "remove_keyring_passphrase":
            response = await self.remove_keyring_passphrase(cast(Dict[str, Any], data))
        elif command == "notify_keyring_migration_completed":
            response = await self.notify_keyring_migration_completed(cast(Dict[str, Any], data))
        elif command == "exit":
            response = await self.stop()
        elif command == "register_service":
            response = await self.register_service(websocket, cast(Dict[str, Any], data))
        elif command == "get_status":
            response = self.get_status()
        elif command == "get_version":
            response = self.get_version()
        elif command == "get_plotters":
            response = await self.get_plotters()
        else:
            self.log.error(f"UK>> {message}")
            response = {"success": False, "error": f"unknown_command {command}"}

        full_response = format_response(message, response)
        return full_response, [websocket]

    async def is_keyring_locked(self) -> Dict[str, Any]:
        locked: bool = Keychain.is_keyring_locked()
        response: Dict[str, Any] = {"success": True, "is_keyring_locked": locked}
        return response

    async def keyring_status(self) -> Dict[str, Any]:
        passphrase_support_enabled: bool = supports_keyring_passphrase()
        can_save_passphrase: bool = supports_os_passphrase_storage()
        user_passphrase_is_set: bool = Keychain.has_master_passphrase() and not using_default_passphrase()
        locked: bool = Keychain.is_keyring_locked()
        needs_migration: bool = Keychain.needs_migration()
        can_remove_legacy_keys: bool = False  # Disabling GUI support for removing legacy keys post-migration
        can_set_passphrase_hint: bool = True
        passphrase_hint: str = Keychain.get_master_passphrase_hint() or ""
        requirements: Dict[str, Any] = passphrase_requirements()
        response: Dict[str, Any] = {
            "success": True,
            "is_keyring_locked": locked,
            "passphrase_support_enabled": passphrase_support_enabled,
            "can_save_passphrase": can_save_passphrase,
            "user_passphrase_is_set": user_passphrase_is_set,
            "needs_migration": needs_migration,
            "can_remove_legacy_keys": can_remove_legacy_keys,
            "can_set_passphrase_hint": can_set_passphrase_hint,
            "passphrase_hint": passphrase_hint,
            "passphrase_requirements": requirements,
        }
        # Help diagnose GUI launch issues
        self.log.debug(f"Keyring status: {response}")
        return response

    async def unlock_keyring(self, request: Dict[str, Any]) -> Dict[str, Any]:
        success: bool = False
        error: Optional[str] = None
        key: Optional[str] = request.get("key", None)
        if type(key) is not str:
            return {"success": False, "error": "missing key"}

        try:
            if Keychain.master_passphrase_is_valid(key, force_reload=True):
                Keychain.set_cached_master_passphrase(key)
                success = True

                # Attempt to silently migrate legacy keys if necessary. Non-fatal if this fails.
                try:
                    if not Keychain.migration_checked_for_current_version():
                        self.log.info("Will attempt to migrate legacy keys...")
                        Keychain.migrate_legacy_keys_silently()
                        self.log.info("Migration of legacy keys complete.")
                    else:
                        self.log.debug("Skipping legacy key migration (previously attempted).")
                except Exception:
                    self.log.exception("Failed to migrate keys silently. Run `chia keys migrate` manually.")

                # Inform the GUI of keyring status changes
                self.keyring_status_changed(await self.keyring_status(), "wallet_ui")
            else:
                error = "bad passphrase"
        except Exception as e:
            tb = traceback.format_exc()
            self.log.error(f"Keyring passphrase validation failed: {e} {tb}")
            error = "validation exception"

        if success and self.run_check_keys_on_unlock:
            try:
                self.log.info("Running check_keys now that the keyring is unlocked")
                check_keys(self.root_path)
                self.run_check_keys_on_unlock = False
            except Exception as e:
                tb = traceback.format_exc()
                self.log.error(f"check_keys failed after unlocking keyring: {e} {tb}")

        response: Dict[str, Any] = {"success": success, "error": error}
        return response

    async def validate_keyring_passphrase(self, request: Dict[str, Any]) -> Dict[str, Any]:
        success: bool = False
        error: Optional[str] = None
        key: Optional[str] = request.get("key", None)
        if type(key) is not str:
            return {"success": False, "error": "missing key"}

        try:
            success = Keychain.master_passphrase_is_valid(key, force_reload=True)
        except Exception as e:
            tb = traceback.format_exc()
            self.log.error(f"Keyring passphrase validation failed: {e} {tb}")
            error = "validation exception"

        response: Dict[str, Any] = {"success": success, "error": error}
        return response

    async def migrate_keyring(self, request: Dict[str, Any]) -> Dict[str, Any]:
        if Keychain.needs_migration() is False:
            # If the keyring has already been migrated, we'll raise an error to the client.
            # The reason for raising an error is because the migration request has side-
            # effects beyond copying keys from the legacy keyring to the new keyring. The
            # request may have set a passphrase and indicated that keys should be cleaned
            # from the legacy keyring. If we were to return early and indicate success,
            # the client and user's expectations may not match reality (were my keys
            # deleted from the legacy keyring? was my passphrase set?).
            return {"success": False, "error": "migration not needed"}

        success: bool = False
        error: Optional[str] = None
        passphrase: Optional[str] = request.get("passphrase", None)
        passphrase_hint: Optional[str] = request.get("passphrase_hint", None)
        save_passphrase: bool = request.get("save_passphrase", False)
        cleanup_legacy_keyring: bool = request.get("cleanup_legacy_keyring", False)

        if passphrase is not None and type(passphrase) is not str:
            return {"success": False, "error": 'expected string value for "passphrase"'}

        if passphrase_hint is not None and type(passphrase_hint) is not str:
            return {"success": False, "error": 'expected string value for "passphrase_hint"'}

        if not Keychain.passphrase_meets_requirements(passphrase):
            return {"success": False, "error": "passphrase doesn't satisfy requirements"}

        if type(cleanup_legacy_keyring) is not bool:
            return {"success": False, "error": 'expected bool value for "cleanup_legacy_keyring"'}

        try:
            Keychain.migrate_legacy_keyring(
                passphrase=passphrase,
                passphrase_hint=passphrase_hint,
                save_passphrase=save_passphrase,
                cleanup_legacy_keyring=cleanup_legacy_keyring,
            )
            success = True
            # Inform the GUI of keyring status changes
            self.keyring_status_changed(await self.keyring_status(), "wallet_ui")
        except Exception as e:
            tb = traceback.format_exc()
            self.log.error(f"Legacy keyring migration failed: {e} {tb}")
            error = f"keyring migration failed: {e}"

        response: Dict[str, Any] = {"success": success, "error": error}
        return response

    async def set_keyring_passphrase(self, request: Dict[str, Any]) -> Dict[str, Any]:
        success: bool = False
        error: Optional[str] = None
        current_passphrase: Optional[str] = None
        new_passphrase: Optional[str] = None
        passphrase_hint: Optional[str] = request.get("passphrase_hint", None)
        save_passphrase: bool = request.get("save_passphrase", False)

        if using_default_passphrase():
            current_passphrase = default_passphrase()

        if Keychain.has_master_passphrase() and not current_passphrase:
            current_passphrase = request.get("current_passphrase", None)
            if type(current_passphrase) is not str:
                return {"success": False, "error": "missing current_passphrase"}

        new_passphrase = request.get("new_passphrase", None)
        if type(new_passphrase) is not str:
            return {"success": False, "error": "missing new_passphrase"}

        if not Keychain.passphrase_meets_requirements(new_passphrase):
            return {"success": False, "error": "passphrase doesn't satisfy requirements"}

        try:
            assert new_passphrase is not None  # mypy, I love you
            Keychain.set_master_passphrase(
                current_passphrase,
                new_passphrase,
                allow_migration=False,
                passphrase_hint=passphrase_hint,
                save_passphrase=save_passphrase,
            )
        except KeyringRequiresMigration:
            error = "keyring requires migration"
        except KeyringCurrentPassphraseIsInvalid:
            error = "current passphrase is invalid"
        except Exception as e:
            tb = traceback.format_exc()
            self.log.error(f"Failed to set keyring passphrase: {e} {tb}")
        else:
            success = True
            # Inform the GUI of keyring status changes
            self.keyring_status_changed(await self.keyring_status(), "wallet_ui")

        response: Dict[str, Any] = {"success": success, "error": error}
        return response

    async def remove_keyring_passphrase(self, request: Dict[str, Any]) -> Dict[str, Any]:
        success: bool = False
        error: Optional[str] = None
        current_passphrase: Optional[str] = None

        if not Keychain.has_master_passphrase():
            return {"success": False, "error": "passphrase not set"}

        current_passphrase = request.get("current_passphrase", None)
        if type(current_passphrase) is not str:
            return {"success": False, "error": "missing current_passphrase"}

        try:
            Keychain.remove_master_passphrase(current_passphrase)
        except KeyringCurrentPassphraseIsInvalid:
            error = "current passphrase is invalid"
        except Exception as e:
            tb = traceback.format_exc()
            self.log.error(f"Failed to remove keyring passphrase: {e} {tb}")
        else:
            success = True
            # Inform the GUI of keyring status changes
            self.keyring_status_changed(await self.keyring_status(), "wallet_ui")

        response: Dict[str, Any] = {"success": success, "error": error}
        return response

    async def notify_keyring_migration_completed(self, request: Dict[str, Any]) -> Dict[str, Any]:
        success: bool = False
        error: Optional[str] = None
        key: Optional[str] = request.get("key", None)

        if type(key) is not str:
            return {"success": False, "error": "missing key"}

        Keychain.handle_migration_completed()

        try:
            if Keychain.master_passphrase_is_valid(key, force_reload=True):
                Keychain.set_cached_master_passphrase(key)
                success = True
                # Inform the GUI of keyring status changes
                self.keyring_status_changed(await self.keyring_status(), "wallet_ui")
            else:
                error = "bad passphrase"
        except Exception as e:
            tb = traceback.format_exc()
            self.log.error(f"Keyring passphrase validation failed: {e} {tb}")
            error = "validation exception"

        response: Dict[str, Any] = {"success": success, "error": error}
        return response

    def get_status(self) -> Dict[str, Any]:
        response = {"success": True, "genesis_initialized": True}
        return response

    def get_version(self) -> Dict[str, Any]:
        response = {"success": True, "version": __version__}
        return response

    async def get_plotters(self) -> Dict[str, Any]:
        plotters: Dict[str, Any] = get_available_plotters(self.root_path)
        response: Dict[str, Any] = {"success": True, "plotters": plotters}
        return response

    async def _keyring_status_changed(self, keyring_status: Dict[str, Any], destination: str):
        """
        Attempt to communicate with the GUI to inform it of any keyring status changes
        (e.g. keyring becomes unlocked or migration completes)
        """
        websockets = self.connections.get("wallet_ui", None)

        if websockets is None:
            return None

        if keyring_status is None:
            return None

        response = create_payload("keyring_status_changed", keyring_status, "daemon", destination)

        for websocket in websockets:
            try:
                await websocket.send(response)
            except Exception as e:
                tb = traceback.format_exc()
                self.log.error(f"Unexpected exception trying to send to websocket: {e} {tb}")
                websockets.remove(websocket)
                await websocket.close()

    def keyring_status_changed(self, keyring_status: Dict[str, Any], destination: str):
        asyncio.create_task(self._keyring_status_changed(keyring_status, destination))

    def plot_queue_to_payload(self, plot_queue_item, send_full_log: bool) -> Dict[str, Any]:
        error = plot_queue_item.get("error")
        has_error = error is not None

        item = {
            "id": plot_queue_item["id"],
            "queue": plot_queue_item["queue"],
            "size": plot_queue_item["size"],
            "parallel": plot_queue_item["parallel"],
            "delay": plot_queue_item["delay"],
            "state": plot_queue_item["state"],
            "error": str(error) if has_error else None,
            "deleted": plot_queue_item["deleted"],
            "log_new": plot_queue_item.get("log_new"),
        }

        if send_full_log:
            item["log"] = plot_queue_item.get("log")
        return item

    def prepare_plot_state_message(self, state: PlotEvent, id):
        message = {
            "state": state,
            "queue": self.extract_plot_queue(id),
        }
        return message

    def extract_plot_queue(self, id=None) -> List[Dict]:
        send_full_log = id is None
        data = []
        for item in self.plots_queue:
            if id is None or item["id"] == id:
                data.append(self.plot_queue_to_payload(item, send_full_log))
        return data

    async def _state_changed(self, service: str, message: Dict[str, Any]):
        """If id is None, send the whole state queue"""
        if service not in self.connections:
            return None

        websockets = self.connections[service]

        if message is None:
            return None

        response = create_payload("state_changed", message, service, "wallet_ui")

        for websocket in websockets:
            try:
                await websocket.send(response)
            except Exception as e:
                tb = traceback.format_exc()
                self.log.error(f"Unexpected exception trying to send to websocket: {e} {tb}")
                websockets.remove(websocket)
                await websocket.close()

    def state_changed(self, service: str, message: Dict[str, Any]):
        asyncio.create_task(self._state_changed(service, message))

    async def _watch_file_changes(self, config, fp: TextIO, loop: asyncio.AbstractEventLoop):
        id: str = config["id"]
        plotter: str = config["plotter"]
        final_words: List[str] = []

        if plotter == "chiapos":
            final_words = ["Renamed final file"]
        elif plotter == "bladebit":
            final_words = ["Finished plotting in"]
        elif plotter == "madmax":
            temp_dir = config["temp_dir"]
            final_dir = config["final_dir"]
            if temp_dir == final_dir:
                final_words = ["Total plot creation time was"]
            else:
                # "Renamed final plot" if moving to a final dir on the same volume
                # "Copy to <path> finished, took..." if copying to another volume
                final_words = ["Renamed final plot", "finished, took"]

        while True:
            new_data = await loop.run_in_executor(io_pool_exc, fp.readline)

            if config["state"] is not PlotState.RUNNING:
                return None

            if new_data not in (None, ""):
                config["log"] = new_data if config["log"] is None else config["log"] + new_data
                config["log_new"] = new_data
                self.state_changed(service_plotter, self.prepare_plot_state_message(PlotEvent.LOG_CHANGED, id))

            if new_data:
                for word in final_words:
                    if word in new_data:
                        return None
            else:
                time.sleep(0.5)

    async def _track_plotting_progress(self, config, loop: asyncio.AbstractEventLoop):
        file_path = config["out_file"]
        with open(file_path, "r") as fp:
            await self._watch_file_changes(config, fp, loop)

    def _common_plotting_command_args(self, request: Any, ignoreCount: bool) -> List[str]:
        n = 1 if ignoreCount else request["n"]  # Plot count
        d = request["d"]  # Final directory
        r = request["r"]  # Threads
        f = request.get("f")  # Farmer pubkey
        p = request.get("p")  # Pool pubkey
        c = request.get("c")  # Pool contract address

        command_args: List[str] = []
        command_args.append(f"-n{n}")
        command_args.append(f"-d{d}")
        command_args.append(f"-r{r}")

        if f is not None:
            command_args.append(f"-f{f}")

        if p is not None:
            command_args.append(f"-p{p}")

        if c is not None:
            command_args.append(f"-c{c}")

        return command_args

    def _chiapos_plotting_command_args(self, request: Any, ignoreCount: bool) -> List[str]:
        k = request["k"]  # Plot size
        t = request["t"]  # Temp directory
        t2 = request["t2"]  # Temp2 directory
        b = request["b"]  # Buffer size
        u = request["u"]  # Buckets
        a = request.get("a")  # Fingerprint
        e = request["e"]  # Disable bitfield
        x = request["x"]  # Exclude final directory
        override_k = request["overrideK"]  # Force plot sizes < k32

        command_args: List[str] = []
        command_args.append(f"-k{k}")
        command_args.append(f"-t{t}")
        command_args.append(f"-2{t2}")
        command_args.append(f"-b{b}")
        command_args.append(f"-u{u}")

        if a is not None:
            command_args.append(f"-a{a}")

        if e is True:
            command_args.append("-e")

        if x is True:
            command_args.append("-x")

        if override_k is True:
            command_args.append("--override-k")

        return command_args

    def _bladebit_plotting_command_args(self, request: Any, ignoreCount: bool) -> List[str]:
        w = request.get("w", False)  # Warm start
        m = request.get("m", False)  # Disable NUMA

        command_args: List[str] = []

        if w is True:
            command_args.append("-w")

        if m is True:
            command_args.append("-m")

        return command_args

    def _madmax_plotting_command_args(self, request: Any, ignoreCount: bool, index: int) -> List[str]:
        k = request["k"]  # Plot size
        t = request["t"]  # Temp directory
        t2 = request["t2"]  # Temp2 directory
        u = request["u"]  # Buckets
        v = request["v"]  # Buckets for phase 3 & 4
        K = request.get("K", 1)  # Thread multiplier for phase 2
        G = request.get("G", False)  # Alternate tmpdir/tmp2dir

        command_args: List[str] = []
        command_args.append(f"-k{k}")
        command_args.append(f"-u{u}")
        command_args.append(f"-v{v}")
        command_args.append(f"-K{K}")

        # Handle madmax's tmptoggle option ourselves when managing GUI plotting
        if G is True and t != t2 and index % 2:
            # Swap tmp and tmp2
            command_args.append(f"-t{t2}")
            command_args.append(f"-2{t}")
        else:
            command_args.append(f"-t{t}")
            command_args.append(f"-2{t2}")

        return command_args

    def _build_plotting_command_args(self, request: Any, ignoreCount: bool, index: int) -> List[str]:
        plotter: str = request.get("plotter", "chiapos")
        command_args: List[str] = ["chia", "plotters", plotter]

        command_args.extend(self._common_plotting_command_args(request, ignoreCount))

        if plotter == "chiapos":
            command_args.extend(self._chiapos_plotting_command_args(request, ignoreCount))
        elif plotter == "madmax":
            command_args.extend(self._madmax_plotting_command_args(request, ignoreCount, index))
        elif plotter == "bladebit":
            command_args.extend(self._bladebit_plotting_command_args(request, ignoreCount))

        return command_args

    def _is_serial_plotting_running(self, queue: str = "default") -> bool:
        response = False
        for item in self.plots_queue:
            if item["queue"] == queue and item["parallel"] is False and item["state"] is PlotState.RUNNING:
                response = True
        return response

    def _get_plots_queue_item(self, id: str):
        config = next(item for item in self.plots_queue if item["id"] == id)
        return config

    def _run_next_serial_plotting(self, loop: asyncio.AbstractEventLoop, queue: str = "default"):
        next_plot_id = None

        if self._is_serial_plotting_running(queue) is True:
            return None

        for item in self.plots_queue:
            if item["queue"] == queue and item["state"] is PlotState.SUBMITTED and item["parallel"] is False:
                next_plot_id = item["id"]
                break

        if next_plot_id is not None:
            loop.create_task(self._start_plotting(next_plot_id, loop, queue))

    def _post_process_plotting_job(self, job: Dict[str, Any]):
        id: str = job["id"]
        final_dir: str = job.get("final_dir", "")
        exclude_final_dir: bool = job.get("exclude_final_dir", False)

        log.info(f"Post-processing plotter job with ID {id}")  # lgtm [py/clear-text-logging-sensitive-data]

        if exclude_final_dir is False and len(final_dir) > 0:
            resolved_final_dir: str = str(Path(final_dir).resolve())
            config = load_config(self.root_path, "config.yaml")
            plot_directories_list: str = config["harvester"]["plot_directories"]

            if resolved_final_dir not in plot_directories_list:
                # Adds the directory to the plot directories if it is not present
                log.info(f"Adding directory {resolved_final_dir} to harvester for farming")
                add_plot_directory(self.root_path, resolved_final_dir)

    async def _start_plotting(self, id: str, loop: asyncio.AbstractEventLoop, queue: str = "default"):
        current_process = None
        try:
            log.info(f"Starting plotting with ID {id}")  # lgtm [py/clear-text-logging-sensitive-data]
            config = self._get_plots_queue_item(id)

            if config is None:
                raise Exception(f"Plot queue config with ID {id} does not exist")

            state = config["state"]
            if state is not PlotState.SUBMITTED:
                raise Exception(f"Plot with ID {id} has no state submitted")

            id = config["id"]
            delay = config["delay"]
            await asyncio.sleep(delay)

            if config["state"] is not PlotState.SUBMITTED:
                return None

            service_name = config["service_name"]
            command_args = config["command_args"]

            # Set the -D/--connect_to_daemon flag to signify that the child should connect
            # to the daemon to access the keychain
            command_args.append("-D")

            self.log.debug(f"command_args before launch_plotter are {command_args}")
            self.log.debug(f"self.root_path before launch_plotter is {self.root_path}")
            process, pid_path = launch_plotter(self.root_path, service_name, command_args, id)

            current_process = process

            config["state"] = PlotState.RUNNING
            config["out_file"] = plotter_log_path(self.root_path, id).absolute()
            config["process"] = process
            self.state_changed(service_plotter, self.prepare_plot_state_message(PlotEvent.STATE_CHANGED, id))

            if service_name not in self.services:
                self.services[service_name] = []

            self.services[service_name].append(process)

            await self._track_plotting_progress(config, loop)

            self.log.debug("finished tracking plotting progress. setting state to FINISHED")

            config["state"] = PlotState.FINISHED
            self.state_changed(service_plotter, self.prepare_plot_state_message(PlotEvent.STATE_CHANGED, id))

            self._post_process_plotting_job(config)

        except (subprocess.SubprocessError, IOError):
            log.exception(f"problem starting {service_name}")  # lgtm [py/clear-text-logging-sensitive-data]
            error = Exception("Start plotting failed")
            config["state"] = PlotState.FINISHED
            config["error"] = error
            self.state_changed(service_plotter, self.prepare_plot_state_message(PlotEvent.STATE_CHANGED, id))
            raise error

        finally:
            if current_process is not None:
                self.services[service_name].remove(current_process)
                current_process.wait()  # prevent zombies
            self._run_next_serial_plotting(loop, queue)

    async def start_plotting(self, request: Dict[str, Any]):
        service_name = request["service"]

        plotter = request.get("plotter", "chiapos")
        delay = int(request.get("delay", 0))
        parallel = request.get("parallel", False)
        size = request.get("k")
        temp_dir = request.get("t")
        final_dir = request.get("d")
        exclude_final_dir = request.get("x", False)
        count = int(request.get("n", 1))
        queue = request.get("queue", "default")

        if ("p" in request) and ("c" in request):
            response = {
                "success": False,
                "service_name": service_name,
                "error": "Choose one of pool_contract_address and pool_public_key",
            }
            return response

        ids: List[str] = []
        for k in range(count):
            id = str(uuid.uuid4())
            ids.append(id)
            config = {
                "id": id,  # lgtm [py/clear-text-logging-sensitive-data]
                "size": size,
                "queue": queue,
                "plotter": plotter,
                "service_name": service_name,
                "command_args": self._build_plotting_command_args(request, True, k),
                "parallel": parallel,
                "delay": delay * k if parallel is True else delay,
                "state": PlotState.SUBMITTED,
                "deleted": False,
                "error": None,
                "log": None,
                "process": None,
                "temp_dir": temp_dir,
                "final_dir": final_dir,
                "exclude_final_dir": exclude_final_dir,
            }

            self.plots_queue.append(config)

            # notify GUI about new plot queue item
            self.state_changed(service_plotter, self.prepare_plot_state_message(PlotEvent.STATE_CHANGED, id))

            # only the first item can start when user selected serial plotting
            can_start_serial_plotting = k == 0 and self._is_serial_plotting_running(queue) is False

            if parallel is True or can_start_serial_plotting:
                log.info(f"Plotting will start in {config['delay']} seconds")
                loop = asyncio.get_event_loop()
                loop.create_task(self._start_plotting(id, loop, queue))
            else:
                log.info("Plotting will start automatically when previous plotting finish")

        response = {
            "success": True,
            "ids": ids,
            "service_name": service_name,
        }

        return response

    async def stop_plotting(self, request: Dict[str, Any]) -> Dict[str, Any]:
        id = request["id"]
        config = self._get_plots_queue_item(id)
        if config is None:
            return {"success": False}

        id = config["id"]
        state = config["state"]
        process = config["process"]
        queue = config["queue"]

        if config["state"] is PlotState.REMOVING:
            return {"success": False}

        try:
            run_next = False
            if process is not None and state == PlotState.RUNNING:
                run_next = True
                config["state"] = PlotState.REMOVING
                self.state_changed(service_plotter, self.prepare_plot_state_message(PlotEvent.STATE_CHANGED, id))
                await kill_process(process, self.root_path, service_plotter, id)

            config["state"] = PlotState.FINISHED
            config["deleted"] = True

            self.state_changed(service_plotter, self.prepare_plot_state_message(PlotEvent.STATE_CHANGED, id))

            self.plots_queue.remove(config)

            if run_next:
                loop = asyncio.get_event_loop()
                self._run_next_serial_plotting(loop, queue)

            return {"success": True}
        except Exception as e:
            log.error(f"Error during killing the plot process: {e}")
            config["state"] = PlotState.FINISHED
            config["error"] = str(e)
            self.state_changed(service_plotter, self.prepare_plot_state_message(PlotEvent.STATE_CHANGED, id))
            return {"success": False}

    async def start_service(self, request: Dict[str, Any]):
        service_command = request["service"]

        error = None
        success = False
        testing = False
        if "testing" in request:
            testing = request["testing"]

        if not validate_service(service_command):
            error = "unknown service"

        if service_command in self.services:
            service = self.services[service_command]
            r = service is not None and service.poll() is None
            if r is False:
                self.services.pop(service_command)
                error = None
            else:
                error = f"Service {service_command} already running"

        if error is None:
            try:
                exe_command = service_command
                if testing is True:
                    exe_command = f"{service_command} --testing=true"
                process, pid_path = launch_service(self.root_path, exe_command)
                self.services[service_command] = process
                success = True
            except (subprocess.SubprocessError, IOError):
                log.exception(f"problem starting {service_command}")
                error = "start failed"

        response = {"success": success, "service": service_command, "error": error}
        return response

    async def stop_service(self, request: Dict[str, Any]) -> Dict[str, Any]:
        service_name = request["service"]
        result = await kill_service(self.root_path, self.services, service_name)
        response = {"success": result, "service_name": service_name}
        return response

    async def is_running(self, request: Dict[str, Any]) -> Dict[str, Any]:
        service_name = request["service"]

        if service_name == service_plotter:
            processes = self.services.get(service_name)
            is_running = processes is not None and len(processes) > 0
            response = {
                "success": True,
                "service_name": service_name,
                "is_running": is_running,
            }
        else:
            process = self.services.get(service_name)
            is_running = process is not None and process.poll() is None
            response = {
                "success": True,
                "service_name": service_name,
                "is_running": is_running,
            }

        return response

    async def exit(self) -> Dict[str, Any]:
        jobs = []
        for k in self.services.keys():
            jobs.append(kill_service(self.root_path, self.services, k))
        if jobs:
            await asyncio.wait(jobs)
        self.services.clear()

        # TODO: fix this hack
        asyncio.get_event_loop().call_later(5, lambda *args: sys.exit(0))
        log.info("chia daemon exiting in 5 seconds")

        response = {"success": True}
        return response

    async def register_service(self, websocket: WebSocketServerProtocol, request: Dict[str, Any]) -> Dict[str, Any]:
        self.log.info(f"Register service {request}")
        service = request["service"]
        if service not in self.connections:
            self.connections[service] = []
        self.connections[service].append(websocket)

        response: Dict[str, Any] = {"success": True}
        if service == service_plotter:
            response = {
                "success": True,
                "service": service,
                "queue": self.extract_plot_queue(),
            }
        else:
            self.remote_address_map[websocket] = service
            if self.ping_job is None:
                self.ping_job = asyncio.create_task(self.ping_task())
        self.log.info(f"registered for service {service}")
        log.info(f"{response}")
        return response


def daemon_launch_lock_path(root_path: Path) -> Path:
    """
    A path to a file that is lock when a daemon is launching but not yet started.
    This prevents multiple instances from launching.
    """
    return root_path / "run" / "start-daemon.launching"


def service_launch_lock_path(root_path: Path, service: str) -> Path:
    """
    A path to a file that is lock when a service is running.
    """
    service_name = service.replace(" ", "-").replace("/", "-")
    return root_path / "run" / f"{service_name}.lock"


def pid_path_for_service(root_path: Path, service: str, id: str = "") -> Path:
    """
    Generate a path for a PID file for the given service name.
    """
    pid_name = service.replace(" ", "-").replace("/", "-")
    return root_path / "run" / f"{pid_name}{id}.pid"


def plotter_log_path(root_path: Path, id: str):
    return root_path / "plotter" / f"plotter_log_{id}.txt"


def launch_plotter(root_path: Path, service_name: str, service_array: List[str], id: str):
    # we need to pass on the possibly altered CHIA_ROOT
    os.environ["CHIA_ROOT"] = str(root_path)
    service_executable = executable_for_service(service_array[0])

    # Swap service name with name of executable
    service_array[0] = service_executable
    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()  # type: ignore
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore

    # Windows-specific.
    # If the current process group is used, CTRL_C_EVENT will kill the parent and everyone in the group!
    try:
        creationflags: int = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore
    except AttributeError:  # Not on Windows.
        creationflags = 0

    plotter_path = plotter_log_path(root_path, id)

    if plotter_path.parent.exists():
        if plotter_path.exists():
            plotter_path.unlink()
    else:
        mkdir(plotter_path.parent)
    outfile = open(plotter_path.resolve(), "w")
    log.info(f"Service array: {service_array}")  # lgtm [py/clear-text-logging-sensitive-data]
    process = subprocess.Popen(
        service_array,
        shell=False,
        stderr=outfile,
        stdout=outfile,
        startupinfo=startupinfo,
        creationflags=creationflags,
    )

    pid_path = pid_path_for_service(root_path, service_name, id)
    try:
        mkdir(pid_path.parent)
        with open(pid_path, "w") as f:
            f.write(f"{process.pid}\n")
    except Exception:
        pass
    return process, pid_path


def launch_service(root_path: Path, service_command) -> Tuple[subprocess.Popen, Path]:
    """
    Launch a child process.
    """
    # set up CHIA_ROOT
    # invoke correct script
    # save away PID

    # we need to pass on the possibly altered CHIA_ROOT
    os.environ["CHIA_ROOT"] = str(root_path)

    log.debug(f"Launching service with CHIA_ROOT: {os.environ['CHIA_ROOT']}")

    # Insert proper e
    service_array = service_command.split()
    service_executable = executable_for_service(service_array[0])
    service_array[0] = service_executable

    if service_command == "chia_full_node_simulator":
        # Set the -D/--connect_to_daemon flag to signify that the child should connect
        # to the daemon to access the keychain
        service_array.append("-D")

    startupinfo = None
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()  # type: ignore
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore

    # CREATE_NEW_PROCESS_GROUP allows graceful shutdown on windows, by CTRL_BREAK_EVENT signal
    if sys.platform == "win32" or sys.platform == "cygwin":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        creationflags = 0
    environ_copy = os.environ.copy()
    process = subprocess.Popen(
        service_array, shell=False, startupinfo=startupinfo, creationflags=creationflags, env=environ_copy
    )
    pid_path = pid_path_for_service(root_path, service_command)
    try:
        mkdir(pid_path.parent)
        with open(pid_path, "w") as f:
            f.write(f"{process.pid}\n")
    except Exception:
        pass
    return process, pid_path


async def kill_process(
    process: subprocess.Popen, root_path: Path, service_name: str, id: str, delay_before_kill: int = 15
) -> bool:
    pid_path = pid_path_for_service(root_path, service_name, id)

    if sys.platform == "win32" or sys.platform == "cygwin":
        log.info("sending CTRL_BREAK_EVENT signal to %s", service_name)
        # pylint: disable=E1101
        kill(process.pid, signal.SIGBREAK)

    else:
        log.info("sending term signal to %s", service_name)
        process.terminate()

    count: float = 0
    while count < delay_before_kill:
        if process.poll() is not None:
            break
        await asyncio.sleep(0.5)
        count += 0.5
    else:
        process.kill()
        log.info("sending kill signal to %s", service_name)
    r = process.wait()
    log.info("process %s returned %d", service_name, r)
    try:
        pid_path_killed = pid_path.with_suffix(".pid-killed")
        if pid_path_killed.exists():
            pid_path_killed.unlink()
        os.rename(pid_path, pid_path_killed)
    except Exception:
        pass

    return True


async def kill_service(
    root_path: Path, services: Dict[str, subprocess.Popen], service_name: str, delay_before_kill: int = 15
) -> bool:
    process = services.get(service_name)
    if process is None:
        return False
    del services[service_name]

    result = await kill_process(process, root_path, service_name, "", delay_before_kill)
    return result


def is_running(services: Dict[str, subprocess.Popen], service_name: str) -> bool:
    process = services.get(service_name)
    return process is not None and process.poll() is None


def create_server_for_daemon(root_path: Path):
    routes = web.RouteTableDef()

    services: Dict = dict()

    @routes.get("/daemon/ping/")
    async def ping(request: web.Request) -> web.Response:
        return web.Response(text="pong")

    @routes.get("/daemon/service/start/")
    async def start_service(request: web.Request) -> web.Response:
        service_name = request.query.get("service")
        if service_name is None or not validate_service(service_name):
            r = f"{service_name} unknown service"
            return web.Response(text=str(r))

        if is_running(services, service_name):
            r = f"{service_name} already running"
            return web.Response(text=str(r))

        try:
            process, pid_path = launch_service(root_path, service_name)
            services[service_name] = process
            r = f"{service_name} started"
        except (subprocess.SubprocessError, IOError):
            log.exception(f"problem starting {service_name}")
            r = f"{service_name} start failed"

        return web.Response(text=str(r))

    @routes.get("/daemon/service/stop/")
    async def stop_service(request: web.Request) -> web.Response:
        service_name = request.query.get("service")
        if service_name is None:
            r = f"{service_name} unknown service"
            return web.Response(text=str(r))
        r = str(await kill_service(root_path, services, service_name))
        return web.Response(text=str(r))

    @routes.get("/daemon/service/is_running/")
    async def is_running_handler(request: web.Request) -> web.Response:
        service_name = request.query.get("service")
        if service_name is None:
            r = f"{service_name} unknown service"
            return web.Response(text=str(r))

        r = str(is_running(services, service_name))
        return web.Response(text=str(r))

    @routes.get("/daemon/exit/")
    async def exit(request: web.Request):
        jobs = []
        for k in services.keys():
            jobs.append(kill_service(root_path, services, k))
        if jobs:
            await asyncio.wait(jobs)
        services.clear()

        # we can't await `site.stop()` here because that will cause a deadlock, waiting for this
        # request to exit


def singleton(lockfile: Path, text: str = "semaphore") -> Optional[TextIO]:
    """
    Open a lockfile exclusively.
    """

    if not lockfile.parent.exists():
        mkdir(lockfile.parent)

    try:
        if has_fcntl:
            f = open(lockfile, "w")
            fcntl.lockf(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:
            if lockfile.exists():
                lockfile.unlink()
            fd = os.open(lockfile, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            f = open(fd, "w")
        f.write(text)
    except IOError:
        return None
    return f


async def async_run_daemon(root_path: Path, wait_for_unlock: bool = False) -> int:
    # When wait_for_unlock is true, we want to skip the check_keys() call in chia_init
    # since it might be necessary to wait for the GUI to unlock the keyring first.
    chia_init(root_path, should_check_keys=(not wait_for_unlock))
    config = load_config(root_path, "config.yaml")
    setproctitle("chia_daemon")
    initialize_logging("daemon", config["logging"], root_path)
    lockfile = singleton(daemon_launch_lock_path(root_path))
    crt_path = root_path / config["daemon_ssl"]["private_crt"]
    key_path = root_path / config["daemon_ssl"]["private_key"]
    ca_crt_path = root_path / config["private_ssl_ca"]["crt"]
    ca_key_path = root_path / config["private_ssl_ca"]["key"]
    sys.stdout.flush()
    json_msg = dict_to_json_str(
        {
            "message": "cert_path",
            "success": True,
            "cert": f"{crt_path}",
            "key": f"{key_path}",
            "ca_crt": f"{ca_crt_path}",
        }
    )
    sys.stdout.write("\n" + json_msg + "\n")
    sys.stdout.flush()
    if lockfile is None:
        print("daemon: already launching")
        return 2

    # TODO: clean this up, ensuring lockfile isn't removed until the listen port is open
    create_server_for_daemon(root_path)
    ws_server = WebSocketServer(
        root_path, ca_crt_path, ca_key_path, crt_path, key_path, run_check_keys_on_unlock=wait_for_unlock
    )
    await ws_server.start()
    assert ws_server.websocket_server is not None
    await ws_server.websocket_server.wait_closed()
    log.info("Daemon WebSocketServer closed")
    # sys.stdout.close()
    return 0


def run_daemon(root_path: Path, wait_for_unlock: bool = False) -> int:
    result = asyncio.get_event_loop().run_until_complete(async_run_daemon(root_path, wait_for_unlock))
    return result


def main(argv) -> int:
    from chia.util.default_root import DEFAULT_ROOT_PATH
    from chia.util.keychain import Keychain

    wait_for_unlock = "--wait-for-unlock" in argv and Keychain.is_keyring_locked()
    return run_daemon(DEFAULT_ROOT_PATH, wait_for_unlock)


if __name__ == "__main__":
    main(sys.argv[1:])
