from clvm.casts import int_from_bytes
from clvm_tools import binutils

from hddcoin.consensus.block_rewards import calculate_base_farmer_reward, calculate_pool_reward
from hddcoin.types.blockchain_format.program import Program
from hddcoin.types.condition_opcodes import ConditionOpcode
from hddcoin.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from hddcoin.util.condition_tools import parse_sexp_to_conditions
from hddcoin.util.ints import uint32

address1 = "hdd1tm2fmappqenrj3c9ngej8k33pujvspxxea6zpu7p4sx0lvle62es9ae95j"  # HDDcoin Network Inc Reserves Account-1
address2 = "hdd1tm2fmappqenrj3c9ngej8k33pujvspxxea6zpu7p4sx0lvle62es9ae95j"  # HDDcoin Network Inc Reserves Account-1

ph1 = decode_puzzle_hash(address1)
ph2 = decode_puzzle_hash(address2)

pool_amounts = int(calculate_pool_reward(uint32(0)) / 2)
farmer_amounts = int(calculate_base_farmer_reward(uint32(0)) / 2)

assert pool_amounts * 2 == calculate_pool_reward(uint32(0))
assert farmer_amounts * 2 == calculate_base_farmer_reward(uint32(0))


def make_puzzle(amount: int) -> int:
    puzzle = f"(q . ((51 0x{ph1.hex()} {amount}) (51 0x{ph2.hex()} {amount})))"
    # print(puzzle)

    puzzle_prog = Program.to(binutils.assemble(puzzle))
    print("Program: ", puzzle_prog)
    puzzle_hash = puzzle_prog.get_tree_hash()

    solution = "()"
    prefix = "hdd"
    print("PH", puzzle_hash)
    print(f"Address: {encode_puzzle_hash(puzzle_hash, prefix)}")

    result = puzzle_prog.run(solution)
    error, result_human = parse_sexp_to_conditions(result)

    total_hddcoin = 0
    if error:
        print(f"Error: {error}")
    else:
        assert result_human is not None
        for cvp in result_human:
            assert len(cvp.vars) == 2
            total_hddcoin += int_from_bytes(cvp.vars[1])
            print(
                f"{ConditionOpcode(cvp.opcode).name}: {encode_puzzle_hash(cvp.vars[0], prefix)},"
                f" amount: {int_from_bytes(cvp.vars[1])}"
            )
    return total_hddcoin


total_hddcoin = 0
print("Pool address: ")
total_hddcoin += make_puzzle(pool_amounts)
print("\nFarmer address: ")
total_hddcoin += make_puzzle(farmer_amounts)

assert total_hddcoin == calculate_base_farmer_reward(uint32(0)) + calculate_pool_reward(uint32(0))
