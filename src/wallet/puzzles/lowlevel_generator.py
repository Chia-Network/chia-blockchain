# from src.wallet.chialisp import eval, sexp, args, make_if, quote, make_list, rest, cons, sha256tree
from src.types.blockchain_format.program import SerializedProgram, Program
from clvm_tools import binutils


def get_generator():
    #
    # # args0 is generate_npc_pair_list, args1 is coin_solutions, args2 is output_list
    # programs = args(0)
    # coin_solutions = args(1)
    # output_list = args(2)
    # # coin_solution = first(coin_solutions)
    # # coin_name = first(coin_solution)
    # # puzzle_solution_pair = first(rest(coin_solution))
    # # puzzle = first(puzzle_solution_pair)
    # # solution = first(rest(puzzle_solution_pair))
    # coin_name = args(0, 0, 1)
    # puzzle = args(0, 1, 0, 1)
    # solution = args(1, 1, 0, 1)
    # # get_puzhash = eval(first(rest(programs)), make_list(first(rest(programs)), puzzle))
    # get_npc = make_list(coin_name, sha256tree(puzzle), eval(puzzle, solution))
    #
    # recursive_call = eval(programs, make_list(programs, rest(coin_solutions), cons(get_npc, output_list)))
    #
    # generate_npc_pair_list = make_if(coin_solutions, recursive_call, output_list)
    #
    # # Run the block_program and enter loop over the results
    # # args0 is generate_npc_pair_list, args1 is block_program being passed in
    #
    # programs = args(0)
    # coin_solutions = args(1)
    # execute_generate_npc_pair = eval(programs, make_list(programs, coin_solutions, sexp()))
    #
    # # Bootstrap the execution by passing functions in as parameters before the actual data arguments
    # get_coinsols = eval(args(0), args(1))
    # core = eval(quote(execute_generate_npc_pair), make_list(quote(generate_npc_pair_list), get_coinsols))

    # The below string is exactly the same as the value of 'core' above, except '(r 5)' is replaced with '13'
    test = "(a (q . (a 2 (c 2 (c 5 (c () ()))))) (c (q . (a (i 5 (q . (a 2 (c 2 (c 13 (c (c (c 17 (c (a (q . (a 2 (c 2 (c 3 0)))) (c (q . (a (i (l 5) (q . (sha256 (q . 2) (a 2 (c 2 (c 9 0))) (a 2 (c 2 (c 13 0))))) (q . (sha256 (q . 1) 5))) 1)) 73)) (c (a 73 169) ()))) 11) ()))))) (q . 11)) 1)) (c (a 2 5) ())))"  # noqa
    ret = SerializedProgram.from_bytes(bytes(Program.to(binutils.assemble(test))))

    return ret
