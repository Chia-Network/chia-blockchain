# flake8: noqa: F501
from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any, List

import pytest
from chia_rs import ALLOW_BACKREFS
from clvm import SExp
from clvm.serialize import sexp_from_stream
from clvm_tools import binutils

from chia.full_node.bundle_tools import (
    bundle_suitable_for_compression,
    compressed_coin_spend_entry_list,
    compressed_spend_bundle_solution,
    match_standard_transaction_at_any_index,
    simple_solution_generator,
    simple_solution_generator_backrefs,
)
from chia.full_node.mempool_check_conditions import get_puzzle_and_solution_for_coin
from chia.types.blockchain_format.program import INFINITE_COST, Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.generator_types import BlockGenerator, CompressorArg
from chia.types.spend_bundle import SpendBundle
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint32
from chia.wallet.puzzles.load_clvm import load_clvm
from tests.core.make_block_generator import make_spend_bundle
from tests.generator.test_rom import run_generator

TEST_GEN_DESERIALIZE = load_clvm("test_generator_deserialize.clsp", package_or_requirement="chia.wallet.puzzles")
DESERIALIZE_MOD = load_clvm("chialisp_deserialisation.clsp", package_or_requirement="chia.wallet.puzzles")

DECOMPRESS_PUZZLE = load_clvm("decompress_puzzle.clsp", package_or_requirement="chia.wallet.puzzles")
DECOMPRESS_CSE = load_clvm("decompress_coin_spend_entry.clsp", package_or_requirement="chia.wallet.puzzles")

DECOMPRESS_CSE_WITH_PREFIX = load_clvm(
    "decompress_coin_spend_entry_with_prefix.clsp", package_or_requirement="chia.wallet.puzzles"
)
DECOMPRESS_BLOCK = load_clvm("block_program_zero.clsp", package_or_requirement="chia.wallet.puzzles")
TEST_MULTIPLE = load_clvm("test_multiple_generator_input_arguments.clsp", package_or_requirement="chia.wallet.puzzles")

Nil = Program.from_bytes(b"\x80")

original_generator = hexstr_to_bytes(
    "ff01ffffffa00000000000000000000000000000000000000000000000000000000000000000ff830186a080ffffff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3ff018080ffff80ffff01ffff33ffa06b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9ff830186a08080ff8080808080"
)  # noqa

gen1 = b"aaaaaaaaaa" + original_generator
gen2 = b"bb" + original_generator
FAKE_BLOCK_HEIGHT1 = uint32(100)
FAKE_BLOCK_HEIGHT2 = uint32(200)


@dataclass(frozen=True)
class MultipleCompressorArg:
    arg: List[CompressorArg]
    split_offset: int


