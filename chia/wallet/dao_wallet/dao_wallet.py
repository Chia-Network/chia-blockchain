from __future__ import annotations

import copy
import dataclasses
import json
import logging
import re
import time
from secrets import token_bytes
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from blspy import AugSchemeMPL, G1Element, G2Element
from clvm.casts import int_from_bytes

import chia.wallet.singleton
from chia.full_node.full_node_api import FullNodeAPI

# from chia.protocols import wallet_protocol
from chia.protocols.wallet_protocol import CoinState, RequestBlockHeader, RespondBlockHeader
from chia.server.ws_connection import WSChiaConnection
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint32, uint64, uint128
from chia.wallet import singleton
from chia.wallet.cat_wallet.cat_utils import SpendableCAT
from chia.wallet.cat_wallet.cat_utils import get_innerpuzzle_from_puzzle as get_innerpuzzle_from_cat_puzzle
from chia.wallet.cat_wallet.cat_utils import unsigned_spend_bundle_for_spendable_cats
from chia.wallet.cat_wallet.cat_wallet import CATWallet

# from chia.wallet.cat_wallet.dao_cat_info import LockedCoinInfo
from chia.wallet.cat_wallet.dao_cat_wallet import DAOCATWallet
from chia.wallet.coin_selection import select_coins
from chia.wallet.dao_wallet.dao_info import DAOInfo, DAORules, ProposalInfo
from chia.wallet.dao_wallet.dao_utils import (
    DAO_FINISHED_STATE,
    DAO_PROPOSAL_MOD,
    DAO_TREASURY_MOD,
    DAO_TREASURY_MOD_HASH,
    SINGLETON_LAUNCHER,
    create_cat_launcher_for_singleton_id,
    curry_singleton,
    generate_cat_tail,
    get_active_votes_from_lockup_puzzle,
    get_asset_id_from_puzzle,
    get_curry_vals_from_proposal_puzzle,
    get_dao_rules_from_update_proposal,
    get_finished_state_puzzle,
    get_innerpuz_from_lockup_puzzle,
    get_new_puzzle_from_proposal_solution,
    get_new_puzzle_from_treasury_solution,
    get_p2_singleton_puzhash,
    get_p2_singleton_puzzle,
    get_proposal_args,
    get_proposal_puzzle,
    get_proposal_timer_puzzle,
    get_proposal_validator,
    get_proposed_puzzle_reveal_from_solution,
    get_spend_p2_singleton_puzzle,
    get_treasury_puzzle,
    get_treasury_rules_from_puzzle,
    get_update_proposal_puzzle,
    singleton_struct_for_id,
    uncurry_proposal,
    uncurry_proposal_validator,
    uncurry_treasury,
)

# from chia.wallet.dao_wallet.dao_wallet_puzzles import get_dao_inner_puzhash_by_p2
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.singleton import (  # get_singleton_id_from_puzzle,
    get_inner_puzzle_from_singleton,
    get_most_recent_singleton_coin_from_coin_spend,
    get_singleton_id_from_puzzle,
)
from chia.wallet.singleton_record import SingletonRecord
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_sync_utils import fetch_coin_spend
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_protocol import WalletProtocol

# from chia.wallet.wallet_state_manager import WalletStateManager

# from chia.wallet.wallet_singleton_store import WalletSingletonStore


