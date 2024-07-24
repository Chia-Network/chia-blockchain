# flake8: noqa: F501
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, List

import pytest
from chia_rs import ALLOW_BACKREFS
from clvm.serialize import sexp_from_stream
from clvm.SExp import SExp
from clvm_tools import binutils

from chia._tests.core.make_block_generator import make_spend_bundle
from chia._tests.generator.test_rom import run_generator
from chia.full_node.bundle_tools import simple_solution_generator, simple_solution_generator_backrefs
from chia.full_node.mempool_check_conditions import get_puzzle_and_solution_for_coin
from chia.simulator.block_tools import test_constants
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.generator_types import BlockGenerator
from chia.types.spend_bundle import SpendBundle
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint32
from chia.wallet.puzzles.load_clvm import load_clvm

TEST_GEN_DESERIALIZE = load_clvm(
    "test_generator_deserialize.clsp", package_or_requirement="chia._tests.generator.puzzles"
)
DESERIALIZE_MOD = load_clvm("chialisp_deserialisation.clsp", package_or_requirement="chia.consensus.puzzles")

DECOMPRESS_PUZZLE = load_clvm("decompress_puzzle.clsp", package_or_requirement="chia.full_node.puzzles")
DECOMPRESS_CSE = load_clvm("decompress_coin_spend_entry.clsp", package_or_requirement="chia.full_node.puzzles")

DECOMPRESS_CSE_WITH_PREFIX = load_clvm(
    "decompress_coin_spend_entry_with_prefix.clsp", package_or_requirement="chia.full_node.puzzles"
)
DECOMPRESS_BLOCK = load_clvm("block_program_zero.clsp", package_or_requirement="chia.full_node.puzzles")
TEST_MULTIPLE = load_clvm(
    "test_multiple_generator_input_arguments.clsp", package_or_requirement="chia._tests.generator.puzzles"
)

Nil = Program.from_bytes(b"\x80")

original_generator = hexstr_to_bytes(
    "ff01ffffffa00000000000000000000000000000000000000000000000000000000000000000ff830186a080ffffff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3ff018080ffff80ffff01ffff33ffa06b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9ff830186a08080ff8080808080"
)  # noqa

gen1 = b"\xff\x01" + original_generator
gen2 = b"\xff\x01\xff\x01" + original_generator
FAKE_BLOCK_HEIGHT1 = uint32(100)
FAKE_BLOCK_HEIGHT2 = uint32(200)

from chia_rs import serialized_length

assert serialized_length(original_generator) == len(original_generator)
assert serialized_length(gen1) == len(gen1)
assert serialized_length(gen2) == len(gen2)


def spend_bundle_to_coin_spend_entry_list(bundle: SpendBundle) -> List[Any]:
    r = []
    for coin_spend in bundle.coin_spends:
        entry = [
            coin_spend.coin.parent_coin_info,
            sexp_from_stream(io.BytesIO(bytes(coin_spend.puzzle_reveal)), SExp.to),
            coin_spend.coin.amount,
            sexp_from_stream(io.BytesIO(bytes(coin_spend.solution)), SExp.to),
        ]
        r.append(entry)
    return r


class TestCompression:
    def test_compress_spend_bundle(self) -> None:
        pass


