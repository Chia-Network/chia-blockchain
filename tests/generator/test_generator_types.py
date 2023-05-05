from __future__ import annotations

from typing import Dict
from unittest import TestCase

from chia.full_node.generator import create_block_generator
from chia.types.blockchain_format.program import Program
from chia.types.blockchain_format.serialized_program import SerializedProgram
from chia.types.generator_types import GeneratorBlockCacheInterface
from chia.util.ints import uint32

gen0 = SerializedProgram.from_bytes(
    bytes.fromhex(
        "ff01ffffffa00000000000000000000000000000000000000000000000000000000000000000ff830186a080ffffff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3ff018080ffff80ffff01ffff33ffa06b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9ff830186a08080ff8080808080"  # noqa
    )
)

gen1 = SerializedProgram.from_bytes(
    bytes.fromhex(
        "ff01ffffffa00000000000000000000000000000000000000000000000000000000000000000ff830186a080ffffff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3ff018080ffff80ffff01ffff33ffa06b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9ff830186a08080ff8080808080"  # noqa
    )
)

gen2 = SerializedProgram.from_bytes(
    bytes.fromhex(
        "ff01ffffffa00000000000000000000000000000000000000000000000000000000000000000ff830186a080ffffff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3ff018080ffff80ffff01ffff33ffa06b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9ff830186a08080ff8080808080"  # noqa
    )
)


class BlockDict(GeneratorBlockCacheInterface):
    def __init__(self, d: Dict[uint32, SerializedProgram]):
        self.d = d

    def get_generator_for_block_height(self, index: uint32) -> SerializedProgram:
        return self.d[index]


class TestGeneratorTypes(TestCase):
    def test_make_generator(self) -> None:
        block_dict = BlockDict({uint32(1): gen1})
        gen = create_block_generator(gen2, [uint32(1)], block_dict)
        print(gen)

    def test_make_generator_args(self) -> None:
        gen_args = Program.to([[bytes(gen1)]])

        # First Argument to the block generator is the first template generator
        arg2 = gen_args.first().first()
        print(arg2)
        assert arg2 == bytes(gen1)

    # It's not a list anymore.
    # TODO: Test the first three arg positions passed through here.
    # def test_generator_arg_is_list(self):
    #    generator_ref_list = [Program.to(b"gen1"), Program.to(b"gen2")]
    #    gen_args = create_generator_args(generator_ref_list)
    #    gen_args_as_program = Program.from_bytes(bytes(gen_args))
    #    arg2 = gen_args_as_program.rest().first()
    #    assert arg2 == binutils.assemble("('gen1' 'gen2')")
    #    print(arg2)
