# flake8: noqa: F501
from unittest import TestCase

from chia.full_node.bundle_tools import (
    bundle_suitable_for_compression,
    simple_solution_generator,
    compressed_spend_bundle_solution,
    match_standard_transaction_at_any_index,
)
from chia.full_node.generator import run_generator, create_generator_args
from chia.types.blockchain_format.program import Program, SerializedProgram, INFINITE_COST
from chia.types.generator_types import CompressorArg
from chia.types.spend_bundle import SpendBundle
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint32
from chia.wallet.puzzles.load_clvm import load_clvm

from tests.core.make_block_generator import make_spend_bundle

from clvm_tools import binutils

TEST_GEN_DESERIALIZE = load_clvm("test_generator_deserialize.clvm", package_or_requirement="chia.wallet.puzzles")
DESERIALIZE_MOD = load_clvm("chialisp_deserialisation.clvm", package_or_requirement="chia.wallet.puzzles")

DECOMPRESS_PUZZLE = load_clvm("decompress_puzzle.clvm", package_or_requirement="chia.wallet.puzzles")
DECOMPRESS_CSE = load_clvm("decompress_coin_solution_entry.clvm", package_or_requirement="chia.wallet.puzzles")

DECOMPRESS_CSE_WITH_PREFIX = load_clvm(
    "decompress_coin_solution_entry_with_prefix.clvm", package_or_requirement="chia.wallet.puzzles"
)
DECOMPRESS_BLOCK = load_clvm("block_program_zero.clvm", package_or_requirement="chia.wallet.puzzles")


Nil = Program.from_bytes(b"\x80")

original_generator = hexstr_to_bytes(
    "ff01ffffffa00000000000000000000000000000000000000000000000000000000000000000ff830186a080ffffff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3ff018080ffff80ffff01ffff33ffa06b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9ff830186a08080ff8080808080"
)  # noqa


class TestCompression(TestCase):
    def test_spend_bundle_suitable(self):
        sb: SpendBundle = make_spend_bundle(1)
        assert bundle_suitable_for_compression(sb)

    def test_compress_spend_bundle(self):
        pass

    def test_compressed_block_results(self):
        sb: SpendBundle = make_spend_bundle(1)
        start, end = match_standard_transaction_at_any_index(original_generator)
        ca = CompressorArg(uint32(0), SerializedProgram.from_bytes(original_generator), start, end)
        c = compressed_spend_bundle_solution(ca, sb)
        s = simple_solution_generator(sb)
        assert c != s
        cost_c, result_c = run_generator(c, INFINITE_COST)
        cost_s, result_s = run_generator(s, INFINITE_COST)
        print(result_c)
        assert result_c is not None
        assert result_s is not None
        assert result_c == result_s


class TestDecompression(TestCase):
    def __init__(self, *args, **kwargs):
        super(TestDecompression, self).__init__(*args, **kwargs)
        self.maxDiff = None

    def test_deserialization(self):
        self.maxDiff = None
        cost, out = DESERIALIZE_MOD.run_with_cost(INFINITE_COST, [bytes(Program.to("hello"))])
        assert out == Program.to("hello")

    def test_deserialization_as_argument(self):
        self.maxDiff = None
        cost, out = TEST_GEN_DESERIALIZE.run_with_cost(
            INFINITE_COST, [DESERIALIZE_MOD, Nil, bytes(Program.to("hello"))]
        )
        print(bytes(Program.to("hello")))
        print()
        print(out)
        assert out == Program.to("hello")

    def test_decompress_puzzle(self):
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

    def test_decompress_cse(self):
        """ Decompress a single CSE / CoinSolutionEntry """
        cse0 = binutils.assemble(
            "((0x0000000000000000000000000000000000000000000000000000000000000000 0x0186a0) (0xb081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3 (() (q (51 0x6b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9 0x0186a0)) ())))"
        )  # noqa
        cost, out = DECOMPRESS_CSE.run_with_cost(
            INFINITE_COST, [DESERIALIZE_MOD, DECOMPRESS_PUZZLE, b"\xff", b"\x80", cse0]
        )

        print()
        print(out)

    def test_decompress_cse_with_prefix(self):
        cse0 = binutils.assemble(
            "((0x0000000000000000000000000000000000000000000000000000000000000000 0x0186a0) (0xb081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3 (() (q (51 0x6b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9 0x0186a0)) ())))"
        )  # noqa

        start = 2 + 44
        end = start + 238
        prefix = original_generator[start:end]
        # (deserialize decompress_puzzle puzzle_prefix cse)
        cost, out = DECOMPRESS_CSE_WITH_PREFIX.run_with_cost(
            INFINITE_COST, [DESERIALIZE_MOD, DECOMPRESS_PUZZLE, prefix, cse0]
        )

        print()
        print(out)

    def test_block_program_zero(self):
        "Decompress a list of CSEs"
        self.maxDiff = None
        cse1 = binutils.assemble(
            "(((0x0000000000000000000000000000000000000000000000000000000000000000 0x0186a0) (0xb081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3 (() (q (51 0x6b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9 0x0186a0)) ()))))"
        )  # noqa
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
        )  # noqa

        start = 2 + 44
        end = start + 238

        # (mod (decompress_puzzle decompress_coin_solution_entry start end compressed_cses deserialize generator_list reserved_arg)
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
                bytes(original_generator),
            ],
        )

        print()
        print(out)

    def test_block_program_zero_with_curry(self):
        self.maxDiff = None
        cse1 = binutils.assemble(
            "(((0x0000000000000000000000000000000000000000000000000000000000000000 0x0186a0) (0xb081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3 (() (q (51 0x6b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9 0x0186a0)) ()))))"
        )  # noqa
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
        )  # noqa

        start = 2 + 44
        end = start + 238

        # (mod (decompress_puzzle decompress_coin_solution_entry start end compressed_cses deserialize generator_list reserved_arg)
        # cost, out = DECOMPRESS_BLOCK.run_with_cost(INFINITE_COST, [DECOMPRESS_PUZZLE, DECOMPRESS_CSE, start, Program.to(end), cse0, DESERIALIZE_MOD, bytes(original_generator)])
        p = DECOMPRESS_BLOCK.curry(DECOMPRESS_PUZZLE, DECOMPRESS_CSE_WITH_PREFIX, start, Program.to(end))
        cost, out = p.run_with_cost(INFINITE_COST, [cse2, DESERIALIZE_MOD, bytes(original_generator)])

        print()
        print(p)
        print(out)

        p_with_cses = DECOMPRESS_BLOCK.curry(
            DECOMPRESS_PUZZLE, DECOMPRESS_CSE_WITH_PREFIX, start, Program.to(end), cse2
        )
        generator_args = create_generator_args([SerializedProgram.from_bytes(original_generator)])
        cost, out = p_with_cses.run_with_cost(INFINITE_COST, generator_args)

        print()
        print(p_with_cses)
        print(out)
