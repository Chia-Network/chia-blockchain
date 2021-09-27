from typing import Tuple, Dict, List

from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.spend_bundle import SpendBundle
from chia.util.ints import uint64
from chia.util.byte_types import hexstr_to_bytes
from chia.wallet.lineage_proof import LineageProof
from chia.wallet.puzzles.load_clvm import load_clvm
from chia.wallet.cc_wallet.cc_utils import CC_MOD, construct_cc_puzzle
from chia.wallet.cc_wallet.cc_info import CCInfo
from chia.wallet.transaction_record import TransactionRecord

GENESIS_BY_ID_MOD = load_clvm("genesis-by-coin-id-with-0.clvm")
GENESIS_BY_PUZHASH_MOD = load_clvm("genesis-by-puzzle-hash-with-0.clvm")
EVERYTHING_WITH_SIG_MOD = load_clvm("everything_with_signature.clvm")
DELEGATED_LIMITATIONS_MOD = load_clvm("delegated_genesis_checker.clvm")


class LimitationsProgram:
    @staticmethod
    def match(uncurried_mod: Program, curried_args: Program) -> Tuple[bool, List[Program]]:
        raise NotImplementedError("Need to implement 'match' on limitations programs")

    @staticmethod
    def construct(args: List[Program]) -> Program:
        raise NotImplementedError("Need to implement 'construct' on limitations programs")

    @staticmethod
    def solve(args: List[Program], solution_dict: Dict) -> Program:
        raise NotImplementedError("Need to implement 'solve' on limitations programs")

    @classmethod
    async def generate_issuance_bundle(cls, wallet: 'CCWallet', cat_tail_info: Dict, amount: uint64) -> SpendBundle:
        raise NotImplementedError("Need to implement 'generate_issuance_bundle' on limitations programs")


class GenesisById(LimitationsProgram):
    """
    This TAIL allows for coins to be issued only by a specific "genesis" coin ID.
    There can therefore only be one issuance. There is no minting or melting allowed.
    """

    @staticmethod
    def match(uncurried_mod: Program, curried_args: Program) -> Tuple[bool, List[Program]]:
        if uncurried_mod == GENESIS_BY_ID_MOD:
            genesis_id = curried_args.first()
            return True, [genesis_id]
        else:
            return False, []

    @staticmethod
    def construct(args: List[Program]) -> Program:
        return GENESIS_BY_ID_MOD.curry(args[0])

    @staticmethod
    def solve(args: List[Program], solution_dict: Dict) -> Program:
        return Program.to([])

    @classmethod
    async def generate_issuance_bundle(cls, wallet: 'CCWallet', _: Dict, amount: uint64) -> SpendBundle:
        coins = await wallet.standard_wallet.select_coins(amount)

        origin = coins.copy().pop()
        origin_id = origin.name()

        cc_inner: Program = await wallet.get_new_inner_puzzle()
        await wallet.add_lineage(origin_id, LineageProof())
        genesis_coin_checker: Program = cls.construct([Program.to(origin_id)])

        minted_cc_puzzle_hash: bytes32 = construct_cc_puzzle(CC_MOD, genesis_coin_checker, cc_inner).get_tree_hash()

        tx_record: TransactionRecord = await wallet.standard_wallet.generate_signed_transaction(
            amount, minted_cc_puzzle_hash, uint64(0), origin_id, coins
        )
        assert tx_record.spend_bundle is not None

        if wallet.cc_info.my_genesis_checker is None:
            await wallet.save_info(CCInfo(genesis_coin_checker, wallet.cc_info.lineage_proofs), False)

        return tx_record.spend_bundle


class GenesisByPuzhash(LimitationsProgram):
    """
    This TAIL allows for issuance of a certain coin only by a specific puzzle hash.
    There is no minting or melting allowed.
    """

    @staticmethod
    def match(uncurried_mod: Program, curried_args: Program) -> Tuple[bool, List[Program]]:
        if uncurried_mod == GENESIS_BY_PUZHASH_MOD:
            genesis_puzhash = curried_args.first()
            return True, [genesis_puzhash]
        else:
            return False, []

    @staticmethod
    def construct(args: List[Program]) -> Program:
        return GENESIS_BY_PUZHASH_MOD.curry(args[0])

    @staticmethod
    def solve(args: List[Program], solution_dict: Dict) -> Program:
        pid = hexstr_to_bytes(solution_dict["parent_coin_info"])
        return Program.to([pid, solution_dict["amount"]])


class EverythingWithSig(LimitationsProgram):
    """
    This TAIL allows for issuance, minting, and melting as long as you provide a signature with the spend.
    """

    @staticmethod
    def match(uncurried_mod: Program, curried_args: Program) -> Tuple[bool, List[Program]]:
        if uncurried_mod == EVERYTHING_WITH_SIG_MOD:
            pubkey = curried_args.first()
            return True, [pubkey]
        else:
            return False, []

    @staticmethod
    def construct(args: List[Program]) -> Program:
        return EVERYTHING_WITH_SIG_MOD.curry(args[0])

    @staticmethod
    def solve(args: List[Program], solution_dict: Dict) -> Program:
        return Program.to([])


class DelegatedLimitations(LimitationsProgram):
    """
    This TAIL allows for another TAIL to be used, as long as a signature of that TAIL's puzzlehash is included.
    """

    @staticmethod
    def match(uncurried_mod: Program, curried_args: Program) -> Tuple[bool, List[Program]]:
        if uncurried_mod == DELEGATED_LIMITATIONS_MOD:
            pubkey = curried_args.first()
            return True, [pubkey]
        else:
            return False, []

    @staticmethod
    def construct(args: List[Program]) -> Program:
        return DELEGATED_LIMITATIONS_MOD.curry(args[0])

    @staticmethod
    def solve(args: List[Program], solution_dict: Dict) -> Program:
        signed_program = ALL_LIMITATIONS_PROGRAMS[solution_dict["signed_program"]["identifier"]]
        inner_program_args = [Program.fromhex(item) for item in solution_dict["signed_program"]["args"]]
        inner_solution_dict = solution_dict["program_arguments"]
        return Program.to(
            [
                signed_program.construct(inner_program_args),
                signed_program.solve(inner_program_args, inner_solution_dict),
            ]
        )


# This should probably be much more elegant than just a dictionary with strings as identifiers
# Right now this is small and experimental so it can stay like this
ALL_LIMITATIONS_PROGRAMS = {
    "genesis_by_id": GenesisById,
    "genesis_by_puzhash": GenesisByPuzhash,
    "everything_with_signature": EverythingWithSig,
    "delegated_limitations": DelegatedLimitations,
}