def create_multiple_ref_generator(args: MultipleCompressorArg, spend_bundle: SpendBundle) -> BlockGenerator:
    """
    Decompress a transaction by referencing bytes from multiple input generator references
    """
    compressed_cse_list = compressed_coin_spend_entry_list(spend_bundle)
    program = TEST_MULTIPLE.curry(
        DECOMPRESS_PUZZLE,
        DECOMPRESS_CSE_WITH_PREFIX,
        args.arg[0].start,
        args.arg[0].end - args.split_offset,
        args.arg[1].end - args.split_offset,
        args.arg[1].end,
        compressed_cse_list,
    )

    # TODO aqk: Improve ergonomics of CompressorArg -> GeneratorArg conversion
    generator_list = [
        args.arg[0].generator,
        args.arg[1].generator,
    ]
    generator_heights = [
        FAKE_BLOCK_HEIGHT1,
        FAKE_BLOCK_HEIGHT2,
    ]
    return BlockGenerator(program, generator_list, generator_heights)


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
    def test_spend_bundle_suitable(self) -> None:
        sb: SpendBundle = make_spend_bundle(1)
        assert bundle_suitable_for_compression(sb)

    def test_compress_spend_bundle(self) -> None:
        pass

    def test_multiple_input_gen_refs(self) -> None:
        match = match_standard_transaction_at_any_index(gen1)
        assert match is not None
        start1, end1 = match
        match = match_standard_transaction_at_any_index(gen2)
        assert match is not None
        start2, end2 = match
        ca1 = CompressorArg(FAKE_BLOCK_HEIGHT1, SerializedProgram.from_bytes(gen1), start1, end1)
        ca2 = CompressorArg(FAKE_BLOCK_HEIGHT2, SerializedProgram.from_bytes(gen2), start2, end2)

        prefix_len1 = end1 - start1
        prefix_len2 = end2 - start2
        assert prefix_len1 == prefix_len2
        prefix_len = prefix_len1
        results = []
        for split_offset in range(prefix_len):
            gen_args = MultipleCompressorArg([ca1, ca2], split_offset)
            spend_bundle: SpendBundle = make_spend_bundle(1)
            multi_gen = create_multiple_ref_generator(gen_args, spend_bundle)
            cost, result = run_generator(multi_gen)
            results.append(result)
            assert result is not None
            assert cost > 0
        assert all(r == results[0] for r in results)

    def test_compressed_block_results(self) -> None:
        sb: SpendBundle = make_spend_bundle(1)
        match = match_standard_transaction_at_any_index(original_generator)
        assert match is not None
        start, end = match
        ca = CompressorArg(uint32(0), SerializedProgram.from_bytes(original_generator), start, end)
        c = compressed_spend_bundle_solution(ca, sb)
        s = simple_solution_generator(sb)
        assert c != s
        cost_c, result_c = run_generator(c)
        cost_s, result_s = run_generator(s)
        print()
        print(result_c)
        assert result_c is not None
        assert result_s is not None
        print(result_s)
        assert result_c == result_s

    def test_get_removals_for_single_coin(self) -> None:
        sb: SpendBundle = make_spend_bundle(1)
        match = match_standard_transaction_at_any_index(original_generator)
        assert match is not None
        start, end = match
        ca = CompressorArg(uint32(0), SerializedProgram.from_bytes(original_generator), start, end)
        c = compressed_spend_bundle_solution(ca, sb)
        removal = sb.coin_spends[0].coin
        spend_info = get_puzzle_and_solution_for_coin(c, removal, 0)
        assert bytes(spend_info.puzzle) == bytes(sb.coin_spends[0].puzzle_reveal)
        assert bytes(spend_info.solution) == bytes(sb.coin_spends[0].solution)
        # Test non compressed generator as well
        s = simple_solution_generator(sb)
        spend_info = get_puzzle_and_solution_for_coin(s, removal, 0)
        assert bytes(spend_info.puzzle) == bytes(sb.coin_spends[0].puzzle_reveal)
        assert bytes(spend_info.solution) == bytes(sb.coin_spends[0].solution)

        # test with backrefs (2.0 hard-fork)
        s = simple_solution_generator_backrefs(sb)
        spend_info = get_puzzle_and_solution_for_coin(s, removal, ALLOW_BACKREFS)
        assert Program.from_bytes(bytes(spend_info.puzzle)) == Program.from_bytes(
            bytes(sb.coin_spends[0].puzzle_reveal)
        )
        assert Program.from_bytes(bytes(spend_info.solution)) == Program.from_bytes(bytes(sb.coin_spends[0].solution))


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
        cse0 = binutils.assemble(  # type: ignore[no-untyped-call]
            "((0x0000000000000000000000000000000000000000000000000000000000000000 0x0186a0) (0xb081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3 (() (q (51 0x6b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9 0x0186a0)) ())))"
        )
        cost, out = DECOMPRESS_CSE.run_with_cost(
            INFINITE_COST, [DESERIALIZE_MOD, DECOMPRESS_PUZZLE, b"\xff", b"\x80", cse0]
        )

        print()
        print(out)

    def test_decompress_cse_with_prefix(self) -> None:
        cse0 = binutils.assemble(  # type: ignore[no-untyped-call]
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
        cse1 = binutils.assemble(  # type: ignore[no-untyped-call]
            "(((0x0000000000000000000000000000000000000000000000000000000000000000 0x0186a0) (0xb081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3 (() (q (51 0x6b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9 0x0186a0)) ()))))"
        )
        cse2 = binutils.assemble(  # type: ignore[no-untyped-call]
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
        cse1 = binutils.assemble(  # type: ignore[no-untyped-call]
            "(((0x0000000000000000000000000000000000000000000000000000000000000000 0x0186a0) (0xb081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3 (() (q (51 0x6b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9 0x0186a0)) ()))))"
        )
        cse2 = binutils.assemble(  # type: ignore[no-untyped-call]
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
