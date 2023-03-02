from __future__ import annotations

from typing import List

from clvm_tools import binutils
from clvm_tools.clvmc import compile_clvm_text

from chia.consensus.condition_costs import ConditionCost
from chia.full_node.generator import run_generator_unsafe
from chia.full_node.mempool_check_conditions import get_name_puzzle_conditions
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.types.generator_types import BlockGenerator
from chia.types.spend_bundle_conditions import ELIGIBLE_FOR_DEDUP, Spend
from chia.util.ints import uint32
from chia.wallet.puzzles.load_clvm import load_clvm

MAX_COST = int(1e15)
COST_PER_BYTE = int(12000)


DESERIALIZE_MOD = load_clvm("chialisp_deserialisation.clvm", package_or_requirement="chia.wallet.puzzles")


GENERATOR_CODE = """
(mod (deserialize-mod historical-generators)
    (defun first-block (deserialize-mod historical-generators)
                       (a deserialize-mod (list (f historical-generators))))

    (defun second-block (deserialize-mod historical-generators)
                        (a deserialize-mod (r historical-generators)))

    (defun go (deserialize-mod historical-generators)
    (c (first-block deserialize-mod historical-generators)
       (second-block deserialize-mod historical-generators)
    ))
    (go deserialize-mod historical-generators)
)
"""


COMPILED_GENERATOR_CODE = bytes.fromhex(
    "ff02ffff01ff04ffff02ff04ffff04ff02ffff04ff05ffff04ff0bff8080808080ffff02"
    "ff06ffff04ff02ffff04ff05ffff04ff0bff808080808080ffff04ffff01ffff02ff05ff"
    "1380ff02ff05ff2b80ff018080"
)

COMPILED_GENERATOR_CODE = bytes(Program.to(compile_clvm_text(GENERATOR_CODE, [])))

FIRST_GENERATOR = Program.to(
    binutils.assemble('((parent_id (c 1 (q "puzzle blob")) 50000 "solution is here" extra data for coin))')
).as_bin()

SECOND_GENERATOR = Program.to(binutils.assemble("(extra data for block)")).as_bin()


FIRST_GENERATOR = Program.to(
    binutils.assemble(
        """
        ((0x0000000000000000000000000000000000000000000000000000000000000000 1 50000
        ((51 0x0000000000000000000000000000000000000000000000000000000000000001 500)) "extra" "data" "for" "coin" ))"""
    )
).as_bin()

SECOND_GENERATOR = Program.to(binutils.assemble("(extra data for block)")).as_bin()


def to_sp(sexp) -> SerializedProgram:
    return SerializedProgram.from_bytes(bytes(sexp))


def block_generator() -> BlockGenerator:
    generator_list = [to_sp(FIRST_GENERATOR), to_sp(SECOND_GENERATOR)]
    generator_heights = [uint32(0), uint32(1)]
    return BlockGenerator(to_sp(COMPILED_GENERATOR_CODE), generator_list, generator_heights)


EXPECTED_ABBREVIATED_COST = 108379
EXPECTED_COST = 113415
EXPECTED_OUTPUT = (
    "ffffffa00000000000000000000000000000000000000000000000000000000000000000"
    "ff01ff8300c350ffffff33ffa00000000000000000000000000000000000000000000000"
    "000000000000000001ff8201f48080ff856578747261ff8464617461ff83666f72ff8463"
    "6f696e8080ff856578747261ff8464617461ff83666f72ff85626c6f636b80"
)


def as_atom_list(prg: Program) -> List[bytes]:
    """
    Pretend `prg` is a list of atoms. Return the corresponding
    python list of atoms.

    At each step, we always assume a node to be an atom or a pair.
    If the assumption is wrong, we exit early. This way we never fail
    and always return SOMETHING.
    """
    items = []
    obj = prg
    while True:
        pair = obj.pair
        if pair is None:
            break
        atom = pair[0].atom
        if atom is None:
            break
        items.append(atom)
        obj = pair[1]
    return items


class TestROM:
    def test_rom_inputs(self):
        # this test checks that the generator just works
        # It's useful for debugging the generator prior to having the ROM invoke it.

        args = Program.to([DESERIALIZE_MOD, [FIRST_GENERATOR, SECOND_GENERATOR]])
        sp = to_sp(COMPILED_GENERATOR_CODE)
        cost, r = sp.run_with_cost(MAX_COST, args)
        assert cost == EXPECTED_ABBREVIATED_COST
        assert r.as_bin().hex() == EXPECTED_OUTPUT

    def test_get_name_puzzle_conditions(self, softfork_height):
        # this tests that extra block or coin data doesn't confuse `get_name_puzzle_conditions`

        gen = block_generator()
        cost, r = run_generator_unsafe(gen, max_cost=MAX_COST)
        print(r)

        npc_result = get_name_puzzle_conditions(
            gen, max_cost=MAX_COST, cost_per_byte=COST_PER_BYTE, mempool_mode=False, height=softfork_height
        )
        assert npc_result.error is None
        assert npc_result.cost == EXPECTED_COST + ConditionCost.CREATE_COIN.value + (
            len(bytes(gen.program)) * COST_PER_BYTE
        )

        spend = Spend(
            coin_id=bytes32.fromhex("e8538c2d14f2a7defae65c5c97f5d4fae7ee64acef7fec9d28ad847a0880fd03"),
            puzzle_hash=bytes32.fromhex("9dcf97a184f32623d11a73124ceb99a5709b083721e878a16d78f596718ba7b2"),
            height_relative=None,
            seconds_relative=0,
            before_height_relative=None,
            before_seconds_relative=None,
            birth_height=None,
            birth_seconds=None,
            create_coin=[(bytes([0] * 31 + [1]), 500, None)],
            agg_sig_me=[],
            flags=ELIGIBLE_FOR_DEDUP,
        )

        assert npc_result.conds.spends == [spend]

    def test_coin_extras(self):
        # the ROM supports extra data after a coin. This test checks that it actually gets passed through

        gen = block_generator()
        cost, r = run_generator_unsafe(gen, max_cost=MAX_COST)
        coin_spends = r.first()
        for coin_spend in coin_spends.as_iter():
            extra_data = coin_spend.rest().rest().rest().rest()
            assert as_atom_list(extra_data) == b"extra data for coin".split()

    def test_block_extras(self):
        # the ROM supports extra data after the coin spend list. This test checks that it actually gets passed through

        gen = block_generator()
        cost, r = run_generator_unsafe(gen, max_cost=MAX_COST)
        extra_block_data = r.rest()
        assert as_atom_list(extra_block_data) == b"extra data for block".split()
