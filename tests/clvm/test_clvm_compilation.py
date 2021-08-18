from pathlib import Path
from unittest import TestCase

from clvm_tools.clvmc import compile_clvm

from chia.types.blockchain_format.program import Program, SerializedProgram

all_program_files = set(
    [
        # Standard wallet
        "chia/wallet/puzzles/calculate_synthetic_public_key.clsp",
        "chia/wallet/puzzles/p2_conditions.clsp",
        "chia/wallet/puzzles/p2_delegated_conditions.clsp",
        "chia/wallet/puzzles/p2_delegated_puzzle.clsp",
        "chia/wallet/puzzles/p2_delegated_puzzle_or_hidden_puzzle.clsp",
        "chia/wallet/puzzles/p2_m_of_n_delegate_direct.clsp",
        "chia/wallet/puzzles/p2_puzzle_hash.clsp",
        # Generators
        "chia/full_node/generator_puzzles/chialisp_deserialisation.clsp",
        "chia/full_node/generator_puzzles/rom_bootstrap_generator.clsp",
        "chia/full_node/generator_puzzles/generator_for_single_coin.clsp",
        "chia/full_node/generator_puzzles/decompress_puzzle.clsp",
        "chia/full_node/generator_puzzles/decompress_coin_spend_entry_with_prefix.clsp",
        "chia/full_node/generator_puzzles/decompress_coin_spend_entry.clsp",
        "chia/full_node/generator_puzzles/block_program_zero.clsp",
        # Coloured Coins
        "chia/wallet/cc_wallet/puzzles/cc.clsp",
        "chia/wallet/cc_wallet/puzzles/genesis_by_coin_id_with_0.clsp",
        "chia/wallet/cc_wallet/puzzles/genesis_by_puzzle_hash_with_0.clsp",
        # DIDs
        "chia/wallet/did_wallet/puzzles/did_innerpuz.clsp",
        # Rate limited wallet
        "chia/wallet/rl_wallet/puzzles/rl_aggregation.clsp",
        "chia/wallet/rl_wallet/puzzles/rl.clsp",
        # Singletons
        "chia/clvm/singletons/puzzles/singleton_launcher.clsp",
        "chia/clvm/singletons/puzzles/singleton_top_layer.clsp",
        "chia/clvm/singletons/puzzles/p2_singleton.clsp",
        "chia/clvm/singletons/puzzles/p2_singleton_or_delayed_puzhash.clsp",
        # Pools
        "chia/pools/puzzles/pool_waitingroom_innerpuz.clsp",
        "chia/pools/puzzles/pool_member_innerpuz.clsp",
        # Tests
        "tests/clvm/puzzles/sha256tree_module.clsp",
        "tests/generator/puzzles/test_generator_deserialize.clsp",
        "tests/generator/puzzles/test_multiple_generator_input_arguments.clsp",
    ]
)

clvm_include_files = set(
    [
        "chia/clvm/clibs/condition_codes.clib",
        "chia/clvm/clibs/curry_and_treehash.clib",
        "chia/clvm/clibs/singleton_truths.clib",
        "chia/clvm/clibs/sha256tree.clib",
        "chia/clvm/clibs/utility_functions.clib",
    ]
)


def list_files(dir, glob):
    dir = Path(dir)
    entries = dir.rglob(glob)
    files = [f for f in entries if f.is_file()]
    return files


def read_file(path):
    with open(path) as f:
        return f.read()


def path_with_ext(path, ext):
    return Path(str(path) + ext)


class TestClvmCompilation(TestCase):
    """
    These are tests, and not just build scripts to regenerate the bytecode, because
    the developer must be aware if the compiled output changes, for any reason.
    """

    def test_all_programs_listed(self):
        """
        Checks to see if a new chialisp file was added to chia/, but not added to `all_program_files`
        """
        CLVM_FILE_PATTERN = "*.cl[vsi][mpb]"
        existing_files = list_files("chia", CLVM_FILE_PATTERN) + list_files("tests", CLVM_FILE_PATTERN)
        existing_file_paths = set([Path(x) for x in existing_files])

        expected_files = set(clvm_include_files).union(set(all_program_files))
        expected_file_paths = set([Path(x) for x in expected_files])

        self.assertEqual(
            expected_file_paths,
            existing_file_paths,
            msg="Please add your new program to `all_program_files` or `clvm_include_files.values`",
        )

    def test_include_and_source_files_separate(self):
        self.assertEqual(clvm_include_files.intersection(all_program_files), set())

    # TODO: Test recompilation with all available compiler configurations & implementations
    def test_all_programs_are_compiled(self):
        """Checks to see if a new chialisp file was added without its .hex file"""
        all_compiled = True
        msg = "Please compile your program with:\n"

        # Note that we cannot test all existing chialisp files - some are not
        # meant to be run as a "module" with load_clvm; some are include files
        # We test for inclusion in `test_all_programs_listed`
        for prog_path in all_program_files:
            try:
                output_path = path_with_ext(prog_path, ".hex")
                hex = output_path.read_text()
                self.assertTrue(len(hex) > 0)
            except Exception as ex:
                all_compiled = False
                msg += f"    run -i {prog_path.parent} -d {prog_path} > {prog_path}.hex\n"
                print(ex)
        msg += "and check it in"
        self.assertTrue(all_compiled, msg=msg)

    def test_recompilation_matches(self):
        self.maxDiff = None
        unique_search_paths = []
        for path in clvm_include_files:
            search_dir = Path(path).parent
            if search_dir not in unique_search_paths:
                unique_search_paths.append(search_dir)
        for f in all_program_files:
            f = Path(f)
            compile_clvm(f, path_with_ext(f, ".recompiled"), search_paths=[f.parent, *unique_search_paths])
            orig_hex = path_with_ext(f, ".hex").read_text().strip()
            new_hex = path_with_ext(f, ".recompiled").read_text().strip()
            self.assertEqual(orig_hex, new_hex, msg=f"Compilation of {f} does not match {f}.hex")
        pass

    def test_all_compiled_programs_are_hashed(self):
        """Checks to see if a .hex file is missing its .sha256tree file"""
        all_hashed = True
        msg = "Please hash your program with:\n"
        for prog_path in all_program_files:
            try:
                hex = path_with_ext(prog_path, ".hex.sha256tree").read_text()
                self.assertTrue(len(hex) > 0)
            except Exception as ex:
                print(ex)
                all_hashed = False
                msg += f"    opd -H {prog_path}.hex | head -1 > {prog_path}.hex.sha256tree\n"
        msg += "and check it in"
        self.assertTrue(all_hashed, msg)

    # TODO: Test all available shatree implementations on all progams
    def test_shatrees_match(self):
        """Checks to see that all .sha256tree files match their .hex files"""
        for prog_path in all_program_files:
            # load the .hex file as a program
            hex_filename = path_with_ext(prog_path, ".hex")
            clvm_hex = hex_filename.read_text()  # .decode("utf8")
            clvm_blob = bytes.fromhex(clvm_hex)
            s = SerializedProgram.from_bytes(clvm_blob)
            p = Program.from_bytes(clvm_blob)

            # load the checked-in shatree
            existing_sha = path_with_ext(prog_path, ".hex.sha256tree").read_text().strip()

            self.assertEqual(
                s.get_tree_hash().hex(),
                existing_sha,
                msg=f"Checked-in shatree hash file does not match shatree hash of loaded SerializedProgram: {prog_path}",  # noqa
            )
            self.assertEqual(
                p.get_tree_hash().hex(),
                existing_sha,
                msg=f"Checked-in shatree hash file does not match shatree hash of loaded Program: {prog_path}",
            )
