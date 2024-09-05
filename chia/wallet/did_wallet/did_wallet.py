from __future__ import annotations

import dataclasses
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Set, Tuple, cast

from chia_rs import AugSchemeMPL, G1Element, G2Element

from chia.protocols.wallet_protocol import CoinState
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, make_spend
from chia.types.signing_mode import CHIP_0002_SIGN_MESSAGE_PREFIX, SigningMode
from chia.util.ints import uint16, uint32, uint64, uint128
from chia.wallet.conditions import (
    AssertCoinAnnouncement,
    Condition,
    ConditionValidTimes,
    CreateCoinAnnouncement,
    parse_timelock_info,
)
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.did_wallet import did_wallet_puzzles
from chia.wallet.did_wallet.did_info import DIDCoinData, DIDInfo
from chia.wallet.did_wallet.did_wallet_puzzles import match_did_puzzle, uncurry_innerpuz
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.payment import Payment
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
    puzzle_hash_for_pk,
)
from chia.wallet.singleton import (
    SINGLETON_LAUNCHER_PUZZLE,
    create_singleton_puzzle,
    create_singleton_puzzle_hash,
    get_inner_puzzle_from_singleton,
)
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.curry_and_treehash import NIL_TREEHASH, shatree_int, shatree_pair
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_sync_utils import fetch_coin_spend, fetch_coin_spend_for_coin_state
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_protocol import WalletProtocol
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


