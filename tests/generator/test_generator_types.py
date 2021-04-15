from typing import Dict
from unittest import TestCase

from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.generator_types import GeneratorBlockCacheInterface
from chia.full_node.generator import create_block_generator, create_generator_args
from chia.util.byte_types import hexstr_to_bytes
from chia.util.ints import uint32


gen0 = SerializedProgram.from_bytes(
    hexstr_to_bytes(
        "ff01ffffffa00000000000000000000000000000000000000000000000000000000000000000ff830186a080ffffff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3ff018080ffff80ffff01ffff33ffa06b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9ff830186a08080ff8080808080"  # noqa
    )
)

gen1 = SerializedProgram.from_bytes(
    hexstr_to_bytes(
        "ff01ffffffa00000000000000000000000000000000000000000000000000000000000000000ff830186a080ffffff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3ff018080ffff80ffff01ffff33ffa06b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9ff830186a08080ff8080808080"  # noqa
    )
)

gen2 = SerializedProgram.from_bytes(
    hexstr_to_bytes(
        "ff01ffffffa00000000000000000000000000000000000000000000000000000000000000000ff830186a080ffffff02ffff01ff02ffff01ff02ffff03ff0bffff01ff02ffff03ffff09ff05ffff1dff0bffff1effff0bff0bffff02ff06ffff04ff02ffff04ff17ff8080808080808080ffff01ff02ff17ff2f80ffff01ff088080ff0180ffff01ff04ffff04ff04ffff04ff05ffff04ffff02ff06ffff04ff02ffff04ff17ff80808080ff80808080ffff02ff17ff2f808080ff0180ffff04ffff01ff32ff02ffff03ffff07ff0580ffff01ff0bffff0102ffff02ff06ffff04ff02ffff04ff09ff80808080ffff02ff06ffff04ff02ffff04ff0dff8080808080ffff01ff0bffff0101ff058080ff0180ff018080ffff04ffff01b081963921826355dcb6c355ccf9c2637c18adf7d38ee44d803ea9ca41587e48c913d8d46896eb830aeadfc13144a8eac3ff018080ffff80ffff01ffff33ffa06b7a83babea1eec790c947db4464ab657dbe9b887fe9acc247062847b8c2a8a9ff830186a08080ff8080808080"  # noqa
    )
)


class BlockDict(GeneratorBlockCacheInterface):
    def __init__(self, d: Dict[uint32, SerializedProgram]):
        self.d = d

    def get_generator_for_block_height(self, index: uint32) -> SerializedProgram:
        return self.d[index]


class TestGeneratorTypes(TestCase):
    def test_make_generator(self):
        block_dict = BlockDict({1: gen1})
        gen = create_block_generator(gen2, [1], block_dict)
        print(gen)

    def test_make_generator_args(self):
        generator_ref_list = [gen1]
        gen_args = create_generator_args(generator_ref_list)
        gen_args_as_program = Program.from_bytes(bytes(gen_args))

        d = gen_args_as_program.first()

        # First arguemnt: clvm deserializer

        b = hexstr_to_bytes("ff8568656c6c6fff86667269656e6480")  # ("hello" "friend")
        cost, output = d.run_with_cost([b])
        # print(cost, output)
        out = Program.to(output)
        assert out == Program.from_bytes(b)

        # Second Argument
        arg2 = gen_args_as_program.rest().first().first()
        print(arg2)
        assert bytes(arg2) == bytes(gen1)
