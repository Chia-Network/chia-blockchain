import logging
import time
from typing import Any, Dict, List, Optional, Set

from blspy import AugSchemeMPL

from chia.types.blockchain_format.coin import Coin
from chia.wallet.db_wallet.db_wallet_puzzles import create_offer_fullpuz
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint32, uint64
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo


class DLOInfo:
    leaf_reveal: bytes
    host_genesis_id: bytes32
    claim_target: bytes32
    recovery_target: bytes32
    recovery_timelock: uint64


class DLOWallet:
    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    coin_record: WalletCoinRecord
    sp_info: DLOInfo
    standard_wallet: Wallet
    base_puzzle_program: Optional[bytes]
    base_inner_puzzle_hash: Optional[bytes32]
    cost_of_single_tx: Optional[int]

    @staticmethod
    async def create_new_sp(
        wallet_state_manager: Any,
        wallet: Wallet,
        amount: uint64,
        type_specific_parameters: List = [],
    ):
        self = DLOWallet()
        self.cost_of_single_tx = None
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(__name__)
        std_wallet_id = self.standard_wallet.wallet_id
        bal = await wallet_state_manager.get_confirmed_balance_for_wallet(std_wallet_id, None)
        if amount > bal:
            raise ValueError("Not enough balance")
        self.wallet_state_manager = wallet_state_manager

        self.dlo_info = DLOInfo(type, None, type_specific_parameters)
        info_as_string = bytes(self.dlo_info).hex()
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "DLO Wallet", WalletType.DATA_LAYER_OFFER, info_as_string
        )
        if self.wallet_info is None:
            raise ValueError("Internal Error")

    def puzzle_for_pk(self, pubkey: bytes) -> Program:
        return create_offer_fullpuz(
            self.dlo_info.leaf_reveal,
            self.dlo_info.host_genesis_id,
            self.dlo_info.claim_target,
            self.dlo_info.recovery_target,
            self.dlo_info.recovery_timelock,
        )

    async def generate_datalayer_offer_spend(
        self: Wallet,
        amount: uint64,
        leaf_reveal: bytes,
        host_genesis_id: bytes32,
        claim_target: bytes32,
        recovery_target: bytes32,
        recovery_timelock: uint64,
    ):
        dlo_info = DLOInfo(
            leaf_reveal,
            host_genesis_id,
            claim_target,
            recovery_target,
            recovery_timelock,
        )
        await self.save_info(dlo_info, True)

        full_puzzle: Program = create_offer_fullpuz(
            leaf_reveal,
            host_genesis_id,
            claim_target,
            recovery_target,
            recovery_timelock,
        )
        tr: TransactionRecord = await self.standard_wallet.generate_signed_transaction(full_puzzle, amount)
        await self.wallet_state_manager.interested_store.add_interested_puzzle_hash(
            full_puzzle.get_tree_hash(), self.wallet_id, True
        )
        self.standard_wallet.push_transaction(tr)
        return tr

    async def create_recover_dl_offer_spend(
        self,
        leaf_reveal: bytes,
        host_genesis_id: bytes32,
        claim_target: bytes32,
        recovery_target: bytes32,
        recovery_timelock: uint64,
        fee=uint64(0)
    ):
        coins = await self.select_coin(1)
        coin = coins.pop()
        solution = Program.to([0, coin.amount])

        full_puzzle: Program = create_offer_fullpuz(
            leaf_reveal,
            host_genesis_id,
            claim_target,
            recovery_target,
            recovery_timelock
        )
        coin_spend = CoinSpend(coin, full_puzzle, solution)
        sb = SpendBundle([coin_spend], AugSchemeMPL.aggregated([]))
        tr = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=recovery_target,
            amount=uint64(coin.amount),
            fee_amount=uint64(fee),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=sb,
            additions=list(sb.additions()),
            removals=list(sb.removals()),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=sb.name(),
        )
        self.standard_wallet.push_transaction(tr)
        return tr

    async def get_confirmed_balance(self, record_list=None) -> uint64:
        if record_list is None:
            record_list = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(self.id())

        amount: uint64 = uint64(0)
        for record in record_list:
            parent = await self.get_parent_for_coin(record.coin)
            if parent is not None:
                amount = uint64(amount + record.coin.amount)

        self.log.info(f"Confirmed balance for dlo wallet is {amount}")
        return uint64(amount)

    async def get_unconfirmed_balance(self, record_list=None) -> uint64:
        confirmed = await self.get_confirmed_balance(record_list)
        return await self.wallet_state_manager._get_unconfirmed_balance(self.id(), confirmed)

    async def get_spendable_balance(self, unspent_records=None) -> uint64:
        spendable_am = await self.wallet_state_manager.get_confirmed_spendable_balance_for_wallet(
            self.wallet_info.id, unspent_records
        )
        return spendable_am

    async def select_coins(self, amount: uint64, exclude: List[Coin] = []) -> Optional[Set[Coin]]:
        """Returns a set of coins that can be used for generating a new transaction."""
        if exclude is None:
            exclude = []

        spendable_amount = await self.get_spendable_balance()
        if amount > spendable_amount:
            self.log.warning(f"Can't select {amount}, from spendable {spendable_amount} for wallet id {self.id()}")
            return None

        self.log.info(f"About to select coins for amount {amount}")
        unspent: List[WalletCoinRecord] = list(
            await self.wallet_state_manager.get_spendable_coins_for_wallet(self.wallet_info.id)
        )
        sum_value = 0
        used_coins: Set[Coin] = set()

        # Use older coins first
        unspent.sort(key=lambda r: r.confirmed_block_height)

        # Try to use coins from the store, if there isn't enough of "unused"
        # coins use change coins that are not confirmed yet
        unconfirmed_removals: Dict[bytes32, Coin] = await self.wallet_state_manager.unconfirmed_removals_for_wallet(
            self.wallet_info.id
        )
        for coinrecord in unspent:
            if sum_value >= amount and len(used_coins) > 0:
                break
            if coinrecord.coin.name() in unconfirmed_removals:
                continue
            if coinrecord.coin in exclude:
                continue
            sum_value += coinrecord.coin.amount
            used_coins.add(coinrecord.coin)

        # This happens when we couldn't use one of the coins because it's already used
        # but unconfirmed, and we are waiting for the change. (unconfirmed_additions)
        if sum_value < amount:
            raise ValueError(
                "Can't make this transaction at the moment. Waiting for the change from the previous transaction."
            )

        self.log.info(f"Successfully selected coins: {used_coins}")
        return used_coins

    async def save_info(self, dlo_info: DLOInfo, in_transaction: bool) -> None:
        self.dlo_info = dlo_info
        current_info = self.wallet_info
        info_as_string = bytes(self.dlo_info).hex()
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, info_as_string)
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info, in_transaction)
        return
