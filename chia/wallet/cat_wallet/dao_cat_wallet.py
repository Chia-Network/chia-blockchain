from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, ClassVar, List, Optional, Set, Tuple, cast

from chia_rs import G1Element

from chia.server.ws_connection import WSChiaConnection
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint32, uint64, uint128
from chia.wallet.cat_wallet.cat_utils import (
    CAT_MOD,
    SpendableCAT,
    construct_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.cat_wallet.dao_cat_info import DAOCATInfo, LockedCoinInfo
from chia.wallet.cat_wallet.lineage_store import CATLineageStore
from chia.wallet.conditions import Condition, CreatePuzzleAnnouncement, parse_timelock_info
from chia.wallet.dao_wallet.dao_utils import (
    add_proposal_to_active_list,
    get_active_votes_from_lockup_puzzle,
    get_finished_state_inner_puzzle,
    get_innerpuz_from_lockup_puzzle,
    get_lockup_puzzle,
)
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.payment import Payment
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.curry_and_treehash import calculate_hash_of_quoted_mod_hash
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.tx_config import TXConfig
from chia.wallet.util.wallet_sync_utils import fetch_coin_spend
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_action_scope import WalletActionScope
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_spend_bundle import WalletSpendBundle

if TYPE_CHECKING:
    from chia.wallet.wallet_state_manager import WalletStateManager

CAT_MOD_HASH = CAT_MOD.get_tree_hash()
CAT_MOD_HASH_HASH = Program.to(CAT_MOD_HASH).get_tree_hash()
QUOTED_MOD_HASH = calculate_hash_of_quoted_mod_hash(CAT_MOD_HASH)


class DAOCATWallet:
    if TYPE_CHECKING:
        from chia.wallet.wallet_protocol import WalletProtocol

        _protocol_check: ClassVar[WalletProtocol[DAOCATInfo]] = cast("DAOCATWallet", None)

    wallet_state_manager: Any
    log: logging.Logger
    wallet_info: WalletInfo
    dao_cat_info: DAOCATInfo
    standard_wallet: Wallet
    cost_of_single_tx: Optional[int]
    lineage_store: CATLineageStore

    @classmethod
    def type(cls) -> WalletType:
        return WalletType.DAO_CAT

    @staticmethod
    async def create(
        wallet_state_manager: WalletStateManager,
        wallet: Wallet,
        wallet_info: WalletInfo,
    ) -> DAOCATWallet:
        self = DAOCATWallet()
        self.log = logging.getLogger(__name__)

        self.cost_of_single_tx = None
        self.wallet_state_manager = wallet_state_manager
        self.wallet_info = wallet_info
        self.standard_wallet = wallet
        try:
            self.dao_cat_info = DAOCATInfo.from_bytes(hexstr_to_bytes(self.wallet_info.data))
            self.lineage_store = await CATLineageStore.create(self.wallet_state_manager.db_wrapper, self.get_asset_id())
        except AssertionError as e:  # pragma: no cover
            self.log.error(f"Error creating DAO CAT wallet: {e}")

        return self

    @staticmethod
    async def get_or_create_wallet_for_cat(
        wallet_state_manager: Any,
        wallet: Wallet,
        limitations_program_hash_hex: str,
        name: Optional[str] = None,
    ) -> DAOCATWallet:
        self = DAOCATWallet()
        self.cost_of_single_tx = None
        self.standard_wallet = wallet
        self.log = logging.getLogger(__name__)

        limitations_program_hash_hex = bytes32.from_hexstr(limitations_program_hash_hex).hex()  # Normalize the format

        dao_wallet_id = None
        free_cat_wallet_id = None
        for id, w in wallet_state_manager.wallets.items():
            if w.type() == DAOCATWallet.type():
                assert isinstance(w, DAOCATWallet)
                if w.get_asset_id() == limitations_program_hash_hex:
                    self.log.warning("Not creating wallet for already existing DAO CAT wallet")
                    return w
            elif w.type() == CATWallet.type():
                assert isinstance(w, CATWallet)
                if w.get_asset_id() == limitations_program_hash_hex:
                    free_cat_wallet_id = w.id()
        assert free_cat_wallet_id is not None
        for id, w in wallet_state_manager.wallets.items():
            if w.type() == WalletType.DAO:
                self.log.info(f"FOUND DAO WALLET: {w}")
                self.log.info(f"ALL WALLETS: {wallet_state_manager.wallets}")
                if w.get_cat_wallet_id() == free_cat_wallet_id:
                    dao_wallet_id = w.id()
        assert dao_wallet_id is not None
        self.wallet_state_manager = wallet_state_manager
        if name is None:
            name = CATWallet.default_wallet_name_for_unknown_cat(limitations_program_hash_hex)

        limitations_program_hash = bytes32.from_hexstr(limitations_program_hash_hex)

        self.dao_cat_info = DAOCATInfo(
            dao_wallet_id,
            uint64(free_cat_wallet_id),
            limitations_program_hash,
            None,
            [],
        )
        info_as_string = bytes(self.dao_cat_info).hex()
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(name, WalletType.DAO_CAT, info_as_string)

        self.lineage_store = await CATLineageStore.create(self.wallet_state_manager.db_wrapper, self.get_asset_id())
        await self.wallet_state_manager.add_new_wallet(self)
        return self

    async def coin_added(self, coin: Coin, height: uint32, peer: WSChiaConnection, coin_data: Optional[Any]) -> None:
        """Notification from wallet state manager that wallet has been received."""
        self.log.info(f"DAO CAT wallet has been notified that {coin} was added")
        wallet_node: Any = self.wallet_state_manager.wallet_node
        parent_coin = (await wallet_node.get_coin_state([coin.parent_coin_info], peer, height))[0]
        parent_spend = await fetch_coin_spend(height, parent_coin.coin, peer)
        uncurried = parent_spend.puzzle_reveal.uncurry()
        cat_inner = uncurried[1].at("rrf")
        active_votes_list: List[Optional[bytes32]] = []

        record = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(coin.puzzle_hash)
        if record:
            inner_puzzle: Optional[Program] = self.standard_wallet.puzzle_for_pk(record.pubkey)
        else:
            inner_puzzle = get_innerpuz_from_lockup_puzzle(cat_inner)
            assert isinstance(inner_puzzle, Program)
            active_votes_list_prg = get_active_votes_from_lockup_puzzle(cat_inner)
            active_votes_list = [bytes32(x.as_atom()) for x in active_votes_list_prg.as_iter()]

        if parent_spend.coin.puzzle_hash == coin.puzzle_hash:
            # shortcut, works for change
            lockup_puz = cat_inner
        else:
            solution = parent_spend.solution.to_program().first()
            if solution.first() == Program.to(0):
                # No vote is being added so inner puz stays the same
                try:
                    removals = solution.at("rrrf")
                    if removals != Program.to(0):
                        for removal in removals.as_iter():
                            active_votes_list.remove(bytes32(removal.as_atom()))
                except Exception:
                    pass
            else:
                new_vote = solution.at("rrrf")
                active_votes_list.insert(0, bytes32(new_vote.as_atom()))

            lockup_puz = get_lockup_puzzle(
                self.dao_cat_info.limitations_program_hash,
                active_votes_list,
                inner_puzzle,
            )

        new_cat_puzhash = construct_cat_puzzle(
            CAT_MOD, self.dao_cat_info.limitations_program_hash, lockup_puz
        ).get_tree_hash()

        if new_cat_puzhash != coin.puzzle_hash:  # pragma: no cover
            raise ValueError(f"Cannot add coin - incorrect lockup puzzle: {coin}")

        lineage_proof = LineageProof(coin.parent_coin_info, lockup_puz.get_tree_hash(), uint64(coin.amount))
        await self.add_lineage(coin.name(), lineage_proof)

        # add the new coin to the list of locked coins and remove the spent coin
        locked_coins = [x for x in self.dao_cat_info.locked_coins if x.coin != parent_spend.coin]
        new_info = LockedCoinInfo(coin, lockup_puz, active_votes_list)
        if new_info not in locked_coins:
            locked_coins.append(LockedCoinInfo(coin, lockup_puz, active_votes_list))
        dao_cat_info: DAOCATInfo = DAOCATInfo(
            self.dao_cat_info.dao_wallet_id,
            self.dao_cat_info.free_cat_wallet_id,
            self.dao_cat_info.limitations_program_hash,
            self.dao_cat_info.my_tail,
            locked_coins,
        )
        await self.save_info(dao_cat_info)

    async def add_lineage(self, name: bytes32, lineage: Optional[LineageProof]) -> None:
        """
        Lineage proofs are stored as a list of parent coins and the lineage proof you will need if they are the
        parent of the coin you are trying to spend. 'If I'm your parent, here's the info you need to spend yourself'
        """
        self.log.info(f"Adding parent {name.hex()}: {lineage}")
        if lineage is not None:
            await self.lineage_store.add_lineage_proof(name, lineage)

    async def get_lineage_proof_for_coin(self, coin: Coin) -> Optional[LineageProof]:
        return await self.lineage_store.get_lineage_proof(coin.parent_coin_info)

    async def remove_lineage(self, name: bytes32) -> None:  # pragma: no cover
        self.log.info(f"Removing parent {name} (probably had a non-CAT parent)")
        await self.lineage_store.remove_lineage_proof(name)

    async def advanced_select_coins(self, amount: uint64, proposal_id: bytes32) -> List[LockedCoinInfo]:
        coins = []
        s = 0
        for coin in self.dao_cat_info.locked_coins:
            compatible = True
            for active_vote in coin.active_votes:
                if active_vote == proposal_id:  # pragma: no cover
                    compatible = False
                    break
            if compatible:
                coins.append(coin)
                s += coin.coin.amount
                if s >= amount:
                    break
        if s < amount:  # pragma: no cover
            raise ValueError(
                "We do not have enough CATs in Voting Mode right now. "
                "Please convert some more or try again with permission to convert."
            )
        return coins

    def id(self) -> uint32:
        return self.wallet_info.id

    async def create_vote_spend(
        self,
        amount: uint64,
        proposal_id: bytes32,
        is_yes_vote: bool,
        proposal_puzzle: Optional[Program] = None,
    ) -> WalletSpendBundle:
        coins: List[LockedCoinInfo] = await self.advanced_select_coins(amount, proposal_id)
        running_sum = 0  # this will be used for change calculation
        change = sum(c.coin.amount for c in coins) - amount
        extra_delta, limitations_solution = 0, Program.to([])
        limitations_program_reveal = Program.to([])
        spendable_cat_list = []
        dao_wallet = self.wallet_state_manager.wallets[self.dao_cat_info.dao_wallet_id]
        if proposal_puzzle is None:  # pragma: no cover
            proposal_puzzle = dao_wallet.get_proposal_puzzle(proposal_id)
        assert proposal_puzzle is not None
        for lci in coins:
            coin = lci.coin
            vote_info = 0
            new_innerpuzzle = add_proposal_to_active_list(lci.inner_puzzle, proposal_id)
            assert new_innerpuzzle is not None
            standard_inner_puz = get_innerpuz_from_lockup_puzzle(new_innerpuzzle)
            assert isinstance(standard_inner_puz, Program)
            # add_proposal_to_active_list also verifies that the lci.inner_puzzle is accurate
            # We must create either: one coin with the new puzzle and all our value
            # OR
            # a coin with the new puzzle and part of our amount AND a coin with our current puzzle and the change
            # We must also create a puzzle announcement which announces the following:
            # message = (sha256tree (list new_proposal_vote_id_or_removal_id vote_amount vote_info my_id))
            message = Program.to([proposal_id, amount, is_yes_vote, coin.name()]).get_tree_hash()
            vote_amounts_list = []
            voting_coin_id_list = []
            previous_votes_list = []
            lockup_innerpuz_list = []
            if running_sum + coin.amount <= amount:
                vote_amount = coin.amount
                running_sum = running_sum + coin.amount
                primaries = [
                    Payment(
                        new_innerpuzzle.get_tree_hash(),
                        vote_amount,
                        [standard_inner_puz.get_tree_hash()],
                    )
                ]
                message = Program.to([proposal_id, vote_amount, is_yes_vote, coin.name()]).get_tree_hash()
                inner_solution = self.standard_wallet.make_solution(
                    primaries=primaries,
                    conditions=(CreatePuzzleAnnouncement(message),),
                )
            else:
                vote_amount = uint64(amount - running_sum)
                running_sum = running_sum + coin.amount
                primaries = [
                    Payment(
                        new_innerpuzzle.get_tree_hash(),
                        vote_amount,
                        [standard_inner_puz.get_tree_hash()],
                    ),
                ]
                if change > 0:
                    primaries.append(
                        Payment(
                            lci.inner_puzzle.get_tree_hash(),
                            uint64(change),
                            [lci.inner_puzzle.get_tree_hash()],
                        )
                    )
                message = Program.to([proposal_id, vote_amount, is_yes_vote, coin.name()]).get_tree_hash()
                inner_solution = self.standard_wallet.make_solution(
                    primaries=primaries,
                    conditions=(CreatePuzzleAnnouncement(message),),
                )
            if is_yes_vote:
                vote_info = 1
            vote_amounts_list.append(vote_amount)
            voting_coin_id_list.append(coin.name())
            previous_votes_list.append(get_active_votes_from_lockup_puzzle(lci.inner_puzzle))
            lockup_innerpuz_list.append(get_innerpuz_from_lockup_puzzle(lci.inner_puzzle))
            solution = Program.to(
                [
                    coin.name(),
                    inner_solution,
                    coin.amount,
                    proposal_id,
                    proposal_puzzle.get_tree_hash(),
                    vote_info,
                    vote_amount,
                    lci.inner_puzzle.get_tree_hash(),
                    0,
                ]
            )
            lineage_proof = await self.get_lineage_proof_for_coin(coin)
            assert lineage_proof is not None
            new_spendable_cat = SpendableCAT(
                coin,
                self.dao_cat_info.limitations_program_hash,
                lci.inner_puzzle,
                solution,
                limitations_solution=limitations_solution,
                extra_delta=extra_delta,
                lineage_proof=lineage_proof,
                limitations_program_reveal=limitations_program_reveal,
            )
            spendable_cat_list.append(new_spendable_cat)

        cat_spend_bundle = unsigned_spend_bundle_for_spendable_cats(CAT_MOD, spendable_cat_list)
        return cat_spend_bundle

    async def enter_dao_cat_voting_mode(
        self,
        amount: uint64,
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> List[TransactionRecord]:
        """
        Enter existing CATs for the DAO into voting mode
        """
        # check there are enough cats to convert
        cat_wallet = self.wallet_state_manager.wallets[self.dao_cat_info.free_cat_wallet_id]
        cat_balance = await cat_wallet.get_spendable_balance()
        if cat_balance < amount:  # pragma: no cover
            raise ValueError(f"Insufficient CAT balance. Requested: {amount} Available: {cat_balance}")
        # get the lockup puzzle hash
        lockup_puzzle = await self.get_new_puzzle()
        # create the cat spend
        txs: List[TransactionRecord] = await cat_wallet.generate_signed_transaction(
            [amount],
            [lockup_puzzle.get_tree_hash()],
            action_scope,
            fee=fee,
            extra_conditions=extra_conditions,
        )
        cat_puzzle_hash: bytes32 = construct_cat_puzzle(
            CAT_MOD, self.dao_cat_info.limitations_program_hash, lockup_puzzle
        ).get_tree_hash()
        await self.wallet_state_manager.add_interested_puzzle_hashes([cat_puzzle_hash], [self.id()])
        return txs

    async def exit_vote_state(
        self,
        coins: List[LockedCoinInfo],
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
        extra_conditions: Tuple[Condition, ...] = tuple(),
    ) -> None:
        extra_delta, limitations_solution = 0, Program.to([])
        limitations_program_reveal = Program.to([])
        spendable_cat_list = []
        total_amt = 0
        spent_coins = []
        for lci in coins:
            coin = lci.coin
            if action_scope.config.tx_config.reuse_puzhash:  # pragma: no cover
                new_inner_puzhash = await self.standard_wallet.get_puzzle_hash(new=False)
            else:
                new_inner_puzhash = await self.standard_wallet.get_puzzle_hash(new=True)

            # CREATE_COIN new_puzzle coin.amount
            primaries = [
                Payment(
                    new_inner_puzhash,
                    uint64(coin.amount),
                    [new_inner_puzhash],
                ),
            ]
            total_amt += coin.amount
            inner_solution = self.standard_wallet.make_solution(
                primaries=primaries,
            )
            # Create the solution using only the values needed for exiting the lockup mode (my_id = 0)
            solution = Program.to(
                [
                    0,  # my_id
                    inner_solution,
                    coin.amount,
                    0,  # new_proposal_vote_id_or_removal_id
                    0,  # proposal_innerpuzhash
                    0,  # vote_info
                    0,  # vote_amount
                    0,  # my_inner_puzhash
                ]
            )
            lineage_proof = await self.get_lineage_proof_for_coin(coin)
            assert lineage_proof is not None
            new_spendable_cat = SpendableCAT(
                coin,
                self.dao_cat_info.limitations_program_hash,
                lci.inner_puzzle,
                solution,
                limitations_solution=limitations_solution,
                extra_delta=extra_delta,
                lineage_proof=lineage_proof,
                limitations_program_reveal=limitations_program_reveal,
            )
            spendable_cat_list.append(new_spendable_cat)
            spent_coins.append(coin)

        spend_bundle = unsigned_spend_bundle_for_spendable_cats(CAT_MOD, spendable_cat_list)

        if fee > 0:  # pragma: no cover
            await self.standard_wallet.create_tandem_xch_tx(
                fee,
                action_scope,
            )

        record = TransactionRecord(
            confirmed_at_height=uint32(0),
            created_at_time=uint64(int(time.time())),
            to_puzzle_hash=new_inner_puzhash,
            amount=uint64(total_amt),
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

        # TODO: Hack to just drop coins from locked list. Need to catch this event in WSM to
        # check if we're adding CATs from our DAO CAT wallet and update the locked coin list
        # accordingly
        new_locked_coins = [x for x in self.dao_cat_info.locked_coins if x.coin not in spent_coins]
        dao_cat_info: DAOCATInfo = DAOCATInfo(
            self.dao_cat_info.dao_wallet_id,
            self.dao_cat_info.free_cat_wallet_id,
            self.dao_cat_info.limitations_program_hash,
            self.dao_cat_info.my_tail,
            new_locked_coins,
        )
        await self.save_info(dao_cat_info)
        async with action_scope.use() as interface:
            interface.side_effects.transactions.append(record)

    async def remove_active_proposal(
        self,
        proposal_id_list: List[bytes32],
        action_scope: WalletActionScope,
        fee: uint64 = uint64(0),
    ) -> WalletSpendBundle:
        locked_coins: List[Tuple[LockedCoinInfo, List[bytes32]]] = []
        for lci in self.dao_cat_info.locked_coins:
            my_finished_proposals = []
            for active_vote in lci.active_votes:
                if active_vote in proposal_id_list:
                    my_finished_proposals.append(active_vote)
            if my_finished_proposals:
                locked_coins.append((lci, my_finished_proposals))
        extra_delta, limitations_solution = 0, Program.to([])
        limitations_program_reveal = Program.to([])
        spendable_cat_list = []

        for lci_proposals_tuple in locked_coins:
            proposal_innerpuzhashes = []
            coin = lci_proposals_tuple[0].coin
            lci = lci_proposals_tuple[0]
            proposals = lci_proposals_tuple[1]
            for proposal_id in proposals:
                INNERPUZ = get_finished_state_inner_puzzle(proposal_id)
                proposal_innerpuzhashes.append(INNERPUZ)
            # new_innerpuzzle = await cat_wallet.get_new_inner_puzzle()
            # my_id  ; if my_id is 0 we do the return to return_address (exit voting mode) spend case
            # inner_solution
            # my_amount
            # new_proposal_vote_id_or_removal_id  ; if we're exiting fully, set this to 0
            # proposal_curry_vals
            # vote_info
            # vote_amount
            # my_puzhash
            solution = Program.to(
                [
                    0,
                    0,
                    coin.amount,
                    proposals,
                    0,
                    0,
                    0,
                    0,
                    0,
                ]
            )
            lineage_proof = await self.get_lineage_proof_for_coin(coin)
            assert lineage_proof is not None
            new_spendable_cat = SpendableCAT(
                coin,
                self.dao_cat_info.limitations_program_hash,
                lci.inner_puzzle,
                solution,
                limitations_solution=limitations_solution,
                extra_delta=extra_delta,
                lineage_proof=lineage_proof,
                limitations_program_reveal=limitations_program_reveal,
            )
            spendable_cat_list.append(new_spendable_cat)

        spend_bundle = unsigned_spend_bundle_for_spendable_cats(CAT_MOD, spendable_cat_list)

        if fee > 0:  # pragma: no cover
            await self.standard_wallet.create_tandem_xch_tx(fee, action_scope=action_scope)

        return spend_bundle

    def get_asset_id(self) -> str:
        return bytes(self.dao_cat_info.limitations_program_hash).hex()

    async def get_new_inner_hash(self, tx_config: TXConfig) -> bytes32:
        puzzle = await self.get_new_inner_puzzle(tx_config)
        return puzzle.get_tree_hash()

    async def get_new_inner_puzzle(self, tx_config: TXConfig) -> Program:
        return await self.standard_wallet.get_puzzle(new=not tx_config.reuse_puzhash)

    async def get_new_puzzle(self) -> Program:
        record = await self.wallet_state_manager.get_unused_derivation_record(self.id())
        inner_puzzle = self.standard_wallet.puzzle_for_pk(record.pubkey)
        puzzle = get_lockup_puzzle(
            self.dao_cat_info.limitations_program_hash,
            [],
            inner_puzzle,
        )
        cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, self.dao_cat_info.limitations_program_hash, puzzle)
        await self.wallet_state_manager.add_interested_puzzle_hashes([puzzle.get_tree_hash()], [self.id()])
        await self.wallet_state_manager.add_interested_puzzle_hashes([cat_puzzle.get_tree_hash()], [self.id()])
        return puzzle

    async def get_new_puzzlehash(self) -> bytes32:
        puzzle = await self.get_new_puzzle()
        return puzzle.get_tree_hash()

    def puzzle_for_pk(self, pubkey: G1Element) -> Program:
        inner_puzzle = self.standard_wallet.puzzle_for_pk(pubkey)
        puzzle = get_lockup_puzzle(
            self.dao_cat_info.limitations_program_hash,
            [],
            inner_puzzle,
        )
        cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, self.dao_cat_info.limitations_program_hash, puzzle)
        return cat_puzzle

    def puzzle_hash_for_pk(self, pubkey: G1Element) -> bytes32:
        puzzle = self.puzzle_for_pk(pubkey)
        return puzzle.get_tree_hash()

    def require_derivation_paths(self) -> bool:
        return True

    async def match_hinted_coin(self, coin: Coin, hint: bytes32) -> bool:
        raise NotImplementedError("Method not implemented for DAO CAT Wallet")  # pragma: no cover

    async def get_spendable_balance(self, records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        return uint128(0)

    async def get_confirmed_balance(self, record_list: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        amount = 0
        for coin in self.dao_cat_info.locked_coins:
            amount += coin.coin.amount
        return uint128(amount)

    async def get_unconfirmed_balance(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        return uint128(0)

    async def get_pending_change_balance(self) -> uint64:
        return uint64(0)

    async def select_coins(
        self,
        amount: uint64,
        action_scope: WalletActionScope,
    ) -> Set[Coin]:
        return set()

    async def get_max_send_amount(self, unspent_records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        return uint128(0)

    async def get_votable_balance(
        self,
        proposal_id: Optional[bytes32] = None,
        include_free_cats: bool = True,
    ) -> uint64:
        balance = 0
        for coin in self.dao_cat_info.locked_coins:
            if proposal_id is not None:
                compatible = True
                for active_vote in coin.active_votes:
                    if active_vote == proposal_id:
                        compatible = False
                        break
                if compatible:
                    balance += coin.coin.amount
            else:
                balance += coin.coin.amount
        if include_free_cats:
            cat_wallet = self.wallet_state_manager.wallets[self.dao_cat_info.free_cat_wallet_id]
            cat_balance = await cat_wallet.get_spendable_balance()
            balance += cat_balance
        return uint64(balance)

    async def save_info(self, dao_cat_info: DAOCATInfo) -> None:
        self.dao_cat_info = dao_cat_info
        current_info = self.wallet_info
        data_str = bytes(dao_cat_info).hex()
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info)

    def get_name(self) -> str:
        return self.wallet_info.name
