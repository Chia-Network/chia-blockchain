from dataclasses import dataclass
import logging
from typing import Dict, Set

from chia.util.ints import uint32
from chia.util.prometheus_server import PrometheusServer, Gauge
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord

# Default port for the full_node prometheus exporter
DEFAULT_PROMETHEUS_PORT = 9917


@dataclass
class PrometheusWallet:
    server: PrometheusServer

    _confirmed_balance: Gauge
    _pending_balance: Gauge
    _spendable_balance: Gauge
    _max_send_amount: Gauge

    @classmethod
    def create(cls, config: Dict, log: logging.Logger):
        enabled = config.get("start_prometheus_server", False)
        if not enabled:
            return None

        port = config.get("prometheus_exporter_port", DEFAULT_PROMETHEUS_PORT)
        prometheus_server = PrometheusServer.create("wallet", enabled, port, log)

        return cls(
            server=prometheus_server,
            _confirmed_balance=prometheus_server.new_gauge(
                "confirmed_balance", "confirmed wallet balance", ("fingerprint", "wallet_id")
            ),
            _pending_balance=prometheus_server.new_gauge(
                "pending_balance", "pending wallet balance", ("fingerprint", "wallet_id")
            ),
            _spendable_balance=prometheus_server.new_gauge(
                "spendable_balance", "spendable wallet balance", ("fingerprint", "wallet_id")
            ),
            _max_send_amount=prometheus_server.new_gauge(
                "max_send_amount",
                "maximum amount that can be sent in one transaction from this wallet",
                ("fingerprint", "wallet_id"),
            ),
        )

    async def update_wallet_balance(self, wallet_id: uint32, wallet: Wallet, unspent_records: Set[WalletCoinRecord]):
        fingerprint = wallet.wallet_state_manager.private_key.get_g1().get_fingerprint()

        self._confirmed_balance.labels(fingerprint, wallet_id).set(await wallet.get_confirmed_balance(unspent_records))
        self._pending_balance.labels(fingerprint, wallet_id).set(await wallet.get_unconfirmed_balance(unspent_records))
        self._spendable_balance.labels(fingerprint, wallet_id).set(await wallet.get_spendable_balance(unspent_records))
        self._max_send_amount.labels(fingerprint, wallet_id).set(await wallet.get_max_send_amount(unspent_records))
