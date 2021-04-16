from typing import Dict
from unittest import TestCase

from chia.types.blockchain_format.program import Program, SerializedProgram
from chia.types.generator_types import GeneratorBlockCacheInterface
from chia.full_node.generator import create_block_generator, make_generator_args, list_to_tree
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
    def test_make_generator(self):
        block_dict = BlockDict({1: gen1})
        gen = create_block_generator(gen2, [1], block_dict)
        print(gen)

    def test_make_generator_args(self):
        generator_ref_list = [gen1]
        gen_args = make_generator_args(generator_ref_list)
        gen_args_as_program = Program.from_bytes(bytes(gen_args))

        d = gen_args_as_program.first()

        # First argument: clvm deserializer

        b = bytes.fromhex("ff8568656c6c6fff86667269656e6480")  # ("hello" "friend")
        cost, output = d.run_with_cost([b])
        # print(cost, output)
        out = Program.to(output)
        assert out == Program.from_bytes(b)

        # Second Argument
        arg2 = gen_args_as_program.rest().first()
        print(arg2)
        assert bytes(arg2) == bytes(gen1)

    def test_list_to_tree(self):
        self.assertEqual([], list_to_tree([]))
        self.assertEqual(1, list_to_tree([1]))
        self.assertEqual((1, 2), list_to_tree([1, 2]))
        self.assertEqual(((1, 2), 3), list_to_tree([1, 2, 3]))
        self.assertEqual(((1, 2), (3, 4)), list_to_tree([1, 2, 3, 4]))
        self.assertEqual((((1, 2), 3), (4, 5)), list_to_tree([1, 2, 3, 4, 5]))
        self.assertEqual((((1, 2), 3), ((4, 5), 6)), list_to_tree([1, 2, 3, 4, 5, 6]))
        self.assertEqual((((1, 2), (3, 4)), ((5, 6), 7)), list_to_tree([1, 2, 3, 4, 5, 6, 7]))
        self.assertEqual((((1, 2), (3, 4)), ((5, 6), (7, 8))), list_to_tree([1, 2, 3, 4, 5, 6, 7, 8]))
        R = (
            (
                (
                    ((((0, 1), 2), (3, 4)), (((5, 6), 7), (8, 9))),
                    ((((10, 11), 12), (13, 14)), (((15, 16), 17), (18, 19))),
                ),
                (
                    ((((20, 21), 22), (23, 24)), (((25, 26), 27), (28, 29))),
                    ((((30, 31), 32), (33, 34)), (((35, 36), 37), (38, 39))),
                ),
            ),
            (
                (
                    ((((40, 41), 42), (43, 44)), (((45, 46), 47), (48, 49))),
                    ((((50, 51), 52), (53, 54)), (((55, 56), 57), (58, 59))),
                ),
                (
                    ((((60, 61), 62), (63, 64)), (((65, 66), 67), (68, 69))),
                    ((((70, 71), 72), (73, 74)), (((75, 76), 77), (78, 79))),
                ),
            ),
        )
        self.assertEqual(R, list_to_tree(list(range(80))))