class TestDecompression:
    def test_deserialization(self) -> None:
        cost, out = DESERIALIZE_MOD.run_with_cost(INFINITE_COST, [bytes(Program.to("hello"))])
        assert out == Program.to("hello")

    def test_deserialization_as_argument(self) -> None:
        cost, out = TEST_GEN_DESERIALIZE.run_with_cost(
            INFINITE_COST, [DESERIALIZE_MOD, Nil, bytes(Program.to("hello"))]
        )
        print(bytes(Program.to("hello")))
        print()
        print(out)
        assert out == Program.to("hello")

    def test_decompress_puzzle(self) -> None:
        cost, out = DECOMPRESS_PUZZLE.run_with_cost(
            INFINITE_COST, [DESERIALIZE_MOD, b"\xff", bytes(Program.to("pubkey")), b"\x80"]
        )

        print()
        print(out)

    # An empty CSE is invalid. (An empty CSE list may be okay)
    # def test_decompress_empty_cse(self):
    #    cse0 = binutils.assemble("()")
    #    cost, out = DECOMPRESS_CSE.run_with_cost(INFINITE_COST, [DESERIALIZE_MOD, DECOMPRESS_PUZZLE, b"\xff", b"\x80", cse0])
    #    print()
    #    print(out)

    def test_decompress_cse(self) -> None:
        """Decompress a single CSE / CoinSpendEntry"""
        cse0 = binutils.assemble(
            "((0x0000000000000000000000000000000000000000000000000000000000000000 0x0186a0) (0xb081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3 (() (q (51 0x6b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9 0x0186a0)) ())))"
        )
        cost, out = DECOMPRESS_CSE.run_with_cost(
            INFINITE_COST, [DESERIALIZE_MOD, DECOMPRESS_PUZZLE, b"\xff", b"\x80", cse0]
        )

        print()
        print(out)

    def test_decompress_cse_with_prefix(self) -> None:
        cse0 = binutils.assemble(
            "((0x0000000000000000000000000000000000000000000000000000000000000000 0x0186a0) (0xb081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3 (() (q (51 0x6b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9 0x0186a0)) ())))"
        )

        start = 2 + 44
        end = start + 238
        prefix = original_generator[start:end]
        # (deserialize decompress_puzzle puzzle_prefix cse)
        cost, out = DECOMPRESS_CSE_WITH_PREFIX.run_with_cost(
            INFINITE_COST, [DESERIALIZE_MOD, DECOMPRESS_PUZZLE, prefix, cse0]
        )

        print()
        print(out)

    def test_block_program_zero(self) -> None:
        "Decompress a list of CSEs"
        cse1 = binutils.assemble(
            "(((0x0000000000000000000000000000000000000000000000000000000000000000 0x0186a0) (0xb081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3 (() (q (51 0x6b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9 0x0186a0)) ()))))"
        )
        cse2 = binutils.assemble(
            """
(
  ((0x0000000000000000000000000000000000000000000000000000000000000000 0x0186a0)
   (0xb081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3
    (() (q (51 0x6b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9 0x0186a0)) ()))
  )

  ((0x0000000000000000000000000000000000000000000000000000000000000001 0x0186a0)
   (0xb0a6207f5173ec41491d9f2c1b8fff5579e13703077e0eaca8fe587669dcccf51e9209a6b65576845ece5f7c2f3229e7e3
   (() (q (51 0x24254a3efc3ebfac9979bbe0d615e2eda043aa329905f65b63846fa24149e2b6 0x0186a0)) ())))

)
        """
        )

        start = 2 + 44
        end = start + 238

        # (mod (decompress_puzzle decompress_coin_spend_entry start end compressed_cses deserialize generator_list reserved_arg)
        # cost, out = DECOMPRESS_BLOCK.run_with_cost(INFINITE_COST, [DECOMPRESS_PUZZLE, DECOMPRESS_CSE, start, Program.to(end), cse0, DESERIALIZE_MOD, bytes(original_generator)])
        cost, out = DECOMPRESS_BLOCK.run_with_cost(
            INFINITE_COST,
            [
                DECOMPRESS_PUZZLE,
                DECOMPRESS_CSE_WITH_PREFIX,
                start,
                Program.to(end),
                cse2,
                DESERIALIZE_MOD,
                [bytes(original_generator)],
            ],
        )

        print()
        print(out)

    def test_block_program_zero_with_curry(self) -> None:
        cse1 = binutils.assemble(
            "(((0x0000000000000000000000000000000000000000000000000000000000000000 0x0186a0) (0xb081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3 (() (q (51 0x6b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9 0x0186a0)) ()))))"
        )
        cse2 = binutils.assemble(
            """
(
  ((0x0000000000000000000000000000000000000000000000000000000000000000 0x0186a0)
   (0xb081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3
    (() (q (51 0x6b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9 0x0186a0)) ()))
  )

  ((0x0000000000000000000000000000000000000000000000000000000000000001 0x0186a0)
   (0xb0a6207f5173ec41491d9f2c1b8fff5579e13703077e0eaca8fe587669dcccf51e9209a6b65576845ece5f7c2f3229e7e3
   (() (q (51 0x24254a3efc3ebfac9979bbe0d615e2eda043aa329905f65b63846fa24149e2b6 0x0186a0)) ())))

)
        """
        )

        start = 2 + 44
        end = start + 238

        # (mod (decompress_puzzle decompress_coin_spend_entry start end compressed_cses deserialize generator_list reserved_arg)
        # cost, out = DECOMPRESS_BLOCK.run_with_cost(INFINITE_COST, [DECOMPRESS_PUZZLE, DECOMPRESS_CSE, start, Program.to(end), cse0, DESERIALIZE_MOD, bytes(original_generator)])
        p = DECOMPRESS_BLOCK.curry(DECOMPRESS_PUZZLE, DECOMPRESS_CSE_WITH_PREFIX, start, Program.to(end))
        cost, out = p.run_with_cost(INFINITE_COST, [cse2, DESERIALIZE_MOD, [bytes(original_generator)]])

        print()
        print(p)
        print(out)

        p_with_cses = DECOMPRESS_BLOCK.curry(
            DECOMPRESS_PUZZLE, DECOMPRESS_CSE_WITH_PREFIX, start, Program.to(end), cse2, DESERIALIZE_MOD
        )
        generator_args = Program.to([[original_generator]])
        cost, out = p_with_cses.run_with_cost(INFINITE_COST, generator_args)

        print()
        print(p_with_cses)
        print(out)
