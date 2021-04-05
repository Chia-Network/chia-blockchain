from typing import Dict, List, Optional

from blspy import AugSchemeMPL, G2Element, PrivateKey

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.coin_solution import CoinSolution
from chia.types.condition_opcodes import ConditionOpcode
from chia.types.condition_var_pair import ConditionVarPair
from chia.types.spend_bundle import SpendBundle
from chia.util.clvm import int_from_bytes, int_to_bytes
from chia.util.condition_tools import conditions_by_opcode, conditions_for_solution, pkm_pairs_for_conditions_dict
from chia.util.ints import uint32, uint64
from chia.wallet.derive_keys import master_sk_to_wallet_sk
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import (
    DEFAULT_HIDDEN_PUZZLE_HASH,
    calculate_synthetic_secret_key,
    puzzle_for_pk,
    solution_for_conditions,
)
from chia.wallet.puzzles.puzzle_utils import (
    make_assert_aggsig_condition,
    make_assert_announcement,
    make_assert_height_age_exceeds_condition,
    make_assert_height_now_exceeds_condition,
    make_assert_my_coin_id_condition,
    make_assert_seconds_now_exceeds_condition,
    make_create_announcement,
    make_create_coin_condition,
    make_reserve_fee_condition,
)

DEFAULT_SEED = b"seed" * 8
assert len(DEFAULT_SEED) == 32


