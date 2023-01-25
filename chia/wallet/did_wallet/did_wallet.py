from __future__ import annotations

import dataclasses
import json
import logging
import re
import time
from secrets import token_bytes
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set, Tuple

from blspy import AugSchemeMPL, G1Element, G2Element

from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols import wallet_protocol
from chia.protocols.wallet_protocol import CoinState
from chia.server.ws_connection import WSChiaConnection
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.wallet.coin_selection import select_coins
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.derive_keys import master_sk_to_wallet_sk_unhardened
from chia.wallet.did_wallet import did_wallet_puzzles
from chia.wallet.did_wallet.did_info import DIDInfo
from chia.wallet.did_wallet.did_wallet_puzzles import create_fullpuz, uncurry_innerpuz
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
    puzzle_hash_for_pk,
)
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.compute_memos import compute_memos
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import CHIP_0002_SIGN_MESSAGE_PREFIX, Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo


class DIDWallet:
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
        backups_ids: List = [],
        num_of_backup_ids_needed: uint64 = None,
        metadata: Dict[str, str] = {},
        name: Optional[str] = None,
        fee: uint64 = uint64(0),
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
            None, backups_ids, num_of_backup_ids_needed, [], None, None, None, None, False, json.dumps(metadata)
        )
        info_as_string = json.dumps(self.did_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name, WalletType.DECENTRALIZED_ID.value, info_as_string
        )
        self.wallet_id = self.wallet_info.id
        std_wallet_id = self.standard_wallet.wallet_id
        bal = await wallet_state_manager.get_confirmed_balance_for_wallet(std_wallet_id)
        if amount > bal:
            raise ValueError("Not enough balance")

        try:
            spend_bundle = await self.generate_new_decentralised_id(amount, fee)
        except Exception:
            await wallet_state_manager.user_store.delete_wallet(self.id())
            raise

        if spend_bundle is None:
            await wallet_state_manager.user_store.delete_wallet(self.id())
            raise ValueError("Failed to create spend.")
        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)

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
            name, WalletType.DECENTRALIZED_ID.value, info_as_string
        )
        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)
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
        if recovery_list_hash != Program.to([]).get_tree_hash():
            try:
                for did in inner_solution.rest().rest().rest().rest().rest().as_python():
                    recovery_list.append(did[0])
            except Exception:
                self.log.warning(
                    f"DID {launch_coin.name().hex()} has a recovery list hash but missing a reveal,"
                    " you may need to reset the recovery info."
                )
        self.did_info = DIDInfo(
            launch_coin,
            recovery_list,
            uint64(backup_required),
            [],
            inner_puzzle,
            None,
            None,
            None,
            False,
            json.dumps(did_wallet_puzzles.program_to_metadata(metadata)),
        )
        self.check_existed_did()
        info_as_string = json.dumps(self.did_info.to_json_dict())

        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name, WalletType.DECENTRALIZED_ID.value, info_as_string
        )
        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)
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
    def type(cls) -> uint8:
        return uint8(WalletType.DECENTRALIZED_ID)

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
        exclude: Optional[List[Coin]] = None,
        min_coin_amount: Optional[uint64] = None,
        max_coin_amount: Optional[uint64] = None,
        excluded_coin_amounts: Optional[List[uint64]] = None,
    ) -> Set[Coin]:
        """
        Returns a set of coins that can be used for generating a new transaction.
        Note: Must be called under wallet state manager lock
        """

        spendable_amount: uint128 = await self.get_spendable_balance()

        if amount > spendable_amount:
            error_msg = f"Can't select {amount}, from spendable {spendable_amount} for wallet id {self.id()}"
            self.log.warning(error_msg)
            raise ValueError(error_msg)

        spendable_coins: List[WalletCoinRecord] = list(
            await self.wallet_state_manager.get_spendable_coins_for_wallet(self.wallet_info.id)
        )

        # Try to use coins from the store, if there isn't enough of "unused"
        # coins use change coins that are not confirmed yet
        unconfirmed_removals: Dict[bytes32, Coin] = await self.wallet_state_manager.unconfirmed_removals_for_wallet(
            self.wallet_info.id
        )
        if max_coin_amount is None:
            max_coin_amount = uint64(self.wallet_state_manager.constants.MAX_COIN_AMOUNT)
        coins = await select_coins(
            spendable_amount,
            max_coin_amount,
            spendable_coins,
            unconfirmed_removals,
            self.log,
            uint128(amount),
            exclude,
            min_coin_amount,
            excluded_coin_amounts,
        )
        assert sum(c.amount for c in coins) >= amount
        return coins

    # This will be used in the recovery case where we don't have the parent info already
    async def coin_added(self, coin: Coin, _: uint32, peer: WSChiaConnection):
        """Notification from wallet state manager that wallet has been received."""

        parent = self.get_parent_for_coin(coin)
        if parent is None:
            # this is the first time we received it, check it's a DID coin
            parent_state: CoinState = (
                await self.wallet_state_manager.wallet_node.get_coin_state([coin.parent_coin_info], peer=peer)
            )[0]
            assert parent_state.spent_height is not None
            puzzle_solution_request = wallet_protocol.RequestPuzzleSolution(
                coin.parent_coin_info, uint32(parent_state.spent_height)
            )
            response = await peer.call_api(FullNodeAPI.request_puzzle_solution, puzzle_solution_request)
            req_puz_sol = response.response
            assert req_puz_sol.puzzle is not None
            parent_innerpuz = did_wallet_puzzles.get_innerpuzzle_from_puzzle(req_puz_sol.puzzle.to_program())
            if parent_innerpuz:
                parent_info = LineageProof(
                    parent_state.coin.parent_coin_info,
                    parent_innerpuz.get_tree_hash(),
                    uint64(parent_state.coin.amount),
                )
                await self.add_parent(coin.parent_coin_info, parent_info)
            else:
                self.log.warning("Parent coin is not a DID, skipping: %s -> %s", coin.name(), coin)
                return
        self.log.info(f"DID wallet has been notified that coin was added: {coin.name()}:{coin}")
        inner_puzzle = await self.inner_puzzle_for_did_puzzle(coin.puzzle_hash)
        # Check inner puzzle consistency
        assert self.did_info.origin_coin is not None
        full_puzzle = create_fullpuz(inner_puzzle, self.did_info.origin_coin.name())
        assert full_puzzle.get_tree_hash() == coin.puzzle_hash
        if self.did_info.temp_coin is not None:
            self.wallet_state_manager.state_changed("did_coin_added", self.wallet_info.id)

        new_info = DIDInfo(
            self.did_info.origin_coin,
            self.did_info.backup_ids,
            self.did_info.num_of_backup_ids_needed,
            self.did_info.parent_info,
            inner_puzzle,
            None,
            None,
            None,
            False,
            self.did_info.metadata,
        )
        await self.save_info(new_info)

        future_parent = LineageProof(
            coin.parent_coin_info,
            inner_puzzle.get_tree_hash(),
            uint64(coin.amount),
        )

        await self.add_parent(coin.name(), future_parent)

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

        new_pubkey = (await self.wallet_state_manager.get_unused_derivation_record(self.wallet_info.id)).pubkey
        new_puzhash = puzzle_for_pk(new_pubkey).get_tree_hash()
        parent_info = None
        assert did_info.origin_coin is not None
        assert did_info.current_inner is not None
        new_did_inner_puzhash = did_wallet_puzzles.get_inner_puzhash_by_p2(
            new_puzhash,
            did_info.backup_ids,
            did_info.num_of_backup_ids_needed,
            did_info.origin_coin.name(),
            did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
        )
        wallet_node = self.wallet_state_manager.wallet_node
        peer: WSChiaConnection = wallet_node.get_full_node_peer()
        if peer is None:
            raise ValueError("Could not find any peers to request puzzle and solution from")

        parent_coin: Coin = did_info.origin_coin
        while True:
            children = await wallet_node.fetch_children(parent_coin.name(), peer)
            if len(children) == 0:
                break

            children_state: CoinState = children[0]
            child_coin = children_state.coin
            future_parent = LineageProof(
                child_coin.parent_coin_info,
                did_info.current_inner.get_tree_hash(),
                uint64(child_coin.amount),
            )
            await self.add_parent(child_coin.name(), future_parent)
            if children_state.spent_height != children_state.created_height:
                did_info = DIDInfo(
                    did_info.origin_coin,
                    did_info.backup_ids,
                    did_info.num_of_backup_ids_needed,
                    self.did_info.parent_info,
                    did_info.current_inner,
                    child_coin,
                    new_did_inner_puzhash,
                    bytes(new_pubkey),
                    did_info.sent_recovery_transaction,
                    did_info.metadata,
                )

                await self.save_info(did_info)
                assert children_state.created_height
                parent_spend = await wallet_node.fetch_puzzle_solution(children_state.created_height, parent_coin, peer)
                assert parent_spend is not None
                parent_innerpuz = did_wallet_puzzles.get_innerpuzzle_from_puzzle(
                    parent_spend.puzzle_reveal.to_program()
                )
                assert parent_innerpuz is not None
                parent_info = LineageProof(
                    parent_coin.parent_coin_info,
                    parent_innerpuz.get_tree_hash(),
                    uint64(parent_coin.amount),
                )
                await self.add_parent(child_coin.parent_coin_info, parent_info)
            parent_coin = child_coin
        assert parent_info is not None

    async def create_tandem_xch_tx(
        self, fee: uint64, announcement_to_assert: Optional[Announcement] = None
    ) -> TransactionRecord:
        chia_coins = await self.standard_wallet.select_coins(fee)
        chia_tx = await self.standard_wallet.generate_signed_transaction(
            uint64(0),
            (await self.standard_wallet.get_new_puzzlehash()),
            fee=fee,
            coins=chia_coins,
            coin_announcements_to_consume={announcement_to_assert} if announcement_to_assert is not None else None,
        )
        assert chia_tx.spend_bundle is not None
        return chia_tx

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:
        if self.did_info.origin_coin is not None:
            innerpuz = did_wallet_puzzles.create_innerpuz(
                puzzle_for_pk(pubkey),
                self.did_info.backup_ids,
                self.did_info.num_of_backup_ids_needed,
                self.did_info.origin_coin.name(),
                did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
            )
            return did_wallet_puzzles.create_fullpuz(innerpuz, self.did_info.origin_coin.name())
        else:
            innerpuz = Program.to((8, 0))
            return did_wallet_puzzles.create_fullpuz(innerpuz, bytes32([0] * 32))

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        if self.did_info.origin_coin is None:
            # TODO: this seem dumb. Why bother with this case? Is it ever used?
            return puzzle_for_pk(pubkey).get_tree_hash()
        origin_coin_name = self.did_info.origin_coin.name()
        innerpuz_hash = did_wallet_puzzles.get_inner_puzhash_by_p2(
            puzzle_hash_for_pk(pubkey),
            self.did_info.backup_ids,
            self.did_info.num_of_backup_ids_needed,
            origin_coin_name,
            did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
        )
        return did_wallet_puzzles.create_fullpuz_hash(innerpuz_hash, origin_coin_name)

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
        import dataclasses

        new_info = dataclasses.replace(self.wallet_info, name=new_name)
        self.wallet_info = new_info
        await self.wallet_state_manager.user_store.update_wallet(self.wallet_info)

    def get_name(self):
        return self.wallet_info.name

    async def create_update_spend(self, fee: uint64 = uint64(0)):
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        coins = await self.select_coins(uint64(1))
        assert coins is not None
        coin = coins.pop()
        new_inner_puzzle = await self.get_new_did_innerpuz()
        uncurried = did_wallet_puzzles.uncurry_innerpuz(new_inner_puzzle)
        assert uncurried is not None
        p2_puzzle = uncurried[0]
        # innerpuz solution is (mode, p2_solution)
        p2_solution = self.standard_wallet.make_solution(
            primaries=[
                {
                    "puzzlehash": new_inner_puzzle.get_tree_hash(),
                    "amount": uint64(coin.amount),
                    "memos": [p2_puzzle.get_tree_hash()],
                }
            ],
            coin_announcements={coin.name()},
        )
        innersol: Program = Program.to([1, p2_solution])
        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        innerpuz: Program = self.did_info.current_inner

        full_puzzle: Program = did_wallet_puzzles.create_fullpuz(
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
        new_full_puzzle: Program = did_wallet_puzzles.create_fullpuz(
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
        list_of_coinspends = [CoinSpend(coin, full_puzzle, fullsol), CoinSpend(new_coin, new_full_puzzle, new_full_sol)]
        unsigned_spend_bundle = SpendBundle(list_of_coinspends, G2Element())
        spend_bundle = await self.sign(unsigned_spend_bundle)
        if fee > 0:
            announcement_to_make = coin.name()
            chia_tx = await self.create_tandem_xch_tx(fee, Announcement(coin.name(), announcement_to_make))
        else:
            announcement_to_make = None
            chia_tx = None
        if chia_tx is not None and chia_tx.spend_bundle is not None:
            spend_bundle = SpendBundle.aggregate([spend_bundle, chia_tx.spend_bundle])
            chia_tx = dataclasses.replace(chia_tx, spend_bundle=None)
            await self.wallet_state_manager.add_pending_transaction(chia_tx)
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
            name=bytes32(token_bytes()),
            memos=list(compute_memos(spend_bundle).items()),
        )
        await self.wallet_state_manager.add_pending_transaction(did_record)

        return spend_bundle

    async def transfer_did(self, new_puzhash: bytes32, fee: uint64, with_recovery: bool) -> TransactionRecord:
        """
        Transfer the current DID to another owner
        :param new_puzhash: New owner's p2_puzzle
        :param fee: Transaction fee
        :param with_recovery: A boolean indicates if the recovery info will be sent through the blockchain
        :return: Spend bundle
        """
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        coins = await self.select_coins(uint64(1))
        assert coins is not None
        coin = coins.pop()
        backup_ids = []
        backup_required = uint64(0)
        if with_recovery:
            backup_ids = self.did_info.backup_ids
            backup_required = self.did_info.num_of_backup_ids_needed
        new_did_puzhash = did_wallet_puzzles.get_inner_puzhash_by_p2(
            new_puzhash,
            backup_ids,
            backup_required,
            self.did_info.origin_coin.name(),
            did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
        )
        p2_solution = self.standard_wallet.make_solution(
            primaries=[
                {
                    "puzzlehash": new_did_puzhash,
                    "amount": uint64(coin.amount),
                    "memos": [new_puzhash],
                }
            ],
            coin_announcements={coin.name()},
        )
        # Need to include backup list reveal here, even we are don't recover
        # innerpuz solution is
        # (mode, p2_solution)
        innersol: Program = Program.to([2, p2_solution])
        if with_recovery:
            innersol = Program.to([2, p2_solution, [], [], [], self.did_info.backup_ids])
        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)

        full_puzzle: Program = did_wallet_puzzles.create_fullpuz(
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
        list_of_coinspends = [CoinSpend(coin, full_puzzle, fullsol)]
        unsigned_spend_bundle = SpendBundle(list_of_coinspends, G2Element())
        spend_bundle = await self.sign(unsigned_spend_bundle)
        if fee > 0:
            announcement_to_make = coin.name()
            chia_tx = await self.create_tandem_xch_tx(fee, Announcement(coin.name(), announcement_to_make))
        else:
            chia_tx = None
        if chia_tx is not None and chia_tx.spend_bundle is not None:
            spend_bundle = SpendBundle.aggregate([spend_bundle, chia_tx.spend_bundle])
            chia_tx = dataclasses.replace(chia_tx, spend_bundle=None)
            await self.wallet_state_manager.add_pending_transaction(chia_tx)
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
            name=bytes32(token_bytes()),
            memos=list(compute_memos(spend_bundle).items()),
        )
        await self.wallet_state_manager.add_pending_transaction(did_record)
        return did_record

    # The message spend can tests\wallet\rpc\test_wallet_rpc.py send messages and also change your innerpuz
    async def create_message_spend(
        self,
        coin_announcements: Optional[Set[bytes]] = None,
        puzzle_announcements: Optional[Set[bytes]] = None,
        new_innerpuzzle: Optional[Program] = None,
    ):
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        coins = await self.select_coins(uint64(1))
        assert coins is not None
        coin = coins.pop()
        innerpuz: Program = self.did_info.current_inner
        # Quote message puzzle & solution
        if new_innerpuzzle is None:
            new_innerpuzzle = innerpuz
        uncurried = did_wallet_puzzles.uncurry_innerpuz(new_innerpuzzle)
        assert uncurried is not None
        p2_puzzle = uncurried[0]
        p2_solution = self.standard_wallet.make_solution(
            primaries=[
                {
                    "puzzlehash": new_innerpuzzle.get_tree_hash(),
                    "amount": uint64(coin.amount),
                    "memos": [p2_puzzle.get_tree_hash()],
                }
            ],
            puzzle_announcements=puzzle_announcements,
            coin_announcements=coin_announcements,
        )
        # innerpuz solution is (mode p2_solution)
        innersol: Program = Program.to([1, p2_solution])

        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        full_puzzle: Program = did_wallet_puzzles.create_fullpuz(
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
        list_of_coinspends = [CoinSpend(coin, full_puzzle, fullsol)]
        unsigned_spend_bundle = SpendBundle(list_of_coinspends, G2Element())
        return await self.sign(unsigned_spend_bundle)

    # This is used to cash out, or update the id_list
    async def create_exit_spend(self, puzhash: bytes32):
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        coins = await self.select_coins(uint64(1))
        assert coins is not None
        coin = coins.pop()
        message_puz = Program.to((1, [[51, puzhash, coin.amount - 1, [puzhash]], [51, 0x00, -113]]))

        # innerpuz solution is (mode p2_solution)
        innersol: Program = Program.to([1, [[], message_puz, []]])
        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        innerpuz: Program = self.did_info.current_inner

        full_puzzle: Program = did_wallet_puzzles.create_fullpuz(
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
        list_of_coinspends = [CoinSpend(coin, full_puzzle, fullsol)]
        unsigned_spend_bundle = SpendBundle(list_of_coinspends, G2Element())
        spend_bundle = await self.sign(unsigned_spend_bundle)

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
            name=bytes32(token_bytes()),
            memos=list(compute_memos(spend_bundle).items()),
        )
        await self.wallet_state_manager.add_pending_transaction(did_record)
        return spend_bundle

    # Pushes a SpendBundle to create a message coin on the blockchain
    # Returns a SpendBundle for the recoverer to spend the message coin
    async def create_attestment(
        self, recovering_coin_name: bytes32, newpuz: bytes32, pubkey: G1Element
    ) -> Tuple[SpendBundle, str]:
        """
        Create an attestment
        :param recovering_coin_name: Coin ID of the DID
        :param newpuz: New puzzle hash
        :param pubkey: New wallet pubkey
        :return: (SpendBundle, attest string)
        """
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        coins = await self.select_coins(uint64(1))
        assert coins is not None and coins != set()
        coin = coins.pop()
        message = did_wallet_puzzles.create_recovery_message_puzzle(recovering_coin_name, newpuz, pubkey)
        innermessage = message.get_tree_hash()
        innerpuz: Program = self.did_info.current_inner
        uncurried = did_wallet_puzzles.uncurry_innerpuz(innerpuz)
        assert uncurried is not None
        p2_puzzle = uncurried[0]
        # innerpuz solution is (mode, p2_solution)
        p2_solution = self.standard_wallet.make_solution(
            primaries=[
                {
                    "puzzlehash": innerpuz.get_tree_hash(),
                    "amount": uint64(coin.amount),
                    "memos": [p2_puzzle.get_tree_hash()],
                },
                {"puzzlehash": innermessage, "amount": uint64(0), "memos": []},
            ],
        )
        innersol = Program.to([1, p2_solution])

        # full solution is (corehash parent_info my_amount innerpuz_reveal solution)
        full_puzzle: Program = did_wallet_puzzles.create_fullpuz(
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
        list_of_coinspends = [CoinSpend(coin, full_puzzle, fullsol)]
        message_spend = did_wallet_puzzles.create_spend_for_message(coin.name(), recovering_coin_name, newpuz, pubkey)
        message_spend_bundle = SpendBundle([message_spend], AugSchemeMPL.aggregate([]))
        unsigned_spend_bundle = SpendBundle(list_of_coinspends, G2Element())
        spend_bundle = await self.sign(unsigned_spend_bundle)
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
            name=bytes32(token_bytes()),
            memos=list(compute_memos(spend_bundle).items()),
        )
        attest_str: str = f"{self.get_my_DID()}:{bytes(message_spend_bundle).hex()}:{coin.parent_coin_info.hex()}:"
        attest_str += f"{self.did_info.current_inner.get_tree_hash().hex()}:{coin.amount}"
        await self.wallet_state_manager.add_pending_transaction(did_record)
        return message_spend_bundle, attest_str

    async def get_info_for_recovery(self) -> Optional[Tuple[bytes32, bytes32, uint64]]:
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None
        coins = await self.select_coins(uint64(1))
        if coins is not None:
            coin = coins.pop()
            parent = coin.parent_coin_info
            innerpuzhash = self.did_info.current_inner.get_tree_hash()
            amount = uint64(coin.amount)
            return (parent, innerpuzhash, amount)
        return None

    async def load_attest_files_for_recovery_spend(self, attest_data: List[str]) -> Tuple[List, SpendBundle]:
        spend_bundle_list = []
        info_dict = {}
        try:
            for attest in attest_data:
                info = attest.split(":")
                info_dict[info[0]] = [
                    bytes.fromhex(info[2]),
                    bytes.fromhex(info[3]),
                    uint64(info[4]),
                ]
                new_sb = SpendBundle.from_bytes(bytes.fromhex(info[1]))
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
            message_spend_bundle = SpendBundle.aggregate(spend_bundle_list)
            return info_list, message_spend_bundle
        except Exception:
            raise

    async def recovery_spend(
        self,
        coin: Coin,
        puzhash: bytes32,
        parent_innerpuzhash_amounts_for_recovery_ids: List[Tuple[bytes, bytes, int]],
        pubkey: G1Element,
        spend_bundle: SpendBundle,
    ) -> SpendBundle:
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
        full_puzzle: Program = did_wallet_puzzles.create_fullpuz(
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
        list_of_coinspends = [CoinSpend(coin, full_puzzle, fullsol)]

        index = await self.wallet_state_manager.puzzle_store.index_for_pubkey(pubkey)
        if index is None:
            raise ValueError("Unknown pubkey.")
        private = master_sk_to_wallet_sk_unhardened(self.wallet_state_manager.private_key, index)
        message = bytes(puzhash)
        sigs = [AugSchemeMPL.sign(private, message)]
        for _ in spend_bundle.coin_spends:
            sigs.append(AugSchemeMPL.sign(private, message))
        aggsig = AugSchemeMPL.aggregate(sigs)
        # assert AugSchemeMPL.verify(pubkey, message, aggsig)
        if spend_bundle is None:
            spend_bundle = SpendBundle(list_of_coinspends, aggsig)
        else:
            spend_bundle = spend_bundle.aggregate([spend_bundle, SpendBundle(list_of_coinspends, aggsig)])

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
            name=bytes32(token_bytes()),
            memos=list(compute_memos(spend_bundle).items()),
        )
        await self.wallet_state_manager.add_pending_transaction(did_record)
        new_did_info = DIDInfo(
            self.did_info.origin_coin,
            self.did_info.backup_ids,
            self.did_info.num_of_backup_ids_needed,
            self.did_info.parent_info,
            self.did_info.current_inner,
            self.did_info.temp_coin,
            self.did_info.temp_puzhash,
            self.did_info.temp_pubkey,
            True,
            self.did_info.metadata,
        )
        await self.save_info(new_did_info)
        return spend_bundle

    async def get_new_p2_inner_hash(self) -> bytes32:
        puzzle = await self.get_new_p2_inner_puzzle()
        return puzzle.get_tree_hash()

    async def get_new_p2_inner_puzzle(self) -> Program:
        return await self.standard_wallet.get_new_puzzle()

    async def get_new_did_innerpuz(self, origin_id=None) -> Program:
        if self.did_info.origin_coin is not None:
            innerpuz = did_wallet_puzzles.create_innerpuz(
                await self.get_new_p2_inner_puzzle(),
                self.did_info.backup_ids,
                uint64(self.did_info.num_of_backup_ids_needed),
                self.did_info.origin_coin.name(),
                did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
            )
        elif origin_id is not None:
            innerpuz = did_wallet_puzzles.create_innerpuz(
                await self.get_new_p2_inner_puzzle(),
                self.did_info.backup_ids,
                uint64(self.did_info.num_of_backup_ids_needed),
                origin_id,
                did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
            )
        else:
            raise ValueError("must have origin coin")

        return innerpuz

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
            puzzle_for_pk(pubkey),
            self.did_info.backup_ids,
            uint64(self.did_info.num_of_backup_ids_needed),
            self.did_info.origin_coin.name(),
            did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
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
            puzzle_for_pk(record.pubkey),
            self.did_info.backup_ids,
            self.did_info.num_of_backup_ids_needed,
            self.did_info.origin_coin.name(),
            did_wallet_puzzles.metadata_to_program(json.loads(self.did_info.metadata)),
            old_recovery_list_hash,
        )
        return inner_puzzle

    def get_parent_for_coin(self, coin) -> Optional[LineageProof]:
        parent_info = None
        for name, ccparent in self.did_info.parent_info:
            if name == coin.parent_coin_info:
                parent_info = ccparent

        return parent_info

    async def sign_message(self, message: str) -> Tuple[G1Element, G2Element]:
        if self.did_info.current_inner is None:
            raise ValueError("Missing DID inner puzzle.")
        puzzle_args = did_wallet_puzzles.uncurry_innerpuz(self.did_info.current_inner)
        if puzzle_args is not None:

            p2_puzzle, _, _, _, _ = puzzle_args
            puzzle_hash = p2_puzzle.get_tree_hash()
            pubkey, private = await self.wallet_state_manager.get_keys(puzzle_hash)
            synthetic_secret_key = calculate_synthetic_secret_key(private, DEFAULT_HIDDEN_PUZZLE_HASH)
            synthetic_pk = synthetic_secret_key.get_g1()
            puzzle: Program = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, message))
            return synthetic_pk, AugSchemeMPL.sign(synthetic_secret_key, puzzle.get_tree_hash())
        else:
            raise ValueError("Invalid inner DID puzzle.")

    async def sign(self, spend_bundle: SpendBundle) -> SpendBundle:
        sigs: List[G2Element] = []
        for spend in spend_bundle.coin_spends:

            puzzle_args = did_wallet_puzzles.match_did_puzzle(*spend.puzzle_reveal.to_program().uncurry())
            if puzzle_args is not None:
                p2_puzzle, _, _, _, _ = puzzle_args
                puzzle_hash = p2_puzzle.get_tree_hash()
                pubkey, private = await self.wallet_state_manager.get_keys(puzzle_hash)
                synthetic_secret_key = calculate_synthetic_secret_key(private, DEFAULT_HIDDEN_PUZZLE_HASH)
                error, conditions, cost = conditions_dict_for_solution(
                    spend.puzzle_reveal.to_program(),
                    spend.solution.to_program(),
                    self.wallet_state_manager.constants.MAX_BLOCK_COST_CLVM,
                )

                if conditions is not None:
                    synthetic_pk = synthetic_secret_key.get_g1()
                    for pk, msg in pkm_pairs_for_conditions_dict(
                        conditions, spend.coin.name(), self.wallet_state_manager.constants.AGG_SIG_ME_ADDITIONAL_DATA
                    ):
                        try:
                            assert bytes(synthetic_pk) == pk
                            sigs.append(AugSchemeMPL.sign(synthetic_secret_key, msg))
                        except AssertionError:
                            raise ValueError("This spend bundle cannot be signed by the DID wallet")

        agg_sig = AugSchemeMPL.aggregate(sigs)
        return SpendBundle.aggregate([spend_bundle, SpendBundle([], agg_sig)])

    async def generate_new_decentralised_id(self, amount: uint64, fee: uint64 = uint64(0)) -> Optional[SpendBundle]:
        """
        This must be called under the wallet state manager lock
        """

        coins = await self.standard_wallet.select_coins(uint64(amount + fee))
        if coins is None:
            return None

        origin = coins.copy().pop()
        genesis_launcher_puz = did_wallet_puzzles.LAUNCHER_PUZZLE
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), amount)

        did_inner: Program = await self.get_new_did_innerpuz(launcher_coin.name())
        did_inner_hash = did_inner.get_tree_hash()
        did_full_puz = did_wallet_puzzles.create_fullpuz(did_inner, launcher_coin.name())
        did_puzzle_hash = did_full_puz.get_tree_hash()

        announcement_set: Set[Announcement] = set()
        announcement_message = Program.to([did_puzzle_hash, amount, bytes(0x80)]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message))

        tx_record: Optional[TransactionRecord] = await self.standard_wallet.generate_signed_transaction(
            amount, genesis_launcher_puz.get_tree_hash(), fee, origin.name(), coins, None, False, announcement_set
        )

        genesis_launcher_solution = Program.to([did_puzzle_hash, amount, bytes(0x80)])

        launcher_cs = CoinSpend(launcher_coin, genesis_launcher_puz, genesis_launcher_solution)
        launcher_sb = SpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))
        eve_coin = Coin(launcher_coin.name(), did_puzzle_hash, amount)
        future_parent = LineageProof(
            eve_coin.parent_coin_info,
            did_inner_hash,
            uint64(eve_coin.amount),
        )
        eve_parent = LineageProof(
            launcher_coin.parent_coin_info,
            launcher_coin.puzzle_hash,
            uint64(launcher_coin.amount),
        )
        await self.add_parent(eve_coin.parent_coin_info, eve_parent)
        await self.add_parent(eve_coin.name(), future_parent)

        if tx_record is None or tx_record.spend_bundle is None:
            return None

        # Only want to save this information if the transaction is valid
        did_info: DIDInfo = DIDInfo(
            launcher_coin,
            self.did_info.backup_ids,
            self.did_info.num_of_backup_ids_needed,
            self.did_info.parent_info,
            did_inner,
            None,
            None,
            None,
            False,
            self.did_info.metadata,
        )
        await self.save_info(did_info)
        eve_spend = await self.generate_eve_spend(eve_coin, did_full_puz, did_inner)
        full_spend = SpendBundle.aggregate([tx_record.spend_bundle, eve_spend, launcher_sb])
        assert self.did_info.origin_coin is not None
        assert self.did_info.current_inner is not None

        did_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            amount=uint64(amount),
            to_puzzle_hash=await self.standard_wallet.get_puzzle_hash(False),
            fee_amount=fee,
            confirmed=False,
            sent=uint32(10),
            spend_bundle=full_spend,
            additions=full_spend.additions(),
            removals=full_spend.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.INCOMING_TX.value),
            name=bytes32(token_bytes()),
            memos=[],
        )
        regular_record = dataclasses.replace(tx_record, spend_bundle=None)
        await self.wallet_state_manager.add_pending_transaction(regular_record)
        await self.wallet_state_manager.add_pending_transaction(did_record)
        return full_spend

    async def generate_eve_spend(self, coin: Coin, full_puzzle: Program, innerpuz: Program):
        assert self.did_info.origin_coin is not None
        uncurried = did_wallet_puzzles.uncurry_innerpuz(innerpuz)
        assert uncurried is not None
        p2_puzzle = uncurried[0]
        # innerpuz solution is (mode p2_solution)
        p2_solution = self.standard_wallet.make_solution(
            primaries=[
                {
                    "puzzlehash": innerpuz.get_tree_hash(),
                    "amount": uint64(coin.amount),
                    "memos": [p2_puzzle.get_tree_hash()],
                }
            ]
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
        list_of_coinspends = [CoinSpend(coin, full_puzzle, fullsol)]
        unsigned_spend_bundle = SpendBundle(list_of_coinspends, G2Element())
        return await self.sign(unsigned_spend_bundle)

    async def get_frozen_amount(self) -> uint64:
        return await self.wallet_state_manager.get_frozen_balance(self.wallet_info.id)

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
        did_info: DIDInfo = DIDInfo(
            self.did_info.origin_coin,
            self.did_info.backup_ids,
            self.did_info.num_of_backup_ids_needed,
            current_list,
            self.did_info.current_inner,
            self.did_info.temp_coin,
            self.did_info.temp_puzhash,
            self.did_info.temp_pubkey,
            self.did_info.sent_recovery_transaction,
            self.did_info.metadata,
        )
        await self.save_info(did_info)

    async def update_recovery_list(self, recover_list: List[bytes32], num_of_backup_ids_needed: uint64) -> bool:
        if num_of_backup_ids_needed > len(recover_list):
            return False
        did_info: DIDInfo = DIDInfo(
            self.did_info.origin_coin,
            recover_list,
            num_of_backup_ids_needed,
            self.did_info.parent_info,
            self.did_info.current_inner,
            self.did_info.temp_coin,
            self.did_info.temp_puzhash,
            self.did_info.temp_pubkey,
            self.did_info.sent_recovery_transaction,
            self.did_info.metadata,
        )
        await self.save_info(did_info)
        await self.wallet_state_manager.update_wallet_puzzle_hashes(self.wallet_info.id)
        return True

    async def update_metadata(self, metadata: Dict[str, str]) -> bool:
        did_info: DIDInfo = DIDInfo(
            self.did_info.origin_coin,
            self.did_info.backup_ids,
            self.did_info.num_of_backup_ids_needed,
            self.did_info.parent_info,
            self.did_info.current_inner,
            self.did_info.temp_coin,
            self.did_info.temp_puzhash,
            self.did_info.temp_pubkey,
            self.did_info.sent_recovery_transaction,
            json.dumps(metadata),
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
        did_info: DIDInfo = DIDInfo(
            origin,
            backup_ids,
            num_of_backup_ids_needed,
            [],
            innerpuz,
            None,
            None,
            None,
            True,
            metadata,
        )
        return did_info

    def require_derivation_paths(self) -> bool:
        return True


if TYPE_CHECKING:
    from chia.wallet.wallet_protocol import WalletProtocol

    _dummy: WalletProtocol = DIDWallet()
