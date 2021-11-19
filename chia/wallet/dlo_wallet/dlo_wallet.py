import logging
import time
from typing import Any, Dict, List, Optional, Set, Tuple

from blspy import AugSchemeMPL
from dataclasses import dataclass
from chia.util.streamable import Streamable, streamable
from chia.types.blockchain_format.coin import Coin
from chia.wallet.db_wallet.db_wallet_puzzles import create_offer_fullpuz, uncurry_offer_puzzle
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint64
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo


@dataclass(frozen=True)
@streamable
class DLOInfo(Streamable):
    leaf_reveal: Optional[bytes]
    host_genesis_id: Optional[bytes32]
    claim_target: Optional[bytes32]
    recovery_target: Optional[bytes32]
    recovery_timelock: Optional[uint64]
    active_offer: Optional[Coin]


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

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.DATA_LAYER_OFFER)

    @staticmethod
    async def create_new_dlo_wallet(
        wallet_state_manager: Any,
        wallet: Wallet,
    ):
        self = DLOWallet()
        self.cost_of_single_tx = None
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(__name__)
        self.wallet_state_manager = wallet_state_manager
        self.dlo_info = DLOInfo(None, None, None, None, None, None)
        info_as_string = bytes(self.dlo_info).hex()
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            "DLO Wallet", WalletType.DATA_LAYER_OFFER.value, info_as_string
        )
        self.wallet_id = self.wallet_info.id
        if self.wallet_info is None:
            raise ValueError("Internal Error")
        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)
        return self

    def puzzle_for_pk(self, pubkey: bytes) -> Program:
        if self.dlo_info.leaf_reveal is not None:
            return create_offer_fullpuz(
                self.dlo_info.leaf_reveal,
                self.dlo_info.host_genesis_id,
                self.dlo_info.claim_target,
                self.dlo_info.recovery_target,
                self.dlo_info.recovery_timelock,
            )
        return Program.to(pubkey)

    def id(self):
        return self.wallet_info.id

    async def generate_datalayer_offer_spend(
        self: Wallet,
        amount: uint64,
        leaf_reveal: bytes,
        host_genesis_id: bytes32,
        claim_target: bytes32,
        recovery_target: bytes32,
        recovery_timelock: uint64,
    ):
        full_puzzle: Program = create_offer_fullpuz(
            leaf_reveal,
            host_genesis_id,
            claim_target,
            recovery_target,
            recovery_timelock,
        )
        tr: TransactionRecord = await self.standard_wallet.generate_signed_transaction(
            amount, full_puzzle.get_tree_hash()
        )
        await self.wallet_state_manager.interested_store.add_interested_puzzle_hash(
            full_puzzle.get_tree_hash(), self.wallet_id, True
        )

        active_coin = None
        for coin in tr.spend_bundle.additions():
            if coin.puzzle_hash == full_puzzle.get_tree_hash():
                active_coin = coin
        if active_coin is None:
            raise ValueError("Unable to find created coin")

        await self.standard_wallet.push_transaction(tr)
        dlo_info = DLOInfo(
            leaf_reveal,
            host_genesis_id,
            claim_target,
            recovery_target,
            recovery_timelock,
            active_coin,
        )
        await self.save_info(dlo_info, True)
        return tr

    async def claim_dl_offer(
        self,
        offer_coin: Coin,
        offer_full_puzzle: Program,
        db_innerpuz_hash: bytes32,
        current_root: bytes32,
        inclusion_proof: Tuple,
        fee: uint64 = uint64(0),
    ):
        solution = Program.to([1, offer_coin.amount, db_innerpuz_hash, current_root, inclusion_proof])
        sb = SpendBundle([CoinSpend(offer_coin, offer_full_puzzle, solution)], AugSchemeMPL.aggregate([]))
        # ret = uncurry_offer_puzzle(offer_full_puzzle)
        # singleton_struct, leaf_reveal, claim_target, recovery_target, recovery_timelock = ret
        # tr = TransactionRecord(
        #     confirmed_at_height=uint32(0),
        #     created_at_time=uint64(int(time.time())),
        #     to_puzzle_hash=claim_target,
        #     amount=uint64(offer_coin.amount),
        #     fee_amount=uint64(fee),
        #     confirmed=False,
        #     sent=uint32(0),
        #     spend_bundle=sb,
        #     additions=list(sb.additions()),
        #     removals=list(sb.removals()),
        #     wallet_id=self.id(),
        #     sent_to=[],
        #     trade_id=None,
        #     type=uint32(TransactionType.OUTGOING_TX.value),
        #     name=sb.name(),
        # )
        # self.standard_wallet.push_transaction(tr)
        return sb

    async def create_recover_dl_offer_spend(
        self,
        leaf_reveal: bytes = None,
        host_genesis_id: bytes32 = None,
        claim_target: bytes32 = None,
        recovery_target: bytes32 = None,
        recovery_timelock: uint64 = None,
        fee=uint64(0),
    ):

        coin = self.dlo_info.active_offer
        solution = Program.to([0, coin.amount])

        if leaf_reveal is None:
            leaf_reveal = self.dlo_info.leaf_reveal
            host_genesis_id = self.dlo_info.host_genesis_id
            claim_target = self.dlo_info.claim_target
            recovery_target = self.dlo_info.recovery_target
            recovery_timelock = self.dlo_info.recovery_timelock
        full_puzzle: Program = create_offer_fullpuz(
            leaf_reveal, host_genesis_id, claim_target, recovery_target, recovery_timelock
        )
        coin_spend = CoinSpend(coin, full_puzzle, solution)
        sb = SpendBundle([coin_spend], AugSchemeMPL.aggregate([]))
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
        await self.standard_wallet.push_transaction(tr)
        return tr

    async def get_coin(self) -> Coin:
        coins = await self.select_coins(1)
        if coins is None or coins == set():
            coin = self.dlo_info.active_offer
        else:
            coin = coins.pop()
        return coin

    async def get_confirmed_balance(self, record_list=None) -> uint64:
        if record_list is None:
            record_list = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(self.id())

        amount: uint64 = uint64(0)
        for record in record_list:
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
        await self.wallet_state_manager.update_wallet_puzzle_hashes(self.wallet_info.id)
        return