class DIDWallet:
    if TYPE_CHECKING:
        if TYPE_CHECKING:
            _protocol_check: ClassVar[WalletProtocol[DIDCoinData]] = cast("DIDWallet", None)

    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    did_info: DIDInfo
    standard_wallet: Wallet
    base_puzzle_program: Optional[bytes]
    base_inner_puzzle_hash: Optional[bytes32]
    wallet_id: int

    @staticmethod
    async def create_new_did_wallet(
        wallet_state_manager: Any,
        wallet: Wallet,
        amount: uint64,
        action_scope: WalletActionScope,
        backups_ids: List[bytes32] = [],
        num_of_backup_ids_needed: uint64 = None,
        metadata: Dict[str, str] = {},
        name: Optional[str] = None,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ):
        """
        Create a brand new DID wallet
        This must be called under the wallet state manager lock
        :param wallet_state_manager: Wallet state manager
        :param wallet: Standard wallet
        :param amount: Amount of the DID coin
        :param backups_ids: A list of DIDs used for recovery this DID
        :param num_of_backup_ids_needed: Needs how many recovery DIDs at least
        :param metadata: Metadata saved in the DID
        :param name: Wallet name
        :param fee: transaction fee
        :return: DID wallet
        """

        self = DIDWallet()
        self.wallet_state_manager = wallet_state_manager
        if name is None:
            name = self.generate_wallet_name()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)
        std_wallet_id = self.standard_wallet.wallet_id
        bal = await wallet_state_manager.get_confirmed_balance_for_wallet(std_wallet_id)
        if amount > bal:
            raise ValueError("Not enough balance")
        if amount & 1 == 0:
            raise ValueError("DID amount must be odd number")

        if num_of_backup_ids_needed is None:
            num_of_backup_ids_needed = uint64(len(backups_ids))
        if num_of_backup_ids_needed > len(backups_ids):
            raise ValueError("Cannot require more IDs than are known.")
        self.did_info = DIDInfo(
            origin_coin=None,
            backup_ids=backups_ids,
            num_of_backup_ids_needed=num_of_backup_ids_needed,
            parent_info=[],
            current_inner=None,
            temp_coin=None,
            temp_puzhash=None,
            temp_pubkey=None,
            sent_recovery_transaction=False,
            metadata=json.dumps(metadata),
        )
        info_as_string = json.dumps(self.did_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name=name, wallet_type=WalletType.DECENTRALIZED_ID.value, data=info_as_string
        )
        self.wallet_id = self.wallet_info.id
        std_wallet_id = self.standard_wallet.wallet_id
        bal = await wallet_state_manager.get_confirmed_balance_for_wallet(std_wallet_id)
        if amount > bal:
            raise ValueError("Not enough balance")

        try:
            await self.generate_new_decentralised_id(amount, action_scope, fee, extra_conditions)
        except Exception:
            await wallet_state_manager.user_store.delete_wallet(self.id())
            raise

        await self.wallet_state_manager.add_new_wallet(self)

        return self

    @staticmethod
    async def create_new_did_wallet_from_recovery(
        wallet_state_manager: Any,
        wallet: Wallet,
        backup_data: str,
        name: Optional[str] = None,
    ):
        """
        Create a DID wallet from a backup file
        :param wallet_state_manager: Wallet state manager
        :param wallet: Standard wallet
        :param backup_data: A serialized backup data
        :param name: Wallet name
        :return: DID wallet
        """
        self = DIDWallet()
        self.wallet_state_manager = wallet_state_manager
        if name is None:
            name = self.generate_wallet_name()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)
        self.log.info("Creating DID wallet from recovery file ...")
        # load backup will also set our DIDInfo
        self.did_info = DIDWallet.deserialize_backup_data(backup_data)
        self.check_existed_did()
        info_as_string = json.dumps(self.did_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name=name, wallet_type=WalletType.DECENTRALIZED_ID.value, data=info_as_string
        )
        await self.wallet_state_manager.add_new_wallet(self)
        await self.save_info(self.did_info)
        await self.wallet_state_manager.update_wallet_puzzle_hashes(self.wallet_info.id)
        await self.load_parent(self.did_info)
        if self.wallet_info is None:
            raise ValueError("Internal Error")
        self.wallet_id = self.wallet_info.id
        return self

    @staticmethod
    async def create_new_did_wallet_from_coin_spend(
        wallet_state_manager: Any,
        wallet: Wallet,
        launch_coin: Coin,
        inner_puzzle: Program,
        coin_spend: CoinSpend,
        name: Optional[str] = None,
    ):
        """
        Create a DID wallet from a transfer
        :param wallet_state_manager: Wallet state manager
        :param wallet: Main wallet
        :param launch_coin: The launch coin of the DID
        :param inner_puzzle: DID inner puzzle
        :param coin_spend: DID transfer spend
        :param name: Wallet name
        :return: DID wallet
        """

        self = DIDWallet()
        self.wallet_state_manager = wallet_state_manager
        if name is None:
            name = self.generate_wallet_name()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)

        self.log.info(f"Creating DID wallet from a coin spend {launch_coin}  ...")
        # Create did info from the coin spend
        args = did_wallet_puzzles.uncurry_innerpuz(inner_puzzle)
        if args is None:
            raise ValueError("Cannot uncurry the DID puzzle.")
        _, recovery_list_hash, num_verification, _, metadata = args
        full_solution: Program = Program.from_bytes(bytes(coin_spend.solution))
        inner_solution: Program = full_solution.rest().rest().first()
        recovery_list: List[bytes32] = []
        backup_required: int = num_verification.as_int()
        if recovery_list_hash != NIL_TREEHASH:
            try:
                for did in inner_solution.rest().rest().rest().rest().rest().as_python():
                    recovery_list.append(bytes32(did[0]))
            except Exception:
                self.log.warning(
                    f"DID {launch_coin.name().hex()} has a recovery list hash but missing a reveal,"
                    " you may need to reset the recovery info."
                )
        self.did_info = DIDInfo(
            origin_coin=launch_coin,
            backup_ids=recovery_list,
            num_of_backup_ids_needed=uint64(backup_required),
            parent_info=[],
            current_inner=inner_puzzle,
            temp_coin=None,
            temp_puzhash=None,
            temp_pubkey=None,
            sent_recovery_transaction=False,
            metadata=json.dumps(did_wallet_puzzles.did_program_to_metadata(metadata)),
        )
        self.check_existed_did()
        info_as_string = json.dumps(self.did_info.to_json_dict())

        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name=name, wallet_type=WalletType.DECENTRALIZED_ID.value, data=info_as_string
        )
        await self.wallet_state_manager.add_new_wallet(self)
        await self.wallet_state_manager.update_wallet_puzzle_hashes(self.wallet_info.id)
        await self.load_parent(self.did_info)
        self.log.info(f"New DID wallet created {info_as_string}.")
        if self.wallet_info is None:
            raise ValueError("Internal Error")
        self.wallet_id = self.wallet_info.id
        return self

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: str = None,
    ):
        """
        Create a DID wallet based on the local database
        :param wallet_state_manager: Wallet state manager
        :param wallet: Standard wallet
        :param wallet_info: Serialized WalletInfo
        :param name: Wallet name
        :return:
        """
        self = DIDWallet()
        self.log = logging.getLogger(name if name else __name__)
        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = wallet_info
        self.wallet_id = wallet_info.id
        self.standard_wallet = wallet
        self.wallet_info = wallet_info
        self.did_info = DIDInfo.from_json_dict(json.loads(wallet_info.data))
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        return self

    @classmethod
    def type(cls) -> WalletType:
        return WalletType.DECENTRALIZED_ID

    def id(self) -> uint32:
        return self.wallet_info.id

    async def get_confirmed_balance(self, record_list=None) -> uint128:
        if record_list is None:
            record_list = await self.wallet_state_manager.coin_store.get_unspent_coins_for_wallet(self.id())

        amount: uint128 = uint128(0)
        for record in record_list:
            parent = self.get_parent_for_coin(record.coin)
            if parent is not None:
                amount = uint128(amount + record.coin.amount)

        self.log.info(f"Confirmed balance for did wallet is {amount}")
        return uint128(amount)

    async def get_pending_change_balance(self) -> uint64:
        unconfirmed_tx = await self.wallet_state_manager.tx_store.get_unconfirmed_for_wallet(self.id())
        addition_amount = 0

        for record in unconfirmed_tx:
            our_spend = False
            for coin in record.removals:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(coin, self.id()):
                    our_spend = True
                    break

            if our_spend is not True:
                continue

            for coin in record.additions:
                if await self.wallet_state_manager.does_coin_belong_to_wallet(coin, self.id()):
                    addition_amount += coin.amount

        return uint64(addition_amount)

    async def get_unconfirmed_balance(self, record_list=None) -> uint128:
        return await self.wallet_state_manager.get_unconfirmed_balance(self.id(), record_list)

    async def select_coins(
        self,
        amount: uint64,
        action_scope: WalletActionScope,
    ) -> Set[Coin]:
        try:
            async with action_scope.use() as interface:
                coin = await self.get_coin()
                interface.side_effects.selected_coins.append(coin)
            return {coin}
        except RuntimeError:
            return set()

    def _coin_is_first_singleton(self, coin: Coin) -> bool:
        parent = self.get_parent_for_coin(coin)
        if parent is None:
            return False
        assert self.did_info.origin_coin
        return parent.parent_name == self.did_info.origin_coin.name()

    # This will be used in the recovery case where we don't have the parent info already
    # But it is also called whenever a Singleton coin from this wallet is spent
    # We can improve this interface by passing in the CoinSpend, as well
    # We need to change DID Wallet coin_added to expect p2 spends as well as recovery spends,
    # or only call it in the recovery spend case
    async def coin_added(self, coin: Coin, _: uint32, peer: WSChiaConnection, parent_coin_data: Optional[DIDCoinData]):
        """Notification from wallet state manager that wallet has been received."""
        parent = self.get_parent_for_coin(coin)
        if parent_coin_data is not None:
            assert isinstance(parent_coin_data, DIDCoinData)
            did_data: DIDCoinData = parent_coin_data
        else:
            parent_state: CoinState = (
                await self.wallet_state_manager.wallet_node.get_coin_state(
                    coin_names=[coin.parent_coin_info], peer=peer
                )
            )[0]
            coin_spend = await fetch_coin_spend_for_coin_state(parent_state, peer)
            uncurried = uncurry_puzzle(coin_spend.puzzle_reveal)
            did_curried_args = match_did_puzzle(uncurried.mod, uncurried.args)
            assert did_curried_args is not None
            p2_puzzle, recovery_list_hash, num_verification, singleton_struct, metadata = did_curried_args
            did_data = DIDCoinData(
                p2_puzzle=p2_puzzle,
                recovery_list_hash=bytes32(recovery_list_hash.as_atom()),
                num_verification=uint16(num_verification.as_int()),
                singleton_struct=singleton_struct,
                metadata=metadata,
                inner_puzzle=get_inner_puzzle_from_singleton(coin_spend.puzzle_reveal),
                coin_state=parent_state,
            )
        if parent is None:
            # this is the first time we received it, check it's a DID coin
            parent_innerpuz = did_data.inner_puzzle
            if parent_innerpuz:
                parent_info = LineageProof(
                    parent_name=did_data.coin_state.coin.parent_coin_info,
                    inner_puzzle_hash=parent_innerpuz.get_tree_hash(),
                    amount=uint64(did_data.coin_state.coin.amount),
                )
                await self.add_parent(coin.parent_coin_info, parent_info)
            else:
                self.log.warning("Parent coin is not a DID, skipping: %s -> %s", coin.name(), coin)
                return
        self.log.info(f"DID wallet has been notified that coin was added: {coin.name()}:{coin}")
        inner_puzzle = await self.inner_puzzle_for_did_puzzle(coin.puzzle_hash)
        # Check inner puzzle consistency
        assert self.did_info.origin_coin is not None

        # TODO: if not the first singleton, and solution mode == recovery
        if not self._coin_is_first_singleton(coin):
            full_puzzle = create_singleton_puzzle(inner_puzzle, self.did_info.origin_coin.name())
            assert full_puzzle.get_tree_hash() == coin.puzzle_hash
        if self.did_info.temp_coin is not None:
            self.wallet_state_manager.state_changed("did_coin_added", self.wallet_info.id)
        new_info = DIDInfo(
            origin_coin=self.did_info.origin_coin,
            backup_ids=self.did_info.backup_ids,
            num_of_backup_ids_needed=self.did_info.num_of_backup_ids_needed,
            parent_info=self.did_info.parent_info,
            current_inner=inner_puzzle,
            temp_coin=None,
            temp_puzhash=None,
            temp_pubkey=None,
            sent_recovery_transaction=False,
            metadata=json.dumps(did_wallet_puzzles.did_program_to_metadata(did_data.metadata)),
        )
        await self.save_info(new_info)

        future_parent = LineageProof(
            parent_name=coin.parent_coin_info,
            inner_puzzle_hash=inner_puzzle.get_tree_hash(),
            amount=uint64(coin.amount),
        )

        await self.add_parent(coin.name(), future_parent)
        await self.wallet_state_manager.add_interested_coin_ids([coin.name()])

    def create_backup(self) -> str:
        """
        Create a serialized backup data for DIDInfo
        :return: Serialized backup data
        """
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        output_str = f"{self.did_info.origin_coin.parent_coin_info.hex()}:"
        output_str += f"{self.did_info.origin_coin.puzzle_hash.hex()}:"
        output_str += f"{self.did_info.origin_coin.amount}:"
        if len(self.did_info.backup_ids) > 0:
            for did in self.did_info.backup_ids:
                output_str = output_str + did.hex() + ","
            output_str = output_str[:-1]
        output_str += f":{bytes(self.did_info.current_inner).hex()}:{self.did_info.num_of_backup_ids_needed}"
        output_str += f":{self.did_info.metadata}"
        return output_str

    async def load_parent(self, did_info: DIDInfo):
        """
        Load the parent info when importing a DID
        :param did_info: DID info
        :return:
        """
        # full_puz = did_wallet_puzzles.create_fullpuz(innerpuz, origin.name())
        # All additions in this block here:

        new_puzhash = await self.wallet_state_manager.main_wallet.get_puzzle_hash(new=False)
        new_pubkey = await self.wallet_state_manager.get_public_key(new_puzhash)
        parent_info = None
        assert did_info.origin_coin is not None
        assert did_info.current_inner is not None
        new_did_inner_puzhash = did_wallet_puzzles.get_inner_puzhash_by_p2(
            p2_puzhash=new_puzhash,
            recovery_list=did_info.backup_ids,
            num_of_backup_ids_needed=did_info.num_of_backup_ids_needed,
            launcher_id=did_info.origin_coin.name(),
            metadata=did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
        )
        wallet_node = self.wallet_state_manager.wallet_node
        parent_coin: Coin = did_info.origin_coin
        while True:
            peer = wallet_node.get_full_node_peer()
            children = await wallet_node.fetch_children(parent_coin.name(), peer)
            if len(children) == 0:
                break

            children_state: CoinState = children[0]
            child_coin = children_state.coin
            future_parent = LineageProof(
                parent_name=child_coin.parent_coin_info,
                inner_puzzle_hash=did_info.current_inner.get_tree_hash(),
                amount=uint64(child_coin.amount),
            )
            await self.add_parent(child_coin.name(), future_parent)
            if children_state.spent_height != children_state.created_height:
                did_info = DIDInfo(
                    origin_coin=did_info.origin_coin,
                    backup_ids=did_info.backup_ids,
                    num_of_backup_ids_needed=did_info.num_of_backup_ids_needed,
                    parent_info=self.did_info.parent_info,
                    current_inner=did_info.current_inner,
                    temp_coin=child_coin,
                    temp_puzhash=new_did_inner_puzhash,
                    temp_pubkey=bytes(new_pubkey),
                    sent_recovery_transaction=did_info.sent_recovery_transaction,
                    metadata=did_info.metadata,
                )

                await self.save_info(did_info)
                assert children_state.created_height
                parent_spend = await fetch_coin_spend(uint32(children_state.created_height), parent_coin, peer)
                assert parent_spend is not None
                parent_innerpuz = get_inner_puzzle_from_singleton(parent_spend.puzzle_reveal)
                assert parent_innerpuz is not None
                parent_info = LineageProof(
                    parent_name=parent_coin.parent_coin_info,
                    inner_puzzle_hash=parent_innerpuz.get_tree_hash(),
                    amount=uint64(parent_coin.amount),
                )
                await self.add_parent(child_coin.parent_coin_info, parent_info)
            parent_coin = child_coin
        assert parent_info is not None

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:
        if self.did_info.origin_coin is not None:
            innerpuz = did_wallet_puzzles.create_innerpuz(
                p2_puzzle_or_hash=puzzle_for_pk(pubkey),
                recovery_list=self.did_info.backup_ids,
                num_of_backup_ids_needed=self.did_info.num_of_backup_ids_needed,
                launcher_id=self.did_info.origin_coin.name(),
                metadata=did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
            )
            return create_singleton_puzzle(innerpuz, self.did_info.origin_coin.name())
        else:
            innerpuz = Program.to((8, 0))
            return create_singleton_puzzle(innerpuz, bytes32([0] * 32))

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        if self.did_info.origin_coin is None:
            # TODO: this seem dumb. Why bother with this case? Is it ever used?
            # inner puzzle: (8 . 0)
            innerpuz_hash = shatree_pair(shatree_int(8), NIL_TREEHASH)
            return create_singleton_puzzle_hash(innerpuz_hash, bytes32([0] * 32))
        origin_coin_name = self.did_info.origin_coin.name()
        innerpuz_hash = did_wallet_puzzles.get_inner_puzhash_by_p2(
            p2_puzhash=puzzle_hash_for_pk(pubkey),
            recovery_list=self.did_info.backup_ids,
            num_of_backup_ids_needed=self.did_info.num_of_backup_ids_needed,
            launcher_id=origin_coin_name,
            metadata=did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
        )
        return create_singleton_puzzle_hash(innerpuz_hash, origin_coin_name)

    async def get_new_puzzle(self) -> Program:
        return self.puzzle_for_pk(
            (await self.wallet_state_manager.get_unused_derivation_record(self.wallet_info.id)).pubkey
        )

    def get_my_DID(self) -> str:
        assert self.did_info.origin_coin is not None
        core = self.did_info.origin_coin.name()
        assert core is not None
        return core.hex()

    async def set_name(self, new_name: str):
        new_info = dataclasses.replace(self.wallet_info, name=new_name)
        self.wallet_info = new_info
        await self.wallet_state_manager.user_store.update_wallet(self.wallet_info)

    def get_name(self):
        return self.wallet_info.name

    async def create_update_spend(
        self,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        coin = await self.get_coin()
        new_inner_puzzle = await self.get_new_did_innerpuz()
        uncurried = did_wallet_puzzles.uncurry_innerpuz(new_inner_puzzle)
        assert uncurried is not None
        p2_puzzle = uncurried[0]
        # innerpuz solution is (mode, p2_solution)
        p2_solution = self.standard_wallet.make_solution(
            primaries=[
                Payment(
                    puzzle_hash=new_inner_puzzle.get_tree_hash(),
                    amount=uint64(coin.amount),
                    memos=[p2_puzzle.get_tree_hash()],
                )
            ],
            conditions=(*extra_conditions, CreateCoinAnnouncement(coin.name())),
        )
        innersol: Program = Program.to([1, p2_solution])
        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        innerpuz: Program = self.did_info.current_inner

        full_puzzle: Program = create_singleton_puzzle(
            innerpuz,
            self.did_info.origin_coin.name(),
        )
        parent_info = self.get_parent_for_coin(coin)
        assert parent_info is not None
        fullsol = Program.to(
            [
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                coin.amount,
                innersol,
            ]
        )
        # Create an additional spend to confirm the change on-chain
        new_full_puzzle: Program = create_singleton_puzzle(
            new_inner_puzzle,
            self.did_info.origin_coin.name(),
        )
        new_full_sol = Program.to(
            [
                [
                    coin.parent_coin_info,
                    innerpuz.get_tree_hash(),
                    coin.amount,
                ],
                coin.amount,
                innersol,
            ]
        )
        new_coin = Coin(coin.name(), new_full_puzzle.get_tree_hash(), coin.amount)
        list_of_coinspends = [
            make_spend(coin, full_puzzle, fullsol),
            make_spend(new_coin, new_full_puzzle, new_full_sol),
        ]
        spend_bundle = WalletSpendBundle(list_of_coinspends, G2Element())
        if fee > 0:
            coin_name = coin.name()
            await self.standard_wallet.create_tandem_xch_tx(
                fee,
                action_scope,
                extra_conditions=(AssertCoinAnnouncement(asserted_id=coin_name, asserted_msg=coin_name),),
            )
        did_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=await self.standard_wallet.get_puzzle_hash(False),
            amount=uint64(coin.amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_info.id,
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=bytes32.secret(),
            memos=list(compute_memos(spend_bundle).items()),
            valid_times=parse_timelock_info(extra_conditions),
        )

        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(did_record)

    async def transfer_did(
        self,
        new_puzhash: bytes32,
        fee: uint64,
        with_recovery: bool,
        action_scope: WalletActionScope,
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        """
        Transfer the current DID to another owner
        :param new_puzhash: New owner's p2_puzzle
        :param fee: Transaction fee
        :param with_recovery: A boolean indicates if the recovery info will be sent through the blockchain
        :return: Spend bundle
        """
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        coin = await self.get_coin()
        backup_ids = []
        backup_required = uint64(0)
        if with_recovery:
            backup_ids = self.did_info.backup_ids
            backup_required = self.did_info.num_of_backup_ids_needed
        new_did_puzhash = did_wallet_puzzles.get_inner_puzhash_by_p2(
            p2_puzhash=new_puzhash,
            recovery_list=backup_ids,
            num_of_backup_ids_needed=backup_required,
            launcher_id=self.did_info.origin_coin.name(),
            metadata=did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
        )
        p2_solution = self.standard_wallet.make_solution(
            primaries=[Payment(new_did_puzhash, uint64(coin.amount), [new_puzhash])],
            conditions=(*extra_conditions, CreateCoinAnnouncement(coin.name())),
        )
        # Need to include backup list reveal here, even we are don't recover
        # innerpuz solution is
        # (mode, p2_solution)
        innersol: Program = Program.to([2, p2_solution])
        if with_recovery:
            innersol = Program.to([2, p2_solution, [], [], [], self.did_info.backup_ids])
        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)

        full_puzzle: Program = create_singleton_puzzle(
            self.did_info.current_inner,
            self.did_info.origin_coin.name(),
        )
        parent_info = self.get_parent_for_coin(coin)
        assert parent_info is not None
        fullsol = Program.to(
            [
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                coin.amount,
                innersol,
            ]
        )
        list_of_coinspends = [make_spend(coin, full_puzzle, fullsol)]
        spend_bundle = WalletSpendBundle(list_of_coinspends, G2Element())
        if fee > 0:
            coin_name = coin.name()
            await self.standard_wallet.create_tandem_xch_tx(
                fee,
                action_scope,
                extra_conditions=(AssertCoinAnnouncement(asserted_id=coin_name, asserted_msg=coin_name),),
            )
        did_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=await self.standard_wallet.get_puzzle_hash(False),
            amount=uint64(coin.amount),
            fee_amount=fee,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_info.id,
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=spend_bundle.name(),
            memos=list(compute_memos(spend_bundle).items()),
            valid_times=parse_timelock_info(extra_conditions),
        )

        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(did_record)

    # The message spend can tests\wallet\rpc\test_wallet_rpc.py send messages and also change your innerpuz
    async def create_message_spend(
        self,
        action_scope: WalletActionScope,
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        coin = await self.get_coin()
        innerpuz: Program = self.did_info.current_inner
        # Quote message puzzle & solution
        if action_scope.config.tx_config.reuse_puzhash:
            new_innerpuzzle_hash = innerpuz.get_tree_hash()
            uncurried = did_wallet_puzzles.uncurry_innerpuz(innerpuz)
            assert uncurried is not None
            p2_ph = uncurried[0].get_tree_hash()
        else:
            p2_ph = await self.standard_wallet.get_puzzle_hash(new=True)
            new_innerpuzzle_hash = did_wallet_puzzles.get_inner_puzhash_by_p2(
                p2_puzhash=p2_ph,
                recovery_list=self.did_info.backup_ids,
                num_of_backup_ids_needed=self.did_info.num_of_backup_ids_needed,
                launcher_id=self.did_info.origin_coin.name(),
                metadata=did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
            )
        p2_solution = self.standard_wallet.make_solution(
            primaries=[Payment(puzzle_hash=new_innerpuzzle_hash, amount=uint64(coin.amount), memos=[p2_ph])],
            conditions=extra_conditions,
        )
        # innerpuz solution is (mode p2_solution)
        innersol: Program = Program.to([1, p2_solution])

        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        full_puzzle: Program = create_singleton_puzzle(
            innerpuz,
            self.did_info.origin_coin.name(),
        )
        parent_info = self.get_parent_for_coin(coin)
        assert parent_info is not None
        fullsol = Program.to(
            [
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                coin.amount,
                innersol,
            ]
        )
        list_of_coinspends = [make_spend(coin, full_puzzle, fullsol)]
        unsigned_spend_bundle = WalletSpendBundle(list_of_coinspends, G2Element())
        tx = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=p2_ph,
            amount=uint64(coin.amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=unsigned_spend_bundle,
            additions=unsigned_spend_bundle.additions(),
            removals=[coin],
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.OUTGOING_TX.value),
            name=unsigned_spend_bundle.name(),
            memos=list(compute_memos(unsigned_spend_bundle).items()),
            valid_times=parse_timelock_info(extra_conditions),
        )
        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(tx)

    # This is used to cash out, or update the id_list
    async def create_exit_spend(self, puzhash: bytes32, action_scope: WalletActionScope) -> None:
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        coin = await self.get_coin()
        message_puz = Program.to((1, [[51, puzhash, coin.amount - 1, [puzhash]], [51, 0x00, -113]]))

        # innerpuz solution is (mode p2_solution)
        innersol: Program = Program.to([1, [[], message_puz, []]])
        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        innerpuz: Program = self.did_info.current_inner

        full_puzzle: Program = create_singleton_puzzle(
            innerpuz,
            self.did_info.origin_coin.name(),
        )
        parent_info = self.get_parent_for_coin(coin)
        assert parent_info is not None
        fullsol = Program.to(
            [
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                coin.amount,
                innersol,
            ]
        )
        list_of_coinspends = [make_spend(coin, full_puzzle, fullsol)]
        spend_bundle = WalletSpendBundle(list_of_coinspends, G2Element())

        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(
                TransactionRecord(
                    confirmed_at_height=uint32(0),
                    created_at_time=uint64(int(time.time())),
                    to_puzzle_hash=await self.standard_wallet.get_puzzle_hash(False),
                    amount=uint64(coin.amount),
                    fee_amount=uint64(0),
                    confirmed=False,
                    sent=uint32(0),
                    spend_bundle=spend_bundle,
                    additions=spend_bundle.additions(),
                    removals=spend_bundle.removals(),
                    wallet_id=self.wallet_info.id,
                    sent_to=[],
                    trade_id=None,
                    type=uint32(TransactionType.OUTGOING_TX.value),
                    name=bytes32.secret(),
                    memos=list(compute_memos(spend_bundle).items()),
                    valid_times=ConditionValidTimes(),
                )
            )

    # Pushes a spend bundle to create a message coin on the blockchain
    # Returns a spend bundle for the recoverer to spend the message coin
    async def create_attestment(
        self,
        recovering_coin_name: bytes32,
        newpuz: bytes32,
        pubkey: G1Element,
        action_scope: WalletActionScope,
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> Tuple[WalletSpendBundle, str]:
        """
        Create an attestment
        TODO:
            1. We should use/respect `action_scope.config.tx_config` (reuse_puzhash and co)
            2. We should take a fee as it's a requirement for every transaction function to do so
        :param recovering_coin_name: Coin ID of the DID
        :param newpuz: New puzzle hash
        :param pubkey: New wallet pubkey
        :return: (Spend bundle, attest string)
        """
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        coin = await self.get_coin()
        message = did_wallet_puzzles.create_recovery_message_puzzle(recovering_coin_name, newpuz, pubkey)
        innermessage = message.get_tree_hash()
        innerpuz: Program = self.did_info.current_inner
        uncurried = did_wallet_puzzles.uncurry_innerpuz(innerpuz)
        assert uncurried is not None
        p2_puzzle = uncurried[0]
        # innerpuz solution is (mode, p2_solution)
        p2_solution = self.standard_wallet.make_solution(
            primaries=[
                Payment(innerpuz.get_tree_hash(), uint64(coin.amount), [p2_puzzle.get_tree_hash()]),
                Payment(innermessage, uint64(0)),
            ],
            conditions=extra_conditions,
        )
        innersol = Program.to([1, p2_solution])

        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        full_puzzle: Program = create_singleton_puzzle(
            innerpuz,
            self.did_info.origin_coin.name(),
        )
        parent_info = self.get_parent_for_coin(coin)
        assert parent_info is not None

        fullsol = Program.to(
            [
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                coin.amount,
                innersol,
            ]
        )
        list_of_coinspends = [make_spend(coin, full_puzzle, fullsol)]
        message_spend = did_wallet_puzzles.create_spend_for_message(coin.name(), recovering_coin_name, newpuz, pubkey)
        message_spend_bundle = WalletSpendBundle([message_spend], AugSchemeMPL.aggregate([]))
        spend_bundle = WalletSpendBundle(list_of_coinspends, G2Element())
        did_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=await self.standard_wallet.get_puzzle_hash(False),
            amount=uint64(coin.amount),
            fee_amount=uint64(0),
            confirmed=False,
            sent=uint32(0),
            spend_bundle=spend_bundle,
            additions=spend_bundle.additions(),
            removals=spend_bundle.removals(),
            wallet_id=self.wallet_info.id,
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.INCOMING_TX.value),
            name=bytes32.secret(),
            memos=list(compute_memos(spend_bundle).items()),
            valid_times=parse_timelock_info(extra_conditions),
        )
        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(did_record)
        attest_str: str = f"{self.get_my_DID()}:{bytes(message_spend_bundle).hex()}:{coin.parent_coin_info.hex()}:"
        attest_str += f"{self.did_info.current_inner.get_tree_hash().hex()}:{coin.amount}"
        return message_spend_bundle, attest_str

    async def get_info_for_recovery(self) -> Optional[Tuple[bytes32, bytes32, uint64]]:
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        try:
            coin = await self.get_coin()
        except RuntimeError:
            return None
        parent = coin.parent_coin_info
        innerpuzhash = self.did_info.current_inner.get_tree_hash()
        amount = uint64(coin.amount)
        return (parent, innerpuzhash, amount)

    async def load_attest_files_for_recovery_spend(self, attest_data: List[str]) -> Tuple[List, WalletSpendBundle]:
        spend_bundle_list = []
        info_dict = {}
        for attest in attest_data:
            info = attest.split(":")
            info_dict[info[0]] = [
                bytes.fromhex(info[2]),
                bytes.fromhex(info[3]),
                uint64(info[4]),
            ]
            new_sb = WalletSpendBundle.from_bytes(bytes.fromhex(info[1]))
            spend_bundle_list.append(new_sb)
        # info_dict {0xidentity: "(0xparent_info 0xinnerpuz amount)"}
        my_recovery_list: List[bytes32] = self.did_info.backup_ids

        # convert info dict into recovery list - same order as wallet
        info_list = []
        for entry in my_recovery_list:
            if entry.hex() in info_dict:
                info_list.append(
                    [
                        info_dict[entry.hex()][0],
                        info_dict[entry.hex()][1],
                        info_dict[entry.hex()][2],
                    ]
                )
            else:
                info_list.append([])
        message_spend_bundle = WalletSpendBundle.aggregate(spend_bundle_list)
        return info_list, message_spend_bundle

    async def recovery_spend(
        self,
        coin: Coin,
        puzhash: bytes32,
        parent_innerpuzhash_amounts_for_recovery_ids: List[Tuple[bytes, bytes, int]],
        pubkey: G1Element,
        spend_bundle: WalletSpendBundle,
        action_scope: WalletActionScope,
    ) -> None:
        assert self.did_info.origin_coin is not None

        # innersol is mode new_amount_or_p2_solution new_inner_puzhash parent_innerpuzhash_amounts_for_recovery_ids pubkey recovery_list_reveal my_id)  # noqa
        innersol: Program = Program.to(
            [
                0,
                coin.amount,
                puzhash,
                parent_innerpuzhash_amounts_for_recovery_ids,
                bytes(pubkey),
                self.did_info.backup_ids,
                coin.name(),
            ]
        )
        # full solution is (parent_info my_amount solution)
        assert self.did_info.current_inner is not None
        innerpuz: Program = self.did_info.current_inner
        full_puzzle: Program = create_singleton_puzzle(
            innerpuz,
            self.did_info.origin_coin.name(),
        )
        parent_info = self.get_parent_for_coin(coin)
        assert parent_info is not None
        fullsol = Program.to(
            [
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                coin.amount,
                innersol,
            ]
        )
        list_of_coinspends = [make_spend(coin, full_puzzle, fullsol)]

        spend_bundle = spend_bundle.aggregate([spend_bundle, WalletSpendBundle(list_of_coinspends, G2Element())])

        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(
                TransactionRecord(
                    confirmed_at_height=uint32(0),
                    created_at_time=uint64(int(time.time())),
                    to_puzzle_hash=await self.standard_wallet.get_puzzle_hash(False),
                    amount=uint64(coin.amount),
                    fee_amount=uint64(0),
                    confirmed=False,
                    sent=uint32(0),
                    spend_bundle=spend_bundle,
                    additions=spend_bundle.additions(),
                    removals=spend_bundle.removals(),
                    wallet_id=self.wallet_info.id,
                    sent_to=[],
                    trade_id=None,
                    type=uint32(TransactionType.OUTGOING_TX.value),
                    name=bytes32.secret(),
                    memos=list(compute_memos(spend_bundle).items()),
                    valid_times=ConditionValidTimes(),
                )
            )
        new_did_info = DIDInfo(
            origin_coin=self.did_info.origin_coin,
            backup_ids=self.did_info.backup_ids,
            num_of_backup_ids_needed=self.did_info.num_of_backup_ids_needed,
            parent_info=self.did_info.parent_info,
            current_inner=self.did_info.current_inner,
            temp_coin=self.did_info.temp_coin,
            temp_puzhash=self.did_info.temp_puzhash,
            temp_pubkey=self.did_info.temp_pubkey,
            sent_recovery_transaction=True,
            metadata=self.did_info.metadata,
        )
        await self.save_info(new_did_info)

    async def get_new_p2_inner_hash(self) -> bytes32:
        puzzle = await self.get_new_p2_inner_puzzle()
        return puzzle.get_tree_hash()

    async def get_new_p2_inner_puzzle(self) -> Program:
        return await self.standard_wallet.get_new_puzzle()

    async def get_new_did_innerpuz(self, origin_id: Optional[bytes32] = None) -> Program:
        if self.did_info.origin_coin is not None:
            launcher_id = self.did_info.origin_coin.name()
        elif origin_id is not None:
            launcher_id = origin_id
        else:
            raise ValueError("must have origin coin")
        return did_wallet_puzzles.create_innerpuz(
            p2_puzzle_or_hash=await self.get_new_p2_inner_puzzle(),
            recovery_list=self.did_info.backup_ids,
            num_of_backup_ids_needed=self.did_info.num_of_backup_ids_needed,
            launcher_id=launcher_id,
            metadata=did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
        )

    async def get_new_did_inner_hash(self) -> bytes32:
        innerpuz = await self.get_new_did_innerpuz()
        return innerpuz.get_tree_hash()

    async def get_innerpuz_for_new_innerhash(self, pubkey: G1Element):
        """
        Get the inner puzzle for a new owner
        :param pubkey: Pubkey
        :return: Inner puzzle
        """
        # Note: the recovery list will be kept.
        # In a selling case, the seller should clean the recovery list then transfer to the new owner.
        assert self.did_info.origin_coin is not None
        return did_wallet_puzzles.create_innerpuz(
            p2_puzzle_or_hash=puzzle_for_pk(pubkey),
            recovery_list=self.did_info.backup_ids,
            num_of_backup_ids_needed=uint64(self.did_info.num_of_backup_ids_needed),
            launcher_id=self.did_info.origin_coin.name(),
            metadata=did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
        )

    async def inner_puzzle_for_did_puzzle(self, did_hash: bytes32) -> Program:
        record: DerivationRecord = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
            did_hash
        )
        assert self.did_info.origin_coin is not None
        assert self.did_info.current_inner is not None
        uncurried_args = uncurry_innerpuz(self.did_info.current_inner)
        assert uncurried_args is not None
        old_recovery_list_hash: Optional[Program] = None
        p2_puzzle, old_recovery_list_hash, _, _, _ = uncurried_args
        if record is None:
            record = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
                p2_puzzle.get_tree_hash()
            )
        if not (self.did_info.num_of_backup_ids_needed > 0 and len(self.did_info.backup_ids) == 0):
            # We have the recovery list, don't reset it
            old_recovery_list_hash = None

        inner_puzzle: Program = did_wallet_puzzles.create_innerpuz(
            p2_puzzle_or_hash=puzzle_for_pk(record.pubkey),
            recovery_list=self.did_info.backup_ids,
            num_of_backup_ids_needed=self.did_info.num_of_backup_ids_needed,
            launcher_id=self.did_info.origin_coin.name(),
            metadata=did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
            recovery_list_hash=old_recovery_list_hash,
        )
        return inner_puzzle

    def get_parent_for_coin(self, coin) -> Optional[LineageProof]:
        parent_info = None
        for name, ccparent in self.did_info.parent_info:
            if name == coin.parent_coin_info:
                parent_info = ccparent

        return parent_info

    async def sign_message(self, message: str, mode: SigningMode) -> Tuple[G1Element, G2Element]:
        if self.did_info.current_inner is None:
            raise ValueError("Missing DID inner puzzle.")
        puzzle_args = did_wallet_puzzles.uncurry_innerpuz(self.did_info.current_inner)
        if puzzle_args is not None:
            p2_puzzle, _, _, _, _ = puzzle_args
            puzzle_hash = p2_puzzle.get_tree_hash()
            private = await self.wallet_state_manager.get_private_key(puzzle_hash)
            synthetic_secret_key = calculate_synthetic_secret_key(private, DEFAULT_HIDDEN_PUZZLE_HASH)
            synthetic_pk = synthetic_secret_key.get_g1()
            if mode == SigningMode.CHIP_0002_HEX_INPUT:
                hex_message: bytes = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, bytes.fromhex(message))).get_tree_hash()
            elif mode == SigningMode.BLS_MESSAGE_AUGMENTATION_UTF8_INPUT:
                hex_message = bytes(message, "utf-8")
            elif mode == SigningMode.BLS_MESSAGE_AUGMENTATION_HEX_INPUT:
                hex_message = bytes.fromhex(message)
            else:
                hex_message = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, message)).get_tree_hash()
            return synthetic_pk, AugSchemeMPL.sign(synthetic_secret_key, hex_message)
        else:
            raise ValueError("Invalid inner DID puzzle.")

    async def generate_new_decentralised_id(
        self,
        amount: uint64,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        """
        This must be called under the wallet state manager lock
        """

        coins = await self.standard_wallet.select_coins(uint64(amount + fee), action_scope)

        origin = coins.copy().pop()
        genesis_launcher_puz = SINGLETON_LAUNCHER_PUZZLE
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), amount)

        did_inner: Program = await self.get_new_did_innerpuz(launcher_coin.name())
        did_inner_hash = did_inner.get_tree_hash()
        did_full_puz = create_singleton_puzzle(did_inner, launcher_coin.name())
        did_puzzle_hash = did_full_puz.get_tree_hash()

        announcement_message = Program.to([did_puzzle_hash, amount, bytes(0x80)]).get_tree_hash()

        await self.standard_wallet.generate_signed_transaction(
            amount=amount,
            puzzle_hash=genesis_launcher_puz.get_tree_hash(),
            action_scope=action_scope,
            fee=fee,
            coins=coins,
            primaries=None,
            origin_id=origin.name(),
            extra_conditions=(
                AssertCoinAnnouncement(asserted_id=launcher_coin.name(), asserted_msg=announcement_message),
                *extra_conditions,
            ),
        )

        genesis_launcher_solution = Program.to([did_puzzle_hash, amount, bytes(0x80)])

        launcher_cs = make_spend(launcher_coin, genesis_launcher_puz, genesis_launcher_solution)
        launcher_sb = WalletSpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))
        eve_coin = Coin(launcher_coin.name(), did_puzzle_hash, amount)
        future_parent = LineageProof(
            parent_name=eve_coin.parent_coin_info,
            inner_puzzle_hash=did_inner_hash,
            amount=uint64(eve_coin.amount),
        )
        eve_parent = LineageProof(
            parent_name=launcher_coin.parent_coin_info,
            inner_puzzle_hash=launcher_coin.puzzle_hash,
            amount=uint64(launcher_coin.amount),
        )
        await self.add_parent(eve_coin.parent_coin_info, eve_parent)
        await self.add_parent(eve_coin.name(), future_parent)

        # Only want to save this information if the transaction is valid
        did_info = DIDInfo(
            origin_coin=launcher_coin,
            backup_ids=self.did_info.backup_ids,
            num_of_backup_ids_needed=self.did_info.num_of_backup_ids_needed,
            parent_info=self.did_info.parent_info,
            current_inner=did_inner,
            temp_coin=None,
            temp_puzhash=None,
            temp_pubkey=None,
            sent_recovery_transaction=False,
            metadata=self.did_info.metadata,
        )
        await self.save_info(did_info)
        eve_spend = await self.generate_eve_spend(eve_coin, did_full_puz, did_inner)
        full_spend = WalletSpendBundle.aggregate([eve_spend, launcher_sb])
        assert self.did_info.origin_coin is not None
        assert self.did_info.current_inner is not None

        did_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            amount=uint64(amount),
            to_puzzle_hash=await self.standard_wallet.get_puzzle_hash(False),
            fee_amount=fee,
            confirmed=False,
            sent=uint32(0),
            spend_bundle=full_spend,
            additions=full_spend.additions(),
            removals=full_spend.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.INCOMING_TX.value),
            name=full_spend.name(),
            memos=[],
            valid_times=ConditionValidTimes(),
        )
        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(did_record)

    async def generate_eve_spend(
        self,
        coin: Coin,
        full_puzzle: Program,
        innerpuz: Program,
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ):
        assert self.did_info.origin_coin is not None
        uncurried = did_wallet_puzzles.uncurry_innerpuz(innerpuz)
        assert uncurried is not None
        p2_puzzle = uncurried[0]
        # innerpuz solution is (mode p2_solution)
        p2_solution = self.standard_wallet.make_solution(
            primaries=[Payment(innerpuz.get_tree_hash(), uint64(coin.amount), [p2_puzzle.get_tree_hash()])],
            conditions=extra_conditions,
        )
        innersol = Program.to([1, p2_solution])
        # full solution is (lineage_proof my_amount inner_solution)
        fullsol = Program.to(
            [
                [self.did_info.origin_coin.parent_coin_info, self.did_info.origin_coin.amount],
                coin.amount,
                innersol,
            ]
        )
        list_of_coinspends = [make_spend(coin, full_puzzle, fullsol)]
        unsigned_spend_bundle = WalletSpendBundle(list_of_coinspends, G2Element())
        return unsigned_spend_bundle

    async def get_spendable_balance(self, unspent_records=None) -> uint128:
        spendable_am = await self.wallet_state_manager.get_confirmed_spendable_balance_for_wallet(
            self.wallet_info.id, unspent_records
        )
        return spendable_am

    async def get_max_send_amount(self, records: Optional[Set[WalletCoinRecord]] = None):
        max_send_amount = await self.get_confirmed_balance()

        return max_send_amount

    async def add_parent(self, name: bytes32, parent: Optional[LineageProof]):
        self.log.info(f"Adding parent {name}: {parent}")
        current_list = self.did_info.parent_info.copy()
        current_list.append((name, parent))
        did_info = DIDInfo(
            origin_coin=self.did_info.origin_coin,
            backup_ids=self.did_info.backup_ids,
            num_of_backup_ids_needed=self.did_info.num_of_backup_ids_needed,
            parent_info=current_list,
            current_inner=self.did_info.current_inner,
            temp_coin=self.did_info.temp_coin,
            temp_puzhash=self.did_info.temp_puzhash,
            temp_pubkey=self.did_info.temp_pubkey,
            sent_recovery_transaction=self.did_info.sent_recovery_transaction,
            metadata=self.did_info.metadata,
        )
        await self.save_info(did_info)

    async def update_recovery_list(self, recover_list: List[bytes32], num_of_backup_ids_needed: uint64) -> bool:
        if num_of_backup_ids_needed > len(recover_list):
            return False
        did_info = DIDInfo(
            origin_coin=self.did_info.origin_coin,
            backup_ids=recover_list,
            num_of_backup_ids_needed=num_of_backup_ids_needed,
            parent_info=self.did_info.parent_info,
            current_inner=self.did_info.current_inner,
            temp_coin=self.did_info.temp_coin,
            temp_puzhash=self.did_info.temp_puzhash,
            temp_pubkey=self.did_info.temp_pubkey,
            sent_recovery_transaction=self.did_info.sent_recovery_transaction,
            metadata=self.did_info.metadata,
        )
        await self.save_info(did_info)
        await self.wallet_state_manager.update_wallet_puzzle_hashes(self.wallet_info.id)
        return True

    async def update_metadata(self, metadata: Dict[str, str]) -> bool:
        # validate metadata
        if not all(isinstance(k, str) and isinstance(v, str) for k, v in metadata.items()):
            raise ValueError("Metadata key value pairs must be strings.")
        did_info = DIDInfo(
            origin_coin=self.did_info.origin_coin,
            backup_ids=self.did_info.backup_ids,
            num_of_backup_ids_needed=self.did_info.num_of_backup_ids_needed,
            parent_info=self.did_info.parent_info,
            current_inner=self.did_info.current_inner,
            temp_coin=self.did_info.temp_coin,
            temp_puzhash=self.did_info.temp_puzhash,
            temp_pubkey=self.did_info.temp_pubkey,
            sent_recovery_transaction=self.did_info.sent_recovery_transaction,
            metadata=json.dumps(metadata),
        )
        await self.save_info(did_info)
        await self.wallet_state_manager.update_wallet_puzzle_hashes(self.wallet_info.id)
        return True

    async def save_info(self, did_info: DIDInfo):
        self.did_info = did_info
        current_info = self.wallet_info
        data_str = json.dumps(did_info.to_json_dict())
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info)

    def generate_wallet_name(self) -> str:
        """
        Generate a new DID wallet name
        :return: wallet name
        """
        max_num = 0
        for wallet in self.wallet_state_manager.wallets.values():
            if wallet.type() == WalletType.DECENTRALIZED_ID:
                matched = re.search(r"^Profile (\d+)$", wallet.get_name())
                if matched and int(matched.group(1)) > max_num:
                    max_num = int(matched.group(1))
        return f"Profile {max_num + 1}"

    def check_existed_did(self):
        """
        Check if the current DID is existed
        :return: None
        """
        for wallet in self.wallet_state_manager.wallets.values():
            if (
                wallet.type() == WalletType.DECENTRALIZED_ID
                and self.did_info.origin_coin.name() == wallet.did_info.origin_coin.name()
            ):
                self.log.warning(f"DID {self.did_info.origin_coin} already existed, ignore the wallet creation.")
                raise ValueError("Wallet already exists")

    @staticmethod
    def deserialize_backup_data(backup_data: str) -> DIDInfo:
        """
        Get a DIDInfo from a serialized string
        :param backup_data: serialized
        :return: DIDInfo
        """
        details = backup_data.split(":")
        origin = Coin(bytes32.fromhex(details[0]), bytes32.fromhex(details[1]), uint64(int(details[2])))
        backup_ids = []
        if len(details[3]) > 0:
            for d in details[3].split(","):
                backup_ids.append(bytes32.from_hexstr(d))
        num_of_backup_ids_needed = uint64(int(details[5]))
        if num_of_backup_ids_needed > len(backup_ids):
            raise Exception
        innerpuz: Program = Program.from_bytes(bytes.fromhex(details[4]))
        metadata: str = details[6]
        did_info = DIDInfo(
            origin_coin=origin,
            backup_ids=backup_ids,
            num_of_backup_ids_needed=num_of_backup_ids_needed,
            parent_info=[],
            current_inner=innerpuz,
            temp_coin=None,
            temp_puzhash=None,
            temp_pubkey=None,
            sent_recovery_transaction=True,
            metadata=metadata,
        )
        return did_info

    def require_derivation_paths(self) -> bool:
        return True

    async def get_coin(self) -> Coin:
        spendable_coins: Set[WalletCoinRecord] = await self.wallet_state_manager.get_spendable_coins_for_wallet(
            self.wallet_info.id
        )
        if len(spendable_coins) == 0:
            raise RuntimeError("DID is not currently spendable")
        return sorted(list(spendable_coins), key=lambda c: c.confirmed_block_height, reverse=True)[0].coin

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:
        if self.did_info.origin_coin is None:
            return False  # pragma: no cover
        return (
            create_singleton_puzzle(
                did_wallet_puzzles.create_innerpuz(
                    p2_puzzle_or_hash=hint,
                    recovery_list=self.did_info.backup_ids,
                    num_of_backup_ids_needed=uint64(self.did_info.num_of_backup_ids_needed),
                    launcher_id=self.did_info.origin_coin.name(),
                    metadata=did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
                ),
                self.did_info.origin_coin.name(),
            ).get_tree_hash_precalc(hint)
            == coin.puzzle_hash
        )
