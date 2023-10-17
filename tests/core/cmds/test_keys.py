from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

import pytest
from click.testing import CliRunner

from chia.cmds.chia import cli
from chia.cmds.keys import delete_all_cmd, generate_and_print_cmd, sign_cmd, verify_cmd
from chia.util.config import load_config
from chia.util.default_root import DEFAULT_KEYS_ROOT_PATH
from chia.util.keychain import Keychain, KeyData, generate_mnemonic
from chia.util.keyring_wrapper import KeyringWrapper

TEST_MNEMONIC_SEED = (
    "grief lock ketchup video day owner torch young work "
    "another venue evidence spread season bright private "
    "tomato remind jaguar original blur embody project can"
)
TEST_FINGERPRINT = 2877570395


@pytest.fixture(scope="function")
def keyring_with_one_key(empty_keyring):
    keychain = empty_keyring
    keychain.add_private_key(TEST_MNEMONIC_SEED)
    return keychain


@pytest.fixture(scope="function")
def mnemonic_seed_file(tmp_path):
    seed_file = Path(tmp_path) / "seed.txt"
    with open(seed_file, "w") as f:
        f.write(TEST_MNEMONIC_SEED)
    return seed_file


@pytest.fixture(scope="function")
def setup_keyringwrapper(tmp_path):
    KeyringWrapper.cleanup_shared_instance()
    KeyringWrapper.set_keys_root_path(tmp_path)
    _ = KeyringWrapper.get_shared_instance()
    yield
    KeyringWrapper.cleanup_shared_instance()
    KeyringWrapper.set_keys_root_path(DEFAULT_KEYS_ROOT_PATH)


def assert_label(keychain: Keychain, label: Optional[str], index: int) -> None:
    all_keys = keychain.get_keys()
    assert len(all_keys) > index
    assert all_keys[index].label == label


