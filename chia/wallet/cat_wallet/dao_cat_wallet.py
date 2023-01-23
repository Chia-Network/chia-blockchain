from __future__ import annotations

import logging
import traceback
from typing import List, Optional, Set
from blspy import AugSchemeMPL, G1Element, G2Element
from chia.wallet.derivation_record import DerivationRecord
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.wallet.uncurried_puzzle import uncurry_puzzle
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
)
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.server.ws_connection import WSChiaConnection
from chia.wallet.lineage_proof import LineageProof
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint8, uint32, uint64, uint128
from chia.wallet.cat_wallet.cat_utils import (
    SpendableCAT,
    construct_cat_puzzle,
    match_cat_puzzle,
    unsigned_spend_bundle_for_spendable_cats,
)
from chia.types.spend_bundle import SpendBundle
from chia.wallet.cat_wallet.cat_wallet import CATWallet
from chia.wallet.cat_wallet.dao_cat_info import DAOCATInfo, LockedCoinInfo
from chia.wallet.cat_wallet.lineage_store import CATLineageStore
from chia.wallet.coin_selection import select_coins
from chia.wallet.dao_wallet.dao_utils import get_lockup_puzzle, add_proposal_to_active_list
from chia.wallet.puzzles.cat_loader import CAT_MOD
from chia.wallet.util.curry_and_treehash import calculate_hash_of_quoted_mod_hash
from chia.wallet.util.wallet_types import WalletType
from chia.wallet.wallet import Wallet
from chia.wallet.wallet_coin_record import WalletCoinRecord
from chia.wallet.wallet_info import WalletInfo
from chia.wallet.wallet_state_manager import WalletStateManager

CAT_MOD_HASH = CAT_MOD.get_tree_hash()
CAT_MOD_HASH_HASH = Program.to(CAT_MOD_HASH).get_tree_hash()
QUOTED_MOD_HASH = calculate_hash_of_quoted_mod_hash(CAT_MOD_HASH)