class WalletTool:
    next_address = 0
    pubkey_num_lookup: Dict[bytes, uint32] = {}

    def __init__(self, sk: Optional[PrivateKey] = None):
        self.current_balance = 0
        self.my_utxos: set = set()
        if sk is not None:
            self.private_key = sk
        else:
            self.private_key = AugSchemeMPL.key_gen(DEFAULT_SEED)
        self.generator_lookups: Dict = {}
        self.puzzle_pk_cache: Dict = {}
        self.get_new_puzzle()

    def get_next_address_index(self) -> uint32:
        self.next_address = uint32(self.next_address + 1)
        return self.next_address

    def get_private_key_for_puzzle_hash(self, puzzle_hash: bytes32) -> PrivateKey:
        if puzzle_hash in self.puzzle_pk_cache:
            child = self.puzzle_pk_cache[puzzle_hash]
            private = master_sk_to_wallet_sk(self.private_key, uint32(child))
            #  pubkey = private.get_g1()
            return private
        else:
            for child in range(self.next_address):
                pubkey = master_sk_to_wallet_sk(self.private_key, uint32(child)).get_g1()
                if puzzle_hash == puzzle_for_pk(bytes(pubkey)).get_tree_hash():
                    return master_sk_to_wallet_sk(self.private_key, uint32(child))
        raise ValueError(f"Do not have the keys for puzzle hash {puzzle_hash}")

    def puzzle_for_pk(self, pubkey: bytes) -> Program:
        return puzzle_for_pk(pubkey)

    def get_new_puzzle(self) -> bytes32:
        next_address_index: uint32 = self.get_next_address_index()
        pubkey = master_sk_to_wallet_sk(self.private_key, next_address_index).get_g1()
        self.pubkey_num_lookup[bytes(pubkey)] = next_address_index

        puzzle = puzzle_for_pk(bytes(pubkey))

        self.puzzle_pk_cache[puzzle.get_tree_hash()] = next_address_index
        return puzzle

    def get_new_puzzlehash(self) -> bytes32:
        puzzle = self.get_new_puzzle()
        return puzzle.get_tree_hash()

    def sign(self, value: bytes, pubkey: bytes) -> G2Element:
        privatekey: PrivateKey = master_sk_to_wallet_sk(self.private_key, self.pubkey_num_lookup[pubkey])
        return AugSchemeMPL.sign(privatekey, value)

    def make_solution(self, condition_dic: Dict[ConditionOpcode, List[ConditionVarPair]]) -> Program:
        ret = []

        for con_list in condition_dic.values():
            for cvp in con_list:
                if cvp.opcode == ConditionOpcode.CREATE_COIN:
                    ret.append(make_create_coin_condition(cvp.vars[0], cvp.vars[1]))
                if cvp.opcode == ConditionOpcode.CREATE_ANNOUNCEMENT:
                    ret.append(make_create_announcement(cvp.vars[0]))
                if cvp.opcode == ConditionOpcode.AGG_SIG:
                    ret.append(make_assert_aggsig_condition(cvp.vars[0]))
                if cvp.opcode == ConditionOpcode.ASSERT_ANNOUNCEMENT:
                    ret.append(make_assert_announcement(cvp.vars[0]))
                if cvp.opcode == ConditionOpcode.ASSERT_SECONDS_NOW_EXCEEDS:
                    ret.append(make_assert_seconds_now_exceeds_condition(cvp.vars[0]))
                if cvp.opcode == ConditionOpcode.ASSERT_MY_COIN_ID:
                    ret.append(make_assert_my_coin_id_condition(cvp.vars[0]))
                if cvp.opcode == ConditionOpcode.ASSERT_HEIGHT_NOW_EXCEEDS:
                    ret.append(make_assert_height_now_exceeds_condition(cvp.vars[0]))
                if cvp.opcode == ConditionOpcode.ASSERT_HEIGHT_AGE_EXCEEDS:
                    ret.append(make_assert_height_age_exceeds_condition(cvp.vars[0]))
                if cvp.opcode == ConditionOpcode.RESERVE_FEE:
                    ret.append(make_reserve_fee_condition(cvp.vars[0]))
        return solution_for_conditions(Program.to(ret))

    def generate_unsigned_transaction(
        self,
        amount: uint64,
        new_puzzle_hash: bytes32,
        coin: Coin,
        condition_dic: Dict[ConditionOpcode, List[ConditionVarPair]],
        fee: int = 0,
        secret_key: Optional[PrivateKey] = None,
    ) -> List[CoinSolution]:
        spends = []
        spend_value = coin.amount
        puzzle_hash = coin.puzzle_hash
        if secret_key is None:
            secret_key = self.get_private_key_for_puzzle_hash(puzzle_hash)
        pubkey = secret_key.get_g1()
        puzzle = puzzle_for_pk(bytes(pubkey))
        if ConditionOpcode.CREATE_COIN not in condition_dic:
            condition_dic[ConditionOpcode.CREATE_COIN] = []

        output = ConditionVarPair(ConditionOpcode.CREATE_COIN, [new_puzzle_hash, int_to_bytes(amount)])
        condition_dic[output.opcode].append(output)
        amount_total = sum(int_from_bytes(cvp.vars[1]) for cvp in condition_dic[ConditionOpcode.CREATE_COIN])
        change = spend_value - amount_total - fee
        if change > 0:
            change_puzzle_hash = self.get_new_puzzlehash()
            change_output = ConditionVarPair(ConditionOpcode.CREATE_COIN, [change_puzzle_hash, int_to_bytes(change)])
            condition_dic[output.opcode].append(change_output)
            solution = self.make_solution(condition_dic)
        else:
            solution = self.make_solution(condition_dic)

        spends.append(CoinSolution(coin, puzzle, solution))
        return spends

    def sign_transaction(self, coin_solutions: List[CoinSolution]) -> SpendBundle:
        signatures = []
        solution: Program
        puzzle: Program
        for coin_solution in coin_solutions:  # type: ignore # noqa
            secret_key = self.get_private_key_for_puzzle_hash(coin_solution.coin.puzzle_hash)
            synthetic_secret_key = calculate_synthetic_secret_key(secret_key, DEFAULT_HIDDEN_PUZZLE_HASH)
            err, con, cost = conditions_for_solution(coin_solution.puzzle_reveal, coin_solution.solution)
            if not con:
                raise ValueError(err)
            conditions_dict = conditions_by_opcode(con)

            for _, msg in pkm_pairs_for_conditions_dict(conditions_dict, bytes(coin_solution.coin.name())):
                signature = AugSchemeMPL.sign(synthetic_secret_key, msg)
                signatures.append(signature)
        aggsig = AugSchemeMPL.aggregate(signatures)
        spend_bundle = SpendBundle(coin_solutions, aggsig)
        return spend_bundle

    def generate_signed_transaction(
        self,
        amount: uint64,
        new_puzzle_hash: bytes32,
        coin: Coin,
        condition_dic: Dict[ConditionOpcode, List[ConditionVarPair]] = None,
        fee: int = 0,
    ) -> SpendBundle:
        if condition_dic is None:
            condition_dic = {}
        transaction = self.generate_unsigned_transaction(amount, new_puzzle_hash, coin, condition_dic, fee)
        assert transaction is not None
        return self.sign_transaction(transaction)
