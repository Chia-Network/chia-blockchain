import json
from typing import List, Tuple, Set, Optional

from blspy import G1Element, PrivateKey, AugSchemeMPL, G2Element

from chia.minter.minding_tools import make_solution, sign
from chia.types.announcement import Announcement
from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_spend import CoinSpend
from chia.types.spend_bundle import SpendBundle
from chia.util.condition_tools import conditions_dict_for_solution, pkm_pairs_for_conditions_dict
from chia.util.hash import std_hash
from chia.util.ints import uint64, uint32
from chia.wallet.derive_keys import master_sk_to_wallet_sk_unhardened
from chia.wallet.did_wallet import did_wallet_puzzles
from chia.wallet.did_wallet.did_info import DIDInfo
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    puzzle_for_pk,
    solution_for_conditions,
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
)
from chia.wallet.puzzles.puzzle_utils import (
    make_create_coin_condition,
    make_reserve_fee_condition,
    make_assert_my_coin_id_condition,
    make_assert_absolute_seconds_exceeds_condition,
    make_create_coin_announcement,
    make_assert_coin_announcement,
    make_create_puzzle_announcement,
    make_assert_puzzle_announcement,
)
from chia.wallet.secret_key_store import SecretKeyStore
from chia.wallet.sign_coin_spends import sign_coin_spends
from chia.wallet.util.wallet_types import AmountWithPuzzlehash


class DIDMintingTool:
    def __init__(self, private_key: PrivateKey, constants):
        self.root_key = private_key
        self.root_public_key = self.root_key.get_g1()
        self.wallet_sk = master_sk_to_wallet_sk_unhardened(self.root_key, 1)
        self.wallet_pk = self.wallet_sk.get_g1()

        self.secret_key_store = SecretKeyStore()
        self.hack_populate_secret_key()
        self.constants = constants

    async def sign_spends(self, spends: List[CoinSpend]) -> SpendBundle:
        sb = await sign_coin_spends(
            spends,
            self.secret_key_store.secret_key_for_public_key,
            self.constants.AGG_SIG_ME_ADDITIONAL_DATA,
            self.constants.MAX_BLOCK_COST_CLVM,
        )
        return sb

    def hack_populate_secret_key(self) -> G1Element:
        secret_key = self.wallet_sk
        public_key = secret_key.get_g1()
        # HACK
        synthetic_secret_key = calculate_synthetic_secret_key(secret_key, DEFAULT_HIDDEN_PUZZLE_HASH)
        self.secret_key_store.save_secret_key(synthetic_secret_key)

        return public_key

    # Def create a DID
    async def create_did_coin(self, origin: Coin, amount: uint64) -> SpendBundle:

        genesis_launcher_puz = did_wallet_puzzles.SINGLETON_LAUNCHER
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), amount)
        self.did_info = DIDInfo(launcher_coin, [], 0, [], None, None, None, None, False, json.dumps({}))
        did_inner: Program = await self.get_new_did_innerpuz(launcher_coin.name(), self.did_info)
        self.did_info = DIDInfo(launcher_coin, [], 0, [], did_inner, None, None, None, False, json.dumps({}))

        did_inner_hash = did_inner.get_tree_hash()
        did_full_puz = did_wallet_puzzles.create_fullpuz(did_inner, launcher_coin.name())
        did_puzzle_hash = did_full_puz.get_tree_hash()
        announcement_set: Set[Announcement] = set()
        announcement_message = Program.to([did_puzzle_hash, amount, bytes(0x80)]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message))

        coin_announcements_bytes: Optional[Set[bytes32]] = {a.name() for a in announcement_set}

        primaries: List[AmountWithPuzzlehash] = []
        primaries.append({"puzzlehash": genesis_launcher_puz.get_tree_hash(), "amount": uint64(amount), "memos": []})
        puzzle: Program = await self.puzzle_for_puzzle_hash(origin.puzzle_hash)
        message_list: List[bytes32] = [origin.name()]
        for primary in primaries:
            message_list.append(Coin(origin.name(), primary["puzzlehash"], primary["amount"]).name())
        message: bytes32 = std_hash(b"".join(message_list))

        solution: Program = make_solution(
            primaries=primaries,
            fee=0,
            coin_announcements={message},
            coin_announcements_to_assert=coin_announcements_bytes,
        )
        coin_spend = CoinSpend(
            origin, SerializedProgram.from_bytes(bytes(puzzle)), SerializedProgram.from_bytes(bytes(solution))
        )
        spend_bundle: SpendBundle = await sign_coin_spends(
            [coin_spend],
            self.secret_key_store.secret_key_for_public_key,
            self.constants.AGG_SIG_ME_ADDITIONAL_DATA,
            self.constants.MAX_BLOCK_COST_CLVM,
        )

        genesis_launcher_solution = Program.to([did_puzzle_hash, origin.amount, bytes(0x80)])
        launcher_cs = CoinSpend(launcher_coin, genesis_launcher_puz, genesis_launcher_solution)
        launcher_sb = SpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))
        eve_coin = Coin(launcher_coin.name(), did_puzzle_hash, amount)
        eve_spend = await self.generate_eve_spend(eve_coin, did_full_puz, did_inner, self.did_info)
        # full_spend = spend_bundle
        full_spend = SpendBundle.aggregate([spend_bundle, eve_spend, launcher_sb])
        return full_spend

    async def generate_eve_spend(self, coin: Coin, full_puzzle: Program, innerpuz: Program, did_info: DIDInfo):
        # innerpuz solution is (mode p2_solution)
        p2_solution = make_solution(
            primaries=[
                {
                    "puzzlehash": innerpuz.get_tree_hash(),
                    "amount": uint64(coin.amount),
                    "memos": [innerpuz.get_tree_hash()],
                }
            ]
        )
        innersol = Program.to([1, p2_solution])
        # full solution is (lineage_proof my_amount inner_solution)
        fullsol = Program.to(
            [
                [did_info.origin_coin.parent_coin_info, did_info.origin_coin.amount],
                coin.amount,
                innersol,
            ]
        )
        list_of_coinspends = [CoinSpend(coin, full_puzzle, fullsol)]
        return await sign(self.wallet_sk, list_of_coinspends, self.constants)

    async def puzzle_for_puzzle_hash(self, puzzle_hash: bytes32) -> Program:
        counter = 0
        while True:
            sk = master_sk_to_wallet_sk_unhardened(self.root_key, uint32(counter))
            inner_puzzle = puzzle_for_pk(sk.get_g1())
            synthetic_secret_key = calculate_synthetic_secret_key(sk, DEFAULT_HIDDEN_PUZZLE_HASH)
            self.secret_key_store.save_secret_key(synthetic_secret_key)
            if inner_puzzle.get_tree_hash() == puzzle_hash:
                return inner_puzzle
            counter += 1

    async def get_new_did_innerpuz(self, origin_id: bytes32, did_info: DIDInfo) -> Program:
        innerpuz = did_wallet_puzzles.create_innerpuz(
            await self.get_new_p2_inner_puzzle(),
            did_info.backup_ids,
            uint64(did_info.num_of_backup_ids_needed),
            origin_id,
            did_wallet_puzzles.metadata_to_program(json.loads(did_info.metadata)),
        )

        return innerpuz

    async def get_new_p2_inner_puzzle(self) -> Program:
        sk = master_sk_to_wallet_sk_unhardened(self.root_key, 1)
        inner_puzzle = puzzle_for_pk(sk.get_g1())
        return inner_puzzle

    async def get_new_p2_inner_hash(self) -> bytes32:
        puzzle = await self.get_new_p2_inner_puzzle()
        return puzzle.get_tree_hash()