class DAOWallet(WalletProtocol):
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
    dao_rules: DAORules
    standard_wallet: Wallet
    wallet_id: uint32

    @staticmethod
    async def create_new_dao_and_wallet(
        wallet_state_manager: Any,
        wallet: Wallet,
        amount_of_cats: uint64,
        dao_rules: DAORules,
        filter_amount: uint64 = uint64(1),
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

        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)
        std_wallet_id = self.standard_wallet.wallet_id
        bal = await wallet_state_manager.get_confirmed_balance_for_wallet(std_wallet_id)
        if amount_of_cats > bal:
            raise ValueError("Not enough balance")

        self.dao_info = DAOInfo(
            bytes32([0] * 32),
            uint32(0),
            uint32(0),
            [],
            [],
            None,
            None,
            uint32(0),
            filter_amount,
            [],
            uint64(0),
        )
        self.dao_rules = dao_rules
        info_as_string = json.dumps(self.dao_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name, WalletType.DAO.value, info_as_string
        )
        self.wallet_id = self.wallet_info.id
        std_wallet_id = self.standard_wallet.wallet_id
        bal = await wallet_state_manager.get_confirmed_balance_for_wallet(std_wallet_id)

        try:
            launcher_spend = await self.generate_new_dao(
                amount_of_cats,
                fee=fee,
            )
        except Exception:
            await wallet_state_manager.user_store.delete_wallet(self.id())
            raise

        if launcher_spend is None:
            await wallet_state_manager.user_store.delete_wallet(self.id())
            raise ValueError("Failed to create spend.")
        await self.wallet_state_manager.add_new_wallet(self)

        # Now the dao wallet is created we can create the dao_cat wallet
        cat_wallet: CATWallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
        cat_tail = cat_wallet.cat_info.limitations_program_hash
        new_dao_cat_wallet = await DAOCATWallet.get_or_create_wallet_for_cat(
            self.wallet_state_manager, self.standard_wallet, cat_tail.hex()
        )
        dao_cat_wallet_id = new_dao_cat_wallet.wallet_info.id
        dao_info = DAOInfo(
            self.dao_info.treasury_id,
            self.dao_info.cat_wallet_id,  # TODO: xxx if this is a local wallet id, we might need to change it.
            dao_cat_wallet_id,  # TODO: xxx if this is a local wallet id, we might need to change it.
            self.dao_info.proposals_list,
            self.dao_info.parent_info,
            self.dao_info.current_treasury_coin,
            self.dao_info.current_treasury_innerpuz,
            self.dao_info.singleton_block_height,
            self.dao_info.filter_below_vote_amount,
            self.dao_info.assets,
            self.dao_info.current_height,
        )
        await self.save_info(dao_info)

        return self

    @staticmethod
    async def create_new_dao_wallet_for_existing_dao(
        wallet_state_manager: Any,
        wallet: Wallet,
        treasury_id: bytes32,
        filter_amount: uint64 = uint64(1),
        name: Optional[str] = None,
    ) -> DAOWallet:
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

        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)
        self.log.info("Creating DAO wallet for existent DAO ...")
        self.dao_info = DAOInfo(
            treasury_id,  # treasury_id: bytes32
            uint32(0),  # cat_wallet_id: uint64
            uint32(0),  # dao_cat_wallet_id: uint64
            [],  # proposals_list: List[ProposalInfo]
            [],  # treasury_id: bytes32
            None,  # current_coin
            None,  # current innerpuz
            uint32(0),
            filter_amount,
            [],
            uint64(0),
        )
        info_as_string = json.dumps(self.dao_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name, WalletType.DAO.value, info_as_string
        )
        await self.resync_treasury_state()
        await self.wallet_state_manager.add_new_wallet(self)
        await self.save_info(self.dao_info)
        if self.wallet_info is None:
            raise ValueError("Internal Error")
        self.wallet_id = self.wallet_info.id

        # Now the dao wallet is created we can create the dao_cat wallet
        cat_wallet: CATWallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
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
            self.dao_info.assets,
            self.dao_info.current_height,
        )
        await self.save_info(dao_info)

        # add interested puzzle hash so we can folllow treasury funds
        await self.wallet_state_manager.add_interested_puzzle_hashes([self.dao_info.treasury_id], [self.id()])
        return self

    @staticmethod
    async def create_new_did_wallet_from_coin_spend(
        wallet_state_manager: Any,
        wallet: Wallet,
        launch_coin: Coin,
        inner_puzzle: Program,
        coin_spend: CoinSpend,
        block_height: uint32,  # this is included in CoinState, pass it in from WSM
        name: Optional[str] = None,
    ) -> DAOWallet:
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

        self = DAOWallet()
        self.wallet_state_manager = wallet_state_manager
        if name is None:
            name = self.generate_wallet_name()
        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)

        self.log.info(f"Creating DAO wallet from a coin spend {launch_coin}  ...")
        # Create did info from the coin spend
        curried_args = uncurry_treasury(inner_puzzle)
        if curried_args is None:
            raise ValueError("Cannot uncurry the DAO puzzle.")
        (
            _DAO_TREASURY_MOD_HASH,
            proposal_validator,
            proposal_timelock,
            soft_close_length,
            attendance_required,
            pass_percentage,
            self_destruct_length,
            oracle_spend_delay,
        ) = curried_args
        # full_solution: Program = Program.from_bytes(bytes(coin_spend.solution))
        # inner_solution: Program = full_solution.rest().rest().first()
        # recovery_list: List[bytes32] = []
        curried_args = uncurry_proposal_validator(proposal_validator)
        (
            SINGLETON_STRUCT,
            PROPOSAL_MOD_HASH,
            PROPOSAL_TIMER_MOD_HASH,
            CAT_MOD_HASH,
            LOCKUP_MOD_HASH,
            TREASURY_MOD_HASH,
            CAT_TAIL_HASH,
        ) = curried_args.as_iter()

        # TODO: how is this working with our system about receiving CATs you haven't subscribed to?
        cat_wallet = await CATWallet.get_or_create_wallet_for_cat(
            wallet_state_manager,
            wallet,
            CAT_TAIL_HASH.as_atom().hex(),
        )

        dao_cat_wallet = await DAOCATWallet.get_or_create_wallet_for_cat(
            wallet_state_manager,
            wallet,
            CAT_TAIL_HASH.as_atom().hex(),
        )

        current_coin = get_most_recent_singleton_coin_from_coin_spend(coin_spend)
        self.dao_rules = get_treasury_rules_from_puzzle(inner_puzzle)

        dao_info = DAOInfo(
            launch_coin.name(),
            cat_wallet.id(),
            dao_cat_wallet.id(),
            [],
            [],
            current_coin,
            inner_puzzle,
            block_height,
            uint64(1),  # TODO: how should we deal with filter integer? Just update it later?
            [],
            uint64(0),
        )

        info_as_string = json.dumps(dao_info.to_json_dict())

        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name, WalletType.DAO.value, info_as_string
        )

        await self.wallet_state_manager.add_new_wallet(self)
        await self.wallet_state_manager.update_wallet_puzzle_hashes(self.wallet_info.id)

        self.log.info(f"New DAO wallet created {info_as_string}.")
        if self.wallet_info is None:
            raise ValueError("Internal Error")
        self.wallet_id = self.wallet_info.id
        return self

    @staticmethod
    async def create_new_dao_for_existing_cat(
        wallet_state_manager: Any,
        wallet: Wallet,
        tail_hash: bytes32,
        dao_rules: DAORules,
        filter_amount: uint64 = uint64(1),
        name: Optional[str] = None,
        fee: uint64 = uint64(0),
    ) -> DAOWallet:
        """
        Create a brand new DAO wallet
        This must be called under the wallet state manager lock
        :param wallet_state_manager: Wallet state manager
        :param wallet: Standard wallet
        :param name: Wallet name
        :param fee: transaction fee
        :return: DAO wallet
        """

        self = DAOWallet()
        self.wallet_state_manager = wallet_state_manager
        if name is None:
            name = self.generate_wallet_name()

        self.standard_wallet = wallet
        self.log = logging.getLogger(name if name else __name__)

        self.dao_info = DAOInfo(
            bytes32([0] * 32),
            uint32(0),
            uint32(0),
            [],
            [],
            None,
            None,
            uint32(0),
            filter_amount,
            [],
            uint64(0),
        )
        self.dao_rules = dao_rules
        info_as_string = json.dumps(self.dao_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name, WalletType.DAO.value, info_as_string
        )
        self.wallet_id = self.wallet_info.id

        try:
            launcher_spend = await self.generate_new_dao(
                None,
                cat_tail_hash=tail_hash,
                fee=fee,
            )
        except Exception:
            await wallet_state_manager.user_store.delete_wallet(self.id())
            raise

        if launcher_spend is None:
            await wallet_state_manager.user_store.delete_wallet(self.id())
            raise ValueError("Failed to create spend.")
        await self.wallet_state_manager.add_new_wallet(self)

        # Now that the dao wallet is created we can create the dao_cat wallet
        cat_wallet: CATWallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
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
            self.dao_info.assets,
            self.dao_info.current_height,
        )
        await self.save_info(dao_info)
        # breakpoint()
        # add interested puzzle hash so we can folllow treasury funds and proposals
        await self.wallet_state_manager.add_interested_puzzle_hashes([self.dao_info.treasury_id], [self.id()])

        return self

    @staticmethod
    async def create(
        wallet_state_manager: Any,
        wallet: Wallet,
        wallet_info: WalletInfo,
        name: Optional[str] = None,
    ) -> DAOWallet:
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
        self.dao_rules = get_treasury_rules_from_puzzle(self.dao_info.current_treasury_innerpuz)
        return self

    @classmethod
    def type(cls) -> WalletType:
        return WalletType.DAO

    def id(self) -> uint32:
        return self.wallet_info.id

    async def get_confirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        # This wallet only tracks coins, and does not hold any spendable value
        return uint128(0)

    async def get_pending_change_balance(self) -> uint64:
        # No spendable or receivable value
        return uint64(0)

    async def get_unconfirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        # TODO: should get_unconfirmed_balance return zero?
        # return uint128(await self.wallet_state_manager.get_unconfirmed_balance(self.id(), record_list))
        return uint128(0)

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

        # Only DID Wallet will return none when this happens, so we do it before select_coins would throw an error.
        if amount > spendable_amount:
            self.log.warning(f"Can't select {amount}, from spendable {spendable_amount} for wallet id {self.id()}")
            return set()

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

    async def coin_added(self, coin: Coin, height: uint32, peer: WSChiaConnection) -> None:
        """Notification from wallet state manager that wallet has been received."""
        self.log.info(f"DAOWallet.coin_added() called with the coin: {coin.name()}:{coin}.")
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer = wallet_node.get_full_node_peer()
        if peer is None:
            raise ValueError("Could not find any peers to request puzzle and solution from")
        # Get the parent coin spend
        cs = (await wallet_node.get_coin_state([coin.parent_coin_info], peer, height))[0]
        parent_spend = await fetch_coin_spend(cs.spent_height, cs.coin, peer)

        # check if it's a singleton and add to singleton_store
        singleton_id = get_singleton_id_from_puzzle(parent_spend.puzzle_reveal)
        if singleton_id:
            await self.wallet_state_manager.singleton_store.add_spend(self.id(), parent_spend, height)
        else:
            # funding coin
            asset_id = get_asset_id_from_puzzle(parent_spend.puzzle_reveal)
            if asset_id not in self.dao_info.assets:
                new_asset_list = self.dao_info.assets.copy()
                new_asset_list.append(asset_id)
                dao_info = dataclasses.replace(self.dao_info, assets=new_asset_list)
                await self.save_info(dao_info)
        return

    async def is_spend_retrievable(self, coin_id: bytes32) -> bool:
        wallet_node = self.wallet_state_manager.wallet_node
        peer: WSChiaConnection = wallet_node.get_full_node_peer()
        children = await wallet_node.fetch_children(coin_id, peer)
        return len(children) > 0

    def get_cat_tail_hash(self) -> bytes32:
        cat_wallet: CATWallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
        cat_tail_hash: bytes32 = cat_wallet.cat_info.limitations_program_hash
        return cat_tail_hash

    async def adjust_filter_level(self, new_filter_level: uint64) -> None:
        dao_info = DAOInfo(
            self.dao_info.treasury_id,
            self.dao_info.cat_wallet_id,
            self.dao_info.dao_cat_wallet_id,
            self.dao_info.proposals_list,
            self.dao_info.parent_info,
            self.dao_info.current_treasury_coin,
            self.dao_info.current_treasury_innerpuz,
            self.dao_info.singleton_block_height,
            new_filter_level,
            self.dao_info.assets,
            self.dao_info.current_height,
        )
        await self.save_info(dao_info)

    async def resync_treasury_state(self) -> None:
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

            children_state_list: List[CoinState] = [child for child in children if child.coin.amount % 2 == 1]
            if len(children_state_list) == 0:
                raise RuntimeError("Could not retrieve child_state")
            children_state = children_state_list[0]
            assert children_state is not None
            child_coin = children_state.coin
            if parent_coin is not None:
                parent_parent_coin = parent_coin
            parent_coin = child_coin
            parent_coin_id = child_coin.name()

        if parent_parent_coin is None:
            raise RuntimeError("could not get parent_parent_coin of %s", children)

        # get lineage proof of parent spend, and also current innerpuz
        assert children_state.created_height
        parent_spend = await fetch_coin_spend(children_state.created_height, parent_parent_coin, peer)
        assert parent_spend is not None
        parent_inner_puz = chia.wallet.singleton.get_inner_puzzle_from_singleton(
            parent_spend.puzzle_reveal.to_program()
        )
        if parent_inner_puz is None:
            raise ValueError("get_innerpuzzle_from_puzzle failed")

        if parent_spend.puzzle_reveal.get_tree_hash() == child_coin.puzzle_hash:
            current_inner_puz = parent_inner_puz
        else:
            # extract the treasury solution from the full singleton solution
            inner_solution = parent_spend.solution.to_program().rest().rest().first()
            # reconstruct the treasury puzzle
            current_inner_puz = get_new_puzzle_from_treasury_solution(parent_inner_puz, inner_solution)
        # set the treasury rules
        self.dao_rules = get_treasury_rules_from_puzzle(current_inner_puz)

        current_lineage_proof = LineageProof(
            parent_parent_coin.parent_coin_info, parent_inner_puz.get_tree_hash(), parent_parent_coin.amount
        )
        await self.add_parent(parent_parent_coin.name(), current_lineage_proof)

        # Hack to find the cat tail hash from the memo of the genesis spend
        launcher_state = await wallet_node.get_coin_state([self.dao_info.treasury_id], peer)
        genesis_coin_id = launcher_state[0].coin.parent_coin_info
        genesis_state = await wallet_node.get_coin_state([genesis_coin_id], peer)
        genesis_spend = await fetch_coin_spend(genesis_state[0].spent_height, genesis_state[0].coin, peer)
        cat_tail_hash = None
        conds = genesis_spend.solution.to_program().at("rfr").as_iter()
        for cond in conds:
            if (cond.first().as_atom() == ConditionOpcode.CREATE_COIN) and (
                int_from_bytes(cond.at("rrf").as_atom()) == 1
            ):
                cat_tail_hash = bytes32(cond.at("rrrff").as_atom())
                break
        assert cat_tail_hash

        cat_wallet: Optional[CATWallet] = None

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
            uint32(cat_wallet_id),  # cat_wallet_id: int
            uint32(0),  # dao_wallet_id: int
            self.dao_info.proposals_list,  # proposals_list: List[ProposalInfo]
            self.dao_info.parent_info,  # treasury_id: bytes32
            child_coin,  # current_coin
            current_inner_puz,  # current innerpuz
            self.dao_info.singleton_block_height,
            self.dao_info.filter_below_vote_amount,
            self.dao_info.assets,
            self.dao_info.current_height,
        )

        future_parent = LineageProof(
            child_coin.parent_coin_info,
            dao_info.current_treasury_innerpuz.get_tree_hash(),
            uint64(child_coin.amount),
        )
        await self.add_parent(child_coin.name(), future_parent)

        await self.save_info(dao_info)
        assert self.dao_info.parent_info is not None

        # get existing xch funds for treasury
        await self.wallet_state_manager.add_interested_puzzle_hashes([self.dao_info.treasury_id], [self.id()])
        await self.wallet_state_manager.add_interested_puzzle_hashes(
            [self.dao_info.current_treasury_coin.puzzle_hash], [self.id()]
        )

        # Resync the wallet from when the treasury was created to get the existing funds
        # TODO: Maybe split this out as an option for users since it may be slow?
        if not wallet_node.is_trusted(peer):
            request = RequestBlockHeader(children_state.created_height)
            response: Optional[RespondBlockHeader] = await peer.call_api(FullNodeAPI.request_block_header, request)
            await wallet_node.sync_from_untrusted_close_to_peak(response.header_block, peer)

        return

    async def create_tandem_xch_tx(
        self,
        fee: uint64,
        announcement_to_assert: Optional[Announcement] = None,
        reuse_puzhash: Optional[bool] = None,
    ) -> TransactionRecord:
        chia_coins = await self.standard_wallet.select_coins(fee)
        if reuse_puzhash is None:
            reuse_puzhash_config = self.wallet_state_manager.config.get("reuse_public_key_for_change", None)
            if reuse_puzhash_config is None:
                reuse_puzhash = False
            else:
                reuse_puzhash = reuse_puzhash_config.get(
                    str(self.wallet_state_manager.wallet_node.logged_in_fingerprint), False
                )
        chia_tx = await self.standard_wallet.generate_signed_transaction(
            uint64(0),
            (await self.standard_wallet.get_puzzle_hash(not reuse_puzhash)),
            fee=fee,
            coins=chia_coins,
            coin_announcements_to_consume={announcement_to_assert} if announcement_to_assert is not None else None,
            reuse_puzhash=reuse_puzhash,
        )
        assert chia_tx.spend_bundle is not None
        return chia_tx

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:
        return Program(Program.to(0))

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        return bytes32(Program.to(0).get_tree_hash())

    async def get_new_puzzle(self) -> Program:
        return self.puzzle_for_pk(
            (await self.wallet_state_manager.get_unused_derivation_record(self.wallet_info.id)).pubkey
        )

    async def set_name(self, new_name: str) -> None:
        import dataclasses

        new_info = dataclasses.replace(self.wallet_info, name=new_name)
        self.wallet_info = new_info
        await self.wallet_state_manager.user_store.update_wallet(self.wallet_info)

    def get_name(self) -> str:
        return self.wallet_info.name

    async def get_new_p2_inner_hash(self) -> bytes32:
        puzzle = await self.get_new_p2_inner_puzzle()
        return puzzle.get_tree_hash()

    async def get_new_p2_inner_puzzle(self) -> Program:
        return await self.standard_wallet.get_new_puzzle()

    def get_parent_for_coin(self, coin: Coin) -> Optional[LineageProof]:
        parent_info = None
        for name, ccparent in self.dao_info.parent_info:
            if name == coin.parent_coin_info:
                parent_info = ccparent

        return parent_info

    @staticmethod
    async def generate_new_dao_spend(
        wallet_state_manager: Any,
        standard_wallet: Wallet,
        dao_rules: DAORules,
        amount_of_cats_to_create: Optional[uint64],
        cat_tail_hash: Optional[bytes32] = None,
        fee: uint64 = uint64(0),
    ) -> Optional[SpendBundle]:
        """
        Create a new DAO treasury using the dao_rules object. This does the first spend to create the launcher
        and eve coins.
        The eve spend has to be completed in a separate tx using 'submit_eve_spend' once the number of blocks required
        by dao_rules.oracle_spend_delay has passed.
        This must be called under the wallet state manager lock
        """

        if amount_of_cats_to_create is not None and amount_of_cats_to_create < 0:
            raise ValueError("amount_of_cats must be >= 0, or None")
        if (amount_of_cats_to_create is None or amount_of_cats_to_create == 0) and cat_tail_hash is None:
            raise ValueError("amount_of_cats must be > 0 or cat_tail_hash must be specified")
        if amount_of_cats_to_create is not None and amount_of_cats_to_create > 0 and cat_tail_hash is not None:
            raise ValueError("cannot create voting cats and use existing cat_tail_hash")

        if amount_of_cats_to_create is not None and amount_of_cats_to_create > 0:
            coins = await standard_wallet.select_coins(uint64(amount_of_cats_to_create + fee + 1))
        else:
            coins = await standard_wallet.select_coins(uint64(fee + 1))

        if coins is None:
            return None
        # origin is normal coin which creates launcher coin
        origin = coins.copy().pop()

        genesis_launcher_puz = SINGLETON_LAUNCHER
        # launcher coin contains singleton launcher, launcher coin ID == singleton_id == treasury_id
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), 1)

        if cat_tail_hash is None:
            assert amount_of_cats_to_create is not None
            different_coins = await standard_wallet.select_coins(uint64(amount_of_cats_to_create), exclude=[origin])
            cat_origin = different_coins.copy().pop()
            assert origin.name() != cat_origin.name()
            cat_tail_hash = generate_cat_tail(cat_origin.name(), launcher_coin.name()).get_tree_hash()

        assert cat_tail_hash is not None

        new_cat_wallet = None
        # This will also mint the coins
        if amount_of_cats_to_create is not None and different_coins is not None:
            cat_tail_info = {
                "identifier": "genesis_by_id_or_singleton",
                "treasury_id": launcher_coin.name(),
                "coins": different_coins,
            }
            new_cat_wallet = await CATWallet.create_new_cat_wallet(
                wallet_state_manager,
                standard_wallet,
                cat_tail_info,
                amount_of_cats_to_create,
            )
            assert new_cat_wallet is not None
        else:
            for wallet in wallet_state_manager.wallets:
                if wallet_state_manager.wallets[wallet].type() == WalletType.CAT:
                    if wallet_state_manager.wallets[wallet].cat_info.limitations_program_hash == cat_tail_hash:
                        new_cat_wallet = wallet_state_manager.wallets[wallet]

        assert new_cat_wallet is not None

        assert cat_tail_hash == new_cat_wallet.cat_info.limitations_program_hash

        dao_treasury_puzzle = get_treasury_puzzle(dao_rules, launcher_coin.name(), cat_tail_hash)
        full_treasury_puzzle = curry_singleton(launcher_coin.name(), dao_treasury_puzzle)
        full_treasury_puzzle_hash = full_treasury_puzzle.get_tree_hash()

        announcement_set: Set[Announcement] = set()
        announcement_message = Program.to([full_treasury_puzzle_hash, 1, bytes(0x80)]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message))

        tx_record: Optional[TransactionRecord] = await standard_wallet.generate_signed_transaction(
            uint64(1),
            genesis_launcher_puz.get_tree_hash(),
            fee,
            origin.name(),
            coins,
            None,
            False,
            announcement_set,
            memos=[new_cat_wallet.cat_info.limitations_program_hash],
        )

        genesis_launcher_solution = Program.to([full_treasury_puzzle_hash, 1, bytes(0x80)])

        launcher_cs = CoinSpend(launcher_coin, genesis_launcher_puz, genesis_launcher_solution)
        launcher_sb = SpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))

        launcher_proof = LineageProof(
            bytes32(launcher_coin.parent_coin_info),
            None,
            uint64(launcher_coin.amount),
        )
        if tx_record is None or tx_record.spend_bundle is None:
            return None
        eve_coin = Coin(launcher_coin.name(), full_treasury_puzzle_hash, uint64(1))

        inner_sol = Program.to([0, 0, 0, 0, 0, singleton_struct_for_id(launcher_coin.name())])
        fullsol = Program.to(
            [
                launcher_proof.to_program(),
                eve_coin.amount,
                inner_sol,
            ]
        )
        eve_coin_spend = CoinSpend(eve_coin, full_treasury_puzzle, fullsol)
        eve_spend_bundle = SpendBundle([eve_coin_spend], G2Element())
        full_spend = SpendBundle.aggregate([tx_record.spend_bundle, launcher_sb, eve_spend_bundle])

        treasury_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=dao_treasury_puzzle.get_tree_hash(),
            amount=uint64(1),
            fee_amount=fee,
            confirmed=False,
            sent=uint32(10),
            spend_bundle=full_spend,
            additions=full_spend.additions(),
            removals=full_spend.removals(),
            wallet_id=standard_wallet.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.INCOMING_TX.value),
            name=bytes32(token_bytes()),
            memos=[],
        )
        regular_record = dataclasses.replace(tx_record, spend_bundle=None)
        await wallet_state_manager.add_pending_transaction(regular_record)
        await wallet_state_manager.add_pending_transaction(treasury_record)

        await wallet_state_manager.add_interested_coin_ids([eve_coin.name(), launcher_coin.name()])
        return full_spend

    async def generate_new_dao(
        self,
        amount_of_cats_to_create: Optional[uint64],
        cat_tail_hash: Optional[bytes32] = None,
        fee: uint64 = uint64(0),
    ) -> Optional[SpendBundle]:
        """
        Create a new DAO treasury using the dao_rules object. This does the first spend to create the launcher
        and eve coins.
        The eve spend has to be completed in a separate tx using 'submit_eve_spend' once the number of blocks required
        by dao_rules.oracle_spend_delay has passed.
        This must be called under the wallet state manager lock
        """

        if amount_of_cats_to_create is not None and amount_of_cats_to_create < 0:
            raise ValueError("amount_of_cats must be >= 0, or None")
        if (amount_of_cats_to_create is None or amount_of_cats_to_create == 0) and cat_tail_hash is None:
            raise ValueError("amount_of_cats must be > 0 or cat_tail_hash must be specified")
        if amount_of_cats_to_create is not None and amount_of_cats_to_create > 0 and cat_tail_hash is not None:
            raise ValueError("cannot create voting cats and use existing cat_tail_hash")
        if self.dao_rules.pass_percentage > 10000 or self.dao_rules.pass_percentage < 0:
            raise ValueError("proposal pass percentage must be between 0 and 10000")

        if amount_of_cats_to_create is not None and amount_of_cats_to_create > 0:
            coins = await self.standard_wallet.select_coins(uint64(amount_of_cats_to_create + fee + 1))
        else:
            coins = await self.standard_wallet.select_coins(uint64(fee + 1))

        if coins is None:
            return None
        # origin is normal coin which creates launcher coin
        origin = coins.copy().pop()

        genesis_launcher_puz = SINGLETON_LAUNCHER
        # launcher coin contains singleton launcher, launcher coin ID == singleton_id == treasury_id
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), 1)

        if cat_tail_hash is None:
            assert amount_of_cats_to_create is not None
            different_coins = await self.standard_wallet.select_coins(
                uint64(amount_of_cats_to_create), exclude=[origin]
            )
            cat_origin = different_coins.copy().pop()
            assert origin.name() != cat_origin.name()
            cat_tail_hash = generate_cat_tail(cat_origin.name(), launcher_coin.name()).get_tree_hash()

        assert cat_tail_hash is not None

        dao_info: DAOInfo = DAOInfo(
            launcher_coin.name(),
            self.dao_info.cat_wallet_id,
            self.dao_info.dao_cat_wallet_id,
            self.dao_info.proposals_list,
            self.dao_info.parent_info,
            None,
            None,
            uint32(0),
            self.dao_info.filter_below_vote_amount,
            self.dao_info.assets,
            self.dao_info.current_height,
        )
        await self.save_info(dao_info)
        new_cat_wallet = None
        # This will also mint the coins
        if amount_of_cats_to_create is not None and different_coins is not None:
            cat_tail_info = {
                "identifier": "genesis_by_id_or_singleton",
                "treasury_id": launcher_coin.name(),
                "coins": different_coins,
            }
            new_cat_wallet = await CATWallet.create_new_cat_wallet(
                self.wallet_state_manager,
                self.standard_wallet,
                cat_tail_info,
                amount_of_cats_to_create,
            )
            assert new_cat_wallet is not None
        else:
            for wallet in self.wallet_state_manager.wallets:
                if self.wallet_state_manager.wallets[wallet].type() == WalletType.CAT:
                    if self.wallet_state_manager.wallets[wallet].cat_info.limitations_program_hash == cat_tail_hash:
                        new_cat_wallet = self.wallet_state_manager.wallets[wallet]

        assert new_cat_wallet is not None
        cat_wallet_id = new_cat_wallet.wallet_info.id

        assert cat_tail_hash == new_cat_wallet.cat_info.limitations_program_hash

        dao_info = DAOInfo(
            self.dao_info.treasury_id,
            cat_wallet_id,
            self.dao_info.dao_cat_wallet_id,
            self.dao_info.proposals_list,
            self.dao_info.parent_info,
            None,
            None,
            uint32(0),
            self.dao_info.filter_below_vote_amount,
            self.dao_info.assets,
            self.dao_info.current_height,
        )

        await self.save_info(dao_info)

        dao_treasury_puzzle = get_treasury_puzzle(self.dao_rules, launcher_coin.name(), cat_tail_hash)
        full_treasury_puzzle = curry_singleton(launcher_coin.name(), dao_treasury_puzzle)
        full_treasury_puzzle_hash = full_treasury_puzzle.get_tree_hash()

        announcement_set: Set[Announcement] = set()
        announcement_message = Program.to([full_treasury_puzzle_hash, 1, bytes(0x80)]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message))

        tx_record: Optional[TransactionRecord] = await self.standard_wallet.generate_signed_transaction(
            uint64(1),
            genesis_launcher_puz.get_tree_hash(),
            fee,
            origin.name(),
            coins,
            None,
            False,
            announcement_set,
            memos=[new_cat_wallet.cat_info.limitations_program_hash],
        )

        genesis_launcher_solution = Program.to([full_treasury_puzzle_hash, 1, bytes(0x80)])

        launcher_cs = CoinSpend(launcher_coin, genesis_launcher_puz, genesis_launcher_solution)
        launcher_sb = SpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))

        launcher_proof = LineageProof(
            bytes32(launcher_coin.parent_coin_info),
            None,
            uint64(launcher_coin.amount),
        )
        await self.add_parent(launcher_coin.name(), launcher_proof)

        if tx_record is None or tx_record.spend_bundle is None:
            return None

        eve_coin = Coin(launcher_coin.name(), full_treasury_puzzle_hash, uint64(1))
        dao_info = DAOInfo(
            launcher_coin.name(),
            cat_wallet_id,
            self.dao_info.dao_cat_wallet_id,
            self.dao_info.proposals_list,
            self.dao_info.parent_info,
            eve_coin,
            dao_treasury_puzzle,
            self.dao_info.singleton_block_height,
            self.dao_info.filter_below_vote_amount,
            self.dao_info.assets,
            self.dao_info.current_height,
        )
        await self.save_info(dao_info)
        eve_spend = await self.generate_treasury_eve_spend(dao_treasury_puzzle, eve_coin)

        full_spend = SpendBundle.aggregate([tx_record.spend_bundle, launcher_sb, eve_spend])

        treasury_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=dao_treasury_puzzle.get_tree_hash(),
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
        # breakpoint()
        regular_record = dataclasses.replace(tx_record, spend_bundle=None)
        await self.wallet_state_manager.add_pending_transaction(regular_record)
        await self.wallet_state_manager.add_pending_transaction(treasury_record)
        await self.wallet_state_manager.add_interested_puzzle_hashes([launcher_coin.name()], [self.id()])
        await self.wallet_state_manager.add_interested_coin_ids([launcher_coin.name()], [self.wallet_id])

        await self.wallet_state_manager.add_interested_coin_ids([eve_coin.name()], [self.wallet_id])
        return full_spend

    async def generate_treasury_eve_spend(
        self, inner_puz: Program, eve_coin: Coin, fee: uint64 = uint64(0)
    ) -> SpendBundle:
        """
        Create the eve spend of the treasury
        This can only be completed after a number of blocks > oracle_spend_delay have been farmed
        """
        if self.dao_info.current_treasury_innerpuz is None:
            raise ValueError("generate_treasury_eve_spend called with nil self.dao_info.current_treasury_innerpuz")
        full_treasury_puzzle = curry_singleton(self.dao_info.treasury_id, inner_puz)
        # full_treasury_puzzle_hash = full_treasury_puzzle.get_tree_hash()
        launcher_id, launcher_proof = self.dao_info.parent_info[0]
        assert launcher_proof
        # eve_coin = Coin(launcher_id, full_treasury_puzzle_hash, uint64(1))
        # inner_puz = self.dao_info.current_treasury_innerpuz
        assert inner_puz
        # proposal_flag  ; if this is set then we are closing a proposal
        # (@ proposal_announcement (announcement_source delegated_puzzle_hash announcement_args spend_or_update_flag))
        # proposal_validator_solution
        # delegated_puzzle_reveal  ; this is the reveal of the puzzle announced by the proposal
        # delegated_solution  ; this is not secure unless the delegated puzzle secures it
        # my_singleton_struct

        inner_sol = Program.to([0, 0, 0, 0, 0, singleton_struct_for_id(launcher_id)])
        fullsol = Program.to(
            [
                launcher_proof.to_program(),
                eve_coin.amount,
                inner_sol,
            ]
        )
        eve_coin_spend = CoinSpend(eve_coin, full_treasury_puzzle, fullsol)
        eve_spend_bundle = SpendBundle([eve_coin_spend], G2Element())

        # assert self.dao_info.current_treasury_innerpuz
        # eve_record = TransactionRecord(
        #     confirmed_at_height=uint32(0),
        #     created_at_time=uint64(int(time.time())),
        #     to_puzzle_hash=self.dao_info.current_treasury_innerpuz.get_tree_hash(),
        #     amount=uint64(1),
        #     fee_amount=fee,
        #     confirmed=False,
        #     sent=uint32(10),
        #     spend_bundle=eve_spend_bundle,
        #     additions=eve_spend_bundle.additions(),
        #     removals=eve_spend_bundle.removals(),
        #     wallet_id=self.id(),
        #     sent_to=[],
        #     trade_id=None,
        #     type=uint32(TransactionType.INCOMING_TX.value),
        #     name=bytes32(token_bytes()),
        #     memos=[],
        # )
        # regular_record = dataclasses.replace(eve_record, spend_bundle=None)
        # await self.wallet_state_manager.add_pending_transaction(regular_record)
        # await self.wallet_state_manager.add_pending_transaction(eve_record)

        next_proof = LineageProof(
            eve_coin.parent_coin_info,
            inner_puz.get_tree_hash(),
            uint64(eve_coin.amount),
        )
        next_coin = Coin(eve_coin.name(), eve_coin.puzzle_hash, eve_coin.amount)
        await self.add_parent(eve_coin.name(), next_proof)
        await self.wallet_state_manager.add_interested_coin_ids([next_coin.name()], [self.wallet_id])

        dao_info = dataclasses.replace(self.dao_info, current_treasury_coin=next_coin)
        await self.save_info(dao_info)
        await self.wallet_state_manager.singleton_store.add_spend(self.id(), eve_coin_spend)
        return eve_spend_bundle

    # This has to be in the wallet because we are taking an ID and then searching our stored proposals for that ID
    def get_proposal_curry_values(self, proposal_id: bytes32) -> Tuple[Program, Program, Program]:
        for prop in self.dao_info.proposals_list:
            if prop.proposal_id == proposal_id:
                return get_curry_vals_from_proposal_puzzle(prop.inner_puzzle)
        raise ValueError("proposal not found")

    def generate_simple_proposal_innerpuz(
        self,
        recipient_puzhashes: List[bytes32],
        amounts: List[uint64],
        asset_types: List[Optional[bytes32]] = [None],
    ) -> Program:
        if len(recipient_puzhashes) != len(amounts):
            raise ValueError("List of amounts and recipient puzzle hashes are not the same length")
        xch_conditions = []
        asset_conditions = []
        for recipient_puzhash, amount, asset_type in zip(recipient_puzhashes, amounts, asset_types):
            if asset_type is not None:
                asset_conditions.append([asset_type, [[51, recipient_puzhash, amount]]])
            else:
                xch_conditions.append([51, recipient_puzhash, amount])
        puzzle = get_spend_p2_singleton_puzzle(self.dao_info.treasury_id, Program.to(xch_conditions), asset_conditions)  # type: ignore[arg-type]
        return puzzle

    async def generate_update_proposal_innerpuz(
        self,
        new_dao_rules: DAORules,
        new_proposal_validator: Optional[Program] = None,
    ) -> Program:
        if not new_proposal_validator:
            assert isinstance(self.dao_info.current_treasury_innerpuz, Program)
            new_proposal_validator = get_proposal_validator(self.dao_info.current_treasury_innerpuz)
            # assert isinstance(new_proposal_validator, Program)
        puzzle = get_update_proposal_puzzle(new_dao_rules, new_proposal_validator)
        return puzzle

    async def generate_mint_proposal_innerpuz(
        self,
        amount_of_cats_to_create: uint64,
        cats_new_innerpuzhash: bytes32,
    ) -> Program:
        cat_launcher = create_cat_launcher_for_singleton_id(self.dao_info.treasury_id)
        xch_conditions = [
            [
                51,
                cat_launcher.get_tree_hash(),
                uint64(amount_of_cats_to_create),
                [cats_new_innerpuzhash],
            ],  # create cat_launcher coin
            [
                60,
                Program.to(["m", cats_new_innerpuzhash]).get_tree_hash(),
            ],  # make an announcement for the launcher to assert
        ]
        puzzle = get_spend_p2_singleton_puzzle(self.dao_info.treasury_id, Program.to(xch_conditions), [])
        return puzzle

    async def generate_new_proposal(
        self,
        proposed_puzzle: Program,
        vote_amount: Optional[uint64] = None,
        fee: uint64 = uint64(0),
        push: bool = True,
    ) -> SpendBundle:
        coins = await self.standard_wallet.select_coins(uint64(fee + 1))
        if coins is None:
            return None
        # origin is normal coin which creates launcher coin
        origin = coins.copy().pop()
        genesis_launcher_puz = SINGLETON_LAUNCHER
        # launcher coin contains singleton launcher, launcher coin ID == singleton_id == treasury_id
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), 1)

        cat_wallet: CATWallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]

        if vote_amount is None:
            dao_cat_wallet = self.wallet_state_manager.get_wallet(
                id=self.dao_info.dao_cat_wallet_id, required_type=DAOCATWallet
            )
            vote_amount = await dao_cat_wallet.get_spendable_balance()
        assert vote_amount is not None
        cat_tail_hash = cat_wallet.cat_info.limitations_program_hash
        assert cat_tail_hash
        dao_proposal_puzzle = get_proposal_puzzle(
            proposal_id=launcher_coin.name(),
            cat_tail_hash=cat_tail_hash,
            treasury_id=self.dao_info.treasury_id,
            votes_sum=uint64(0),
            total_votes=uint64(0),
            proposed_puzzle_hash=proposed_puzzle.get_tree_hash(),
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
            eve_coin=eve_coin,
            full_proposal_puzzle=full_proposal_puzzle,
            dao_proposal_puzzle=dao_proposal_puzzle,
            proposed_puzzle_reveal=proposed_puzzle,
            launcher_coin=launcher_coin,
            vote_amount=vote_amount,
        )
        assert tx_record
        assert tx_record.spend_bundle is not None

        full_spend = SpendBundle.aggregate([tx_record.spend_bundle, eve_spend, launcher_sb])

        if push:
            record = TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=full_proposal_puzzle.get_tree_hash(),
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
            await self.wallet_state_manager.add_pending_transaction(record)
        return full_spend

    async def generate_proposal_eve_spend(
        self,
        *,
        eve_coin: Coin,
        full_proposal_puzzle: Program,
        dao_proposal_puzzle: Program,
        proposed_puzzle_reveal: Program,
        launcher_coin: Coin,
        vote_amount: uint64,
    ) -> SpendBundle:
        cat_wallet: CATWallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
        cat_tail = cat_wallet.cat_info.limitations_program_hash
        dao_cat_wallet = await DAOCATWallet.get_or_create_wallet_for_cat(
            self.wallet_state_manager, self.standard_wallet, cat_tail.hex()
        )
        assert dao_cat_wallet is not None

        curry_vals = get_curry_vals_from_proposal_puzzle(dao_proposal_puzzle)
        dao_cat_spend = await dao_cat_wallet.create_vote_spend(
            vote_amount, launcher_coin.name(), True, curry_vals=curry_vals
        )
        # vote_amounts_or_proposal_validator_hash  ; The qty of "votes" to add or subtract. ALWAYS POSITIVE.
        # vote_info_or_money_receiver_hash ; vote_info is whether we are voting YES or NO. XXX rename vote_type?
        # vote_coin_ids_or_proposal_timelock_length  ; this is either the coin ID we're taking a vote from
        # previous_votes_or_pass_margin  ; this is the active votes of the lockup we're communicating with
        #                              ; OR this is what percentage of the total votes must be YES - represented as an integer from 0 to 10,000 - typically this is set at 5100 (51%)
        # lockup_innerpuzhashes_or_attendance_required  ; this is either the innerpuz of the locked up CAT we're taking a vote from OR
        #                                           ; the attendance required - the percentage of the current issuance which must have voted represented as 0 to 10,000 - this is announced by the treasury
        # innerpuz_reveal  ; this is only added during the first vote
        # soft_close_length  ; revealed by the treasury
        # self_destruct_time ; revealed by the treasury
        # oracle_spend_delay  ; used to recreate the treasury
        # self_destruct_flag ; if not 0, do the self-destruct spend
        vote_amounts = []
        vote_coins = []
        previous_votes = []
        lockup_inner_puzhashes = []
        for spend in dao_cat_spend.coin_spends:
            vote_amounts.append(spend.coin.amount)
            vote_coins.append(spend.coin.name())
            previous_votes.append(
                get_active_votes_from_lockup_puzzle(
                    get_innerpuzzle_from_cat_puzzle(Program.from_bytes(bytes(spend.puzzle_reveal)))
                )
            )
            lockup_inner_puzhashes.append(
                get_innerpuz_from_lockup_puzzle(
                    get_innerpuzzle_from_cat_puzzle(Program.from_bytes(bytes(spend.puzzle_reveal)))
                ).get_tree_hash()
            )
        inner_sol = Program.to(
            [
                vote_amounts,
                1,
                vote_coins,
                previous_votes,
                lockup_inner_puzhashes,
                proposed_puzzle_reveal,
                0,
                0,
                0,
                0,
            ]
        )
        # full solution is (lineage_proof my_amount inner_solution)
        fullsol = Program.to(
            [
                [launcher_coin.parent_coin_info, launcher_coin.amount],
                eve_coin.amount,
                inner_sol,
            ]
        )
        list_of_coinspends = [CoinSpend(eve_coin, full_proposal_puzzle, fullsol)]
        unsigned_spend_bundle = SpendBundle(list_of_coinspends, G2Element())
        return unsigned_spend_bundle.aggregate([unsigned_spend_bundle, dao_cat_spend])

    async def generate_proposal_vote_spend(
        self,
        proposal_id: bytes32,
        vote_amount: Optional[uint64],
        is_yes_vote: bool,
        fee: uint64 = uint64(0),
        push: bool = True,
    ) -> SpendBundle:
        self.log.info(f"Trying to create a proposal close spend with ID: {proposal_id}")
        proposal_info = None
        for pi in self.dao_info.proposals_list:
            if pi.proposal_id == proposal_id:
                proposal_info = pi
                break
        if proposal_info is None:
            raise ValueError("Unable to find a proposal with that ID.")
        if proposal_info.timer_coin is None:
            # TODO: we should also check the current_inner puzzle is the finished state puzzle
            raise ValueError("This proposal is already closed. Feel free to unlock your coins.")
        # TODO: we may well want to add in options for more specificity later, but for now this will do
        cat_wallet: CATWallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
        cat_tail = cat_wallet.cat_info.limitations_program_hash
        dao_cat_wallet = await DAOCATWallet.get_or_create_wallet_for_cat(
            self.wallet_state_manager, self.standard_wallet, cat_tail.hex()
        )
        assert dao_cat_wallet is not None
        assert proposal_info.current_innerpuz is not None
        curry_vals = get_curry_vals_from_proposal_puzzle(proposal_info.current_innerpuz)
        if vote_amount is None:
            vote_amount = await dao_cat_wallet.get_votable_balance(proposal_id)
        assert vote_amount is not None
        dao_cat_spend = await dao_cat_wallet.create_vote_spend(
            vote_amount, proposal_id, is_yes_vote, curry_vals=curry_vals
        )
        # vote_amounts_or_proposal_validator_hash  ; The qty of "votes" to add or subtract. ALWAYS POSITIVE.
        # vote_info_or_money_receiver_hash ; vote_info is whether we are voting YES or NO. XXX rename vote_type?
        # vote_coin_ids_or_proposal_timelock_length  ; this is either the coin ID we're taking a vote from
        # previous_votes_or_pass_margin  ; this is the active votes of the lockup we're communicating with
        #                              ; OR this is what percentage of the total votes must be YES - represented as an integer from 0 to 10,000 - typically this is set at 5100 (51%)
        # lockup_innerpuzhashes_or_attendance_required  ; this is either the innerpuz of the locked up CAT we're taking a vote from OR
        #                                           ; the attendance required - the percentage of the current issuance which must have voted represented as 0 to 10,000 - this is announced by the treasury
        # innerpuz_reveal  ; this is only added during the first vote
        # soft_close_length  ; revealed by the treasury
        # self_destruct_time ; revealed by the treasury
        # oracle_spend_delay  ; used to recreate the treasury
        # self_destruct_flag ; if not 0, do the self-destruct spend
        vote_amounts = []
        vote_coins = []
        previous_votes = []
        lockup_inner_puzhashes = []
        assert dao_cat_spend is not None
        for spend in dao_cat_spend.coin_spends:
            vote_amounts.append(
                Program.from_bytes(bytes(spend.solution)).at("frrrrrrf")
            )  # this is the vote_amount field of the solution
            # breakpoint()
            vote_coins.append(spend.coin.name())
            previous_votes.append(
                get_active_votes_from_lockup_puzzle(
                    get_innerpuzzle_from_cat_puzzle(Program.from_bytes(bytes(spend.puzzle_reveal)))
                )
            )
            lockup_inner_puzhashes.append(
                get_innerpuz_from_lockup_puzzle(
                    get_innerpuzzle_from_cat_puzzle(Program.from_bytes(bytes(spend.puzzle_reveal)))
                ).get_tree_hash()
            )
        inner_sol = Program.to(
            [
                vote_amounts,
                1 if is_yes_vote else 0,
                vote_coins,
                previous_votes,
                lockup_inner_puzhashes,
                0,
                0,
                0,
                0,
                0,
            ]
        )
        parent_info = self.get_parent_for_coin(proposal_info.current_coin)
        assert parent_info is not None
        # full solution is (lineage_proof my_amount inner_solution)
        fullsol = Program.to(
            [
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                1,
                inner_sol,
            ]
        )
        full_proposal_puzzle = curry_singleton(proposal_id, proposal_info.current_innerpuz)
        list_of_coinspends = [CoinSpend(proposal_info.current_coin, full_proposal_puzzle, fullsol)]
        unsigned_spend_bundle = SpendBundle(list_of_coinspends, G2Element())
        if fee > 0:
            chia_tx = await self.create_tandem_xch_tx(fee)
            assert chia_tx.spend_bundle is not None
            spend_bundle = unsigned_spend_bundle.aggregate([unsigned_spend_bundle, dao_cat_spend, chia_tx.spend_bundle])
        spend_bundle = unsigned_spend_bundle.aggregate([unsigned_spend_bundle, dao_cat_spend])
        if push:
            record = TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=full_proposal_puzzle.get_tree_hash(),
                amount=uint64(1),
                fee_amount=fee,
                confirmed=False,
                sent=uint32(10),
                spend_bundle=spend_bundle,
                additions=spend_bundle.additions(),
                removals=spend_bundle.removals(),
                wallet_id=self.id(),
                sent_to=[],
                trade_id=None,
                type=uint32(TransactionType.INCOMING_TX.value),
                name=bytes32(token_bytes()),
                memos=[],
            )
            await self.wallet_state_manager.add_pending_transaction(record)
        return spend_bundle

    async def create_proposal_close_spend(
        self, proposal_id: bytes32, fee: uint64 = uint64(0), push: bool = True, self_destruct: bool = False
    ) -> SpendBundle:
        self.log.info(f"Trying to create a proposal close spend with ID: {proposal_id}")
        proposal_info = None
        for pi in self.dao_info.proposals_list:
            if pi.proposal_id == proposal_id:
                proposal_info = pi
                break
        if proposal_info is None:
            raise ValueError("Unable to find a proposal with that ID.")
        if proposal_info.timer_coin is None:
            # TODO: we should also check the current_inner is finished puzzle
            raise ValueError("This proposal is already closed. Feel free to unlock your coins.")
        # TODO: do we need to re-sync proposal state here?
        assert self.dao_info.current_treasury_innerpuz is not None
        curried_args = uncurry_treasury(self.dao_info.current_treasury_innerpuz)
        (
            _DAO_TREASURY_MOD_HASH,
            proposal_validator,
            proposal_timelock,
            soft_close_length,
            attendance_required,
            pass_percentage,
            self_destruct_length,
            oracle_spend_delay,
        ) = curried_args
        proposal_state = await self.get_proposal_state(proposal_id)
        if not proposal_state["closable"]:
            raise ValueError(f"This proposal is not ready to be closed. proposal_id: {proposal_id}")
        if proposal_state["passed"]:
            self.log.info(f"Closing passed proposal: {proposal_id}")
        else:
            self.log.info(f"Closing failed proposal: {proposal_id}")
        assert proposal_info.current_innerpuz is not None
        full_proposal_puzzle = curry_singleton(proposal_id, proposal_info.current_innerpuz)
        assert proposal_info.current_coin.puzzle_hash == full_proposal_puzzle.get_tree_hash()

        # vote_amounts_or_proposal_validator_hash  ; The qty of "votes" to add or subtract. ALWAYS POSITIVE.
        # vote_info ; vote_info is whether we are voting YES or NO. XXX rename vote_type?
        # vote_coin_ids_or_proposal_timelock_length  ; this is either the coin ID we're taking a vote from
        # previous_votes_or_pass_margin  ; this is the active votes of the lockup we're communicating with
        #                              ; OR this is what percentage of the total votes must be YES - represented as an integer from 0 to 10,000 - typically this is set at 5100 (51%)
        # lockup_innerpuzhashes_or_attendance_required  ; this is either the innerpuz of the locked up CAT we're taking a vote from OR
        #                                           ; the attendance required - the percentage of the current issuance which must have voted represented as 0 to 10,000 - this is announced by the treasury
        # innerpuz_reveal  ; this is only added during the first vote
        # soft_close_length  ; revealed by the treasury
        # self_destruct_time ; revealed by the treasury
        # oracle_spend_delay  ; used to recreate the treasury
        # self_destruct_flag ; if not 0, do the self-destruct spend
        solution = Program.to(
            [
                proposal_validator.get_tree_hash(),
                0,
                proposal_timelock,
                pass_percentage,
                attendance_required,
                0,
                soft_close_length,
                self_destruct_length,
                oracle_spend_delay,
                1 if self_destruct else 0,
            ]
        )
        parent_info = self.get_parent_for_coin(proposal_info.current_coin)
        assert parent_info is not None
        fullsol = Program.to(
            [
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                1,
                solution,
            ]
        )
        proposal_cs = CoinSpend(proposal_info.current_coin, full_proposal_puzzle, fullsol)
        # PROPOSAL_MOD_HASH
        # PROPOSAL_TIMER_MOD_HASH
        # CAT_MOD_HASH
        # CAT_TAIL_HASH
        # (@ MY_PARENT_SINGLETON_STRUCT (SINGLETON_MOD_HASH SINGLETON_ID . LAUNCHER_PUZZLE_HASH))
        # TREASURY_ID
        # proposal_yes_votes
        # proposal_total_votes
        # proposal_innerpuzhash
        # proposal_timelock
        # parent_parent  this is the parent of the timer's parent
        if not self_destruct:
            timer_puzzle = get_proposal_timer_puzzle(
                self.get_cat_tail_hash(),
                proposal_info.proposal_id,
                self.dao_info.treasury_id,
            )
            curried_args = uncurry_proposal(proposal_info.current_innerpuz)
            (
                SINGLETON_STRUCT,  # (SINGLETON_MOD_HASH (SINGLETON_ID . LAUNCHER_PUZZLE_HASH))
                PROPOSAL_MOD_HASH,
                PROPOSAL_TIMER_MOD_HASH,  # proposal timer needs to know which proposal created it, AND
                CAT_MOD_HASH,
                TREASURY_MOD_HASH,
                LOCKUP_MOD_HASH,
                CAT_TAIL_HASH,
                TREASURY_ID,
                YES_VOTES,  # yes votes are +1, no votes don't tally - we compare yes_votes/total_votes at the end
                TOTAL_VOTES,  # how many people responded
                PROPOSED_PUZ_HASH,  # this is what runs if this proposal is successful - the inner puzzle of this proposal
            ) = curried_args.as_iter()

            if TOTAL_VOTES.as_int() < attendance_required.as_int():
                raise ValueError("Unable to pass this proposal as it has not met the minimum vote attendance.")

            if (YES_VOTES.as_int() * 10000) // TOTAL_VOTES.as_int() < pass_percentage.as_int():
                raise ValueError("Unable to pass this proposal as it has insufficient yes votes.")

            # treasury_mod_hash
            # proposal_yes_votes
            # proposal_total_votes
            # proposal_innerpuzhash
            # proposal_timelock
            # parent_parent
            timer_solution = Program.to(
                [
                    DAO_TREASURY_MOD_HASH,
                    YES_VOTES,
                    TOTAL_VOTES,
                    PROPOSED_PUZ_HASH,
                    proposal_timelock,
                    proposal_id,  # TODO: our parent is the eve so our parent's parent is always the launcher coin ID, right?
                ]
            )
            timer_cs = CoinSpend(proposal_info.timer_coin, timer_puzzle, timer_solution)

        full_treasury_puz = curry_singleton(self.dao_info.treasury_id, self.dao_info.current_treasury_innerpuz)
        # proposal_flag
        # (@ proposal_announcement (announcement_source delegated_puzzle_hash announcement_args))
        # proposal_validator_solution
        # delegated_puzzle_reveal  ; this is the reveal of the puzzle announced by the proposal
        # delegated_solution  ; this is not secure unless the delegated puzzle secures it

        # (
        #   proposal_id
        #   total_votes
        #   yes_votes
        # )
        cat_spend_bundle = None
        delegated_puzzle_sb = None
        puzzle_reveal = await self.fetch_proposed_puzzle_reveal(proposal_id)
        if proposal_state["passed"] and not self_destruct:
            validator_solution = Program.to(
                [
                    proposal_id,
                    TOTAL_VOTES,
                    YES_VOTES,
                ]
            )
            # p2_singleton_parent_amount_list  ; for xch this is just a list of (coin_parent coin_amount)
            # p2_singleton_tailhash_parent_amount_list   ; list of ((asset (parent amount) (parent amount)... ) (asset (parent amount)... )... ),

            proposal_type, curried_args = get_proposal_args(puzzle_reveal)
            if proposal_type == "spend":
                # (
                #  treasury_solution,
                #  cat_spend_bundle,
                #  delegated_solution,
                #  delegated_puzzle_sb
                # ) = await self.get_delegated_solution_for_spend_proposal(
                #     curried_args,
                #     full_proposal_puzzle,
                #     PROPOSED_PUZ_HASH,
                #     validator_solution,
                #     puzzle_reveal,
                # )
                (
                    _,
                    _,
                    CONDITIONS,
                    LIST_OF_TAILHASH_CONDITIONS,
                    P2_SINGLETON_VIA_DELEGATED_PUZZLE_PUZHASH,
                ) = curried_args.as_iter()

                sum = 0

                # p2_singleton solution is:
                # singleton_inner_puzhash
                # delegated_puzzle
                # delegated_solution
                # my_id
                # my_puzhash
                # list_of_parent_amounts
                # my_amount
                coin_spends = []
                xch_parent_amount_list = []
                tailhash_parent_amount_list = []
                treasury_inner_puzhash = self.dao_info.current_treasury_innerpuz.get_tree_hash()
                p2_singleton_puzzle = get_p2_singleton_puzzle(self.dao_info.treasury_id)
                cat_launcher = create_cat_launcher_for_singleton_id(self.dao_info.treasury_id)

                # handle CAT minting
                for cond in CONDITIONS.as_iter():
                    if cond.first().as_int() == 51:
                        if cond.rest().first().as_atom() == cat_launcher.get_tree_hash():
                            mint_amount = cond.rest().rest().first().as_int()
                            new_cat_puzhash = cond.rest().rest().rest().first().first().as_atom()
                            cat_launcher_coin = Coin(
                                self.dao_info.current_treasury_coin.name(), cat_launcher.get_tree_hash(), mint_amount
                            )
                            # treasury_inner_puz_hash
                            # parent_parent
                            # new_puzzle_hash  ; the full CAT puzzle
                            # amount
                            solution = Program.to(
                                [
                                    treasury_inner_puzhash,
                                    self.dao_info.current_treasury_coin.parent_coin_info,
                                    new_cat_puzhash,
                                    mint_amount,
                                ]
                            )
                            coin_spends.append(CoinSpend(cat_launcher_coin, cat_launcher, solution))

                for condition_statement in CONDITIONS.as_iter():
                    if condition_statement.first().as_int() == 51:
                        sum += condition_statement.rest().rest().first().as_int()
                if sum > 0:
                    xch_coins = await self.select_coins_for_asset_type(uint64(sum))
                    for xch_coin in xch_coins:
                        xch_parent_amount_list.append([xch_coin.parent_coin_info, xch_coin.amount])
                        solution = Program.to(
                            [
                                treasury_inner_puzhash,
                                0,
                                0,
                                xch_coin.name(),
                                0,
                                0,
                                xch_coin.amount,
                            ]
                        )
                        coin_spends.append(CoinSpend(xch_coin, p2_singleton_puzzle, solution))
                    delegated_puzzle_sb = SpendBundle(coin_spends, AugSchemeMPL.aggregate([]))
                for tail_hash_conditions_pair in LIST_OF_TAILHASH_CONDITIONS.as_iter():
                    tail_hash: bytes32 = tail_hash_conditions_pair.first().as_atom()
                    conditions: Program = tail_hash_conditions_pair.rest().first()
                    sum_of_conditions = 0
                    sum_of_coins = 0
                    spendable_cat_list = []
                    for condition in conditions.as_iter():
                        if condition.first().as_int() == 51:
                            sum_of_conditions += condition.rest().rest().first().as_int()
                    cat_coins = await self.select_coins_for_asset_type(uint64(sum), tail_hash)
                    parent_amount_list = []
                    for cat_coin in cat_coins:
                        sum_of_coins += cat_coin.amount
                        parent_amount_list.append([cat_coin.parent_coin_info, cat_coin.amount])
                        lineage_proof = await self.fetch_cat_lineage_proof(cat_coin)
                        # singleton_inner_puzhash
                        # delegated_puzzle
                        # delegated_solution
                        # my_id
                        # my_puzhash  ; only needed for merging, set to 0 otherwise
                        if cat_coin == cat_coins[-1]:  # the last coin is the one that makes the conditions
                            change_condition = Program.to(
                                [51, p2_singleton_puzzle.get_tree_hash(), sum_of_coins - sum_of_conditions]
                            )
                            delegated_puzzle = Program.to((1, change_condition.cons(conditions)))
                            solution = Program.to(
                                [
                                    treasury_inner_puzhash,
                                    delegated_puzzle,
                                    0,
                                    cat_coin.name(),
                                    0,
                                ]
                            )
                        else:
                            solution = Program.to(
                                [
                                    treasury_inner_puzhash,
                                    0,
                                    0,
                                    cat_coin.name(),
                                    0,
                                ]
                            )
                        new_spendable_cat = SpendableCAT(
                            cat_coin,
                            tail_hash,
                            p2_singleton_puzzle,
                            solution,
                            lineage_proof=lineage_proof,
                        )
                        spendable_cat_list.append(new_spendable_cat)
                    # create or merge with other CAT spends
                    if cat_spend_bundle is None:
                        cat_spend_bundle = unsigned_spend_bundle_for_spendable_cats(CAT_MOD, spendable_cat_list)
                    else:
                        cat_spend_bundle = cat_spend_bundle.aggregate(
                            [cat_spend_bundle, unsigned_spend_bundle_for_spendable_cats(spendable_cat_list)]
                        )
                    tailhash_parent_amount_list.append([tail_hash, parent_amount_list])

                delegated_solution = Program.to(
                    [
                        xch_parent_amount_list,
                        tailhash_parent_amount_list,
                        treasury_inner_puzhash,
                    ]
                )
                # proposal_flag  ; if this is set then we are closing a proposal
                # (announcement_source delegated_puzzle_hash announcement_args)
                # proposal_validator_solution
                # delegated_puzzle_reveal  ; this is the reveal of the puzzle announced by the proposal
                # delegated_solution  ; this is not secure unless the delegated puzzle secures it
                # treasury_solution = Program.to(
                #     [
                #         1,
                #         [full_proposal_puzzle.get_tree_hash(), PROPOSED_PUZ_HASH.as_atom(), 0],
                #         validator_solution,
                #         puzzle_reveal,
                #         delegated_solution,
                #     ]
                # )
            elif proposal_type == "update":
                (
                    _,
                    PROPOSAL_VALIDATOR,
                    PROPOSAL_LENGTH,
                    PROPOSAL_SOFTCLOSE_LENGTH,
                    ATTENDANCE_REQUIRED,
                    PASS_MARGIN,
                    PROPOSAL_SELF_DESTRUCT_TIME,
                    ORACLE_SPEND_DELAY,
                ) = curried_args.as_iter()
                coin_spends = []
                treasury_inner_puzhash = self.dao_info.current_treasury_innerpuz.get_tree_hash()
                delegated_solution = Program.to([])

            treasury_solution = Program.to(
                [
                    1,
                    [full_proposal_puzzle.get_tree_hash(), PROPOSED_PUZ_HASH.as_atom(), 0],
                    validator_solution,
                    puzzle_reveal,
                    delegated_solution,
                ]
            )
        else:
            treasury_solution = Program.to([0, 0, 0, 0, 0, 0, 0])

        assert self.dao_info.current_treasury_coin is not None
        parent_info = self.get_parent_for_coin(self.dao_info.current_treasury_coin)
        assert parent_info is not None
        full_treasury_solution = Program.to(
            [
                [
                    parent_info.parent_name,
                    parent_info.inner_puzzle_hash,
                    parent_info.amount,
                ],
                1,
                treasury_solution,
            ]
        )

        treasury_cs = CoinSpend(self.dao_info.current_treasury_coin, full_treasury_puz, full_treasury_solution)

        if self_destruct:
            spend_bundle = SpendBundle([proposal_cs, treasury_cs], AugSchemeMPL.aggregate([]))
        else:
            spend_bundle = SpendBundle([proposal_cs, timer_cs, treasury_cs], AugSchemeMPL.aggregate([]))
        if fee > 0:
            chia_tx = await self.create_tandem_xch_tx(fee)
            assert chia_tx.spend_bundle is not None
            full_spend = SpendBundle.aggregate([spend_bundle, chia_tx.spend_bundle])
        else:
            full_spend = SpendBundle.aggregate([spend_bundle])
        if cat_spend_bundle is not None:
            full_spend = full_spend.aggregate([full_spend, cat_spend_bundle])
        if delegated_puzzle_sb is not None:
            full_spend = full_spend.aggregate([full_spend, delegated_puzzle_sb])

        if push:
            record = TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=DAO_FINISHED_STATE.get_tree_hash(),
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
            await self.wallet_state_manager.add_pending_transaction(record)
        return full_spend

    async def fetch_proposed_puzzle_reveal(self, proposal_id: bytes32) -> Program:
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer: WSChiaConnection = wallet_node.get_full_node_peer()
        if peer is None:
            raise ValueError("Could not find any peers to request puzzle and solution from")
        # The proposal_id is launcher coin, so proposal_id's child is eve and the eve spend contains the reveal
        children = await wallet_node.fetch_children(proposal_id, peer)
        eve_state = children[0]

        eve_spend = await fetch_coin_spend(eve_state.created_height, eve_state.coin, peer)
        puzzle_reveal = get_proposed_puzzle_reveal_from_solution(eve_spend.solution)
        # breakpoint()
        return puzzle_reveal

    async def fetch_cat_lineage_proof(self, cat_coin: Coin) -> LineageProof:
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer: WSChiaConnection = wallet_node.get_full_node_peer()
        if peer is None:
            raise ValueError("Could not find any peers to request puzzle and solution from")
        state = await wallet_node.get_coin_state([cat_coin.parent_coin_info], peer)
        assert state is not None
        # CoinState contains Coin, spent_height, and created_height,
        parent_spend = await fetch_coin_spend(state[0].spent_height, state[0].coin, peer)
        parent_inner_puz = get_innerpuzzle_from_cat_puzzle(parent_spend.puzzle_reveal.to_program())
        return LineageProof(state[0].coin.parent_coin_info, parent_inner_puz.get_tree_hash(), state[0].coin.amount)

    async def _create_treasury_fund_transaction(
        self, funding_wallet: WalletProtocol, amount: uint64, fee: uint64 = uint64(0)
    ) -> TransactionRecord:
        if funding_wallet.type() == WalletType.STANDARD_WALLET.value:
            p2_singleton_puzhash = get_p2_singleton_puzhash(self.dao_info.treasury_id, asset_id=None)
            wallet: Wallet = funding_wallet  # type: ignore[assignment]
            return await wallet.generate_signed_transaction(
                amount,
                p2_singleton_puzhash,
                fee=fee,
                memos=[self.dao_info.treasury_id],
            )
        elif funding_wallet.type() == WalletType.CAT.value:
            cat_wallet: CATWallet = funding_wallet  # type: ignore[assignment]
            # generate_signed_transaction has a different type signature in Wallet and CATWallet
            # CATWallet uses a List of amounts and a List of puzhashes as the first two arguments
            p2_singleton_puzhash = get_p2_singleton_puzhash(self.dao_info.treasury_id)
            tx_records: List[TransactionRecord] = await cat_wallet.generate_signed_transactions(
                [amount],
                [p2_singleton_puzhash],
                fee=fee,
                memos=[[self.dao_info.treasury_id]],
                override_memos=True,
            )
            return tx_records[0]
        else:
            raise ValueError(f"Assets of type {funding_wallet.type()} are not currently supported.")

    async def create_add_money_to_treasury_spend(
        self, amount: uint64, fee: uint64 = uint64(0), funding_wallet_id: uint32 = uint32(1)
    ) -> TransactionRecord:
        # TODO: add tests for create_add_money_to_treasury_spend
        # set up the p2_singleton
        funding_wallet = self.wallet_state_manager.wallets[funding_wallet_id]
        tx_record = await self._create_treasury_fund_transaction(funding_wallet, amount, fee)
        await self.wallet_state_manager.add_pending_transaction(tx_record)
        return tx_record

    async def fetch_singleton_lineage_proof(self, coin: Coin) -> LineageProof:
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer: WSChiaConnection = wallet_node.get_full_node_peer()
        if peer is None:
            raise ValueError("Could not find any peers to request puzzle and solution from")
        state = await wallet_node.get_coin_state([coin.parent_coin_info], peer)
        assert state is not None
        # CoinState contains Coin, spent_height, and created_height,
        parent_spend = await fetch_coin_spend(state[0].spent_height, state[0].coin, peer)
        parent_inner_puz = get_inner_puzzle_from_singleton(parent_spend.puzzle_reveal.to_program())
        return LineageProof(state[0].coin.parent_coin_info, parent_inner_puz.get_tree_hash(), state[0].coin.amount)

    async def free_coins_from_finished_proposals(self, fee=uint64(0), push=True) -> SpendBundle:
        dao_cat_wallet: DAOCATWallet = self.wallet_state_manager.wallets[self.dao_info.dao_cat_wallet_id]
        full_spend = None
        spends = []
        for proposal_info in self.dao_info.proposals_list:
            if proposal_info.closed:
                inner_solution = Program.to(
                    [
                        get_finished_state_puzzle(proposal_info.proposal_id).get_tree_hash(),
                        proposal_info.current_coin.amount,
                    ]
                )
                lineage_proof: LineageProof = await self.fetch_singleton_lineage_proof(proposal_info.current_coin)
                solution = Program.to([lineage_proof.to_program(), proposal_info.current_coin.amount, inner_solution])
                finished_puz = get_finished_state_puzzle(proposal_info.proposal_id)
                cs = CoinSpend(proposal_info.current_coin, finished_puz, solution)
                prop_sb = SpendBundle([cs], AugSchemeMPL.aggregate([]))
                sb = await dao_cat_wallet.remove_active_proposal(proposal_info.proposal_id)
                spends.append(prop_sb)
                spends.append(sb)

        if not spends:
            raise ValueError("No proposals are available for release")

        full_spend = SpendBundle.aggregate(spends)
        if fee > 0:
            chia_tx = await self.create_tandem_xch_tx(fee)
            assert chia_tx.spend_bundle is not None
            full_spend = full_spend.aggregate([full_spend, chia_tx.spend_bundle])
        if push:
            record = TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=finished_puz.get_tree_hash(),
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
            await self.wallet_state_manager.add_pending_transaction(record)
        return full_spend

    async def parse_proposal(self, proposal_id: bytes32):
        for prop_info in self.dao_info.proposals_list:
            if prop_info.proposal_id == proposal_id:
                state = await self.get_proposal_state(proposal_id)
                proposed_puzzle_reveal = await self.fetch_proposed_puzzle_reveal(proposal_id)
                proposal_type, curried_args = get_proposal_args(proposed_puzzle_reveal)
                if proposal_type == "spend":
                    cat_launcher = create_cat_launcher_for_singleton_id(self.dao_info.treasury_id)
                    (
                        _,
                        _,
                        CONDITIONS,
                        LIST_OF_TAILHASH_CONDITIONS,
                        P2_SINGLETON_VIA_DELEGATED_PUZZLE_PUZHASH,
                    ) = curried_args.as_iter()
                    mint_amount = None
                    new_cat_puzhash = None
                    xch_created_coins = []
                    for cond in CONDITIONS.as_iter():
                        if cond.first().as_int() == 51:
                            if cond.rest().first().as_atom() == cat_launcher.get_tree_hash():
                                mint_amount = cond.rest().rest().first().as_int()
                                new_cat_puzhash = cond.rest().rest().rest().first().first().as_atom()
                            else:
                                cc = {"puzzle_hash": cond.at("rf").as_atom(), "amount": cond.at("rrf").as_int()}
                                xch_created_coins.append(cc)

                    asset_create_coins = {}
                    for asset in LIST_OF_TAILHASH_CONDITIONS.as_iter():
                        if asset == Program.to(0):
                            asset_create_coins = None
                        else:
                            asset_id = asset.first().as_atom()
                            cc_list = []
                            for cond in asset.rest().first():
                                if cond.first().as_int() == 51:
                                    cc = {"puzzle_hash": cond.at("rf").as_atom(), "amount": cond.at("rrf").as_int()}
                                    cc_list.append(cc)
                            asset_create_coins[asset_id] = cc_list
                    dictionary = {
                        "state": state,
                        "proposal_type": proposal_type,
                        "proposed_puzzle_reveal": proposed_puzzle_reveal,
                        "xch_conditions": xch_created_coins,
                        "asset_conditions": asset_create_coins,
                    }
                    if mint_amount is not None and new_cat_puzhash is not None:
                        dictionary["mint_amount"] = mint_amount
                        dictionary["new_cat_puzhash"] = new_cat_puzhash
                elif proposal_type == "update":
                    dao_rules = get_dao_rules_from_update_proposal(proposed_puzzle_reveal)
                    dictionary = {
                        "state": state,
                        "proposal_type": proposal_type,
                        "dao_rules": dao_rules,
                    }
                return dictionary
        raise ValueError(f"Unable to find proposal with id: {proposal_id.hex()}")

    async def is_proposal_closeable(self, proposal_info: ProposalInfo) -> bool:
        dao_rules = get_treasury_rules_from_puzzle(self.dao_info.current_treasury_innerpuz)
        if proposal_info.singleton_block_height + dao_rules.proposal_timelock < self.dao_info.current_block_height:
            return False
        tip_height = await self.get_tip_created_height(proposal_info.proposal_id)
        if tip_height + dao_rules.soft_close_length < self.dao_info.current_block_height:
            return False
        return True

    async def get_frozen_amount(self) -> uint64:
        return uint64(0)

    async def get_spendable_balance(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        return uint128(0)

    async def get_max_send_amount(self, records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        return uint128(0)

    # if asset_id == None: then we get normal XCH
    async def get_balance_by_asset_type(self, asset_id: Optional[bytes32] = None) -> uint128:
        # TODO: Pull coins from DB once they're being stored
        puzhash = get_p2_singleton_puzhash(self.dao_info.treasury_id, asset_id=asset_id)
        records = await self.wallet_state_manager.coin_store.get_coin_records_by_puzzle_hash(puzhash)
        return uint128(sum([record.coin.amount for record in records if not record.spent]))

    # if asset_id == None: then we get normal XCH
    async def select_coins_for_asset_type(self, amount: uint64, asset_id: Optional[bytes32] = None) -> List[Coin]:
        # TODO: Pull coins from DB once they're being stored
        puzhash = get_p2_singleton_puzhash(self.dao_info.treasury_id, asset_id=asset_id)
        records = await self.wallet_state_manager.coin_store.get_coin_records_by_puzzle_hash(puzhash)
        # TODO: smarter coin selection algorithm
        total = 0
        coins = []
        for record in records:
            total += record.coin.amount
            coins.append(record.coin)
            if total >= amount:
                break
        if total < amount:
            raise ValueError(f"Not enough of that asset_id: {asset_id}")
        return coins

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
            self.dao_info.assets,
            self.dao_info.current_height,
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
        Generate a new DAO wallet name
        :return: wallet name
        """
        max_num = 0
        for wallet in self.wallet_state_manager.wallets.values():
            if wallet.type() == WalletType.DAO:
                matched = re.search(r"^Profile (\d+)$", wallet.wallet_info.name)  # TODO: bug: wallet.wallet_info
                if matched and int(matched.group(1)) > max_num:
                    max_num = int(matched.group(1))
        return f"Profile {max_num + 1}"

    def require_derivation_paths(self) -> bool:
        return True

    def get_cat_wallet_id(self) -> uint32:
        return self.dao_info.cat_wallet_id

    async def create_new_dao_cats(
        self, amount: uint64, push: bool = False
    ) -> Tuple[List[TransactionRecord], Optional[List[Coin]]]:
        # get the lockup puzzle hash
        dao_cat_wallet: DAOCATWallet = self.wallet_state_manager.wallets[self.dao_info.dao_cat_wallet_id]
        return await dao_cat_wallet.create_new_dao_cats(amount, push)

    @staticmethod
    def get_next_interesting_coin(spend: CoinSpend) -> Optional[Coin]:
        # CoinSpend of one of the coins that we cared about. This coin was spent in a block, but might be in a reorg
        # If we return a value, it is a coin that we are also interested in (to support two transitions per block)
        return get_most_recent_singleton_coin_from_coin_spend(spend)

    async def get_tip(self, singleton_id: bytes32) -> Optional[Tuple[uint32, SingletonRecord]]:
        ret: List[
            Tuple[uint32, SingletonRecord]
        ] = await self.wallet_state_manager.singleton_store.get_records_by_singleton_id(singleton_id)
        if len(ret) == 0:
            return None
        return ret[-1]

    async def get_tip_created_height(self, singleton_id: bytes32) -> Optional[int]:
        ret: List[
            Tuple[uint32, SingletonRecord]
        ] = await self.wallet_state_manager.singleton_store.get_records_by_singleton_id(singleton_id)
        if len(ret) < 1:
            return None
        return ret[-2].removed_height

    async def add_or_update_proposal_info(
        self,
        new_state: CoinSpend,
        block_height: uint32,
    ) -> None:
        new_dao_info = copy.copy(self.dao_info)
        puzzle = get_inner_puzzle_from_singleton(new_state.puzzle_reveal)
        if puzzle is None:
            raise ValueError("get_innerpuzzle_from_puzzle failed")
        solution = (
            Program.from_bytes(bytes(new_state.solution)).rest().rest().first()
        )  # get proposal solution from full singleton solution
        singleton_id = singleton.get_singleton_id_from_puzzle(new_state.puzzle_reveal)
        if singleton_id is None:
            raise ValueError("get_singleton_id_from_puzzle failed")
        curried_args = puzzle.uncurry()[1].as_iter()
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

        current_coin = get_most_recent_singleton_coin_from_coin_spend(new_state)
        if current_coin is None:
            raise RuntimeError("get_most_recent_singleton_coin_from_coin_spend({new_state}) failed")
        ended = False
        timer_coin = None
        if solution.at("rrrrrrf").as_int() == 0:
            # we need to add the vote amounts from the solution to get accurate totals
            is_yes_vote = solution.at("rf").as_int()
            votes_added = solution.at("ff").as_int()
            current_innerpuz = get_new_puzzle_from_proposal_solution(puzzle, solution)
            if current_innerpuz is None:
                raise RuntimeError("get_new_puzzle_from_proposal_solution failed")
        else:
            # If we have entered the finished state
            # TODO: we need to alert the user that they can free up their coins
            is_yes_vote = 0
            votes_added = 0
            current_innerpuz = get_new_puzzle_from_proposal_solution(puzzle, solution)
            if current_innerpuz == DAO_FINISHED_STATE:
                ended = True

        new_total_votes = TOTAL_VOTES.as_int() + votes_added
        if new_total_votes < self.dao_info.filter_below_vote_amount:
            return  # ignore all proposals below the filter amount

        if is_yes_vote == 1:
            new_yes_votes = YES_VOTES.as_int() + votes_added
        else:
            new_yes_votes = YES_VOTES.as_int()

        required_yes_votes = (self.dao_rules.attendance_required * self.dao_rules.pass_percentage) // 10000
        yes_votes_needed = max(0, required_yes_votes - new_yes_votes)

        passed = True if yes_votes_needed == 0 else False

        index = 0
        for current_info in new_dao_info.proposals_list:
            # Search for current proposal_info
            if current_info.proposal_id == singleton_id:
                # If we are receiving a voting spend update

                # TODO: what do we do here?
                # GW: Removed a block height check
                new_proposal_info = ProposalInfo(
                    singleton_id,
                    puzzle,
                    new_total_votes,
                    new_yes_votes,
                    current_coin,
                    current_innerpuz,
                    current_info.timer_coin,
                    block_height,
                    passed,
                    ended,
                )
                new_dao_info.proposals_list[index] = new_proposal_info
                await self.save_info(new_dao_info)
                future_parent = LineageProof(
                    new_state.coin.parent_coin_info,
                    puzzle.get_tree_hash(),
                    uint64(new_state.coin.amount),
                )
                await self.add_parent(new_state.coin.name(), future_parent)
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

            if self.dao_info.current_treasury_innerpuz is None:
                raise ValueError("self.dao_info.current_treasury_innerpuz is None")

            timer_coin_puzhash = get_proposal_timer_puzzle(
                CAT_TAIL_HASH.as_atom(),
                singleton_id,
                self.dao_info.treasury_id,
            ).get_tree_hash()

            while not found and len(children) > 0:
                children = await wallet_node.fetch_children(parent_coin_id, peer)
                if len(children) == 0:
                    break
                children_state = [child for child in children if child.coin.amount == 1]
                assert children_state is not None
                assert len(children_state) > 0
                child_state = children_state[0]
                for child in children:
                    if child.coin.puzzle_hash == timer_coin_puzhash:
                        found = True
                        timer_coin = child.coin
                        break
                child_coin = child_state.coin
                parent_coin_id = child_coin.name()

        # If we reach here then we don't currently know about this coin
        new_proposal_info = ProposalInfo(
            singleton_id,
            puzzle,
            uint64(new_total_votes),
            uint64(new_yes_votes),
            current_coin,
            current_innerpuz,
            timer_coin,  # if this is None then the proposal has finished
            block_height,  # block height that current proposal singleton coin was created in
            passed,
            ended,
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

    async def get_proposal_state(self, proposal_id: bytes32) -> Dict[str, Union[int, bool]]:
        """
        Use this to figure out whether a proposal has passed or failed and whether it can be closed
        Given a proposal_id:
        - if required yes votes are recorded then proposal passed.
        - if timelock and attendance are met then proposal can close
        Returns a dict of passed and closable bools, and the remaining votes/blocks needed

        Note that a proposal can be in a passed and closable state now, but become failed if a large number of
        'no' votes are recieved before the soft close is reached.
        """
        for prop in self.dao_info.proposals_list:
            if prop.proposal_id == proposal_id:
                is_closed = prop.closed
                break
        else:
            raise ValueError(f"Proposal not found for id {proposal_id}")

        wallet_node = self.wallet_state_manager.wallet_node
        peer: WSChiaConnection = wallet_node.get_full_node_peer()
        if peer is None:
            raise ValueError("Could not find any peers to request puzzle and solution from")
        assert isinstance(prop.timer_coin, Coin)
        timer_cs = (await wallet_node.get_coin_state([prop.timer_coin.name()], peer))[0]
        peak = await self.wallet_state_manager.blockchain.get_peak_block()
        blocks_elapsed = peak.height - timer_cs.created_height

        required_yes_votes = (self.dao_rules.attendance_required * self.dao_rules.pass_percentage) // 10000
        total_votes_needed = max(0, self.dao_rules.attendance_required - prop.amount_voted)
        yes_votes_needed = max(0, required_yes_votes - prop.yes_votes)
        blocks_needed = max(0, self.dao_rules.proposal_timelock - blocks_elapsed)

        passed = True if yes_votes_needed == 0 else False
        closable = True if total_votes_needed == blocks_needed == 0 else False
        proposal_state = {
            "total_votes_needed": total_votes_needed,
            "yes_votes_needed": yes_votes_needed,
            "blocks_needed": blocks_needed,
            "passed": passed,
            "closable": closable,
            "closed": is_closed,
        }
        return proposal_state

    async def update_treasury_info(
        self,
        new_state: CoinSpend,
        block_height: uint32,
    ) -> None:
        if self.dao_info.singleton_block_height <= block_height:
            # TODO: what do we do here?
            # return
            pass
        puzzle = get_inner_puzzle_from_singleton(new_state.puzzle_reveal)
        if puzzle is None:
            raise ValueError("get_innerpuzzle_from_puzzle failed")
        solution = (
            Program.from_bytes(bytes(new_state.solution)).rest().rest().first()
        )  # get proposal solution from full singleton solution
        new_innerpuz = get_new_puzzle_from_treasury_solution(puzzle, solution)
        child_coin = get_most_recent_singleton_coin_from_coin_spend(new_state)
        assert isinstance(child_coin, Coin)
        assert isinstance(self.dao_info.current_treasury_coin, Coin)
        if child_coin.puzzle_hash != self.dao_info.current_treasury_coin.puzzle_hash:
            # update dao rules
            assert isinstance(new_innerpuz, Program)
            self.dao_rules = get_treasury_rules_from_puzzle(new_innerpuz)
        dao_info = DAOInfo(
            self.dao_info.treasury_id,  # treasury_id: bytes32
            self.dao_info.cat_wallet_id,
            self.dao_info.dao_cat_wallet_id,
            self.dao_info.proposals_list,  # proposals_list: List[ProposalInfo]
            self.dao_info.parent_info,  # treasury_id: bytes32
            child_coin,  # current_coin
            new_innerpuz,  # current innerpuz
            block_height,  # block_height: uint32
            self.dao_info.filter_below_vote_amount,
            self.dao_info.assets,
            self.dao_info.current_height,
        )
        await self.save_info(dao_info)
        future_parent = LineageProof(
            new_state.coin.parent_coin_info,
            puzzle.get_tree_hash(),
            uint64(new_state.coin.amount),
        )
        await self.add_parent(new_state.coin.name(), future_parent)
        return

    async def get_spend_history(self, singleton_id: bytes32) -> List[Tuple[uint32, CoinSpend]]:
        ret: List[
            Tuple[uint32, CoinSpend]
        ] = await self.wallet_state_manager.singleton_store.get_records_by_singleton_id(singleton_id)
        if len(ret) == 0:
            raise ValueError(f"No records found in singleton store for singleton id {singleton_id}")
        return ret

    # TODO: Find a nice way to express interest in more than one singleton.
    #     e.g. def register_singleton_for_wallet()
    async def apply_state_transition(self, new_state: CoinSpend, block_height: uint32) -> bool:
        """
        We are being notified of a singleton state transition. A Singleton has been spent.
        Returns True iff the spend is a valid transition spend for the singleton, False otherwise.
        """

        self.log.info(
            f"DAOWallet.apply_state_transition called with the height: {block_height} and CoinSpend of {new_state.coin.name()}."
        )
        singleton_id = get_singleton_id_from_puzzle(new_state.puzzle_reveal)
        if not singleton_id:
            raise ValueError("Received a non singleton coin for dao wallet")
        tip: Optional[Tuple[uint32, SingletonRecord]] = await self.get_tip(singleton_id)
        if tip is None:
            # this is our first time, just store it
            await self.wallet_state_manager.singleton_store.add_spend(self.wallet_id, new_state, block_height)
        else:
            assert isinstance(tip, SingletonRecord)
            tip_spend = tip.parent_coinspend

            tip_coin: Optional[Coin] = get_most_recent_singleton_coin_from_coin_spend(tip_spend)
            assert tip_coin is not None
            # spent_coin_name: bytes32 = tip_coin.name()

            # TODO: Work out what is needed here
            # if spent_coin_name != new_state.coin.name():
            #     history: List[Tuple[uint32, CoinSpend]] = await self.get_spend_history()
            #     if new_state.coin.name() in [sp.coin.name() for _, sp in history]:
            #         self.log.info(f"Already have state transition: {new_state.coin.name().hex()}")
            #     else:
            #         self.log.warning(
            #             f"Failed to apply state transition. tip: {tip_coin} new_state: {new_state} height {block_height}"
            #         )
            #     return False

            # TODO: Add check for pending transaction on our behalf in here
            # if we have pending transaction that is now invalidated, then:
            # check if we should auto re-create spend or flash error to use (should we have a failed tx db?)
            await self.wallet_state_manager.singleton_store.add_spend(self.wallet_id, new_state, block_height)

        # Consume new DAOBlockchainInfo
        # Determine if this is a treasury spend or a proposal spend
        puzzle = get_inner_puzzle_from_singleton(new_state.puzzle_reveal)
        assert puzzle
        try:
            mod, curried_args = puzzle.uncurry()
        except ValueError as e:
            self.log.warning("Cannot uncurry puzzle in DAO Wallet: error: %s", e)
            raise e
        if mod == DAO_TREASURY_MOD:
            await self.update_treasury_info(new_state, block_height)
        elif mod == DAO_PROPOSAL_MOD:
            await self.add_or_update_proposal_info(new_state, block_height)
        else:
            raise ValueError(f"Unsupported spend in DAO Wallet: {self.id()}")

        return True

    async def new_peak(self, peak_height: uint64) -> None:
        """
        new_peak is called from the WalletStateManager whenever there is a new peak
        # This is where we can attempt to push spends, check on time locks, etc.
        """

        dao_info = DAOInfo(
            self.dao_info.treasury_id,  # treasury_id: bytes32
            self.dao_info.cat_wallet_id,
            self.dao_info.dao_cat_wallet_id,
            self.dao_info.proposals_list,  # proposals_list: List[ProposalInfo]
            self.dao_info.parent_info,  # treasury_id: bytes32
            self.dao_info.current_treasury_coin,
            self.dao_info.current_treasury_innerpuz,
            self.dao_info.singleton_block_height,
            self.dao_info.filter_below_vote_amount,
            self.dao_info.assets,
            self.dao_info.current_height,
        )
        await self.save_info(dao_info)
        pass
