from __future__ import annotations

import copy
import dataclasses
import json
import logging
import re
import time
from typing import TYPE_CHECKING, Any, ClassVar, Dict, List, Optional, Set, Tuple, Union, cast

from chia_rs import AugSchemeMPL, G1Element, G2Element
from clvm.casts import int_from_bytes

from chia.full_node.full_node_api import FullNodeAPI
from chia.protocols.wallet_protocol import CoinState, RequestBlockHeader, RespondBlockHeader
from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend, make_spend
from chia.types.condition_opcodes import ConditionOpcode
from chia.util.ints import uint32, uint64, uint128
from chia.wallet import singleton
from chia.wallet.cat_wallet.cat_utils import CAT_MOD, SpendableCAT, construct_cat_puzzle
from chia.wallet.cat_wallet.cat_utils import get_innerpuzzle_from_puzzle as get_innerpuzzle_from_cat_puzzle
from chia.wallet.cat_wallet.cat_utils import unsigned_spend_bundle_for_spendable_cats
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.cat_wallet.dao_cat_wallet import DAOCATWallet
from chia.wallet.coin_selection import select_coins
from chia.wallet.conditions import AssertCoinAnnouncement, Condition, parse_timelock_info
from chia.wallet.dao_wallet.dao_info import DAOInfo, DAORules, ProposalInfo, ProposalType
from chia.wallet.dao_wallet.dao_utils import (
    DAO_FINISHED_STATE,
    DAO_PROPOSAL_MOD,
    DAO_TREASURY_MOD,
    SINGLETON_LAUNCHER,
    create_cat_launcher_for_singleton_id,
    curry_cat_eve,
    curry_singleton,
    generate_cat_tail,
    get_active_votes_from_lockup_puzzle,
    get_asset_id_from_puzzle,
    get_dao_rules_from_update_proposal,
    get_finished_state_inner_puzzle,
    get_finished_state_puzzle,
    get_innerpuz_from_lockup_puzzle,
    get_new_puzzle_from_proposal_solution,
    get_new_puzzle_from_treasury_solution,
    get_p2_singleton_puzhash,
    get_p2_singleton_puzzle,
    get_proposal_args,
    get_proposal_puzzle,
    get_proposal_timer_puzzle,
    get_proposed_puzzle_reveal_from_solution,
    get_treasury_puzzle,
    get_treasury_rules_from_puzzle,
    match_funding_puzzle,
    uncurry_proposal,
    uncurry_treasury,
)
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.singleton import (
    get_inner_puzzle_from_singleton,
    get_most_recent_singleton_coin_from_coin_spend,
    get_singleton_id_from_puzzle,
    get_singleton_struct_for_id,
)
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.wallet_sync_utils import fetch_coin_spend
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_spend_bundle import WalletSpendBundle


