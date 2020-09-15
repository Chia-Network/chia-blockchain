from typing import List, Optional, Dict, Tuple

from blspy import PrivateKey, AugSchemeMPL, G1Element, G2Element

from src.types.condition_var_pair import ConditionVarPair
from src.types.condition_opcodes import ConditionOpcode
from src.types.program import Program
from src.types.coin import Coin
from src.types.coin_solution import CoinSolution
from src.types.spend_bundle import SpendBundle
from src.util.clvm import int_to_bytes, int_from_bytes
from src.util.condition_tools import (
    conditions_by_opcode,
    pkm_pairs_for_conditions_dict,
    conditions_for_solution,
)
from src.util.ints import uint32, uint64
from src.wallet.puzzles.p2_conditions import puzzle_for_conditions
from src.wallet.puzzles.p2_delegated_puzzle import puzzle_for_pk
from src.wallet.puzzles.puzzle_utils import (
    make_assert_coin_consumed_condition,
    make_assert_my_coin_id_condition,
    make_create_coin_condition,
    make_assert_block_index_exceeds_condition,
    make_assert_block_age_exceeds_condition,
    make_assert_aggsig_condition,
    make_assert_time_exceeds_condition,
    make_assert_fee_condition,
)
from src.wallet.derive_keys import master_sk_to_wallet_sk
from src.types.sized_bytes import bytes32


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

    def get_keys(self, puzzle_hash) -> Tuple[G1Element, PrivateKey]:
        if puzzle_hash in self.puzzle_pk_cache:
            child = self.puzzle_pk_cache[puzzle_hash]
            private = master_sk_to_wallet_sk(self.private_key, uint32(child))
            pubkey = private.get_g1()
            return pubkey, private
        else:
            for child in range(self.next_address):
                pubkey = master_sk_to_wallet_sk(
                    self.private_key, uint32(child)
                ).get_g1()
                if puzzle_hash == puzzle_for_pk(bytes(pubkey)).get_tree_hash():
                    return (
                        pubkey,
                        master_sk_to_wallet_sk(self.private_key, uint32(child)),
                    )
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

    def sign(self, value, pubkey) -> G2Element:
        privatekey: PrivateKey = master_sk_to_wallet_sk(
            self.private_key, self.pubkey_num_lookup[pubkey]
        )
        return AugSchemeMPL.sign(privatekey, value)

    def make_solution(
        self, condition_dic: Dict[ConditionOpcode, List[ConditionVarPair]]
    ) -> Program:
        ret = []

        for con_list in condition_dic.values():
            for cvp in con_list:
                if cvp.opcode == ConditionOpcode.CREATE_COIN:
                    ret.append(make_create_coin_condition(cvp.var1, cvp.var2))
                if cvp.opcode == ConditionOpcode.AGG_SIG:
                    ret.append(make_assert_aggsig_condition(cvp.var1))
                if cvp.opcode == ConditionOpcode.ASSERT_COIN_CONSUMED:
                    ret.append(make_assert_coin_consumed_condition(cvp.var1))
                if cvp.opcode == ConditionOpcode.ASSERT_TIME_EXCEEDS:
                    ret.append(make_assert_time_exceeds_condition(cvp.var1))
                if cvp.opcode == ConditionOpcode.ASSERT_MY_COIN_ID:
                    ret.append(make_assert_my_coin_id_condition(cvp.var1))
                if cvp.opcode == ConditionOpcode.ASSERT_BLOCK_INDEX_EXCEEDS:
                    ret.append(make_assert_block_index_exceeds_condition(cvp.var1))
                if cvp.opcode == ConditionOpcode.ASSERT_BLOCK_AGE_EXCEEDS:
                    ret.append(make_assert_block_age_exceeds_condition(cvp.var1))
                if cvp.opcode == ConditionOpcode.ASSERT_FEE:
                    ret.append(make_assert_fee_condition(cvp.var1))

        return Program.to([puzzle_for_conditions(ret), []])

    def generate_unsigned_transaction(
        self,
        amount: uint64,
        newpuzzlehash: bytes32,
        coin: Coin,
        condition_dic: Dict[ConditionOpcode, List[ConditionVarPair]],
        fee: int = 0,
        secretkey=None,
    ) -> List[Tuple[Program, CoinSolution]]:
        spends = []
        spend_value = coin.amount
        puzzle_hash = coin.puzzle_hash
        if secretkey is None:
            pubkey, secretkey = self.get_keys(puzzle_hash)
        else:
            pubkey = secretkey.get_g1()
        puzzle = puzzle_for_pk(bytes(pubkey))
        if ConditionOpcode.CREATE_COIN not in condition_dic:
            condition_dic[ConditionOpcode.CREATE_COIN] = []

        output = ConditionVarPair(
            ConditionOpcode.CREATE_COIN, newpuzzlehash, int_to_bytes(amount)
        )
        condition_dic[output.opcode].append(output)
        amount_total = sum(
            int_from_bytes(cvp.var2)
            for cvp in condition_dic[ConditionOpcode.CREATE_COIN]
        )
        change = spend_value - amount_total - fee
        if change > 0:
            changepuzzlehash = self.get_new_puzzlehash()
            change_output = ConditionVarPair(
                ConditionOpcode.CREATE_COIN, changepuzzlehash, int_to_bytes(change)
            )
            condition_dic[output.opcode].append(change_output)
            solution = self.make_solution(condition_dic)
        else:
            solution = self.make_solution(condition_dic)

        spends.append((puzzle, CoinSolution(coin, solution)))
        return spends

    def sign_transaction(
        self, spends: List[Tuple[Program, CoinSolution]]
    ) -> SpendBundle:
        sigs = []
        solution: Program
        puzzle: Program
        for puzzle, solution in spends:  # type: ignore # noqa
            pubkey, secretkey = self.get_keys(solution.coin.puzzle_hash)
            code_ = [puzzle, solution.solution]
            sexp = Program.to(code_)
            err, con, cost = conditions_for_solution(sexp)
            if not con:
                raise ValueError(err)
            conditions_dict = conditions_by_opcode(con)

            for _, msg in pkm_pairs_for_conditions_dict(
                conditions_dict, bytes(solution.coin)
            ):
                signature = AugSchemeMPL.sign(secretkey, msg)
                sigs.append(signature)
        aggsig = AugSchemeMPL.aggregate(sigs)
        solution_list: List[CoinSolution] = [
            CoinSolution(
                coin_solution.coin, Program.to([puzzle, coin_solution.solution])
            )
            for (puzzle, coin_solution) in spends
        ]
        return SpendBundle(solution_list, aggsig)

    def generate_signed_transaction(
        self,
        amount,
        newpuzzlehash,
        coin: Coin,
        condition_dic: Dict[ConditionOpcode, List[ConditionVarPair]] = None,
        fee: int = 0,
    ) -> SpendBundle:
        if condition_dic is None:
            condition_dic = {}
        transaction = self.generate_unsigned_transaction(
            amount, newpuzzlehash, coin, condition_dic, fee
        )
        assert transaction is not None
        return self.sign_transaction(transaction)