class DAOCATWallet:
    wallet_state_manager: WalletStateManager
    log: logging.Logger
    wallet_info: WalletInfo
    dao_cat_info: DAOCATInfo
    standard_wallet: Wallet
    cost_of_single_tx: Optional[int]
    lineage_store: CATLineageStore

    @classmethod
    def type(cls) -> uint8:
        return uint8(WalletType.DAO_CAT)

    @staticmethod
    async def get_or_create_wallet_for_cat(
        wallet_state_manager: WalletStateManager,
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
                if w.get_cat_wallet_id() == free_cat_wallet_id:
                    dao_wallet_id = w.id()
        assert dao_wallet_id is not None
        self.wallet_state_manager = wallet_state_manager
        if name is None:
            name = CATWallet.default_wallet_name_for_unknown_cat(limitations_program_hash_hex)

        limitations_program_hash = bytes32(hexstr_to_bytes(limitations_program_hash_hex))

        self.dao_cat_info = DAOCATInfo(
            dao_wallet_id,
            free_cat_wallet_id,
            limitations_program_hash,
            None,
            [],
        )
        info_as_string = bytes(self.dao_cat_info).hex()
        self.wallet_info = await wallet_state_manager.user_store.create_wallet(name, WalletType.DAO_CAT, info_as_string)

        self.lineage_store = await CATLineageStore.create(self.wallet_state_manager.db_wrapper, self.get_asset_id())
        await self.wallet_state_manager.add_new_wallet(self, self.id())
        return self

    async def inner_puzzle_for_cat_puzhash(self, cat_hash: bytes32) -> Program:
        record: Optional[
            DerivationRecord
        ] = await self.wallet_state_manager.puzzle_store.get_derivation_record_for_puzzle_hash(cat_hash)
        if record is None:
            raise RuntimeError(f"Missing Derivation Record for CAT puzzle_hash {cat_hash}")
        inner_puzzle: Program = self.standard_wallet.puzzle_for_pk(record.pubkey)
        return inner_puzzle

    async def coin_added(self, coin: Coin, height: uint32, peer: WSChiaConnection) -> None:
        """Notification from wallet state manager that wallet has been received."""
        self.log.info(f"CAT wallet has been notified that {coin} was added")

        inner_puzzle = await self.inner_puzzle_for_cat_puzhash(coin.puzzle_hash)
        lineage_proof = LineageProof(coin.parent_coin_info, inner_puzzle.get_tree_hash(), uint64(coin.amount))
        # breakpoint()  # if we get here, then success
        await self.add_lineage(coin.name(), lineage_proof)

        lineage = await self.get_lineage_proof_for_coin(coin)

        if lineage is None:
            try:
                coin_state = await self.wallet_state_manager.wallet_node.get_coin_state(
                    [coin.parent_coin_info], peer=peer
                )
                assert coin_state[0].coin.name() == coin.parent_coin_info
                coin_spend = await self.wallet_state_manager.wallet_node.fetch_puzzle_solution(
                    coin_state[0].spent_height, coin_state[0].coin, peer
                )
                await self.puzzle_solution_received(coin_spend, parent_coin=coin_state[0].coin)
            except Exception as e:
                self.log.debug(f"Exception: {e}, traceback: {traceback.format_exc()}")

        # add the new coin to the list of locked coins.
        # GW: I'm not sure if we want to update the dao cat info here here?
        #     Should the incoming coins to this wallet already have a proposal ID?
        # Matt - I changed the dao_cat_info to use previous_votes instead of active_proposal_votes
        locked_coins = self.dao_cat_info.locked_coins
        locked_coins.append(LockedCoinInfo(coin, inner_puzzle, []))
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

    async def remove_lineage(self, name: bytes32) -> None:
        self.log.info(f"Removing parent {name} (probably had a non-CAT parent)")
        await self.lineage_store.remove_lineage_proof(name)

    # maybe we change this to return the full records and just add the clean ones ourselves later
    async def advanced_select_coins(self, amount: uint64, proposal_id: bytes32) -> List[LockedCoinInfo]:
        coins = []
        s = 0
        for coin in self.dao_cat_info.locked_coins:
            compatible = True
            for prev_vote in coin.previous_votes:
                if prev_vote == proposal_id:
                    compatible = False
                    break
            if compatible:
                coins.append(coin)
                s += coin.coin.amount
                if s >= amount:
                    break
        assert s >= amount
        return coins

    def id(self) -> uint32:
        return self.wallet_info.id

    async def create_vote_spend(self, amount: uint64, proposal_id: bytes32, is_yes_vote: bool):
        coins: List[LockedCoinInfo] = await self.advanced_select_coins(amount, proposal_id)
        running_sum = 0  # this will be used for change calculation
        change = sum(c.coin.amount for c in coins) - amount
        extra_delta, limitations_solution = 0, Program.to([])
        limitations_program_reveal = Program.to([])
        spendable_cat_list = []
        for lci in coins:
            # my_id  ; if my_id is 0 we do the return to return_address (exit voting mode) spend case
            # inner_solution
            # my_amount
            # new_proposal_vote_id_or_removal_id
            # proposal_curry_vals
            # vote_info
            # vote_amount
            # my_puzhash
            coin = lci.coin

            dao_wallet = self.wallet_state_manager.user_store.get_wallet_by_id(self.dao_cat_info.dao_wallet_id)
            YES_VOTES, TOTAL_VOTES, INNERPUZ = await dao_wallet.get_proposal_curry_values(proposal_id)
            vote_info = 0
            new_innerpuzzle = add_proposal_to_active_list(lci.inner_puzzle, proposal_id)
            if running_sum + coin.amount < amount:
                vote_amount = coin.amount
                running_sum = running_sum + coin.amount
                # CREATE_COIN new_puzzle coin.amount
                # CREATE_PUZZLE_ANNOUNCEMENT (sha256tree (list new_proposal_vote_id_or_removal_id my_amount vote_info my_id))
                primaries = [{
                    "puzzlehash": new_innerpuzzle.get_tree_hash(),
                    "amount": uint64(vote_amount),
                    "memos": [new_innerpuzzle.get_tree_hash()]
                }]
                puzzle_announcements = set(
                    Program.to([proposal_id, vote_amount, vote_info, coin.name()]).get_tree_hash()
                )
                inner_solution = await self.standard_wallet.make_solution(
                    primaries=primaries,
                    puzzle_announcements=puzzle_announcements
                )
            else:
                vote_amount = amount - running_sum
                # CREATE_COIN new_puzzle vote_amount
                # CREATE_COIN old_puzzle change
                # CREATE_PUZZLE_ANNOUNCEMENT (sha256tree (list new_proposal_vote_id_or_removal_id my_amount vote_info my_id))
                primaries = [
                    {
                        "puzzlehash": new_innerpuzzle.get_tree_hash(),
                        "amount": uint64(vote_amount),
                        "memos": [new_innerpuzzle.get_tree_hash()]
                    },
                    {
                        "puzzlehash": lci.inner_puzzle.get_tree_hash(),
                        "amount": uint64(change),
                        "memos": [lci.inner_puzzle.get_tree_hash()]
                    },
                ]
                puzzle_announcements = set(
                    Program.to([proposal_id, vote_amount, vote_info, coin.name()]).get_tree_hash()
                )
                inner_solution = await self.standard_wallet.make_solution(
                    primaries=primaries,
                    puzzle_announcements=puzzle_announcements
                )
            if is_yes_vote:
                vote_info = 1
            solution = Program.to([
                coin.name(),
                inner_solution,
                coin.amount,
                proposal_id,
                [YES_VOTES, TOTAL_VOTES, INNERPUZ],
                vote_info,
                vote_amount,
                coin.puzzle_hash
            ])
            lineage_proof = await self.get_lineage_proof_for_coin(coin)
            assert lineage_proof is not None
            new_spendable_cat = SpendableCAT(
                coin,
                self.cat_info.limitations_program_hash,
                lci.inner_puzzle,
                solution,
                limitations_solution=limitations_solution,
                extra_delta=extra_delta,
                lineage_proof=lineage_proof,
                limitations_program_reveal=limitations_program_reveal,
            )
            spendable_cat_list.append(new_spendable_cat)

        cat_spend_bundle = unsigned_spend_bundle_for_spendable_cats(CAT_MOD, spendable_cat_list)
        spend_bundle = await self.sign(cat_spend_bundle)
        breakpoint()
        return spend_bundle

    async def get_new_vote_state_puzzle(self, coins: Optional[List[Coin]] = None):
        innerpuz = await self.get_new_inner_puzzle()
        puzzle = get_lockup_puzzle(
            self.dao_cat_info.limitations_program_hash,
            [],
            innerpuz,
        )
        cat_puzzle: Program = construct_cat_puzzle(CAT_MOD, self.dao_cat_info.limitations_program_hash, puzzle)
        # breakpoint()
        await self.wallet_state_manager.add_interested_puzzle_hashes([puzzle.get_tree_hash()], [self.id()])
        await self.wallet_state_manager.add_interested_puzzle_hashes([cat_puzzle.get_tree_hash()], [self.id()])
        return puzzle

    async def exit_vote_state():

        return

    async def add_coin_to_tracked_list():

        return

    async def update_coin_in_tracked_list():

        return

    def get_asset_id(self):
        return bytes(self.dao_cat_info.limitations_program_hash).hex()

    async def get_new_inner_hash(self) -> bytes32:
        puzzle = await self.get_new_inner_puzzle()
        return puzzle.get_tree_hash()

    async def get_new_inner_puzzle(self) -> Program:
        return await self.standard_wallet.get_new_puzzle()

    # MH: I have a feeling we may want the real full puzzle here
    async def get_new_puzzlehash(self) -> bytes32:
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

    async def get_cat_spendable_coins(self, records: Optional[Set[WalletCoinRecord]] = None) -> List[WalletCoinRecord]:
        result: List[WalletCoinRecord] = []

        record_list: Set[WalletCoinRecord] = await self.wallet_state_manager.get_spendable_coins_for_wallet(
            self.id(), records
        )

        for record in record_list:
            lineage = await self.get_lineage_proof_for_coin(record.coin)
            if lineage is not None and not lineage.is_none():
                result.append(record)

        return result

    async def get_spendable_balance(self, records: Optional[Set[WalletCoinRecord]] = None) -> uint128:
        coins = await self.get_cat_spendable_coins(records)
        amount = 0
        for record in coins:
            amount += record.coin.amount

        return uint128(amount)

    async def sign(self, spend_bundle: SpendBundle) -> SpendBundle:
        sigs: List[G2Element] = []
        for spend in spend_bundle.coin_spends:
            args = match_cat_puzzle(uncurry_puzzle(spend.puzzle_reveal.to_program()))
            if args is not None:
                _, _, inner_puzzle = args
                puzzle_hash = inner_puzzle.get_tree_hash()
                ret = await self.wallet_state_manager.get_keys(puzzle_hash)
                if ret is None:
                    # Abort signing the entire SpendBundle - sign all or none
                    raise RuntimeError(f"Failed to get keys for puzzle_hash {puzzle_hash}")
                pubkey, private = ret
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
                            raise ValueError("This spend bundle cannot be signed by this DAO CAT wallet")

        agg_sig = AugSchemeMPL.aggregate(sigs)
        return SpendBundle.aggregate([spend_bundle, SpendBundle([], agg_sig)])

    async def save_info(self, dao_cat_info: DAOCATInfo) -> None:
        self.dao_cat_info = dao_cat_info
        current_info = self.wallet_info
        data_str = bytes(dao_cat_info).hex()
        wallet_info = WalletInfo(current_info.id, current_info.name, current_info.type, data_str)
        self.wallet_info = wallet_info
        await self.wallet_state_manager.user_store.update_wallet(wallet_info)
