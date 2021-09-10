from typing import Optional
from blspy import G1Element

from chia.types.blockchain_format.coin import Coin
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.wallet.puzzles.load_clvm import load_clvm

GENESIS_BY_ID_MOD = load_clvm("genesis-by-coin-id-with-0.clvm")
GENESIS_BY_PUZHASH_MOD = load_clvm("genesis-by-puzzle-hash-with-0.clvm")
EVERYTHING_WITH_SIG_MOD = load_clvm("everything_with_signature.clvm")
DELEGATED_GENESIS_CHECKER_MOD = load_clvm("delegated_genesis_checker.clvm")


class GenesisById:
    @staticmethod
    def create(genesis_coin_id: bytes32) -> Program:
        """
        Given a specific genesis coin id, create a `genesis_coin_mod` that allows
        both that coin id to issue a cc, or anyone to create a cc with amount 0.
        """
        return GENESIS_BY_ID_MOD.curry(genesis_coin_id)

    @staticmethod
    def uncurry(
        genesis_coin_checker: Program,
    ) -> Optional[bytes32]:
        """
        Given a `genesis_coin_checker` program, pull out the genesis coin id.
        """
        r = genesis_coin_checker.uncurry()
        if r is None:
            return r
        f, args = r
        if f != GENESIS_BY_ID_MOD:
            return None
        return args.first().as_atom()

    @staticmethod
    def proof() -> Program:
        return Program.to((0, []))


class GenesisByPuzhash:
    @staticmethod
    def create(genesis_puzhash: bytes32) -> Program:
        return GENESIS_BY_PUZHASH_MOD.curry(genesis_puzhash)

    @staticmethod
    def uncurry(
        genesis_coin_checker: Program,
    ) -> Optional[bytes32]:
        r = genesis_coin_checker.uncurry()
        if r is None:
            return r
        f, args = r
        if f != GENESIS_BY_PUZHASH_MOD:
            return None
        return args.first().as_atom()

    @staticmethod
    def proof(parent_coin: Coin) -> Program:
        return Program.to((0, [parent_coin.parent_coin_info, parent_coin.amount]))


class EverythingWithSig:
    @staticmethod
    def create(pubkey: G1Element) -> Program:
        return EVERYTHING_WITH_SIG_MOD.curry(pubkey)

    @staticmethod
    def uncurry(
        genesis_coin_checker: Program,
    ) -> Optional[G1Element]:
        r = genesis_coin_checker.uncurry()
        if r is None:
            return r
        f, args = r
        if f != EVERYTHING_WITH_SIG_MOD:
            return None
        return args.first().as_atom()

    @staticmethod
    def proof() -> Program:
        return Program.to((0, []))


class DelegatedGenesis:
    @staticmethod
    def create(pubkey: G1Element) -> Program:
        return DELEGATED_GENESIS_CHECKER_MOD.curry(pubkey)

    @staticmethod
    def uncurry(
        genesis_coin_checker: Program,
    ) -> Optional[G1Element]:
        r = genesis_coin_checker.uncurry()
        if r is None:
            return r
        f, args = r
        if f != DELEGATED_GENESIS_CHECKER_MOD:
            return None
        return args.first().as_atom()

    @staticmethod
    def proof(signed_program: Program, inner_proof: Program) -> Program:
        return Program.to((0, [signed_program, inner_proof]))