class TestKeysCommands:
    def test_generate_with_new_config(self, tmp_path, empty_keyring):
        """
        Generate a new config and a new key. Verify that the config has
        the correct xch_target_address entries.
        """

        keychain = empty_keyring
        keys_root_path = keychain.keyring_wrapper.keys_root_path

        # Generate the new config
        runner = CliRunner()
        init_result = runner.invoke(
            cli,
            ["--root-path", os.fspath(tmp_path), "--keys-root-path", os.fspath(keys_root_path), "init"],
            catch_exceptions=False,
        )

        assert init_result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 0

        # Generate a new key
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "--keys-root-path",
                os.fspath(keys_root_path),
                "keys",
                "generate",
            ],
            input="\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 1

        # Verify that the config has the correct xch_target_address entries
        address_matches = re.findall(r"xch1[^\n]+", result.output)
        assert len(address_matches) > 1
        address = address_matches[0]

        config: Dict = load_config(tmp_path, "config.yaml")
        assert config["farmer"]["xch_target_address"] == address
        assert config["pool"]["xch_target_address"] == address

    def test_generate_with_existing_config(self, tmp_path, empty_keyring):
        """
        Generate a new key using an existing config. Verify that the config has
        the original xch_target_address entries.
        """

        keychain = empty_keyring
        keys_root_path = keychain.keyring_wrapper.keys_root_path

        # Generate the new config
        runner = CliRunner()
        init_result = runner.invoke(
            cli,
            ["--root-path", os.fspath(tmp_path), "--keys-root-path", os.fspath(keys_root_path), "init"],
            catch_exceptions=False,
        )

        assert init_result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 0

        # Generate the first key
        runner = CliRunner()
        generate_result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "--keys-root-path",
                os.fspath(keys_root_path),
                "keys",
                "generate",
            ],
            input="\n",
            catch_exceptions=False,
        )

        assert generate_result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 1

        # Verify that the config has the correct xch_target_address entries
        address_matches = re.findall(r"xch1[^\n]+", generate_result.output)
        assert len(address_matches) > 1
        address = address_matches[0]

        existing_config: Dict = load_config(tmp_path, "config.yaml")
        assert existing_config["farmer"]["xch_target_address"] == address
        assert existing_config["pool"]["xch_target_address"] == address

        # Generate the second key
        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "--keys-root-path",
                os.fspath(keys_root_path),
                "keys",
                "generate",
            ],
            input="\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 2

        # Verify that the config's xch_target_address entries have not changed
        config: Dict = load_config(tmp_path, "config.yaml")
        assert config["farmer"]["xch_target_address"] == existing_config["farmer"]["xch_target_address"]
        assert config["pool"]["xch_target_address"] == existing_config["pool"]["xch_target_address"]

    @pytest.mark.parametrize(
        "cmd_params, label, input_str",
        [
            (["generate"], None, "\n"),
            (["generate", "-l", "key_0"], "key_0", None),
            (["generate", "--label", "key_0"], "key_0", None),
            (["generate", "-l", ""], None, None),
            (["generate", "--label", ""], None, None),
            (["generate"], "key_0", "key_0\n"),
            (["add"], None, f"{TEST_MNEMONIC_SEED}\n\n"),
            (["add"], "key_0", f"{TEST_MNEMONIC_SEED}\nkey_0\n"),
            (["add", "-l", "key_0"], "key_0", f"{TEST_MNEMONIC_SEED}\n"),
            (["add", "--label", "key_0"], "key_0", f"{TEST_MNEMONIC_SEED}\n"),
            (["add", "-l", ""], None, f"{TEST_MNEMONIC_SEED}\n"),
            (["add", "--label", ""], None, f"{TEST_MNEMONIC_SEED}\n"),
        ],
    )
    def test_generate_and_add_label_parameter(
        self, cmd_params: List[str], label: Optional[str], input_str: Optional[str], tmp_path, empty_keyring
    ):
        keychain = empty_keyring
        keys_root_path = keychain.keyring_wrapper.keys_root_path
        base_params = [
            "--root-path",
            os.fspath(tmp_path),
            "--keys-root-path",
            os.fspath(keys_root_path),
        ]
        runner = CliRunner()
        # Generate a new config
        assert runner.invoke(cli, [*base_params, "init"], catch_exceptions=False).exit_code == 0
        # Run the command
        result = runner.invoke(
            cli,
            [*base_params, "keys", *cmd_params],
            catch_exceptions=False,
            input=input_str,
        )
        assert result.exit_code == 0
        # And make sure the label was set to the expected label
        assert_label(keychain, label, 0)

    def test_set_label(self, keyring_with_one_key, tmp_path):
        keychain = keyring_with_one_key
        keys_root_path = keychain.keyring_wrapper.keys_root_path
        base_params = [
            "--root-path",
            os.fspath(tmp_path),
            "--keys-root-path",
            os.fspath(keys_root_path),
        ]
        cmd_params = ["keys", "label", "set", "-f", TEST_FINGERPRINT]
        runner = CliRunner()

        def set_and_validate(label: str):
            result = runner.invoke(cli, [*base_params, *cmd_params, "-l", label], catch_exceptions=False)
            assert result.exit_code == 0
            assert result.output == f"label {label!r} assigned to {TEST_FINGERPRINT!r}\n"
            assert_label(keychain, label, 0)

        # Generate a new config
        assert runner.invoke(cli, [*base_params, "init"], catch_exceptions=False).exit_code == 0
        # There should be no label for this key
        assert_label(keychain, None, 0)
        # Set a label
        set_and_validate("key_0")
        # Change the label
        set_and_validate("changed")

    def test_delete_label(self, keyring_with_one_key, tmp_path):
        keychain = keyring_with_one_key
        keys_root_path = keychain.keyring_wrapper.keys_root_path
        base_params = [
            "--root-path",
            os.fspath(tmp_path),
            "--keys-root-path",
            os.fspath(keys_root_path),
        ]
        cmd_params = ["keys", "label", "delete", "-f", TEST_FINGERPRINT]
        runner = CliRunner()
        # Generate a new config
        assert runner.invoke(cli, [*base_params, "init"], catch_exceptions=False).exit_code == 0
        # There should be no label for this key
        assert_label(keychain, None, 0)
        # Set a label
        keychain.set_label(TEST_FINGERPRINT, "key_0")
        assert_label(keychain, "key_0", 0)
        # Delete the label
        result = runner.invoke(cli, [*base_params, *cmd_params], catch_exceptions=False)
        assert result.output == f"label removed for {TEST_FINGERPRINT!r}\n"
        assert_label(keychain, None, 0)

    def test_show_labels(self, empty_keyring, tmp_path):
        keychain = empty_keyring
        runner = CliRunner()
        keys_root_path = keychain.keyring_wrapper.keys_root_path
        base_params = [
            "--root-path",
            os.fspath(tmp_path),
            "--keys-root-path",
            os.fspath(keys_root_path),
        ]
        cmd_params = ["keys", "label", "show"]
        # Generate a new config
        assert runner.invoke(cli, [*base_params, "init"], catch_exceptions=False).exit_code == 0
        # Make sure the command works with no keys
        result = runner.invoke(cli, [*base_params, *cmd_params], catch_exceptions=False)
        assert result.output == "No keys are present in the keychain. Generate them with 'chia keys generate'\n"
        # Add 10 keys to the keychain, give every other a label
        keys = [KeyData.generate(f"key_{i}" if i % 2 == 0 else None) for i in range(10)]
        for key in keys:
            keychain.add_private_key(key.mnemonic_str(), key.label)
        # Make sure all 10 keys are printed correct
        result = runner.invoke(cli, [*base_params, *cmd_params], catch_exceptions=False)
        assert result.exit_code == 0
        lines = result.output.splitlines()[2:]  # Split into lines but drop the header
        fingerprints = [int(line.split("|")[1].strip()) for line in lines]
        labels = [line.split("|")[2].strip() for line in lines]
        assert len(fingerprints) == len(labels) == len(keys)
        for fingerprint, label, key in zip(fingerprints, labels, keys):
            assert fingerprint == key.fingerprint
            if key.label is None:
                assert label == "No label assigned"
            else:
                assert label == key.label

    def test_show(self, keyring_with_one_key, tmp_path):
        """
        Test that the `chia keys show` command shows the correct key.
        """

        keychain = keyring_with_one_key

        assert len(keychain.get_all_private_keys()) == 1

        keys_root_path = keychain.keyring_wrapper.keys_root_path
        base_params = [
            "--root-path",
            os.fspath(tmp_path),
            "--keys-root-path",
            os.fspath(keys_root_path),
        ]
        runner = CliRunner()
        cmd_params = ["keys", "show"]
        # Generate a new config
        assert runner.invoke(cli, [*base_params, "init"], catch_exceptions=False).exit_code == 0
        # Run the command
        result = runner.invoke(cli, [*base_params, *cmd_params], catch_exceptions=False)

        # assert result.exit_code == 0
        assert result.output.find(f"Fingerprint: {TEST_FINGERPRINT}") != -1

    def test_show_fingerprint(self, keyring_with_one_key, tmp_path):
        """
        Test that the `chia keys show --fingerprint` command shows the correct key.
        """

        keychain = keyring_with_one_key

        # add a key
        keychain.add_private_key(generate_mnemonic())
        assert len(keychain.get_all_private_keys()) == 2

        keys_root_path = keychain.keyring_wrapper.keys_root_path
        base_params = [
            "--root-path",
            os.fspath(tmp_path),
            "--keys-root-path",
            os.fspath(keys_root_path),
        ]
        runner = CliRunner()
        cmd_params = ["keys", "show", "--fingerprint", TEST_FINGERPRINT]
        # Generate a new config
        assert runner.invoke(cli, [*base_params, "init"], catch_exceptions=False).exit_code == 0
        # Run the command
        result = runner.invoke(cli, [*base_params, *cmd_params], catch_exceptions=False)

        assert result.exit_code == 0
        fingerprints = [line for line in result.output.splitlines() if "Fingerprint:" in line]
        assert len(fingerprints) == 1
        assert str(TEST_FINGERPRINT) in fingerprints[0]

    def test_show_json(self, keyring_with_one_key, tmp_path):
        """
        Test that the `chia keys show --json` command shows the correct key.
        """

        keychain = keyring_with_one_key

        assert len(keychain.get_all_private_keys()) == 1

        keys_root_path = keychain.keyring_wrapper.keys_root_path
        base_params = [
            "--root-path",
            os.fspath(tmp_path),
            "--keys-root-path",
            os.fspath(keys_root_path),
        ]
        runner = CliRunner()
        cmd_params = ["keys", "show", "--json"]
        # Generate a new config
        assert runner.invoke(cli, [*base_params, "init"], catch_exceptions=False).exit_code == 0
        # Run the command
        result = runner.invoke(cli, [*base_params, *cmd_params], catch_exceptions=False)

        json_result = json.loads(result.output)

        # assert result.exit_code == 0
        assert json_result["keys"][0]["fingerprint"] == TEST_FINGERPRINT

    def test_show_mnemonic(self, keyring_with_one_key, tmp_path):
        """
        Test that the `chia keys show --show-mnemonic-seed` command shows the key's mnemonic seed.
        """

        keychain = keyring_with_one_key

        assert len(keychain.get_all_private_keys()) == 1

        keys_root_path = keychain.keyring_wrapper.keys_root_path
        base_params = [
            "--root-path",
            os.fspath(tmp_path),
            "--keys-root-path",
            os.fspath(keys_root_path),
        ]
        runner = CliRunner()
        cmd_params = ["keys", "show", "--show-mnemonic-seed"]
        # Generate a new config
        assert runner.invoke(cli, [*base_params, "init"], catch_exceptions=False).exit_code == 0
        # Run the command
        result = runner.invoke(cli, [*base_params, *cmd_params], catch_exceptions=False)

        # assert result.exit_code == 0
        assert result.output.find(f"Fingerprint: {TEST_FINGERPRINT}") != -1
        assert result.output.find("Mnemonic seed (24 secret words):") != -1
        assert result.output.find(TEST_MNEMONIC_SEED) != -1

    def test_show_mnemonic_json(self, keyring_with_one_key, tmp_path):
        """
        Test that the `chia keys show --show-mnemonic-seed --json` command shows the key's mnemonic seed.
        """

        keychain = keyring_with_one_key

        assert len(keychain.get_all_private_keys()) == 1

        keys_root_path = keychain.keyring_wrapper.keys_root_path
        base_params = [
            "--root-path",
            os.fspath(tmp_path),
            "--keys-root-path",
            os.fspath(keys_root_path),
        ]
        runner = CliRunner()
        cmd_params = ["keys", "show", "--show-mnemonic-seed", "--json"]
        # Generate a new config
        assert runner.invoke(cli, [*base_params, "init"], catch_exceptions=False).exit_code == 0
        # Run the command
        result = runner.invoke(cli, [*base_params, *cmd_params], catch_exceptions=False)
        json_result = json.loads(result.output)

        # assert result.exit_code == 0
        assert json_result["keys"][0]["fingerprint"] == TEST_FINGERPRINT
        assert json_result["keys"][0]["mnemonic"] == TEST_MNEMONIC_SEED

    def test_add_interactive(self, tmp_path, empty_keyring):
        """
        Test adding a key from mnemonic seed using the interactive prompt.
        """

        keychain = empty_keyring
        keys_root_path = keychain.keyring_wrapper.keys_root_path

        runner = CliRunner()
        init_result = runner.invoke(
            cli,
            ["--root-path", os.fspath(tmp_path), "--keys-root-path", os.fspath(keys_root_path), "init"],
            catch_exceptions=False,
        )

        assert init_result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 0

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "--keys-root-path",
                os.fspath(keys_root_path),
                "keys",
                "add",
            ],
            catch_exceptions=False,
            input=f"{TEST_MNEMONIC_SEED}\n\n",
        )

        assert result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 1

    def test_add_from_mnemonic_seed(self, tmp_path, empty_keyring, mnemonic_seed_file):
        """
        Test adding a key from a mnemonic seed file using the `--filename` flag.
        """

        keychain = empty_keyring
        keys_root_path = keychain.keyring_wrapper.keys_root_path

        runner = CliRunner()
        init_result = runner.invoke(
            cli,
            ["--root-path", os.fspath(tmp_path), "--keys-root-path", os.fspath(keys_root_path), "init"],
            catch_exceptions=False,
        )

        assert init_result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 0

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "--keys-root-path",
                os.fspath(keys_root_path),
                "keys",
                "add",
                "--filename",
                os.fspath(mnemonic_seed_file),
            ],
            catch_exceptions=False,
            input="\n",
        )

        assert result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 1

    def test_delete(self, tmp_path, empty_keyring, mnemonic_seed_file):
        """
        Test deleting a key using the `--fingerprint` option.
        """

        keychain = empty_keyring
        keys_root_path = keychain.keyring_wrapper.keys_root_path

        runner = CliRunner()
        init_result = runner.invoke(
            cli,
            ["--root-path", os.fspath(tmp_path), "--keys-root-path", os.fspath(keys_root_path), "init"],
            catch_exceptions=False,
        )

        assert init_result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 0

        runner = CliRunner()
        add_result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "--keys-root-path",
                os.fspath(keys_root_path),
                "keys",
                "add",
                "--filename",
                os.fspath(mnemonic_seed_file),
            ],
            catch_exceptions=False,
            input="\n",
        )

        assert add_result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 1

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "--keys-root-path",
                os.fspath(keys_root_path),
                "keys",
                "delete",
                "--fingerprint",
                TEST_FINGERPRINT,
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 0

    def test_delete_all(self, empty_keyring):
        """
        Test deleting all keys from the keyring
        """

        keychain = empty_keyring

        assert len(keychain.get_all_private_keys()) == 0

        for i in range(5):
            mnemonic: str = generate_mnemonic()
            keychain.add_private_key(mnemonic)

        assert len(keychain.get_all_private_keys()) == 5

        runner = CliRunner()
        result = runner.invoke(delete_all_cmd, [], catch_exceptions=False)

        assert result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 0

    def test_generate_and_print(self):
        """
        Test the `chia keys generate_and_print` command.
        """

        runner = CliRunner()
        result = runner.invoke(generate_and_print_cmd, [], catch_exceptions=False)

        assert result.exit_code == 0
        assert result.output.find("Mnemonic (24 secret words):") != -1

    def test_sign(self, keyring_with_one_key):
        """
        Test the `chia keys sign` command.
        """

        message: str = "hello world"
        hd_path: str = "m/12381/8444/0/1"
        runner = CliRunner()
        result = runner.invoke(
            sign_cmd,
            ["--message", message, "--fingerprint", str(TEST_FINGERPRINT), "--hd_path", hd_path],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert (
            result.output.find(
                (
                    "Public Key: 92f15caed8a5495faa7ec25a8af3f223438ef73c974b0aa81e788057b1154870f149739b2c2d0e"
                    "736234baf9386f7f83"
                )
            )
            != -1
        )
        assert (
            result.output.find(
                (
                    "Signature: a82e7d1b87d8c25a6ccac603194011d73f71fc76c17c1ce4ee53484f81874f116b1cb9dd991bcf9"
                    "aa41c10beaab54a830fc6f7e5e25a9144f73e38a6fb852a87e36d80f575a6f84359144e6e9499ba9208912de55"
                    "a1f7514cd8cfa166ae48e64"
                )
            )
            != -1
        )

    def test_sign_non_observer(self, keyring_with_one_key):
        """
        Test the `chia keys sign` command with a non-observer key.
        """

        message: str = "hello world"
        hd_path: str = "m/12381n/8444n/0n/1n"
        runner = CliRunner()
        result = runner.invoke(
            sign_cmd,
            ["--message", message, "--fingerprint", str(TEST_FINGERPRINT), "--hd_path", hd_path],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert (
            result.output.find(
                (
                    "Public Key: b5e383b8192dacff662455bdb3bbfc433f678f0d7ff7f118149e0d2ad39aa6d59ac4cb3662acf8"
                    "e8307e66069d3a13cc"
                )
            )
        ) != -1
        assert (
            result.output.find(
                (
                    "Signature: b5b3bc1417f67498748018a7ad2c95acfc5ae2dcd0d9dd0f3abfc7e3f047f2e6cf6c3e775b6caff"
                    "a3e0baaadc2fe705a100cd4c961d6ff3c575c5c33683eb7b1e2dbbcaf37318227ae40ef8ccf57879a7818fad8f"
                    "dc573d55c908be2611b8077"
                )
            )
        ) != -1

    def test_sign_mnemonic_seed_file(self, empty_keyring, mnemonic_seed_file):
        """
        Test signing a message using a key imported from a mnemonic seed file.
        """

        message: str = "hello world"
        hd_path: str = "m/12381/8444/0/1"
        runner = CliRunner()
        result = runner.invoke(
            sign_cmd,
            [
                "--message",
                message,
                "--hd_path",
                hd_path,
                "--mnemonic-seed-filename",
                mnemonic_seed_file,
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert (
            result.output.find(
                (
                    "Public Key: "
                    "92f15caed8a5495faa7ec25a8af3f223438ef73c974b0aa81e788057b1154870f149739b2c2d0e736234baf9386f7f83"
                )
            )
            != -1
        )
        assert (
            result.output.find(
                (
                    "Signature: a82e7d1b87d8c25a6ccac603194011d73f71fc76c17c1ce4ee53484f81874f116b1cb9dd991bcf"
                    "9aa41c10beaab54a830fc6f7e5e25a9144f73e38a6fb852a87e36d80f575a6f84359144e6e9499ba9208912de"
                    "55a1f7514cd8cfa166ae48e64"
                )
            )
            != -1
        )

    def test_verify(self):
        """
        Test the `chia keys verify` command.
        """

        message: str = "hello world"
        signature: str = (
            "a82e7d1b87d8c25a6ccac603194011d73f71fc76c17c1ce4ee53484f81874f116b1cb9dd991bcf9aa41c10beaab54a83"
            "0fc6f7e5e25a9144f73e38a6fb852a87e36d80f575a6f84359144e6e9499ba9208912de55a1f7514cd8cfa166ae48e64"
        )
        public_key: str = (
            "92f15caed8a5495faa7ec25a8af3f223438ef73c974b0aa81e788057b1154870f149739b2c2d0e736234baf9386f7f83"
        )
        runner = CliRunner()
        result = runner.invoke(
            verify_cmd,
            ["--message", message, "--public_key", public_key, "--signature", signature],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert result.output.find("True") == 0

    def test_derive_search(self, tmp_path, keyring_with_one_key):
        """
        Test the `chia keys derive search` command, searching a public and private key
        """

        keychain = keyring_with_one_key
        keys_root_path = keychain.keyring_wrapper.keys_root_path

        runner = CliRunner()
        init_result = runner.invoke(
            cli,
            ["--root-path", os.fspath(tmp_path), "--keys-root-path", os.fspath(keys_root_path), "init"],
            catch_exceptions=False,
        )

        assert init_result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 1

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "--keys-root-path",
                os.fspath(keys_root_path),
                "keys",
                "derive",
                "--fingerprint",
                str(TEST_FINGERPRINT),
                "search",
                "--limit",
                "10",
                "--search-type",
                "all",
                "a4601f992f24047097a30854ef656382911575694439108723698972941e402d737c13df76fdf43597f7b3c2fa9ed27a",
                "028e33fa3f8caa3102c028f3bff6b6680e528d9a0c543c479ef0b0339060ef36",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert (
            result.output.find(
                (
                    "Found public key: a4601f992f24047097a30854ef656382911575694439108723698"
                    "972941e402d737c13df76fdf43597f7b3c2fa9ed27a (HD path: m/12381/8444/2/9)"
                )
            )
            != -1
        )
        assert (
            result.output.find(
                (
                    "Found private key: "
                    "028e33fa3f8caa3102c028f3bff6b6680e528d9a0c543c479ef0b0339060ef36 (HD path: m/12381/8444/2/9)"
                )
            )
            != -1
        )

    def test_derive_search_wallet_address(self, tmp_path, keyring_with_one_key):
        """
        Test the `chia keys derive search` command, searching for a wallet address
        """

        keychain = keyring_with_one_key
        keys_root_path = keychain.keyring_wrapper.keys_root_path

        runner = CliRunner()
        init_result = runner.invoke(
            cli,
            ["--root-path", os.fspath(tmp_path), "--keys-root-path", os.fspath(keys_root_path), "init"],
            catch_exceptions=False,
        )

        assert init_result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 1

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "--keys-root-path",
                os.fspath(keys_root_path),
                "keys",
                "derive",
                "--fingerprint",
                str(TEST_FINGERPRINT),
                "search",
                "--limit",
                "40",
                "--search-type",
                "address",
                "xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8taffd",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert (
            result.output.find(
                (
                    "Found wallet address: "
                    "xch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs8taffd (HD path: m/12381/8444/2/30)"
                )
            )
            != -1
        )

    def test_derive_search_wallet_testnet_address(self, tmp_path, keyring_with_one_key):
        """
        Test the `chia keys derive search` command, searching for a testnet wallet address
        """

        keychain = keyring_with_one_key
        keys_root_path = keychain.keyring_wrapper.keys_root_path

        runner = CliRunner()
        init_result = runner.invoke(
            cli,
            ["--root-path", os.fspath(tmp_path), "--keys-root-path", os.fspath(keys_root_path), "init"],
            catch_exceptions=False,
        )

        assert init_result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 1

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "--keys-root-path",
                os.fspath(keys_root_path),
                "keys",
                "derive",
                "--fingerprint",
                str(TEST_FINGERPRINT),
                "search",
                "--limit",
                "40",
                "--search-type",
                "address",
                "txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7",
                "--prefix",
                "txch",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert (
            result.output.find(
                (
                    "Found wallet address: "
                    "txch1mnr0ygu7lvmk3nfgzmncfk39fwu0dv933yrcv97nd6pmrt7fzmhs2v6lg7 (HD path: m/12381/8444/2/30)"
                )
            )
            != -1
        )

    def test_derive_search_failure(self, tmp_path, keyring_with_one_key):
        """
        Test the `chia keys derive search` command with a failing search.
        """

        keychain = keyring_with_one_key
        keys_root_path = keychain.keyring_wrapper.keys_root_path

        runner = CliRunner()
        init_result = runner.invoke(
            cli,
            ["--root-path", os.fspath(tmp_path), "--keys-root-path", os.fspath(keys_root_path), "init"],
            catch_exceptions=False,
        )

        assert init_result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 1

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "--keys-root-path",
                os.fspath(keys_root_path),
                "keys",
                "derive",
                "--fingerprint",
                str(TEST_FINGERPRINT),
                "search",
                "--limit",
                "10",
                "--search-type",
                "all",
                "something_that_doesnt_exist",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code != 0

    def test_derive_search_hd_path(self, tmp_path, empty_keyring, mnemonic_seed_file):
        """
        Test the `chia keys derive search` command, searching under a provided HD path.
        """

        keychain = empty_keyring
        keys_root_path = keychain.keyring_wrapper.keys_root_path

        runner = CliRunner()
        init_result = runner.invoke(
            cli,
            ["--root-path", os.fspath(tmp_path), "--keys-root-path", os.fspath(keys_root_path), "init"],
            catch_exceptions=False,
        )

        assert init_result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 0

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "--keys-root-path",
                os.fspath(keys_root_path),
                "keys",
                "derive",
                "--mnemonic-seed-filename",
                os.fspath(mnemonic_seed_file),
                "search",
                "--limit",
                "50",
                "--search-type",
                "all",
                "--derive-from-hd-path",
                "m/12381n/8444n/2/",
                "80dc3a2ea450eb09e24debe22e1b5934911ba530792ef0be361badebb168780bd328ff8d4655e5dd573d5bef4a340344",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert (
            result.output.find(
                (
                    "Found public key: 80dc3a2ea450eb09e24debe22e1b5934911ba530792ef0be361bad"
                    "ebb168780bd328ff8d4655e5dd573d5bef4a340344 (HD path: m/12381n/8444n/2/35)"
                )
            )
            != -1
        )

    def test_derive_wallet_address(self, tmp_path, keyring_with_one_key):
        """
        Test the `chia keys derive wallet-address` command, generating a couple of wallet addresses.
        """

        keychain = keyring_with_one_key
        keys_root_path = keychain.keyring_wrapper.keys_root_path

        runner = CliRunner()
        init_result = runner.invoke(
            cli,
            ["--root-path", os.fspath(tmp_path), "--keys-root-path", os.fspath(keys_root_path), "init"],
            catch_exceptions=False,
        )

        assert init_result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 1

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "--keys-root-path",
                os.fspath(keys_root_path),
                "keys",
                "derive",
                "--fingerprint",
                str(TEST_FINGERPRINT),
                "wallet-address",
                "--index",
                "50",
                "--count",
                "2",
                "--non-observer-derivation",
                "--show-hd-path",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert (
            result.output.find(
                (
                    "Wallet address 50 (m/12381n/8444n/2n/50n): "
                    "xch1jp2u7an0mn9hdlw2x05nmje49gwgzmqyvh0qmh6008yksetuvkfs6wrfdq"
                )
            )
            != -1
        )
        assert (
            result.output.find(
                (
                    "Wallet address 51 (m/12381n/8444n/2n/51n): "
                    "xch1006n6l3x5e8exar8mlj004znjl5pq0tq73h76kz0yergswnjzn8sumvfmt"
                )
            )
            != -1
        )

    def test_derive_wallet_testnet_address(self, tmp_path, keyring_with_one_key):
        """
        Test the `chia keys derive wallet-address` command, generating a couple of testnet wallet addresses.
        """

        keychain = keyring_with_one_key
        keys_root_path = keychain.keyring_wrapper.keys_root_path

        runner = CliRunner()
        init_result = runner.invoke(
            cli,
            ["--root-path", os.fspath(tmp_path), "--keys-root-path", os.fspath(keys_root_path), "init"],
            catch_exceptions=False,
        )

        assert init_result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 1

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "--keys-root-path",
                os.fspath(keys_root_path),
                "keys",
                "derive",
                "--fingerprint",
                str(TEST_FINGERPRINT),
                "wallet-address",
                "--index",
                "50",
                "--count",
                "2",
                "--non-observer-derivation",
                "--show-hd-path",
                "--prefix",
                "txch",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert (
            result.output.find(
                (
                    "Wallet address 50 (m/12381n/8444n/2n/50n): "
                    "txch1jp2u7an0mn9hdlw2x05nmje49gwgzmqyvh0qmh6008yksetuvkfshfylvn"
                )
            )
            != -1
        )
        assert (
            result.output.find(
                (
                    "Wallet address 51 (m/12381n/8444n/2n/51n): "
                    "txch1006n6l3x5e8exar8mlj004znjl5pq0tq73h76kz0yergswnjzn8s3utl6c"
                )
            )
            != -1
        )

    def test_derive_child_keys(self, tmp_path, keyring_with_one_key):
        """
        Test the `chia keys derive child-keys` command, generating a couple of derived keys.
        """

        keychain = keyring_with_one_key
        keys_root_path = keychain.keyring_wrapper.keys_root_path

        runner = CliRunner()
        init_result = runner.invoke(
            cli,
            ["--root-path", os.fspath(tmp_path), "--keys-root-path", os.fspath(keys_root_path), "init"],
            catch_exceptions=False,
        )

        assert init_result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 1

        runner = CliRunner()
        result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "--keys-root-path",
                os.fspath(keys_root_path),
                "keys",
                "derive",
                "--fingerprint",
                str(TEST_FINGERPRINT),
                "child-key",
                "--derive-from-hd-path",
                "m/12381n/8444n/2/3/4/",
                "--index",
                "30",
                "--count",
                "2",
                "--show-private-keys",
                "--show-hd-path",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0
        assert (
            result.output.find(
                (
                    "Observer public key 30 (m/12381n/8444n/2/3/4/30): "
                    "979a1fa0bfc140488d4a9edcfbf244a398fe922618a981cc0fffe5445d811f2237ff8234c0520b28b3096c8269f2731e"
                )
            )
            != -1
        )
        assert (
            result.output.find(
                (
                    "Observer private key 30 (m/12381n/8444n/2/3/4/30): "
                    "5dd22db24fe28805b101104c543f5bec3808328ad67de3d3dcd9efd6faab13aa"
                )
            )
            != -1
        )
        assert (
            result.output.find(
                (
                    "Observer public key 31 (m/12381n/8444n/2/3/4/31): "
                    "ab5885df340a27b5eb3f1c4b8c32889f529ad5ecc4c9718247e36756de2e143c604af9956941a72239124e6fb352782e"
                )
            )
            != -1
        )
        assert (
            result.output.find(
                (
                    "Observer private key 31 (m/12381n/8444n/2/3/4/31): "
                    "113610b39c2151fd68d7f795d5dd596b94889a3cf7825a56da5c6d2c7e5141a1"
                )
            )
            != -1
        )
