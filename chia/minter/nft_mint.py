# Start with a coin


# Generate X divisions
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
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.nft_wallet import nft_puzzles
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


class NFTMintingTool:
    def __init__(self, private_key: PrivateKey, constants, did_info):
        self.root_key = private_key
        self.root_public_key = self.root_key.get_g1()
        self.wallet_sk = master_sk_to_wallet_sk_unhardened(self.root_key, 1)
        self.wallet_pk = self.wallet_sk.get_g1()

        self.secret_key_store = SecretKeyStore()
        self.hack_populate_secret_key()
        self.constants = constants
        self.did_info = did_info

    def hack_populate_secret_key(self) -> G1Element:
        secret_key = self.wallet_sk
        public_key = secret_key.get_g1()
        # HACK
        synthetic_secret_key = calculate_synthetic_secret_key(secret_key, DEFAULT_HIDDEN_PUZZLE_HASH)
        self.secret_key_store.save_secret_key(synthetic_secret_key)

        return public_key

    def get_parent_for_coin(self, coin) -> Optional[LineageProof]:
        parent_info = None
        for name, ccparent in self.did_info.parent_info:
            if name == coin.parent_coin_info:
                parent_info = ccparent

        return parent_info

    async def min_nft_with_did(
        self,
        did_coin: Coin,
        did_info: DIDInfo,
        regular_coin: Coin,
        metadata: Program,
        backpayment_address: bytes32,
        percentage: uint64,
    ) -> SpendBundle:
        amount = 1
        origin = did_coin
        genesis_launcher_puz = nft_puzzles.LAUNCHER_PUZZLE
        launcher_coin = Coin(origin.name(), genesis_launcher_puz.get_tree_hash(), uint64(amount))
        nft_transfer_program = nft_puzzles.get_transfer_puzzle()
        eve_fullpuz = nft_puzzles.create_full_puzzle(
            launcher_coin.name(),
            did_info.origin_coin.name(),
            nft_transfer_program.get_tree_hash(),
            metadata,
            backpayment_address,
            percentage,
        )
        announcement_set: Set[Announcement] = set()
        announcement_message = Program.to([eve_fullpuz.get_tree_hash(), amount, bytes(0x80)]).get_tree_hash()
        announcement_set.add(Announcement(launcher_coin.name(), announcement_message))
        # Spend DID coin and create launcher
        launcher_bundle = await self.spend_did_and_generate_launcher(did_coin, launcher_coin.puzzle_hash)

        genesis_launcher_solution = Program.to([eve_fullpuz.get_tree_hash(), amount, bytes(0x80)])
        launcher_cs = CoinSpend(launcher_coin, genesis_launcher_puz, genesis_launcher_solution)
        launcher_sb = SpendBundle([launcher_cs], AugSchemeMPL.aggregate([]))
        eve_coin = Coin(launcher_coin.name(), eve_fullpuz.get_tree_hash(), uint64(amount))

        # Spend regular coin to provide value

    async def spend_did_and_generate_launcher(self, did_coin: Coin, launcher_puzzle_hash: bytes32) -> SpendBundle:
        """
        Spend did and recreate it self and NFT launcher
        :param launcher_puzzle_hash: New owner's p2_puzzle
        :param amount: launcher value
        :return: Spend bundle
        """
        assert self.did_info.current_inner is not None
        assert self.did_info.origin_coin is not None

        coin = did_coin

        inner_puzzle = self.did_info.current_inner.get_tree_hash()
        p2_solution = make_solution(
            primaries=[
                {
                    "puzzlehash": coin.puzzle_hash,
                    "amount": uint64(coin.amount),
                    "memos": [inner_puzzle],
                },
                {
                    "puzzlehash": launcher_puzzle_hash,
                    "amount": uint64(0),
                    "memos": [launcher_puzzle_hash],
                },
            ]
        )
        # Need to include backup list reveal here, even we are don't recover
        # innerpuz solution is
        # (mode, p2_solution)
        innersol: Program = Program.to([1, p2_solution])
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
        spend_bundle = await sign(self.wallet_sk, list_of_coinspends, self.constants)

        return spend_bundle
