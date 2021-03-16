from blspy import G1Element
from clvm.casts import int_from_bytes
from clvm_tools import binutils

from src.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from src.consensus.coinbase import create_puzzlehash_for_pk
from src.types.blockchain_format.program import Program
from src.types.condition_opcodes import ConditionOpcode
from src.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from src.util.condition_tools import parse_sexp_to_conditions
from src.util.ints import uint32

prefix = "xch"
# address1 = "txch15gx26ndmacfaqlq8m0yajeggzceu7cvmaz4df0hahkukes695rss6lej7h"  # Gene wallet (m/12381/8444/2/42):
# address2 = "txch1c2cguswhvmdyz9hr3q6hak2h6p9dw4rz82g4707k2xy2sarv705qcce4pn"  # Mariano address (m/12381/8444/2/0)
pk_1_hex = "9007423b5041adb5c77913a428f2665732d5dba9e1ce817aa0b5f61b1254b8bccf256d52cb4a18c85c60d46c2201d7f5"  # key 1 (m/12381/8444/2/69)
pk_2_hex = "aa9dba0bb5b9d636f063cd9ddf916c9fbc0eb7f16dbe162749bc91fa46019ee20596b07102652774992b7cda3afb97d7"  # key 2 (m/12381/8444/2/69)

assert len(pk_1_hex) == len(pk_2_hex) == 96
ph_1 = create_puzzlehash_for_pk(G1Element.from_bytes(bytes.fromhex(pk_1_hex)))
ph_2 = create_puzzlehash_for_pk(G1Element.from_bytes(bytes.fromhex(pk_2_hex)))
address_1_gen = encode_puzzle_hash(ph_1, prefix)
address_2_gen = encode_puzzle_hash(ph_2, prefix)

address1 = "xch1rdatypul5c642jkeh4yp933zu3hw8vv8tfup8ta6zfampnyhjnusxdgns6"  # Key 1
address2 = "xch1duvy5ur5eyj7lp5geetfg84cj2d7xgpxt7pya3lr2y6ke3696w9qvda66e"  # Key 2

assert address1 == address_1_gen and address2 == address_2_gen


ph1 = decode_puzzle_hash(address1)
ph2 = decode_puzzle_hash(address2)

pool_amounts = int(calculate_pool_reward(uint32(0)) / 2)
farmer_amounts = int(calculate_base_farmer_reward(uint32(0)) / 2)

assert pool_amounts * 2 == calculate_pool_reward(uint32(0))
assert farmer_amounts * 2 == calculate_base_farmer_reward(uint32(0))


def make_puzzle(amount: int) -> int:
    puzzle = f"(q . ((51 0x{ph1.hex()} {amount}) (51 0x{ph2.hex()} {amount})))"

    puzzle_prog = Program.to(binutils.assemble(puzzle))
    print("Program: ", puzzle_prog)
    puzzle_hash = puzzle_prog.get_tree_hash()

    solution = "()"
    print("PH", puzzle_hash)
    print(f"Address: {encode_puzzle_hash(puzzle_hash, prefix)}")

    result = puzzle_prog.run(solution)
    error, result_human = parse_sexp_to_conditions(result)

    total_chia = 0
    if error:
        print(f"Error: {error}")
    else:
        assert result_human is not None
        for cvp in result_human:
            assert len(cvp.vars) == 2
            total_chia += int_from_bytes(cvp.vars[1])
            print(
                f"{ConditionOpcode(cvp.opcode).name}: {encode_puzzle_hash(cvp.vars[0], prefix)},"
                f" amount: {int_from_bytes(cvp.vars[1])}"
            )
    return total_chia


total_chia = 0
print("Pool address: ")
total_chia += make_puzzle(pool_amounts)
print("\nFarmer address: ")
total_chia += make_puzzle(farmer_amounts)

assert total_chia == calculate_base_farmer_reward(uint32(0)) + calculate_pool_reward(uint32(0))
