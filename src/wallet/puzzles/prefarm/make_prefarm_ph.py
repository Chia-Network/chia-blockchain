from clvm.casts import int_from_bytes
from clvm_tools import binutils

from src.types.blockchain_format.program import Program
from src.types.condition_opcodes import ConditionOpcode
from src.util.bech32m import decode_puzzle_hash, encode_puzzle_hash
from src.util.condition_tools import parse_sexp_to_conditions
from src.consensus.block_rewards import calculate_pool_reward, calculate_base_farmer_reward
from src.util.ints import uint32

address1 = "txch17gqxp6vnq90ypl8kzn56c2jejcva90tf6sh2dumw05nrxwggf2lskq2es5"  # Gene wallet (m/12381/8444/2/59):
address2 = "txch1n4l69tm4s4ekju9uce6xaq7fym8mkzcxrrn77xngl9ej7t8nd8ks409lhk"  # mariano main key

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
    print("PH", puzzle_hash)
    print(f"Address: {encode_puzzle_hash(puzzle_hash)}")

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
                f"{ConditionOpcode(cvp.opcode).name}: {encode_puzzle_hash(cvp.vars[0])},"
                f" amount: {int_from_bytes(cvp.vars[1])}"
            )
    return total_chia


total_chia = 0
print("Pool address: ")
total_chia += make_puzzle(pool_amounts)
print("\nFarmer address: ")
total_chia += make_puzzle(farmer_amounts)

assert total_chia == calculate_base_farmer_reward(uint32(0)) + calculate_pool_reward(uint32(0))