class DAOWallet:
    """
    This is a wallet in the sense that it conforms to the interface needed by WalletStateManager.
    It is not a user-facing wallet. A user cannot spend or receive XCH though a wallet of this type.

    Wallets of type CAT and DAO_CAT are the user-facing wallets which hold the voting tokens a user
    owns. The DAO Wallet is used for state-tracking of the Treasury Singleton and its associated
    Proposals.

    State change Spends (spends this user creates, either from DAOWallet or DAOCATWallet:
      * Create a proposal
      * Add more votes to a proposal
      * Lock / Unlock voting tokens
      * Collect finished state of a Proposal - spend to read the oracle result and Get our CAT coins back
      * Anyone can send money to the Treasury, whether in possession of a voting CAT or not

    Incoming spends we listen for:
      * Update Treasury state if treasury is spent
      * Hear about a finished proposal
      * Hear about a new proposal -- check interest threshold (how many votes)
      * Get Updated Proposal Data
    """

    if TYPE_CHECKING:
        from chia.wallet.wallet_protocol import WalletProtocol

        _protocol_check: ClassVar[WalletProtocol[DAOInfo]] = cast("DAOWallet", None)

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
        action_scope: WalletActionScope,
        filter_amount: uint64 = uint64(1),
        name: Optional[str] = None,
        fee: uint64 = uint64(0),
        fee_for_cat: uint64 = uint64(0),
    ) -> DAOWallet:
        """
        Create a brand new DAO wallet
        This must be called under the wallet state manager lock
        :param wallet_state_manager: Wallet state manager
        :param wallet: Standard wallet
        :param amount_of_cats: Initial amount of voting CATs
        :param dao_rules: The rules which govern the DAO
        :param filter_amount: Min votes to see proposal (user defined)
        :param name: Wallet name
        :param fee: transaction fee
        :param fee_for_cat: transaction fee for creating the CATs
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
            raise ValueError(f"Your balance of {bal} mojos is not enough to create {amount_of_cats} CATs")

        self.dao_info = DAOInfo(
            treasury_id=bytes32([0] * 32),
            cat_wallet_id=uint32(0),
            dao_cat_wallet_id=uint32(0),
            proposals_list=[],
            parent_info=[],
            current_treasury_coin=None,
            current_treasury_innerpuz=None,
            singleton_block_height=uint32(0),
            filter_below_vote_amount=filter_amount,
            assets=[],
            current_height=uint64(0),
        )
        self.dao_rules = dao_rules
        info_as_string = json.dumps(self.dao_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name, WalletType.DAO.value, info_as_string
        )
        self.wallet_id = self.wallet_info.id
        std_wallet_id = self.standard_wallet.wallet_id

        try:
            await self.generate_new_dao(
                amount_of_cats,
                action_scope,
                fee=fee,
                fee_for_cat=fee_for_cat,
            )
        except Exception as e_info:  # pragma: no cover
            await wallet_state_manager.user_store.delete_wallet(self.id())
            self.log.exception(f"Failed to create dao wallet: {e_info}")
            raise

        await self.wallet_state_manager.add_new_wallet(self)

        # Now the dao wallet is created we can create the dao_cat wallet
        cat_wallet: CATWallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
        cat_tail = cat_wallet.cat_info.limitations_program_hash
        new_dao_cat_wallet = await DAOCATWallet.get_or_create_wallet_for_cat(
            self.wallet_state_manager, self.standard_wallet, cat_tail.hex()
        )
        dao_cat_wallet_id = new_dao_cat_wallet.wallet_info.id
        dao_info = dataclasses.replace(
            self.dao_info, cat_wallet_id=cat_wallet.id(), dao_cat_wallet_id=dao_cat_wallet_id
        )
        await self.save_info(dao_info)

        return self

    @staticmethod
    async def create_new_dao_wallet_for_existing_dao(
        wallet_state_manager: Any,
        main_wallet: Wallet,
        treasury_id: bytes32,
        filter_amount: uint64 = uint64(1),
        name: Optional[str] = None,
    ) -> DAOWallet:
        """
        Create a DAO wallet for existing DAO
        :param wallet_state_manager: Wallet state manager
        :param main_wallet: Standard wallet
        :param treasury_id: The singleton ID of the DAO treasury coin
        :param filter_amount: Min votes to see proposal (user defined)
        :param name: Wallet name
        :return: DAO wallet
        """
        self = DAOWallet()
        self.wallet_state_manager = wallet_state_manager
        if name is None:
            name = self.generate_wallet_name()

        self.standard_wallet = main_wallet
        self.log = logging.getLogger(name if name else __name__)
        self.log.info("Creating DAO wallet for existent DAO ...")
        self.dao_info = DAOInfo(
            treasury_id=treasury_id,
            cat_wallet_id=uint32(0),
            dao_cat_wallet_id=uint32(0),
            proposals_list=[],
            parent_info=[],
            current_treasury_coin=None,
            current_treasury_innerpuz=None,
            singleton_block_height=uint32(0),
            filter_below_vote_amount=filter_amount,
            assets=[],
            current_height=uint64(0),
        )
        info_as_string = json.dumps(self.dao_info.to_json_dict())
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(
            name, WalletType.DAO.value, info_as_string
        )
        await self.wallet_state_manager.add_new_wallet(self)
        await self.resync_treasury_state()
        await self.save_info(self.dao_info)
        self.wallet_id = self.wallet_info.id

        # Now the dao wallet is created we can create the dao_cat wallet
        cat_wallet: CATWallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
        cat_tail = cat_wallet.cat_info.limitations_program_hash
        new_dao_cat_wallet = await DAOCATWallet.get_or_create_wallet_for_cat(
            self.wallet_state_manager, self.standard_wallet, cat_tail.hex()
        )
        dao_cat_wallet_id = new_dao_cat_wallet.wallet_info.id
        dao_info = dataclasses.replace(
            self.dao_info, cat_wallet_id=cat_wallet.id(), dao_cat_wallet_id=dao_cat_wallet_id
        )
        await self.save_info(dao_info)

        # add treasury id to interested puzzle hashes. This is hinted in funding coins so we can track them
        funding_inner_hash = get_p2_singleton_puzhash(self.dao_info.treasury_id)
        await self.wallet_state_manager.add_interested_puzzle_hashes(
            [self.dao_info.treasury_id, funding_inner_hash], [self.id(), self.id()]
        )
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
        self.dao_info = DAOInfo.from_json_dict(json.loads(wallet_info.data))
        self.dao_rules = get_treasury_rules_from_puzzle(self.dao_info.current_treasury_innerpuz)
        return self

    @classmethod
    def type(cls) -> WalletType:
        return WalletType.DAO

    def id(self) -> uint32:
        return self.wallet_info.id

    async def set_name(self, new_name: str) -> None:
        new_info = dataclasses.replace(self.wallet_info, name=new_name)
        self.wallet_info = new_info
        await self.wallet_state_manager.user_store.update_wallet(self.wallet_info)

    def get_name(self) -> str:
        return self.wallet_info.name

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:
        raise NotImplementedError("Method not implemented for DAO Wallet")  # pragma: no cover

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        raise NotImplementedError("puzzle_hash_for_pk is not available in DAO wallets")  # pragma: no cover

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

    async def get_max_send_amount(self, records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        return uint128(0)  # pragma: no cover

    async def get_spendable_balance(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        # No spendable or receivable value
        return uint128(1)

    async def get_confirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        # No spendable or receivable value
        return uint128(1)

    async def select_coins(
        self,
        amount: uint64,
        action_scope: WalletActionScope,
    ) -> Set[Coin]:
        """
        Returns a set of coins that can be used for generating a new transaction.
        Note: Must be called under wallet state manager lock
        There is no need for max/min coin amount or excluded amount because the dao treasury should
        always be a single coin with amount 1
        """
        spendable_amount: uint128 = await self.get_spendable_balance()
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
        async with action_scope.use() as interface:
            coins = await select_coins(
                spendable_amount,
                action_scope.config.adjust_for_side_effects(interface.side_effects).tx_config.coin_selection_config,
                spendable_coins,
                unconfirmed_removals,
                self.log,
                uint128(amount),
            )
            interface.side_effects.selected_coins.extend([*coins])
        assert sum(c.amount for c in coins) >= amount
        return coins

    async def get_pending_change_balance(self) -> uint64:
        # No spendable or receivable value
        return uint64(0)

    async def get_unconfirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        # No spendable or receivable value
        return uint128(1)

    # if asset_id == None: then we get normal XCH
    async def get_balance_by_asset_type(self, asset_id: Optional[bytes32] = None) -> uint128:
        puzhash = get_p2_singleton_puzhash(self.dao_info.treasury_id, asset_id=asset_id)
        records = await self.wallet_state_manager.coin_store.get_coin_records_by_puzzle_hash(puzhash)
        return uint128(sum(cr.coin.amount for cr in records if not cr.spent))

    # if asset_id == None: then we get normal XCH
    async def select_coins_for_asset_type(
        self, amount: uint64, action_scope: WalletActionScope, asset_id: Optional[bytes32] = None
    ) -> List[Coin]:
        puzhash = get_p2_singleton_puzhash(self.dao_info.treasury_id, asset_id=asset_id)
        records = await self.wallet_state_manager.coin_store.get_coin_records_by_puzzle_hash(puzhash)
        unspent_records = [r for r in records if not r.spent]
        spendable_amount = uint128(sum(r.coin.amount for r in unspent_records))
        async with action_scope.use() as interface:
            return list(
                await select_coins(
                    spendable_amount,
                    action_scope.config.adjust_for_side_effects(interface.side_effects).tx_config.coin_selection_config,
                    unspent_records,
                    {},
                    self.log,
                    uint128(amount),
                )
            )

    async def coin_added(self, coin: Coin, height: uint32, peer: WSChiaConnection, coin_data: Optional[Any]) -> None:
        """
        Notification from wallet state manager that a coin has been received.
        This can be either a treasury coin update or funds added to the treasury
        """
        self.log.info(f"DAOWallet.coin_added() called with the coin: {coin.name().hex()}:{coin}.")
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer = wallet_node.get_full_node_peer()
        if peer is None:  # pragma: no cover
            raise ValueError("Could not find any peers to request puzzle and solution from")
        try:
            # Get the parent coin spend
            cs = (await wallet_node.get_coin_state([coin.parent_coin_info], peer, height))[0]
            parent_spend = await fetch_coin_spend(cs.spent_height, cs.coin, peer)

            uncurried = uncurry_puzzle(parent_spend.puzzle_reveal)
            matched_funding_puz = match_funding_puzzle(
                uncurried, parent_spend.solution.to_program(), coin, [self.dao_info.treasury_id]
            )
            if matched_funding_puz:
                # funding coin
                xch_funds_puzhash = get_p2_singleton_puzhash(self.dao_info.treasury_id, asset_id=None)
                if coin.puzzle_hash == xch_funds_puzhash:
                    asset_id = None
                else:
                    asset_id = get_asset_id_from_puzzle(parent_spend.puzzle_reveal.to_program())
                # to prevent fake p2_singletons being added
                assert coin.puzzle_hash == get_p2_singleton_puzhash(self.dao_info.treasury_id, asset_id=asset_id)
                if asset_id not in self.dao_info.assets:
                    new_asset_list = self.dao_info.assets.copy()
                    new_asset_list.append(asset_id)
                    dao_info = dataclasses.replace(self.dao_info, assets=new_asset_list)
                    await self.save_info(dao_info)
                    await self.wallet_state_manager.add_interested_puzzle_hashes([coin.puzzle_hash], [self.id()])
                self.log.info(f"DAO funding coin added: {coin.name().hex()}:{coin}. Asset ID: {asset_id}")
        except Exception as e:  # pragma: no cover
            self.log.exception(f"Error occurred during dao wallet coin addition: {e}")
        return

    def get_cat_tail_hash(self) -> bytes32:
        cat_wallet: CATWallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
        return cat_wallet.cat_info.limitations_program_hash

    async def adjust_filter_level(self, new_filter_level: uint64) -> None:
        dao_info = dataclasses.replace(self.dao_info, filter_below_vote_amount=new_filter_level)
        await self.save_info(dao_info)

    async def clear_finished_proposals_from_memory(self) -> None:
        dao_cat_wallet: DAOCATWallet = self.wallet_state_manager.wallets[self.dao_info.dao_cat_wallet_id]
        new_list = [
            prop_info
            for prop_info in self.dao_info.proposals_list
            if not prop_info.closed
            or prop_info.closed is None
            or any(prop_info.proposal_id in lci.active_votes for lci in dao_cat_wallet.dao_cat_info.locked_coins)
        ]
        dao_info = dataclasses.replace(self.dao_info, proposals_list=new_list)
        await self.save_info(dao_info)
        return

    async def resync_treasury_state(self) -> None:
        """
        This is called during create_new_dao_wallet_for_existing_dao.
        When we want to sync to an existing DAO, we provide the treasury coins singleton ID, and then trace all
        the child coins until we reach the current DAO treasury coin. We use the puzzle reveal and solution to
        get the current state of the DAO, and to work out what the tail of the DAO CAT token is.
        This also captures all the proposals that have been created and their state.
        """
        parent_coin_id: bytes32 = self.dao_info.treasury_id
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer: WSChiaConnection = wallet_node.get_full_node_peer()
        if peer is None:  # pragma: no cover
            raise ValueError("Could not find any peers to request puzzle and solution from")

        parent_coin = None
        parent_parent_coin = None
        while True:
            children = await wallet_node.fetch_children(parent_coin_id, peer)
            if len(children) == 0:
                break

            children_state_list: List[CoinState] = [child for child in children if child.coin.amount % 2 == 1]
            # ensure children_state_list has only one odd amount coin (the treasury)
            if (len(children_state_list) == 0) or (len(children_state_list) > 1):  # pragma: no cover
                raise RuntimeError("Could not retrieve child_state")
            children_state = children_state_list[0]
            assert children_state is not None
            child_coin = children_state.coin
            if parent_coin is not None:
                parent_parent_coin = parent_coin
            parent_coin = child_coin
            parent_coin_id = child_coin.name()

        if parent_parent_coin is None:  # pragma: no cover
            raise RuntimeError("could not get parent_parent_coin of %s", children)

        # ensure the child coin is unspent to prevent untrusted nodes sending false coin states
        assert children_state.spent_height is None

        # get lineage proof of parent spend, and also current innerpuz
        assert children_state.created_height
        parent_spend = await fetch_coin_spend(children_state.created_height, parent_parent_coin, peer)
        assert parent_spend is not None
        parent_inner_puz = get_inner_puzzle_from_singleton(parent_spend.puzzle_reveal)
        if parent_inner_puz is None:  # pragma: no cover
            raise ValueError("get_innerpuzzle_from_puzzle failed")

        if parent_spend.puzzle_reveal.get_tree_hash() == child_coin.puzzle_hash:
            current_inner_puz = parent_inner_puz
        else:  # pragma: no cover
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
                cat_origin_id = bytes32(cond.at("rrrfrf").as_atom())
                # Calculate the CAT tail from the memo data. If someone tries to use a fake tail hash in
                # the memo field, it won't match with the DAO's actual treasury ID.
                cat_tail = generate_cat_tail(cat_origin_id, self.dao_info.treasury_id)
                break
        assert cat_tail_hash
        assert cat_tail.get_tree_hash() == cat_tail_hash

        cat_wallet: Optional[CATWallet] = None

        # Get or create a cat wallet
        for wallet_id in self.wallet_state_manager.wallets:
            wallet = self.wallet_state_manager.wallets[wallet_id]
            if wallet.type() == WalletType.CAT:  # pragma: no cover
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
        await cat_wallet.set_tail_program(bytes(cat_tail).hex())
        cat_wallet_id = cat_wallet.wallet_info.id
        dao_info = dataclasses.replace(
            self.dao_info,
            cat_wallet_id=uint32(cat_wallet_id),
            dao_cat_wallet_id=uint32(0),
            current_treasury_coin=child_coin,
            current_treasury_innerpuz=current_inner_puz,
        )
        await self.save_info(dao_info)

        future_parent = LineageProof(
            child_coin.parent_coin_info,
            dao_info.current_treasury_innerpuz.get_tree_hash(),
            uint64(child_coin.amount),
        )
        await self.add_parent(child_coin.name(), future_parent)
        assert self.dao_info.parent_info is not None

        # get existing xch funds for treasury
        xch_funds_puzhash = get_p2_singleton_puzhash(self.dao_info.treasury_id, asset_id=None)
        await self.wallet_state_manager.add_interested_puzzle_hashes([xch_funds_puzhash], [self.id()])
        await self.wallet_state_manager.add_interested_puzzle_hashes([self.dao_info.treasury_id], [self.id()])
        await self.wallet_state_manager.add_interested_puzzle_hashes(
            [self.dao_info.current_treasury_coin.puzzle_hash], [self.id()]
        )

        # Resync the wallet from when the treasury was created to get the existing funds
        # TODO: Maybe split this out as an option for users since it may be slow?
        if not wallet_node.is_trusted(peer):
            # Untrusted nodes won't automatically send us the history of all the treasury and proposal coins,
            # so we have to request them via sync_from_untrusted_close_to_peak
            request = RequestBlockHeader(children_state.created_height)
            response: Optional[RespondBlockHeader] = await peer.call_api(FullNodeAPI.request_block_header, request)
            await wallet_node.sync_from_untrusted_close_to_peak(response.header_block, peer)

        return

    async def generate_new_dao(
        self,
        amount_of_cats_to_create: Optional[uint64],
        action_scope: WalletActionScope,
        cat_tail_hash: Optional[bytes32] = None,
        fee: uint64 = uint64(0),
        fee_for_cat: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        """
        Create a new DAO treasury using the dao_rules object. This does the first spend to create the launcher
        and eve coins.
        The eve spend has to be completed in a separate tx using 'submit_eve_spend' once the number of blocks required
        by dao_rules.oracle_spend_delay has passed.
        This must be called under the wallet state manager lock
        """

        if amount_of_cats_to_create is not None and amount_of_cats_to_create < 0:  # pragma: no cover
            raise ValueError("amount_of_cats must be >= 0, or None")
        if (
            amount_of_cats_to_create is None or amount_of_cats_to_create == 0
        ) and cat_tail_hash is None:  # pragma: no cover
            raise ValueError("amount_of_cats must be > 0 or cat_tail_hash must be specified")
        if (
            amount_of_cats_to_create is not None and amount_of_cats_to_create > 0 and cat_tail_hash is not None
        ):  # pragma: no cover
            raise ValueError("cannot create voting cats and use existing cat_tail_hash")
        if self.dao_rules.pass_percentage > 10000 or self.dao_rules.pass_percentage < 0:  # pragma: no cover
            raise ValueError("proposal pass percentage must be between 0 and 10000")

        if amount_of_cats_to_create is not None and amount_of_cats_to_create > 0:
            coins = await self.standard_wallet.select_coins(
                uint64(amount_of_cats_to_create + fee + 1),
                action_scope,
            )
        else:  # pragma: no cover
            coins = await self.standard_wallet.select_coins(uint64(fee + 1), action_scope)

        if coins is None:  # pragma: no cover
            return None
        # origin is normal coin which creates launcher coin
        origin = coins.copy().pop()

        genesis_launcher_puz = SINGLETON_LAUNCHER
        # launcher coin contains singleton launcher, launcher coin ID == singleton_id == treasury_id
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), uint64(1))

        if cat_tail_hash is None:
            assert amount_of_cats_to_create is not None
            different_coins = await self.standard_wallet.select_coins(
                uint64(amount_of_cats_to_create + fee_for_cat),
                action_scope,
            )
            cat_origin = different_coins.copy().pop()
            assert origin.name() != cat_origin.name()
            cat_tail = generate_cat_tail(cat_origin.name(), launcher_coin.name())
            cat_tail_hash = cat_tail.get_tree_hash()

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
                action_scope,
                fee=fee_for_cat,
                push=False,
            )
            assert new_cat_wallet is not None
        else:  # pragma: no cover
            for wallet in self.wallet_state_manager.wallets:
                if self.wallet_state_manager.wallets[wallet].type() == WalletType.CAT:
                    if self.wallet_state_manager.wallets[wallet].cat_info.limitations_program_hash == cat_tail_hash:
                        new_cat_wallet = self.wallet_state_manager.wallets[wallet]

        assert new_cat_wallet is not None
        cat_wallet_id = new_cat_wallet.wallet_info.id

        assert cat_tail_hash == new_cat_wallet.cat_info.limitations_program_hash
        await new_cat_wallet.set_tail_program(bytes(cat_tail).hex())
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

        announcement_message = Program.to([full_treasury_puzzle_hash, 1, bytes(0x80)]).get_tree_hash()

        await self.standard_wallet.generate_signed_transaction(
            uint64(1),
            genesis_launcher_puz.get_tree_hash(),
            action_scope,
            fee,
            origin_id=origin.name(),
            coins=set(coins),
            memos=[new_cat_wallet.cat_info.limitations_program_hash, cat_origin.name()],
            extra_conditions=(
                AssertCoinAnnouncement(asserted_id=launcher_coin.name(), asserted_msg=announcement_message),
            ),
        )

        genesis_launcher_solution = Program.to([full_treasury_puzzle_hash, 1, bytes(0x80)])

        launcher_cs = make_spend(launcher_coin, genesis_launcher_puz, genesis_launcher_solution)
        launcher_sb = WalletSpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))

        launcher_proof = LineageProof(
            bytes32(launcher_coin.parent_coin_info),
            None,
            uint64(launcher_coin.amount),
        )
        await self.add_parent(launcher_coin.name(), launcher_proof)

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
        new_spend = WalletSpendBundle.aggregate([launcher_sb, eve_spend])

        treasury_record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=dao_treasury_puzzle.get_tree_hash(),
            amount=uint64(1),
            fee_amount=fee,
            confirmed=False,
            sent=uint32(10),
            spend_bundle=new_spend,
            additions=new_spend.additions(),
            removals=new_spend.removals(),
            wallet_id=self.id(),
            sent_to=[],
            trade_id=None,
            type=uint32(TransactionType.INCOMING_TX.value),
            name=eve_coin.name(),
            memos=[],
            valid_times=parse_timelock_info(extra_conditions),
        )

        funding_inner_puzhash = get_p2_singleton_puzhash(self.dao_info.treasury_id)
        await self.wallet_state_manager.add_interested_puzzle_hashes([funding_inner_puzhash], [self.id()])
        await self.wallet_state_manager.add_interested_puzzle_hashes([launcher_coin.name()], [self.id()])
        await self.wallet_state_manager.add_interested_coin_ids([launcher_coin.name()], [self.wallet_id])

        await self.wallet_state_manager.add_interested_coin_ids([eve_coin.name()], [self.wallet_id])
        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(treasury_record)

    async def generate_treasury_eve_spend(
        self, inner_puz: Program, eve_coin: Coin, fee: uint64 = uint64(0)
    ) -> WalletSpendBundle:
        """
        Create the eve spend of the treasury
        This can only be completed after a number of blocks > oracle_spend_delay have been farmed
        """
        if self.dao_info.current_treasury_innerpuz is None:  # pragma: no cover
            raise ValueError("generate_treasury_eve_spend called with nil self.dao_info.current_treasury_innerpuz")
        full_treasury_puzzle = curry_singleton(self.dao_info.treasury_id, inner_puz)
        launcher_id, launcher_proof = self.dao_info.parent_info[0]
        assert launcher_proof
        assert inner_puz
        inner_sol = Program.to([0, 0, 0, 0, get_singleton_struct_for_id(launcher_id)])
        fullsol = Program.to(
            [
                launcher_proof.to_program(),
                eve_coin.amount,
                inner_sol,
            ]
        )
        eve_coin_spend = make_spend(eve_coin, full_treasury_puzzle, fullsol)
        eve_spend_bundle = WalletSpendBundle([eve_coin_spend], G2Element())

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
        return eve_spend_bundle

    async def generate_new_proposal(
        self,
        proposed_puzzle: Program,
        action_scope: WalletActionScope,
        vote_amount: Optional[uint64] = None,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        dao_rules = get_treasury_rules_from_puzzle(self.dao_info.current_treasury_innerpuz)
        coins = await self.standard_wallet.select_coins(
            uint64(fee + dao_rules.proposal_minimum_amount),
            action_scope,
        )
        if coins is None:  # pragma: no cover
            return None
        # origin is normal coin which creates launcher coin
        origin = coins.copy().pop()
        genesis_launcher_puz = SINGLETON_LAUNCHER
        # launcher coin contains singleton launcher, launcher coin ID == singleton_id == treasury_id
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), dao_rules.proposal_minimum_amount)

        cat_wallet: CATWallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]

        if vote_amount is None:  # pragma: no cover
            dao_cat_wallet = self.wallet_state_manager.get_wallet(
                id=self.dao_info.dao_cat_wallet_id, required_type=DAOCATWallet
            )
            vote_amount = await dao_cat_wallet.get_votable_balance(include_free_cats=False)
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

        announcement_message = Program.to(
            [full_proposal_puzzle_hash, dao_rules.proposal_minimum_amount, bytes(0x80)]
        ).get_tree_hash()

        await self.standard_wallet.generate_signed_transaction(
            uint64(dao_rules.proposal_minimum_amount),
            genesis_launcher_puz.get_tree_hash(),
            action_scope,
            fee,
            origin_id=origin.name(),
            coins=coins,
            extra_conditions=(
                AssertCoinAnnouncement(asserted_id=launcher_coin.name(), asserted_msg=announcement_message),
            ),
        )

        genesis_launcher_solution = Program.to(
            [full_proposal_puzzle_hash, dao_rules.proposal_minimum_amount, bytes(0x80)]
        )

        launcher_cs = make_spend(launcher_coin, genesis_launcher_puz, genesis_launcher_solution)
        launcher_sb = WalletSpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))
        eve_coin = Coin(launcher_coin.name(), full_proposal_puzzle_hash, dao_rules.proposal_minimum_amount)

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

        full_spend = WalletSpendBundle.aggregate([eve_spend, launcher_sb])

        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(
                TransactionRecord(
                    confirmed_at_height=uint32(0),
                    created_at_time=uint64(int(time.time())),
                    to_puzzle_hash=full_proposal_puzzle.get_tree_hash(),
                    amount=uint64(dao_rules.proposal_minimum_amount),
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
                    name=full_spend.name(),
                    memos=[],
                    valid_times=parse_timelock_info(extra_conditions),
                )
            )

    async def generate_proposal_eve_spend(
        self,
        *,
        eve_coin: Coin,
        full_proposal_puzzle: Program,
        dao_proposal_puzzle: Program,
        proposed_puzzle_reveal: Program,
        launcher_coin: Coin,
        vote_amount: uint64,
    ) -> WalletSpendBundle:
        cat_wallet: CATWallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
        cat_tail = cat_wallet.cat_info.limitations_program_hash
        dao_cat_wallet = await DAOCATWallet.get_or_create_wallet_for_cat(
            self.wallet_state_manager, self.standard_wallet, cat_tail.hex()
        )
        assert dao_cat_wallet is not None

        dao_cat_spend = await dao_cat_wallet.create_vote_spend(
            vote_amount, launcher_coin.name(), True, proposal_puzzle=dao_proposal_puzzle
        )
        vote_amounts = []
        vote_coins = []
        previous_votes = []
        lockup_inner_puzhashes = []
        for spend in dao_cat_spend.coin_spends:
            spend_vote_amount = Program.from_bytes(bytes(spend.solution)).at("frrrrrrf").as_int()
            vote_amounts.append(spend_vote_amount)
            vote_coins.append(spend.coin.name())
            previous_votes.append(
                get_active_votes_from_lockup_puzzle(
                    get_innerpuzzle_from_cat_puzzle(Program.from_bytes(bytes(spend.puzzle_reveal)))
                )
            )
            lockup_inner_puz = get_innerpuz_from_lockup_puzzle(
                get_innerpuzzle_from_cat_puzzle(Program.from_bytes(bytes(spend.puzzle_reveal)))
            )
            assert isinstance(lockup_inner_puz, Program)
            lockup_inner_puzhashes.append(lockup_inner_puz.get_tree_hash())
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
                eve_coin.amount,
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
        list_of_coinspends = [make_spend(eve_coin, full_proposal_puzzle, fullsol)]
        unsigned_spend_bundle = WalletSpendBundle(list_of_coinspends, G2Element())
        return unsigned_spend_bundle.aggregate([unsigned_spend_bundle, dao_cat_spend])

    async def generate_proposal_vote_spend(
        self,
        proposal_id: bytes32,
        vote_amount: Optional[uint64],
        is_yes_vote: bool,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        self.log.info(f"Trying to create a proposal close spend with ID: {proposal_id}")
        proposal_info = None
        for pi in self.dao_info.proposals_list:
            if pi.proposal_id == proposal_id:
                proposal_info = pi
                break
        if proposal_info is None:  # pragma: no cover
            raise ValueError("Unable to find a proposal with that ID.")
        if (proposal_info.timer_coin is None) and (
            proposal_info.current_innerpuz == get_finished_state_puzzle(proposal_info.proposal_id)
        ):
            raise ValueError("This proposal is already closed. Feel free to unlock your coins.")  # pragma: no cover
        cat_wallet: CATWallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
        cat_tail = cat_wallet.cat_info.limitations_program_hash
        dao_cat_wallet = await DAOCATWallet.get_or_create_wallet_for_cat(
            self.wallet_state_manager, self.standard_wallet, cat_tail.hex()
        )
        assert dao_cat_wallet is not None
        assert proposal_info.current_innerpuz is not None

        if vote_amount is None:  # pragma: no cover
            vote_amount = await dao_cat_wallet.get_votable_balance(proposal_id)
        assert vote_amount is not None
        dao_cat_spend = await dao_cat_wallet.create_vote_spend(
            vote_amount, proposal_id, is_yes_vote, proposal_puzzle=proposal_info.current_innerpuz
        )
        vote_amounts = []
        vote_coins = []
        previous_votes = []
        lockup_inner_puzhashes = []
        assert dao_cat_spend is not None
        for spend in dao_cat_spend.coin_spends:
            vote_amounts.append(
                Program.from_bytes(bytes(spend.solution)).at("frrrrrrf")
            )  # this is the vote_amount field of the solution
            vote_coins.append(spend.coin.name())
            previous_votes.append(
                get_active_votes_from_lockup_puzzle(
                    get_innerpuzzle_from_cat_puzzle(Program.from_bytes(bytes(spend.puzzle_reveal)))
                )
            )
            lockup_inner_puz = get_innerpuz_from_lockup_puzzle(
                get_innerpuzzle_from_cat_puzzle(Program.from_bytes(bytes(spend.puzzle_reveal)))
            )
            assert isinstance(lockup_inner_puz, Program)
            lockup_inner_puzhashes.append(lockup_inner_puz.get_tree_hash())
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
                proposal_info.current_coin.amount,
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
                proposal_info.current_coin.amount,
                inner_sol,
            ]
        )
        full_proposal_puzzle = curry_singleton(proposal_id, proposal_info.current_innerpuz)
        list_of_coinspends = [
            make_spend(proposal_info.current_coin, full_proposal_puzzle, fullsol),
            *dao_cat_spend.coin_spends,
        ]
        spend_bundle = WalletSpendBundle(list_of_coinspends, G2Element())
        if fee > 0:
            await self.standard_wallet.create_tandem_xch_tx(
                fee,
                action_scope,
            )

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
            name=spend_bundle.name(),
            memos=[],
            valid_times=parse_timelock_info(extra_conditions),
        )
        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(record)

    async def create_proposal_close_spend(
        self,
        proposal_id: bytes32,
        action_scope: WalletActionScope,
        genesis_id: Optional[bytes32] = None,
        fee: uint64 = uint64(0),
        self_destruct: bool = False,
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        self.log.info(f"Trying to create a proposal close spend with ID: {proposal_id}")
        proposal_info = None
        for pi in self.dao_info.proposals_list:
            if pi.proposal_id == proposal_id:
                proposal_info = pi
                break
        if proposal_info is None:  # pragma: no cover
            raise ValueError("Unable to find a proposal with that ID.")
        if proposal_info.timer_coin is None:  # pragma: no cover
            raise ValueError("This proposal is already closed. Feel free to unlock your coins.")
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
        if not proposal_state["closable"]:  # pragma: no cover
            raise ValueError(f"This proposal is not ready to be closed. proposal_id: {proposal_id}")
        if proposal_state["passed"]:
            self.log.info(f"Closing passed proposal: {proposal_id}")
        else:
            self.log.info(f"Closing failed proposal: {proposal_id}")
        assert proposal_info.current_innerpuz is not None
        full_proposal_puzzle = curry_singleton(proposal_id, proposal_info.current_innerpuz)
        assert proposal_info.current_coin.puzzle_hash == full_proposal_puzzle.get_tree_hash()
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
                proposal_info.current_coin.amount,
                solution,
            ]
        )
        proposal_cs = make_spend(proposal_info.current_coin, full_proposal_puzzle, fullsol)
        if not self_destruct:
            timer_puzzle = get_proposal_timer_puzzle(
                self.get_cat_tail_hash(),
                proposal_info.proposal_id,
                self.dao_info.treasury_id,
            )
            c_a, curried_args_prg = uncurry_proposal(proposal_info.current_innerpuz)
            (
                SELF_HASH,
                PROPOSAL_ID,
                PROPOSED_PUZ_HASH,
                YES_VOTES,
                TOTAL_VOTES,
            ) = c_a.as_iter()

            if TOTAL_VOTES.as_int() < attendance_required.as_int():  # pragma: no cover
                raise ValueError("Unable to pass this proposal as it has not met the minimum vote attendance.")
            timer_solution = Program.to(
                [
                    YES_VOTES,
                    TOTAL_VOTES,
                    PROPOSED_PUZ_HASH,
                    proposal_timelock,
                    proposal_id,
                    proposal_info.current_coin.amount,
                ]
            )
            timer_cs = make_spend(proposal_info.timer_coin, timer_puzzle, timer_solution)

        full_treasury_puz = curry_singleton(self.dao_info.treasury_id, self.dao_info.current_treasury_innerpuz)
        assert isinstance(self.dao_info.current_treasury_coin, Coin)
        assert full_treasury_puz.get_tree_hash() == self.dao_info.current_treasury_coin.puzzle_hash

        cat_spend_bundle = None
        delegated_puzzle_sb = None
        puzzle_reveal = await self.fetch_proposed_puzzle_reveal(proposal_id)
        if proposal_state["passed"] and not self_destruct:
            validator_solution = Program.to(
                [
                    proposal_id,
                    TOTAL_VOTES,
                    YES_VOTES,
                    proposal_info.current_coin.parent_coin_info,
                    proposal_info.current_coin.amount,
                ]
            )

            proposal_type, curried_args_prg = get_proposal_args(puzzle_reveal)
            if proposal_type == ProposalType.SPEND:
                (
                    TREASURY_SINGLETON_STRUCT,
                    CAT_MOD_HASH,
                    CONDITIONS,
                    LIST_OF_TAILHASH_CONDITIONS,
                    P2_SINGLETON_VIA_DELEGATED_PUZZLE_PUZHASH,
                ) = curried_args_prg.as_iter()

                sum = 0
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
                            cat_wallet: CATWallet = self.wallet_state_manager.wallets[self.dao_info.cat_wallet_id]
                            cat_tail_hash = cat_wallet.cat_info.limitations_program_hash
                            mint_amount = uint64(cond.rest().rest().first().as_int())
                            new_cat_puzhash = bytes32(cond.rest().rest().rest().first().first().as_atom())
                            eve_puzzle = curry_cat_eve(new_cat_puzhash)
                            if genesis_id is None:
                                tail_reconstruction = cat_wallet.cat_info.my_tail
                            else:  # pragma: no cover
                                tail_reconstruction = generate_cat_tail(genesis_id, self.dao_info.treasury_id)
                            assert tail_reconstruction is not None
                            assert tail_reconstruction.get_tree_hash() == cat_tail_hash
                            assert isinstance(self.dao_info.current_treasury_coin, Coin)
                            cat_launcher_coin = Coin(
                                self.dao_info.current_treasury_coin.name(),
                                cat_launcher.get_tree_hash(),
                                uint64(mint_amount),
                            )
                            full_puz = construct_cat_puzzle(CAT_MOD, cat_tail_hash, eve_puzzle)

                            solution = Program.to(
                                [
                                    treasury_inner_puzhash,
                                    self.dao_info.current_treasury_coin.parent_coin_info,
                                    full_puz.get_tree_hash(),
                                    mint_amount,
                                ]
                            )
                            coin_spends.append(make_spend(cat_launcher_coin, cat_launcher, solution))
                            eve_coin = Coin(cat_launcher_coin.name(), full_puz.get_tree_hash(), uint64(mint_amount))
                            tail_solution = Program.to([cat_launcher_coin.parent_coin_info, cat_launcher_coin.amount])
                            solution = Program.to([mint_amount, tail_reconstruction, tail_solution])
                            new_spendable_cat = SpendableCAT(
                                eve_coin,
                                cat_tail_hash,
                                eve_puzzle,
                                solution,
                            )
                            if cat_spend_bundle is None:
                                cat_spend_bundle = unsigned_spend_bundle_for_spendable_cats(
                                    CAT_MOD, [new_spendable_cat]
                                )
                            else:  # pragma: no cover
                                cat_spend_bundle = cat_spend_bundle.aggregate(
                                    [
                                        cat_spend_bundle,
                                        unsigned_spend_bundle_for_spendable_cats(CAT_MOD, [new_spendable_cat]),
                                    ]
                                )

                for condition_statement in CONDITIONS.as_iter():
                    if condition_statement.first().as_int() == 51:
                        sum += condition_statement.rest().rest().first().as_int()
                if sum > 0:
                    xch_coins = await self.select_coins_for_asset_type(uint64(sum), action_scope)
                    for xch_coin in xch_coins:
                        xch_parent_amount_list.append([xch_coin.parent_coin_info, xch_coin.amount])
                        solution = Program.to(
                            [
                                0,
                                treasury_inner_puzhash,
                                0,
                                0,
                                xch_coin.name(),
                            ]
                        )
                        coin_spends.append(make_spend(xch_coin, p2_singleton_puzzle, solution))
                    delegated_puzzle_sb = WalletSpendBundle(coin_spends, AugSchemeMPL.aggregate([]))
                for tail_hash_conditions_pair in LIST_OF_TAILHASH_CONDITIONS.as_iter():
                    tail_hash = bytes32(tail_hash_conditions_pair.first().as_atom())
                    conditions: Program = tail_hash_conditions_pair.rest().first()
                    sum_of_conditions = 0
                    sum_of_coins = 0
                    spendable_cat_list = []
                    for condition in conditions.as_iter():
                        if condition.first().as_int() == 51:
                            sum_of_conditions += condition.rest().rest().first().as_int()
                    cat_coins = await self.select_coins_for_asset_type(
                        uint64(sum_of_conditions), action_scope, tail_hash
                    )
                    parent_amount_list = []
                    for cat_coin in cat_coins:
                        sum_of_coins += cat_coin.amount
                        parent_amount_list.append([cat_coin.parent_coin_info, cat_coin.amount])
                        lineage_proof = await self.fetch_cat_lineage_proof(cat_coin)
                        if cat_coin == cat_coins[-1]:  # the last coin is the one that makes the conditions
                            if sum_of_coins - sum_of_conditions > 0:
                                p2_singleton_puzhash = p2_singleton_puzzle.get_tree_hash()
                                change_condition = Program.to(
                                    [
                                        51,
                                        p2_singleton_puzhash,
                                        sum_of_coins - sum_of_conditions,
                                        [p2_singleton_puzhash],
                                    ]
                                )
                                delegated_puzzle = Program.to((1, change_condition.cons(conditions)))
                            else:  # pragma: no cover
                                delegated_puzzle = Program.to((1, conditions))

                            solution = Program.to(
                                [
                                    0,
                                    treasury_inner_puzhash,
                                    delegated_puzzle,
                                    0,
                                    cat_coin.name(),
                                ]
                            )
                        else:
                            solution = Program.to(
                                [
                                    0,
                                    treasury_inner_puzhash,
                                    0,
                                    0,
                                    cat_coin.name(),
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
                            [cat_spend_bundle, unsigned_spend_bundle_for_spendable_cats(CAT_MOD, spendable_cat_list)]
                        )
                    tailhash_parent_amount_list.append([tail_hash, parent_amount_list])

                delegated_solution = Program.to(
                    [
                        xch_parent_amount_list,
                        tailhash_parent_amount_list,
                        treasury_inner_puzhash,
                    ]
                )

            elif proposal_type == ProposalType.UPDATE:
                (
                    TREASURY_MOD_HASH,
                    VALIDATOR_MOD_HASH,
                    SINGLETON_STRUCT,
                    PROPOSAL_SELF_HASH,
                    PROPOSAL_MINIMUM_AMOUNT,
                    PROPOSAL_EXCESS_PAYOUT_PUZHASH,
                    PROPOSAL_LENGTH,
                    PROPOSAL_SOFTCLOSE_LENGTH,
                    ATTENDANCE_REQUIRED,
                    PASS_MARGIN,
                    PROPOSAL_SELF_DESTRUCT_TIME,
                    ORACLE_SPEND_DELAY,
                ) = curried_args_prg.as_iter()
                coin_spends = []
                treasury_inner_puzhash = self.dao_info.current_treasury_innerpuz.get_tree_hash()
                delegated_solution = Program.to([])

            else:
                raise Exception(f"Unknown proposal type: {proposal_type!r}")

            treasury_solution = Program.to(
                [
                    [proposal_info.current_coin.name(), PROPOSED_PUZ_HASH.as_atom(), 0],
                    validator_solution,
                    puzzle_reveal,
                    delegated_solution,
                ]
            )
        else:
            treasury_solution = Program.to([0, 0, 0, 0, 0, 0])

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
                self.dao_info.current_treasury_coin.amount,
                treasury_solution,
            ]
        )

        treasury_cs = make_spend(self.dao_info.current_treasury_coin, full_treasury_puz, full_treasury_solution)

        if self_destruct:
            spend_bundle = WalletSpendBundle([proposal_cs, treasury_cs], AugSchemeMPL.aggregate([]))
        else:
            # TODO: maybe we can refactor this to provide clarity around timer_cs having been defined
            # pylint: disable-next=E0606
            spend_bundle = WalletSpendBundle([proposal_cs, timer_cs, treasury_cs], AugSchemeMPL.aggregate([]))
        if fee > 0:
            await self.standard_wallet.create_tandem_xch_tx(fee, action_scope)
        full_spend = spend_bundle
        if cat_spend_bundle is not None:
            full_spend = full_spend.aggregate([full_spend, cat_spend_bundle])
        if delegated_puzzle_sb is not None:
            full_spend = full_spend.aggregate([full_spend, delegated_puzzle_sb])

        record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=get_finished_state_puzzle(proposal_info.proposal_id).get_tree_hash(),
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
            name=full_spend.name(),
            memos=[],
            valid_times=parse_timelock_info(extra_conditions),
        )
        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(record)

    async def fetch_proposed_puzzle_reveal(self, proposal_id: bytes32) -> Program:
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer: WSChiaConnection = wallet_node.get_full_node_peer()
        if peer is None:  # pragma: no cover
            raise ValueError("Could not find any peers to request puzzle and solution from")
        # The proposal_id is launcher coin, so proposal_id's child is eve and the eve spend contains the reveal
        children = await wallet_node.fetch_children(proposal_id, peer)
        eve_state = children[0]

        eve_spend = await fetch_coin_spend(eve_state.created_height, eve_state.coin, peer)
        puzzle_reveal = get_proposed_puzzle_reveal_from_solution(eve_spend.solution.to_program())
        return puzzle_reveal

    async def fetch_cat_lineage_proof(self, cat_coin: Coin) -> LineageProof:
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer: WSChiaConnection = wallet_node.get_full_node_peer()
        if peer is None:  # pragma: no cover
            raise ValueError("Could not find any peers to request puzzle and solution from")
        state = await wallet_node.get_coin_state([cat_coin.parent_coin_info], peer)
        assert state is not None
        # CoinState contains Coin, spent_height, and created_height,
        parent_spend = await fetch_coin_spend(state[0].spent_height, state[0].coin, peer)
        parent_inner_puz = get_innerpuzzle_from_cat_puzzle(parent_spend.puzzle_reveal.to_program())
        return LineageProof(state[0].coin.parent_coin_info, parent_inner_puz.get_tree_hash(), state[0].coin.amount)

    async def _create_treasury_fund_transaction(
        self,
        funding_wallet: WalletProtocol[Any],
        amount: uint64,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        if funding_wallet.type() == WalletType.STANDARD_WALLET.value:
            p2_singleton_puzhash = get_p2_singleton_puzhash(self.dao_info.treasury_id, asset_id=None)
            wallet: Wallet = funding_wallet  # type: ignore[assignment]
            await wallet.generate_signed_transaction(
                amount,
                p2_singleton_puzhash,
                action_scope,
                fee=fee,
                memos=[p2_singleton_puzhash],
            )
        elif funding_wallet.type() == WalletType.CAT.value:
            cat_wallet: CATWallet = funding_wallet  # type: ignore[assignment]
            # generate_signed_transaction has a different type signature in Wallet and CATWallet
            # CATWallet uses a List of amounts and a List of puzhashes as the first two arguments
            p2_singleton_puzhash = get_p2_singleton_puzhash(self.dao_info.treasury_id)
            await cat_wallet.generate_signed_transaction(
                [amount],
                [p2_singleton_puzhash],
                action_scope,
                fee=fee,
                extra_conditions=extra_conditions,
            )
        else:  # pragma: no cover
            raise ValueError(f"Assets of type {funding_wallet.type()} are not currently supported.")

    async def create_add_funds_to_treasury_spend(
        self,
        amount: uint64,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        funding_wallet_id: uint32 = uint32(1),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        # set up the p2_singleton
        funding_wallet = self.wallet_state_manager.wallets[funding_wallet_id]
        await self._create_treasury_fund_transaction(
            funding_wallet, amount, action_scope, fee, extra_conditions=extra_conditions
        )

    async def fetch_singleton_lineage_proof(self, coin: Coin) -> LineageProof:
        wallet_node: Any = self.wallet_state_manager.wallet_node
        peer: WSChiaConnection = wallet_node.get_full_node_peer()
        if peer is None:  # pragma: no cover
            raise ValueError("Could not find any peers to request puzzle and solution from")
        state = await wallet_node.get_coin_state([coin.parent_coin_info], peer)
        assert state is not None
        # CoinState contains Coin, spent_height, and created_height,
        parent_spend = await fetch_coin_spend(state[0].spent_height, state[0].coin, peer)
        parent_inner_puz = get_inner_puzzle_from_singleton(parent_spend.puzzle_reveal)
        assert isinstance(parent_inner_puz, Program)
        return LineageProof(state[0].coin.parent_coin_info, parent_inner_puz.get_tree_hash(), state[0].coin.amount)

    async def free_coins_from_finished_proposals(
        self,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        dao_cat_wallet: DAOCATWallet = self.wallet_state_manager.wallets[self.dao_info.dao_cat_wallet_id]
        spends = []
        closed_list = []
        finished_puz = None
        for proposal_info in self.dao_info.proposals_list:
            if proposal_info.closed:
                closed_list.append(proposal_info.proposal_id)
                inner_solution = Program.to(
                    [
                        proposal_info.current_coin.amount,
                    ]
                )
                lineage_proof: LineageProof = await self.fetch_singleton_lineage_proof(proposal_info.current_coin)
                solution = Program.to([lineage_proof.to_program(), proposal_info.current_coin.amount, inner_solution])
                finished_puz = get_finished_state_puzzle(proposal_info.proposal_id)
                cs = make_spend(proposal_info.current_coin, finished_puz, solution)
                prop_sb = WalletSpendBundle([cs], AugSchemeMPL.aggregate([]))
                spends.append(prop_sb)

        sb = await dao_cat_wallet.remove_active_proposal(closed_list, action_scope=action_scope)
        spends.append(sb)

        if not spends:  # pragma: no cover
            raise ValueError("No proposals are available for release")

        full_spend = WalletSpendBundle.aggregate(spends)
        if fee > 0:
            await self.standard_wallet.create_tandem_xch_tx(fee, action_scope)

        assert isinstance(finished_puz, Program)
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
            name=full_spend.name(),
            memos=[],
            valid_times=parse_timelock_info(extra_conditions),
        )
        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(record)

    async def parse_proposal(self, proposal_id: bytes32) -> Dict[str, Any]:
        for prop_info in self.dao_info.proposals_list:
            if prop_info.proposal_id == proposal_id:
                state = await self.get_proposal_state(proposal_id)
                proposed_puzzle_reveal = await self.fetch_proposed_puzzle_reveal(proposal_id)
                proposal_type, curried_args = get_proposal_args(proposed_puzzle_reveal)
                if proposal_type == ProposalType.SPEND:
                    cat_launcher = create_cat_launcher_for_singleton_id(self.dao_info.treasury_id)
                    (
                        TREASURY_SINGLETON_STRUCT,
                        CAT_MOD_HASH,
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

                    asset_create_coins: List[Dict[Any, Any]] = []
                    for asset in LIST_OF_TAILHASH_CONDITIONS.as_iter():
                        if asset == Program.to(0):  # pragma: no cover
                            asset_dict: Optional[Dict[str, Any]] = None
                        else:
                            asset_id = asset.first().as_atom()
                            cc_list = []
                            for cond in asset.rest().first().as_iter():
                                if cond.first().as_int() == 51:
                                    asset_dict = {
                                        "puzzle_hash": cond.at("rf").as_atom(),
                                        "amount": cond.at("rrf").as_int(),
                                    }
                                    # cc_list.append([asset_id, asset_dict])
                                    cc_list.append(asset_dict)
                            asset_create_coins.append({"asset_id": asset_id, "conditions": cc_list})
                    dictionary: Dict[str, Any] = {
                        "state": state,
                        "proposal_type": proposal_type.value,
                        "proposed_puzzle_reveal": proposed_puzzle_reveal,
                        "xch_conditions": xch_created_coins,
                        "asset_conditions": asset_create_coins,
                    }
                    if mint_amount is not None and new_cat_puzhash is not None:
                        dictionary["mint_amount"] = mint_amount
                        dictionary["new_cat_puzhash"] = new_cat_puzhash
                elif proposal_type == ProposalType.UPDATE:
                    dao_rules = get_dao_rules_from_update_proposal(proposed_puzzle_reveal)
                    dictionary = {
                        "state": state,
                        "proposal_type": proposal_type.value,
                        "dao_rules": dao_rules,
                    }
                return dictionary
        raise ValueError(f"Unable to find proposal with id: {proposal_id.hex()}")  # pragma: no cover

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
            if wallet.type() == WalletType.DAO:  # pragma: no cover
                matched = re.search(r"^Profile (\d+)$", wallet.wallet_info.name)  # TODO: bug: wallet.wallet_info
                if matched and int(matched.group(1)) > max_num:
                    max_num = int(matched.group(1))
        return f"Profile {max_num + 1}"

    def require_derivation_paths(self) -> bool:
        return False

    def get_cat_wallet_id(self) -> uint32:
        return self.dao_info.cat_wallet_id

    async def enter_dao_cat_voting_mode(
        self,
        amount: uint64,
        action_scope: WalletActionScope,
    ) -> List[TransactionRecord]:
        dao_cat_wallet: DAOCATWallet = self.wallet_state_manager.wallets[self.dao_info.dao_cat_wallet_id]
        return await dao_cat_wallet.enter_dao_cat_voting_mode(amount, action_scope)

    @staticmethod
    def get_next_interesting_coin(spend: CoinSpend) -> Optional[Coin]:  # pragma: no cover
        # CoinSpend of one of the coins that we cared about. This coin was spent in a block, but might be in a reorg
        # If we return a value, it is a coin that we are also interested in (to support two transitions per block)
        return get_most_recent_singleton_coin_from_coin_spend(spend)

    async def add_or_update_proposal_info(
        self,
        new_state: CoinSpend,
        block_height: uint32,
    ) -> None:
        new_dao_info = copy.copy(self.dao_info)
        puzzle = get_inner_puzzle_from_singleton(new_state.puzzle_reveal)
        if puzzle is None:  # pragma: no cover
            raise ValueError("get_innerpuzzle_from_puzzle failed")
        solution = (
            Program.from_bytes(bytes(new_state.solution)).rest().rest().first()
        )  # get proposal solution from full singleton solution
        singleton_id = singleton.get_singleton_id_from_puzzle(new_state.puzzle_reveal)
        if singleton_id is None:  # pragma: no cover
            raise ValueError("get_singleton_id_from_puzzle failed")
        ended = False
        dao_rules = get_treasury_rules_from_puzzle(self.dao_info.current_treasury_innerpuz)
        current_coin = get_most_recent_singleton_coin_from_coin_spend(new_state)
        if current_coin is None:  # pragma: no cover
            raise ValueError("get_most_recent_singleton_coin_from_coin_spend failed")

        current_innerpuz = get_new_puzzle_from_proposal_solution(puzzle, solution)
        assert isinstance(current_innerpuz, Program)
        assert current_coin.puzzle_hash == curry_singleton(singleton_id, current_innerpuz).get_tree_hash()
        # check if our parent puzzle was the finished state
        if puzzle.uncurry()[0] == DAO_FINISHED_STATE:
            ended = True
            index = 0
            for current_info in new_dao_info.proposals_list:
                # Search for current proposal_info
                if current_info.proposal_id == singleton_id:
                    new_proposal_info = ProposalInfo(
                        singleton_id,
                        puzzle,
                        current_info.amount_voted,
                        current_info.yes_votes,
                        current_coin,
                        current_innerpuz,
                        current_info.timer_coin,
                        block_height,
                        current_info.passed,
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

        # check if we are the finished state
        if current_innerpuz == get_finished_state_inner_puzzle(singleton_id):
            ended = True

        c_a, curried_args = uncurry_proposal(puzzle)
        (
            DAO_PROPOSAL_TIMER_MOD_HASH,
            SINGLETON_MOD_HASH,
            SINGLETON_LAUNCHER_PUZHASH,
            CAT_MOD_HASH,
            DAO_FINISHED_STATE_HASH,
            _DAO_TREASURY_MOD_HASH,
            lockup_self_hash,
            cat_tail_hash,
            treasury_id,
        ) = curried_args.as_iter()
        (
            curry_one,
            proposal_id,
            proposed_puzzle_hash,
            yes_votes,
            total_votes,
        ) = c_a.as_iter()

        if current_coin is None:  # pragma: no cover
            raise RuntimeError("get_most_recent_singleton_coin_from_coin_spend({new_state}) failed")

        timer_coin = None
        if solution.at("rrrrrrf").as_int() == 0:
            # we need to add the vote amounts from the solution to get accurate totals
            is_yes_vote = solution.at("rf").as_int()
            votes_added = 0
            for vote_amount in solution.first().as_iter():
                votes_added += vote_amount.as_int()
        else:
            # If we have entered the finished state
            # TODO: we need to alert the user that they can free up their coins
            is_yes_vote = 0
            votes_added = 0

        if current_coin.amount < dao_rules.proposal_minimum_amount and not ended:  # pragma: no cover
            raise ValueError("this coin does not meet the minimum requirements and can be ignored")
        new_total_votes = total_votes.as_int() + votes_added
        if new_total_votes < self.dao_info.filter_below_vote_amount:  # pragma: no cover
            return  # ignore all proposals below the filter amount

        if is_yes_vote == 1:
            new_yes_votes = yes_votes.as_int() + votes_added
        else:
            new_yes_votes = yes_votes.as_int()

        required_yes_votes = (self.dao_rules.attendance_required * self.dao_rules.pass_percentage) // 10000
        yes_votes_needed = max(0, required_yes_votes - new_yes_votes)

        passed = True if yes_votes_needed == 0 else False

        index = 0
        for current_info in new_dao_info.proposals_list:
            # Search for current proposal_info
            if current_info.proposal_id == singleton_id:
                # If we are receiving a voting spend update
                new_proposal_info = ProposalInfo(
                    singleton_id,
                    puzzle,
                    uint64(new_total_votes),
                    uint64(new_yes_votes),
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
            if peer is None:  # pragma: no cover
                raise ValueError("Could not find any peers to request puzzle and solution from")
            children = await wallet_node.fetch_children(singleton_id, peer)
            assert len(children) > 0
            found = False
            parent_coin_id = singleton_id

            if self.dao_info.current_treasury_innerpuz is None:  # pragma: no cover
                raise ValueError("self.dao_info.current_treasury_innerpuz is None")

            timer_coin_puzhash = get_proposal_timer_puzzle(
                bytes32(cat_tail_hash.as_atom()),
                singleton_id,
                self.dao_info.treasury_id,
            ).get_tree_hash()

            while not found and len(children) > 0:
                children = await wallet_node.fetch_children(parent_coin_id, peer)
                if len(children) == 0:  # pragma: no cover
                    break
                children_state = [child for child in children if child.coin.amount % 2 == 1]
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
        # We only want to add this coin if it has a timer coin since fake proposals without a timer can
        # be created.
        if found:
            new_proposal_info = ProposalInfo(
                singleton_id,
                puzzle,
                uint64(new_total_votes),
                uint64(new_yes_votes),
                current_coin,
                current_innerpuz,
                timer_coin,  # if this is None then the proposal has finished
                block_height,  # block height that current proposal singleton coin was created
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

    async def update_closed_proposal_coin(self, new_state: CoinSpend, block_height: uint32) -> None:
        new_dao_info = copy.copy(self.dao_info)
        puzzle = get_inner_puzzle_from_singleton(new_state.puzzle_reveal)
        proposal_id = singleton.get_singleton_id_from_puzzle(new_state.puzzle_reveal)
        current_coin = get_most_recent_singleton_coin_from_coin_spend(new_state)
        index = 0
        for pi in self.dao_info.proposals_list:
            if pi.proposal_id == proposal_id:
                assert isinstance(current_coin, Coin)
                new_info = ProposalInfo(
                    proposal_id,
                    pi.inner_puzzle,
                    pi.amount_voted,
                    pi.yes_votes,
                    current_coin,
                    pi.current_innerpuz,
                    pi.timer_coin,
                    pi.singleton_block_height,
                    pi.passed,
                    pi.closed,
                )
                new_dao_info.proposals_list[index] = new_info
                await self.save_info(new_dao_info)
                assert isinstance(puzzle, Program)
                future_parent = LineageProof(
                    new_state.coin.parent_coin_info,
                    puzzle.get_tree_hash(),
                    uint64(new_state.coin.amount),
                )
                await self.add_parent(new_state.coin.name(), future_parent)
                return
            index = index + 1

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
        else:  # pragma: no cover
            raise ValueError(f"Proposal not found for id {proposal_id}")

        wallet_node = self.wallet_state_manager.wallet_node
        peer: WSChiaConnection = wallet_node.get_full_node_peer()
        if peer is None:  # pragma: no cover
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
        if puzzle is None:  # pragma: no cover
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
        dao_info = dataclasses.replace(
            self.dao_info,
            current_treasury_coin=child_coin,
            current_treasury_innerpuz=new_innerpuz,
            singleton_block_height=block_height,
        )
        await self.save_info(dao_info)
        future_parent = LineageProof(
            new_state.coin.parent_coin_info,
            puzzle.get_tree_hash(),
            uint64(new_state.coin.amount),
        )
        await self.add_parent(new_state.coin.name(), future_parent)
        return

    async def apply_state_transition(self, new_state: CoinSpend, block_height: uint32) -> bool:
        """
        We are being notified of a singleton state transition. A Singleton has been spent.
        Returns True iff the spend is a valid transition spend for the singleton, False otherwise.
        """

        self.log.info(
            f"DAOWallet.apply_state_transition called with the height: {block_height} "
            f"and CoinSpend of {new_state.coin.name()}."
        )
        singleton_id = get_singleton_id_from_puzzle(new_state.puzzle_reveal)
        if not singleton_id:  # pragma: no cover
            raise ValueError("Received a non singleton coin for dao wallet")

        # Consume new DAOBlockchainInfo
        # Determine if this is a treasury spend or a proposal spend
        puzzle = get_inner_puzzle_from_singleton(new_state.puzzle_reveal)
        assert puzzle
        try:
            mod, curried_args = puzzle.uncurry()
        except ValueError as e:  # pragma: no cover
            self.log.warning("Cannot uncurry puzzle in DAO Wallet: error: %s", e)
            raise e
        if mod == DAO_TREASURY_MOD:
            await self.update_treasury_info(new_state, block_height)
        elif (mod == DAO_PROPOSAL_MOD) or (mod.uncurry()[0] == DAO_PROPOSAL_MOD):
            await self.add_or_update_proposal_info(new_state, block_height)
        elif mod == DAO_FINISHED_STATE:
            await self.update_closed_proposal_coin(new_state, block_height)
        else:  # pragma: no cover
            raise ValueError(f"Unsupported spend in DAO Wallet: {self.id()}")

        return True
