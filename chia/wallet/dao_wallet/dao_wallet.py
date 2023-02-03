from __future__ import annotations

import dataclasses
import json
import logging
import re
import time
from secrets import token_bytes
from typing import Any, Dict, List, Optional, Set, Tuple

from blspy import AugSchemeMPL, G1Element, G2Element

import chia.wallet.singleton
from chia.protocols import wallet_protocol
from chia.protocols.wallet_protocol import CoinState
from chia.server.ws_connection import WSChiaConnection
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.wallet import singleton
from chia.wallet.cat_wallet.cat_wallet import CATWallet

# from chia.wallet.cat_wallet.dao_cat_info import LockedCoinInfo
from chia.wallet.cat_wallet.dao_cat_wallet import DAOCATWallet
from chia.wallet.coin_selection import select_coins
from chia.wallet.dao_wallet.dao_info import DAOInfo, ProposalInfo
from chia.wallet.dao_wallet.dao_utils import (
    SINGLETON_LAUNCHER,
    DAO_PROPOSAL_MOD,
    DAO_TREASURY_MOD,
    curry_singleton,
    generate_cat_tail,
    get_cat_tail_hash_from_treasury_puzzle,
    get_new_puzzle_from_treasury_solution,
    get_proposal_puzzle,
    get_treasury_puzzle,
    uncurry_proposal,
    get_finished_state_puzzle,
    get_new_puzzle_from_proposal_solution,
    get_proposal_timer_puzzle,
    uncurry_treasury,
)

# from chia.wallet.dao_wallet.dao_wallet_puzzles import get_dao_inner_puzhash_by_p2
from chia.wallet.derivation_record import DerivationRecord
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_for_pk
from chia.wallet.singleton import (
    get_most_recent_singleton_coin_from_coin_spend,
    get_innerpuzzle_from_puzzle,
    get_singleton_id_from_puzzle,
)
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo


class DAOWallet:
    """
    This is a wallet in the sense that it conforms to the interface needed by WalletStateManager.
    It is not a user-facing wallet. A user cannot spend or receive XCH though a wallet of this type.

    It is expected that a wallet of type DAOCATWallet will be the user-facing wallet, and use a
    DAOWallet for state-tracking of the Treasury Singleton and its associated Proposals.

    State change Spends (spends this user creates, either from DAOWallet or DAOCATWallet:
      * Create a proposal
      * Initial Vote on proposal
      * Add more votes to a proposal
      * Collect finished state of a Proposal - spend to read the oracle result and Get our (CAT) coins back
      * Anyone can send money to the Treasury, whether in possession of a voting CAT or not

    Incoming spends we listen for:
      * Update Treasury state if treasury is spent
      * Hear about a finished proposal
      * Hear about a new proposal -- check interest threshold (how many votes)
      * Get Updated Proposal Data
    """

    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    dao_info: DAOInfo
    standard_wallet: Wallet
    wallet_id: int
    apply_state_transition_call_count: int = 0
    new_peak_call_count: int = 0

    @staticmethod
    async def create_new_dao_and_wallet(
        wallet_state_manager: Any,
        wallet: Wallet,
        amount_of_cats: uint64,
        filter_amount: uint64 = 1,
        name: Optional[str] = None,
        fee: uint64 = uint64(0),
    ) -> DAOWallet:
        """
        Create a brand new DAO wallet
        This must be called under the wallet state manager lock
        :param wallet_state_manager: Wallet state manager
        :param wallet: Standard wallet
        :param amount_of_cats: Initial amount of voting CATs
        :param name: Wallet name
        :param fee: transaction fee
        :return: DAO wallet
        """

        self = DAOWallet()
        self.wallet_state_manager = wallet_state_manager
        if name is None:
            name = self.generate_wallet_name()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)
        std_wallet_id = self.standard_wallet.wallet_id
        bal = await wallet_state_manager.get_confirmed_balance_for_wallet(std_wallet_id)
        if amount_of_cats > bal:
            raise ValueError("Not enough balance")

        self.dao_info = DAOInfo(
            bytes32([0] * 32),
            0,
            0,
            [],
            [],
            None,
            None,
            0,
            filter_amount,
        )
        info_as_string = json.dumps(self.dao_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name, WalletType.DAO.value, info_as_string
        )
        self.wallet_id = self.wallet_info.id
        std_wallet_id = self.standard_wallet.wallet_id
        bal = await wallet_state_manager.get_confirmed_balance_for_wallet(std_wallet_id)

        attendance_required_percentage = uint64(10)
        proposal_pass_percentage = uint64(10)
        proposal_timelock = uint64(10)
        try:
            spend_bundle = await self.generate_new_dao(
                amount_of_cats, attendance_required_percentage, proposal_pass_percentage, proposal_timelock, fee
            )
        except Exception:
            await wallet_state_manager.user_store.delete_wallet(self.id())
            raise

        if spend_bundle is None:
            await wallet_state_manager.user_store.delete_wallet(self.id())
            raise ValueError("Failed to create spend.")
        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)

        # Now the dao wallet is created we can create the dao_cat wallet
        cat_wallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
        cat_tail = cat_wallet.cat_info.limitations_program_hash
        new_dao_cat_wallet = await DAOCATWallet.get_or_create_wallet_for_cat(
            self.wallet_state_manager, self.standard_wallet, cat_tail.hex()
        )
        dao_cat_wallet_id = new_dao_cat_wallet.wallet_info.id
        dao_info = DAOInfo(
            self.dao_info.treasury_id,
            self.dao_info.cat_wallet_id,
            dao_cat_wallet_id,
            self.dao_info.proposals_list,
            self.dao_info.parent_info,
            self.dao_info.current_treasury_coin,
            self.dao_info.current_treasury_innerpuz,
            self.dao_info.singleton_block_height,
            self.dao_info.filter_below_vote_amount,
        )
        await self.save_info(dao_info)

        return self

    @staticmethod
    async def create_new_dao_wallet_for_existing_dao(
        wallet_state_manager: Any,
        wallet: Wallet,
        treasury_id: bytes32,
        filter_amount: uint64 = 1,
        name: Optional[str] = None,
    ):
        """
        Create a DAO wallet for existing DAO
        :param wallet_state_manager: Wallet state manager
        :param wallet: Standard wallet
        :param name: Wallet name
        :return: DAO wallet
        """
        self = DAOWallet()
        self.wallet_state_manager = wallet_state_manager
        if name is None:
            name = self.generate_wallet_name()
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)
        self.log.info("Creating DAO wallet for existent DAO ...")
        self.dao_info = DAOInfo(
            treasury_id,  # treasury_id: bytes32
            0,  # cat_wallet_id: int
            0,  # dao_cat_wallet_id: int
            [],  # proposals_list: List[ProposalInfo]
            [],  # treasury_id: bytes32
            None,  # current_coin
            None,  # current innerpuz
            0,
            filter_amount,
        )
        info_as_string = json.dumps(self.dao_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name, WalletType.DAO.value, info_as_string
        )
        await self.resync_treasury_state()
        await self.wallet_state_manager.add_new_wallet(self, self.wallet_info.id)
        await self.save_info(self.dao_info)

        if self.wallet_info is None:
            raise ValueError("Internal Error")
        self.wallet_id = self.wallet_info.id

        # Now the dao wallet is created we can create the dao_cat wallet
        cat_wallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
        cat_tail = cat_wallet.cat_info.limitations_program_hash
        new_dao_cat_wallet = await DAOCATWallet.get_or_create_wallet_for_cat(
            self.wallet_state_manager, self.standard_wallet, cat_tail.hex()
        )
        dao_cat_wallet_id = new_dao_cat_wallet.wallet_info.id
        dao_info = DAOInfo(
            self.dao_info.treasury_id,
            self.dao_info.cat_wallet_id,
            dao_cat_wallet_id,
            self.dao_info.proposals_list,
            self.dao_info.parent_info,
            self.dao_info.current_treasury_coin,
            self.dao_info.current_treasury_innerpuz,
            self.dao_info.singleton_block_height,
            self.dao_info.filter_below_vote_amount,
        )
        await self.save_info(dao_info)

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
        self = DAOWallet()
        self.log = logging.getLogger(name if name else __name__)
        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = wallet_info
        self.wallet_id = wallet_info.id
        self.standard_wallet = wallet
        self.wallet_info = wallet_info
        self.dao_info = DAOInfo.from_json_dict(json.loads(wallet_info.data))
        self.base_puzzle_program = None
        self.base_inner_puzzle_hash = None
        return self

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.DAO)

    def id(self) -> uint32:
        return self.wallet_info.id

    async def get_confirmed_balance(self, record_list=None) -> uint128:
        # This wallet only tracks coins, and does not hold any spendable value
        return uint128(0)

    async def get_pending_change_balance(self) -> uint64:
        # No spendable or receivable value
        return uint64(0)

    async def get_unconfirmed_balance(self, record_list=None) -> uint128:  # comment
        return await self.wallet_state_manager.get_unconfirmed_balance(self.id(), record_list)

    async def select_coins(
        self,
        amount: uint64,
        exclude: Optional[List[Coin]] = None,
        min_coin_amount: Optional[uint64] = None,
        max_coin_amount: Optional[uint64] = None,
    ) -> Optional[Set[Coin]]:
        """
        Returns a set of coins that can be used for generating a new transaction.
        Note: Must be called under wallet state manager lock
        """

        spendable_amount: uint128 = await self.get_spendable_balance()

        # Only DID Wallet will return none when this happens, so we do it before select_coins would throw an error.
        if amount > spendable_amount:
            self.log.warning(f"Can't select {amount}, from spendable {spendable_amount} for wallet id {self.id()}")
            return None

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
        )
        assert sum(c.amount for c in coins) >= amount
        return coins

    # This will be used in the recovery case where we don't have the parent info already
    async def coin_added(self, coin: Coin, _: uint32, peer: WSChiaConnection):
        """Notification from wallet state manager that wallet has been received."""
        breakpoint()  # TODO: we should be hitting this actually
        self.log.info(f"DAO wallet has been notified that coin was added: {coin.name()}:{coin}")
        inner_puzzle = await self.inner_puzzle_for_did_puzzle(coin.puzzle_hash)
        # TODO: this is wrong and needs changing

        # new_info = DAOInfo(
        #     self.dao_info.origin_coin,
        #     self.dao_info.backup_ids,
        #     self.dao_info.num_of_backup_ids_needed,
        #     self.dao_info.parent_info,
        #     inner_puzzle,
        #     None,
        #     None,
        #     None,
        #     False,
        #     self.dao_info.metadata,
        # )
        # await self.save_info(new_info)

        future_parent = LineageProof(
            coin.parent_coin_info,
            inner_puzzle.get_tree_hash(),
            uint64(coin.amount),
        )

        await self.add_parent(coin.name(), future_parent)
        parent = self.get_parent_for_coin(coin)
        if parent is None:
            parent_state: CoinState = (
                await self.wallet_state_manager.wallet_node.get_coin_state([coin.parent_coin_info], peer=peer)
            )[0]
            assert parent_state.spent_height is not None
            puzzle_solution_request = wallet_protocol.RequestPuzzleSolution(
                coin.parent_coin_info, uint32(parent_state.spent_height)
            )
            response = await peer.request_puzzle_solution(puzzle_solution_request)
            req_puz_sol = response.response
            assert req_puz_sol.puzzle is not None
            parent_innerpuz = singleton.get_innerpuzzle_from_puzzle(req_puz_sol.puzzle.to_program())
            assert parent_innerpuz is not None
            parent_info = LineageProof(
                parent_state.coin.parent_coin_info,
                parent_innerpuz.get_tree_hash(),
                uint64(parent_state.coin.amount),
            )
            await self.add_parent(coin.parent_coin_info, parent_info)

    async def is_spend_retrievable(self, coin_id):
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer: WSChiaConnection = wallet_node.get_full_node_peer()
        children = await wallet_node.fetch_children(coin_id, peer)
        return len(children) > 0

    def get_cat_tail_hash(self) -> bytes32:
        cat_wallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
        cat_tail_hash = cat_wallet.cat_info.limitations_program_hash
        return cat_tail_hash

    async def resync_treasury_state(self):
        parent_coin_id: bytes32 = self.dao_info.treasury_id
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer: WSChiaConnection = wallet_node.get_full_node_peer()
        if peer is None:
            raise ValueError("Could not find any peers to request puzzle and solution from")

        children = await wallet_node.fetch_children(parent_coin_id, peer)
        parent_coin = None
        parent_parent_coin = None
        assert len(children) > 0
        while len(children) > 0:
            children = await wallet_node.fetch_children(parent_coin_id, peer)
            if len(children) == 0:
                break
            children_state = None
            children_state: CoinState = [child for child in children if child.coin.amount % 2 == 1][0]
            assert children_state is not None
            # breakpoint()
            child_coin = children_state.coin

            #  I don't remember why the below code was originally included in the DID Wallet

            # if children_state.spent_height != children_state.created_height:
            #     dao_info = DAOInfo(
            #         self.dao_info.treasury_id,  # treasury_id: bytes32
            #         self.dao_info.cat_wallet_id,  # cat_wallet_id: int
            #         self.dao_info.proposals_list,  # proposals_list: List[ProposalInfo]
            #         self.dao_info.parent_info,  # treasury_id: bytes32
            #         children,  # current_coin
            #         inner_puz,  # current innerpuz
            #     )
            #
            #     await self.save_info(dao_info)
            #     assert children_state.created_height
            #     cs = await wallet_node.get_coin_state([children[0]], peer)
            #     parent_coin = cs[0].coin
            #     parent_spend = await wallet_node.fetch_puzzle_solution(children_state.created_height, parent_coin, peer)
            #     assert parent_spend is not None
            #     parent_innerpuz = chia.wallet.singleton.get_innerpuzzle_from_puzzle(
            #         parent_spend.puzzle_reveal.to_program()
            #     )
            #     assert parent_innerpuz is not None
            #     parent_info = LineageProof(
            #         parent_coin.parent_coin_info,
            #         parent_innerpuz.get_tree_hash(),
            #         uint64(parent_coin.amount),
            #     )
            #     await self.add_parent(child_coin.parent_coin_info, parent_info)
            if parent_coin is not None:
                parent_parent_coin = parent_coin
            parent_coin = child_coin
            parent_coin_id = child_coin.name()

        # get lineage proof of parent spend, and also current innerpuz
        assert children_state.created_height
        parent_spend = await wallet_node.fetch_puzzle_solution(children_state.created_height, parent_parent_coin, peer)
        assert parent_spend is not None
        parent_inner_puz = chia.wallet.singleton.get_innerpuzzle_from_puzzle(parent_spend.puzzle_reveal.to_program())
        if parent_spend.puzzle_reveal.get_tree_hash() == child_coin.puzzle_hash:
            current_inner_puz = parent_inner_puz
        else:
            inner_solution = parent_spend.solution.to_program().rest().rest().first()
            current_inner_puz = get_new_puzzle_from_treasury_solution(parent_inner_puz, inner_solution)

        current_lineage_proof = LineageProof(
            parent_parent_coin.parent_coin_info, parent_inner_puz.get_tree_hash(), parent_parent_coin.amount  # ...
        )
        await self.add_parent(parent_parent_coin.name(), current_lineage_proof)

        # if nonexistent, then create one
        cat_tail_hash = get_cat_tail_hash_from_treasury_puzzle(parent_inner_puz)
        cat_wallet = None

        # Get or create a cat wallet
        for wallet_id in self.wallet_state_manager.wallets:
            wallet = self.wallet_state_manager.wallets[wallet_id]
            if wallet.type() == WalletType.CAT:
                assert isinstance(wallet, CATWallet)
                if wallet.cat_info.limitations_program_hash == cat_tail_hash:
                    cat_wallet = wallet
                    break
        else:
            # Didn't find a cat wallet, so create one
            cat_wallet = await CATWallet.get_or_create_wallet_for_cat(
                self.wallet_state_manager, self.standard_wallet, cat_tail_hash.hex()
            )

        assert cat_wallet is not None
        cat_wallet_id = cat_wallet.wallet_info.id

        dao_info = DAOInfo(
            self.dao_info.treasury_id,  # treasury_id: bytes32
            cat_wallet_id,  # cat_wallet_id: int
            0,  # dao_wallet_id: int
            self.dao_info.proposals_list,  # proposals_list: List[ProposalInfo]
            self.dao_info.parent_info,  # treasury_id: bytes32
            child_coin,  # current_coin
            current_inner_puz,  # current innerpuz
            self.dao_info.singleton_block_height,
            self.dao_info.filter_below_vote_amount,
        )

        future_parent = LineageProof(
            child_coin.parent_coin_info,
            dao_info.current_treasury_innerpuz.get_tree_hash(),
            uint64(child_coin.amount),
        )
        await self.add_parent(child_coin.name(), future_parent)

        await self.save_info(dao_info)
        assert self.dao_info.parent_info is not None
        return

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
        return Program.to(0)

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> Program:
        return Program.to(0).get_tree_hash()

    async def get_new_puzzle(self) -> Program:
        return self.puzzle_for_pk(
            (await self.wallet_state_manager.get_unused_derivation_record(self.wallet_info.id)).pubkey
        )

    async def set_name(self, new_name: str):
        import dataclasses

        new_info = dataclasses.replace(self.wallet_info, name=new_name)
        self.wallet_info = new_info
        await self.wallet_state_manager.user_store.update_wallet(self.wallet_info)

    async def get_name(self):
        return self.wallet_info.name

    async def get_new_p2_inner_hash(self) -> bytes32:
        puzzle = await self.get_new_p2_inner_puzzle()
        return puzzle.get_tree_hash()

    async def get_new_p2_inner_puzzle(self) -> Program:
        return await self.standard_wallet.get_new_puzzle()

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
        assert self.dao_info.origin_coin is not None
        return singleton.create_innerpuz(
            puzzle_for_pk(pubkey),
            self.dao_info.backup_ids,
            uint64(self.dao_info.num_of_backup_ids_needed),
            self.dao_info.origin_coin.name(),
            singleton.metadata_to_program(json.loads(self.dao_info.metadata)),
        )

    async def inner_puzzle_for_did_puzzle(self, did_hash: bytes32) -> Program:
        record: DerivationRecord = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(
            did_hash
        )
        assert self.dao_info.origin_coin is not None
        inner_puzzle: Program = singleton.create_innerpuz(
            puzzle_for_pk(record.pubkey),
            self.dao_info.backup_ids,
            self.dao_info.num_of_backup_ids_needed,
            self.dao_info.origin_coin.name(),
            singleton.metadata_to_program(json.loads(self.dao_info.metadata)),
        )
        return inner_puzzle

    def get_parent_for_coin(self, coin) -> Optional[LineageProof]:
        parent_info = None
        for name, ccparent in self.dao_info.parent_info:
            if name == coin.parent_coin_info:
                parent_info = ccparent

        return parent_info

    async def generate_new_dao(
        self,
        amount_of_cats: uint64,
        attendance_required_percentage: uint64,
        proposal_pass_percentage: uint64,  # reminder that this is between 0 - 10,000
        proposal_timelock: uint64,
        fee: uint64 = uint64(0),
    ) -> Optional[SpendBundle]:
        """
        This must be called under the wallet state manager lock
        """

        if proposal_pass_percentage > 10000 or proposal_pass_percentage < 0:
            raise ValueError("proposal pass percentage must be between 0 and 10000")

        coins = await self.standard_wallet.select_coins(uint64(fee + 1))
        if coins is None:
            return None
        # origin is normal coin which creates launcher coin
        origin = coins.copy().pop()

        different_coins = await self.standard_wallet.select_coins(uint64(amount_of_cats), exclude=[origin])
        cat_origin = different_coins.copy().pop()

        assert origin.name() != cat_origin.name()
        genesis_launcher_puz = SINGLETON_LAUNCHER
        # launcher coin contains singleton launcher, launcher coin ID == singleton_id == treasury_id
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), 1)

        cat_wallet = None
        cat_tail_hash = None
        if self.dao_info.cat_wallet_id is None:
            cat_wallet = await self.wallet_state_manager.user_store.get_wallet_by_id(self.dao_info.cat_wallet_id)
            if cat_wallet is not None:
                cat_tail_hash = cat_wallet.cat_info.limitations_program_hash
        if cat_tail_hash is None:
            cat_tail_hash = generate_cat_tail(cat_origin.name(), launcher_coin.name()).get_tree_hash()

        assert cat_tail_hash is not None
        cat_tail_info = {
            "identifier": "genesis_by_id_or_proposal",
            "treasury_id": launcher_coin.name(),
            "coins": different_coins,
        }

        dao_info: DAOInfo = DAOInfo(
            launcher_coin.name(),
            self.dao_info.cat_wallet_id,
            self.dao_info.dao_cat_wallet_id,
            self.dao_info.proposals_list,
            self.dao_info.parent_info,
            None,
            None,
            0,
            self.dao_info.filter_below_vote_amount,
        )
        await self.save_info(dao_info)

        # This will also mint the coins
        new_cat_wallet = await CATWallet.create_new_cat_wallet(
            self.wallet_state_manager,
            self.standard_wallet,
            cat_tail_info,
            amount_of_cats,
        )
        assert new_cat_wallet is not None

        cat_wallet_id = new_cat_wallet.wallet_info.id

        dao_info = DAOInfo(
            self.dao_info.treasury_id,
            cat_wallet_id,
            self.dao_info.dao_cat_wallet_id,
            self.dao_info.proposals_list,
            self.dao_info.parent_info,
            None,
            None,
            0,
            self.dao_info.filter_below_vote_amount,
        )

        await self.save_info(dao_info)

        dao_treasury_puzzle = get_treasury_puzzle(
            launcher_coin.name(),
            cat_tail_hash,
            amount_of_cats,
            attendance_required_percentage,
            proposal_pass_percentage,
            proposal_timelock,
        )

        full_treasury_puzzle = curry_singleton(launcher_coin.name(), dao_treasury_puzzle)
        full_treasury_puzzle_hash = full_treasury_puzzle.get_tree_hash()

        announcement_set: Set[Announcement] = set()
        announcement_message = Program.to([full_treasury_puzzle_hash, 1, bytes(0x80)]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message))

        tx_record: Optional[TransactionRecord] = await self.standard_wallet.generate_signed_transaction(
            uint64(1), genesis_launcher_puz.get_tree_hash(), fee, origin.name(), coins, None, False, announcement_set
        )

        genesis_launcher_solution = Program.to([full_treasury_puzzle_hash, 1, bytes(0x80)])

        launcher_cs = CoinSpend(launcher_coin, genesis_launcher_puz, genesis_launcher_solution)
        launcher_sb = SpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))
        eve_coin = Coin(launcher_coin.name(), full_treasury_puzzle_hash, 1)
        future_parent = LineageProof(
            eve_coin.parent_coin_info,
            dao_treasury_puzzle.get_tree_hash(),
            uint64(eve_coin.amount),
        )
        eve_parent = LineageProof(
            bytes32(launcher_coin.parent_coin_info),
            bytes32(launcher_coin.puzzle_hash),
            uint64(launcher_coin.amount),
        )
        await self.add_parent(bytes32(eve_coin.parent_coin_info), eve_parent)
        await self.add_parent(eve_coin.name(), future_parent)

        if tx_record is None or tx_record.spend_bundle is None:
            return None

        eve_spend = await self.generate_treasury_eve_spend(
            eve_coin,
            full_treasury_puzzle,
            dao_treasury_puzzle,
            launcher_coin,
        )

        full_spend = SpendBundle.aggregate([tx_record.spend_bundle, eve_spend, launcher_sb])

        # assert self.dao_info.origin_coin is not None
        # assert self.dao_info.current_inner is not None

        treasury_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=dao_treasury_puzzle.get_tree_hash(),  # Should this be full_treasury_puzzle_hash?
            # MH: I don't think so, the CAT Wallet doesn't include the CAT Layer
            amount=uint64(1),
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
        await self.wallet_state_manager.add_pending_transaction(treasury_record)
        await self.wallet_state_manager.add_interested_puzzle_hashes([launcher_coin.name()], [self.id()])
        current_coin = Coin(eve_coin.name(), full_treasury_puzzle.get_tree_hash(), eve_coin.amount)
        await self.wallet_state_manager.add_interested_coin_ids([current_coin.name()])
        await self.wallet_state_manager.add_interested_coin_ids([launcher_coin.name()])
        dao_info = DAOInfo(
            self.dao_info.treasury_id,
            cat_wallet_id,
            self.dao_info.dao_cat_wallet_id,
            self.dao_info.proposals_list,
            self.dao_info.parent_info,
            current_coin,
            dao_treasury_puzzle,
            self.dao_info.singleton_block_height,
            self.dao_info.filter_below_vote_amount,
        )
        await self.save_info(dao_info)
        # breakpoint()
        return full_spend

    async def generate_treasury_eve_spend(
        self, coin: Coin, full_puzzle: Program, innerpuz: Program, origin_coin: Coin
    ) -> SpendBundle:
        inner_sol = Program.to(
            [
                coin.amount,
                0,  # Make a payment with relative change 0, just to spend the coin
                innerpuz.get_tree_hash(),
                [],  # A list of messages which the treasury will parrot - assert from the proposal and also create
                0,  # If this variable is 0 then we do the "add_money" spend case
                0,
            ]
        )
        # full solution is (lineage_proof my_amount inner_solution)
        fullsol = Program.to(
            [
                [origin_coin.parent_coin_info, origin_coin.amount],
                coin.amount,
                inner_sol,
            ]
        )
        list_of_coinspends = [CoinSpend(coin, full_puzzle, fullsol)]
        unsigned_spend_bundle = SpendBundle(list_of_coinspends, G2Element())
        return unsigned_spend_bundle

    async def generate_new_proposal(self, proposed_puzzle_hash, fee):
        coins = await self.standard_wallet.select_coins(uint64(fee + 1))
        if coins is None:
            return None
        # origin is normal coin which creates launcher coin
        origin = coins.copy().pop()
        genesis_launcher_puz = SINGLETON_LAUNCHER
        # launcher coin contains singleton launcher, launcher coin ID == singleton_id == treasury_id
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), 1)
        # MH: do you think we should store the cat tail locally as well?
        cat_wallet = await self.wallet_state_manager.user_store.get_wallet_by_id(self.dao_info.cat_wallet_id)
        cat_tail_hash = cat_wallet.cat_info.my_tail.get_tree_hash()
        dao_proposal_puzzle = get_proposal_puzzle(
            launcher_coin.name(),
            cat_tail_hash,
            self.dao_info.treasury_id,
            0,
            0,
            proposed_puzzle_hash,
        )

        full_proposal_puzzle = curry_singleton(launcher_coin.name(), dao_proposal_puzzle)
        full_proposal_puzzle_hash = full_proposal_puzzle.get_tree_hash()

        announcement_set: Set[Announcement] = set()
        announcement_message = Program.to([full_proposal_puzzle_hash, 1, bytes(0x80)]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message))

        tx_record: Optional[TransactionRecord] = await self.standard_wallet.generate_signed_transaction(
            uint64(1), genesis_launcher_puz.get_tree_hash(), fee, origin.name(), coins, None, False, announcement_set
        )

        genesis_launcher_solution = Program.to([full_proposal_puzzle_hash, 1, bytes(0x80)])

        launcher_cs = CoinSpend(launcher_coin, genesis_launcher_puz, genesis_launcher_solution)
        launcher_sb = SpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))
        eve_coin = Coin(launcher_coin.name(), full_proposal_puzzle_hash, 1)

        future_parent = LineageProof(
            eve_coin.parent_coin_info,
            dao_proposal_puzzle.get_tree_hash(),
            uint64(eve_coin.amount),
        )
        eve_parent = LineageProof(
            bytes32(launcher_coin.parent_coin_info),
            bytes32(launcher_coin.puzzle_hash),
            uint64(launcher_coin.amount),
        )

        await self.add_parent(bytes32(eve_coin.parent_coin_info), eve_parent)
        await self.add_parent(eve_coin.name(), future_parent)

        eve_spend = await self.generate_proposal_eve_spend(
            eve_coin,
            full_proposal_puzzle,
            dao_proposal_puzzle,
            launcher_coin,
        )
        full_spend = SpendBundle.aggregate([tx_record.spend_bundle, eve_spend, launcher_sb])
        return full_spend

    async def get_proposal_curry_values(self, proposal_id: bytes32) -> Tuple[Program, Program, Program]:
        # The proposal_curry_vals used by the dao_lockup puzzle are the following.
        # We only need to return the bottom 3, I believe
        # (
        #   TREASURY_MOD_HASH
        #   PROPOSAL_TIMER_MOD_HASH
        #   TREASURY_ID
        #   YES_VOTES
        #   TOTAL_VOTES
        #   INNERPUZHASH
        # )
        curried_args = None
        for prop in self.dao_info.proposals_list:
            if prop.proposal_id == proposal_id:
                curried_args = uncurry_proposal(prop.inner_puzzle)
                break

        assert curried_args is not None
        (
            SINGLETON_STRUCT,  # (SINGLETON_MOD_HASH, (SINGLETON_ID, LAUNCHER_PUZZLE_HASH))
            PROPOSAL_MOD_HASH,
            PROPOSAL_TIMER_MOD_HASH,
            CAT_MOD_HASH,
            TREASURY_MOD_HASH,
            LOCKUP_MOD_HASH,
            CAT_TAIL_HASH,
            TREASURY_ID,
            YES_VOTES,  # yes votes are +1, no votes don't tally - we compare yes_votes/total_votes at the end
            TOTAL_VOTES,  # how many people responded
            INNERPUZ,
        ) = curried_args
        return YES_VOTES, TOTAL_VOTES, INNERPUZ

    # TODO: add an amount of dao_cat to spend on voting on the new proposal here
    async def generate_proposal_eve_spend(
        self,
        eve_coin: Coin,
        full_proposal_puzzle: Program,
        dao_proposal_puzzle: Program,
        launcher_coin: Coin,
    ) -> SpendBundle:

        # TODO: connect with DAO CAT Wallet here

        # vote_amount_or_solution  ; The qty of "votes" to add or subtract. ALWAYS POSITIVE.
        # vote_info_or_p2_singleton_mod_hash
        # vote_coin_id_or_current_cat_issuance  ; this is either the coin ID we're taking a vote from
        # previous_votes  ; set this to 0 if we have passed
        # lockup_innerpuzhash_or_attendance_required  ; this is either the innerpuz of the locked up CAT we're taking a vote from
        inner_sol = Program.to([])
        # full solution is (lineage_proof my_amount inner_solution)
        fullsol = Program.to(
            [
                [eve_coin.parent_coin_info, launcher_coin.amount],
                eve_coin.amount,
                inner_sol,
            ]
        )
        list_of_coinspends = [CoinSpend(eve_coin, full_proposal_puzzle, fullsol)]
        unsigned_spend_bundle = SpendBundle(list_of_coinspends, G2Element())
        return unsigned_spend_bundle

    async def generate_proposal_vote_spend(
        self,
        proposal_id: bytes32,
        vote_amounts_list: List[uint64],
        voting_coin_id_list: List[bytes32],
        previous_votes_list: List[Program],
        lockup_innerpuz_list: List[Program],
        is_yes_vote: bool,
    ):
        proposal_info = None
        for prop in self.dao_info.proposals_list:
            if prop.proposal_id == proposal_id:
                proposal_info = prop
                break
        assert proposal_info is not None
        # vote_amount_or_solution  ; The qty of "votes" to add or subtract. ALWAYS POSITIVE.
        # vote_info_or_p2_singleton_mod_hash ; vote_info is whether we are voting YES or NO. XXX rename vote_type?
        # vote_coin_id_or_current_cat_issuance  ; this is either the coin ID we're taking a vote from OR...
        #                                     ; the total number of CATs in circulation according to the treasury
        # previous_votes_or_pass_margin  ; this is the active votes of the lockup we're communicating with
        #                              ; OR this is what percentage of the total votes must be YES - represented as an integer from 0 to 10,000 - typically this is set at 5100 (51%)
        # lockup_innerpuzhash_or_attendance_required  ; this is either the innerpuz of the locked up CAT we're taking a vote from OR
        #                                           ; the attendance required - the percentage of the current issuance which must have voted represented as 0 to 10,000 - this is announced by the treasury
        # proposal_timelock  ; we assert this from the treasury and announce it, so the timer knows what the the current timelock is
        #                  ; we only use this when closing out so set it to 0 and we will do the vote spend case

        # TODO: fill this in when we can take a list of coins in dao_proposal.clvm
        voting_info = 0
        if is_yes_vote:
            voting_info = 1

        inner_sol = Program.to(
            [
                vote_amounts_list,
                voting_info,
                voting_coin_id_list,
                previous_votes_list,
                lockup_innerpuz_list,
                0,
            ]
        )

        return

    async def create_add_money_to_treasury_spend(self, amount: uint64, fee: uint64 = uint64(0)) -> Optional[TransactionRecord]:
        # make sure we're generating an odd output amount
        if amount + self.dao_info.current_treasury_coin.amount % 2 == 0:
            amount -= 1
        new_amount_change = amount
        new_amount_total = amount + self.dao_info.current_treasury_coin.amount

        # get the treasury puzzle and check that it matches out current coin
        full_treasury_puzzle = curry_singleton(self.dao_info.treasury_id, self.dao_info.current_treasury_innerpuz)
        full_treasury_puzzle_hash = full_treasury_puzzle.get_tree_hash()
        assert full_treasury_puzzle_hash == self.dao_info.current_treasury_coin.puzzle_hash

        # Create the treasury solution for our new amount
        inner_sol = Program.to(
            [
                self.dao_info.current_treasury_coin.amount,
                new_amount_change,
                self.dao_info.current_treasury_innerpuz.get_tree_hash(),
                [],  # Announcement_messages
                0,  # do the "add_money" spend case
                0,
            ]
        )
        lineage_proof = [info[1] for info in self.dao_info.parent_info if info[0] == self.dao_info.current_treasury_coin.parent_coin_info][0]
        fullsol = Program.to(
            [
                lineage_proof.to_program(),
                self.dao_info.current_treasury_coin.amount,
                inner_sol,
            ]
        )
        treasury_coin_spend = CoinSpend(self.dao_info.current_treasury_coin, full_treasury_puzzle, fullsol)
        treasury_sb = SpendBundle([treasury_coin_spend], G2Element())

        # Create the puzzle announcement and xch spend
        announcement_set: Set[Announcement] = set()
        announcement_message = Program.to([new_amount_change, 0]).get_tree_hash()
        announcement_set.add(Announcement(self.dao_info.current_treasury_coin.puzzle_hash, announcement_message).name())

        xch_sb = await self.standard_wallet.create_spend_bundle_relative_chia(-new_amount_change, fee=fee, puzzle_announcements_to_assert=announcement_set)

        full_spend = SpendBundle.aggregate([treasury_sb, xch_sb])

        treasury_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=self.dao_info.current_treasury_innerpuz.get_tree_hash(),
            amount=uint64(new_amount_change),
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
        await self.wallet_state_manager.add_pending_transaction(treasury_record)

        # Update dao_info with the new coin
        current_coin = Coin(self.dao_info.current_treasury_coin.name(), full_treasury_puzzle.get_tree_hash(), new_amount_total)
        await self.wallet_state_manager.add_interested_coin_ids([current_coin.name()])

        # MH: We should do this on receiving the coin instead of sending the spend incase our spend doesn't go through
        # dao_info = DAOInfo(
        #     self.dao_info.treasury_id,
        #     self.dao_info.cat_wallet_id,
        #     self.dao_info.dao_cat_wallet_id,
        #     self.dao_info.proposals_list,
        #     self.dao_info.parent_info,
        #     current_coin,
        #     self.dao_info.current_treasury_innerpuz,
        #     self.dao_info.singleton_block_height,
        #     self.dao_info.filter_below_vote_amount,
        # )
        # await self.save_info(dao_info)

        return treasury_record

    async def get_frozen_amount(self) -> uint64:
        return uint64(0)

    async def get_spendable_balance(self, unspent_records: Set[WalletCoinRecord] = None) -> uint128:
        return uint128(0)

    async def get_max_send_amount(self, records: Set[WalletCoinRecord] = None) -> uint128:
        return uint128(0)

    async def add_parent(self, name: bytes32, parent: Optional[LineageProof]) -> None:
        self.log.info(f"Adding parent {name}: {parent}")
        current_list = self.dao_info.parent_info.copy()
        current_list.append((name, parent))
        dao_info: DAOInfo = DAOInfo(
            self.dao_info.treasury_id,
            self.dao_info.cat_wallet_id,
            self.dao_info.dao_cat_wallet_id,
            self.dao_info.proposals_list,
            current_list,
            self.dao_info.current_treasury_coin,
            self.dao_info.current_treasury_innerpuz,
            self.dao_info.singleton_block_height,
            self.dao_info.filter_below_vote_amount,
        )
        await self.save_info(dao_info)

    async def save_info(self, dao_info: DAOInfo) -> None:
        self.dao_info = dao_info
        current_info = self.wallet_info
        data_str = json.dumps(dao_info.to_json_dict())
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
            if wallet.type() == WalletType.DAO:
                matched = re.search(r"^Profile (\d+)$", wallet.wallet_info.name)
                if matched and int(matched.group(1)) > max_num:
                    max_num = int(matched.group(1))
        return f"Profile {max_num + 1}"

    def require_derivation_paths(self) -> bool:
        return True

    def get_cat_wallet_id(self) -> uint64:
        return self.dao_info.cat_wallet_id

    async def create_new_dao_cats(self, amount: uint64):
        # check there are enough cats to convert
        cat_wallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
        cat_balance = await cat_wallet.get_spendable_balance()
        if cat_balance < amount:
            raise ValueError(f"Insufficient CAT balance. Requested: {amount} Available: {cat_balance}")
        # get the lockup puzzle hash
        dao_cat_wallet = self.wallet_state_manager.wallets[self.dao_info.dao_cat_wallet_id]
        lockup_puzzle_hash = await dao_cat_wallet.get_new_puzzlehash()

        # create the cat spend
        txs = await cat_wallet.generate_signed_transaction([amount], [lockup_puzzle_hash])
        for tx in txs:
            await self.wallet_state_manager.add_pending_transaction(tx)
        return txs

    @staticmethod
    def get_next_interesting_coin(spend: CoinSpend) -> Optional[Coin]:
        # CoinSpend of one of the coins that we cared about. This coin was spent in a block, but might be in a reorg
        # If we return a value, it is a coin that we are also interested in (to support two transitions per block)
        return get_most_recent_singleton_coin_from_coin_spend(spend)

    async def get_tip(self) -> Tuple[uint32, CoinSpend]:
        return (await self.wallet_state_manager.pool_store.get_spends_for_wallet(self.wallet_id))[-1]

    async def add_or_update_proposal_info(
        self,
        new_state: CoinSpend,
        block_height: uint32,
    ):
        new_dao_info = self.dao_info.copy()
        puzzle = get_innerpuzzle_from_puzzle(new_state.puzzle_reveal)
        solution = new_state.solution.rest().rest().first()  # get proposal solution from full singleton solution
        singleton_id = singleton.get_singleton_id_from_puzzle(new_state.puzzle_reveal)
        YES_VOTES, TOTAL_VOTES, INNERPUZ = self.get_proposal_curry_values(puzzle)  # not sure if we're going to use this
        if TOTAL_VOTES < self.dao_info.filter_below_vote_amount:
            return  # ignore all proposals below the filter amount
        current_coin = get_most_recent_singleton_coin_from_coin_spend(new_state)
        ended = False
        timer_coin = None
        if solution.rest().rest().rest().rest().rest().first() == Program.to(0):
            current_innerpuz = get_new_puzzle_from_proposal_solution(puzzle, solution)
            # TODO: find timer coin
        else:
            # If we have entered the finished state
            # TODO: we need to alert the user that they can free up their coins
            current_innerpuz = get_finished_state_puzzle(singleton_id)
            ended = True

        index = 0
        for current_info in new_dao_info.proposals_list:
            # Search for current proposal_info
            if current_info.proposal_id == singleton_id:
                # If we are receiving a voting spend update
                if current_info.singleton_block_height <= block_height:
                    # TODO: what do we do here?
                    print()
                else:
                    new_proposal_info = ProposalInfo(
                        singleton_id,
                        puzzle,
                        current_info.amount_voted,
                        current_info.is_yes_vote,
                        current_coin,
                        current_innerpuz,
                        current_info.timer_coin,
                        block_height,
                    )
                    new_dao_info.proposals_list[index] = new_proposal_info
                    await self.save_info(new_dao_info)
                    return
            index = index + 1

            # Search for the timer coin
            if not ended:
                wallet_node: Any = self.wallet_state_manager.wallet_node
                peer: WSChiaConnection = wallet_node.get_full_node_peer()
                if peer is None:
                    raise ValueError("Could not find any peers to request puzzle and solution from")
                children = await wallet_node.fetch_children(singleton_id, peer)
                assert len(children) > 0
                found = False
                parent_coin_id = singleton_id

                treasury_args = uncurry_treasury(self.dao_info.current_treasury_innerpuz)
                (
                    singleton_struct,
                    DAO_TREASURY_MOD_HASH,
                    DAO_PROPOSAL_MOD_HASH,
                    DAO_PROPOSAL_TIMER_MOD_HASH,
                    DAO_LOCKUP_MOD_HASH,
                    CAT_MOD_HASH,
                    cat_tail_hash,
                    current_cat_issuance,
                    attendance_required_percentage,
                    proposal_pass_percentage,
                    proposal_timelock,
                ) = treasury_args

                timer_coin_puzhash = get_proposal_timer_puzzle(
                    cat_tail_hash.as_atom(),
                    singleton_id,
                    singleton_struct.rest().first().as_atom(),
                ).get_tree_hash()

                while not found and len(children) > 0:
                    children = await wallet_node.fetch_children(parent_coin_id, peer)
                    if len(children) == 0:
                        break
                    children_state = None
                    children_state: CoinState = [child for child in children if child.coin.amount % 2 == 1][0]
                    assert children_state is not None
                    for child in children:
                        if children.coin.puzzle_hash == timer_coin_puzhash:
                            found = True
                            timer_coin = children.coin
                            break
                    child_coin = children_state.coin
                    parent_coin_id = child_coin.name()

        # If we reach here then we don't currently know about this coin
        new_proposal_info = ProposalInfo(
            singleton_id,
            puzzle,
            0,  # assume we haven't voted any if we don't already know about this
            None,
            current_coin,
            current_innerpuz,
            timer_coin,  # if this is None then the proposal has finished
            block_height,  # block height that current proposal singleton coin was created in
        )
        new_dao_info.proposals_list.append(new_proposal_info)
        await self.save_info(new_dao_info)
        future_parent = LineageProof(
            new_state.coin.parent_coin_info,
            puzzle.get_tree_hash(),
            uint64(new_state.coin.amount),
        )
        await self.add_parent(new_state.coin.name(), future_parent)
        return

    async def update_treasury_info(
        self,
        new_state: CoinSpend,
        block_height: uint32,
    ):
        if self.dao_info.singleton_block_height <= block_height:
            # TODO: what do we do here?
            return
        puzzle = get_innerpuzzle_from_puzzle(new_state.puzzle_reveal)
        solution = new_state.solution.rest().rest().first()  # get proposal solution from full singleton solution
        new_innerpuz = get_new_puzzle_from_treasury_solution(puzzle, solution)
        child_coin = get_most_recent_singleton_coin_from_coin_spend(new_state)
        dao_info = DAOInfo(
            self.dao_info.treasury_id,  # treasury_id: bytes32
            self.dao_info.cat_wallet_id,  # cat_wallet_id: int
            self.dao_info.dao_wallet_id,  # dao_wallet_id: int
            self.dao_info.proposals_list,  # proposals_list: List[ProposalInfo]
            self.dao_info.parent_info,  # treasury_id: bytes32
            child_coin,  # current_coin
            new_innerpuz,  # current innerpuz
            block_height,
            self.dao_info.filter_below_vote_amount,
        )
        await self.save_info(dao_info)
        future_parent = LineageProof(
            new_state.coin.parent_coin_info,
            puzzle.get_tree_hash(),
            uint64(new_state.coin.amount),
        )
        await self.add_parent(new_state.coin.name(), future_parent)
        return

    # TODO: Find a nice way to express interest in more than one singleton.
    #     e.g. def register_singleton_for_wallet()
    async def apply_state_transition(self, new_state: CoinSpend, block_height: uint32) -> bool:
        """
        We are being notified of a singleton state transition. A Singleton has been spent.
        Returns True iff the spend is a valid transition spend for the singleton, False otherwise.
        """
        breakpoint()
        self.apply_state_transition_call_count += 1
        tip: Tuple[uint32, CoinSpend] = await self.get_tip()
        tip_spend = tip[1]

        tip_coin: Optional[Coin] = get_most_recent_singleton_coin_from_coin_spend(tip_spend)
        assert tip_coin is not None
        spent_coin_name: bytes32 = tip_coin.name()

        if spent_coin_name != new_state.coin.name():
            history: List[Tuple[uint32, CoinSpend]] = await self.get_spend_history()
            if new_state.coin.name() in [sp.coin.name() for _, sp in history]:
                self.log.info(f"Already have state transition: {new_state.coin.name().hex()}")
            else:
                self.log.warning(
                    f"Failed to apply state transition. tip: {tip_coin} new_state: {new_state} height {block_height}"
                )
            return False

        # Consume new DAOBlockchainInfo
        # Determine if this is a treasury spend or a proposal spend
        puzzle = get_innerpuzzle_from_puzzle(new_state.puzzle_reveal)
        try:
            mod, curried_args = puzzle.uncurry()
        except ValueError as e:
            self.log.warning("Cannot uncurry puzzle in DAO Wallet: error: %s", e)
            raise e
        if mod == DAO_PROPOSAL_MOD:
            await self.update_treasury_info(new_state, block_height)
        elif mod == DAO_TREASURY_MOD:
            await self.add_or_update_proposal_info(new_state, block_height)
        else:
            raise ValueError(f"Unsupported spend in DAO Wallet: {self.id()}")

        return True

    async def new_peak(self, peak_height: uint64) -> None:
        """
        new_peak is called from the WalletStateManager whenever there is a new peak
        # This is where we can attempt to push spends, check on time locks, etc.
        """
        self.new_peak_call_count += 1

        # Check to see if a proposal timer has expired

        pass
