import os
import pkg_resources
import pytest
import re

from blspy import PrivateKey
from chia.cmds.chia import cli
from chia.cmds.keys import delete_all_cmd, generate_and_print_cmd, show_cmd, sign_cmd, verify_cmd
from chia.util.config import load_config
from chia.util.file_keyring import FileKeyring
from chia.util.keychain import DEFAULT_USER, DEFAULT_SERVICE, Keychain, generate_mnemonic
from chia.util.keyring_wrapper import DEFAULT_KEYS_ROOT_PATH, KeyringWrapper, LegacyKeyring
from click.testing import CliRunner, Result
from keyring.backend import KeyringBackend
from pathlib import Path
from tests.util.keyring import TempKeyring
from typing import Dict, List, Optional, Tuple


TEST_MNEMONIC_SEED = (
    "grief lock ketchup video day owner torch young work "
    "another venue evidence spread season bright private "
    "tomato remind jaguar original blur embody project can"
)
TEST_FINGERPRINT = 2877570395


class DummyLegacyKeyring(KeyringBackend):

    # Fingerprint 2474840988
    KEY_0 = (
        "89e29e5f9c3105b2a853475cab2392468cbfb1d65c3faabea8ebc78fe903fd279e56a8d93f6325fc6c3d833a2ae74832"
        "b8feaa3d6ee49998f43ce303b66dcc5abb633e5c1d80efe85c40766135e4a44c"
    )

    # Fingerprint 4149609062
    KEY_1 = (
        "8b0d72288727af6238fcd9b0a663cd7d4728738fca597d0046cbb42b6432e0a5ae8026683fc5f9c73df26fb3e1cec2c8"
        "ad1b4f601107d96a99f6fa9b9d2382918fb1e107fb6655c7bdd8c77c1d9c201f"
    )

    # Fingerprint 3618811800
    KEY_2 = (
        "8b2a26ba319f83bd3da5b1b147a817ecc4ca557f037c9db1cfedc59b16ee6880971b7d292f023358710a292c8db0eb82"
        "35808f914754ae24e493fad9bc7f654b0f523fb406973af5235256a39bed1283"
    )

    def __init__(self, populate: bool = True):
        self.service_dict = {}

        if populate:
            self.service_dict[DEFAULT_SERVICE] = {
                f"wallet-{DEFAULT_USER}-0": DummyLegacyKeyring.KEY_0,
                f"wallet-{DEFAULT_USER}-1": DummyLegacyKeyring.KEY_1,
                f"wallet-{DEFAULT_USER}-2": DummyLegacyKeyring.KEY_2,
            }

    def get_password(self, service, username, password=None):
        return self.service_dict.get(service, {}).get(username)

    def set_password(self, service, username, password):
        self.service_dict.setdefault(service, {})[username] = password

    def delete_password(self, service, username):
        del self.service_dict[service][username]


class TestKeysCommands:
    @pytest.fixture(scope="function")
    def empty_keyring(self):
        with TempKeyring(user="user-chia-1.8", service="chia-user-chia-1.8") as keychain:
            yield keychain
            KeyringWrapper.cleanup_shared_instance()

    @pytest.fixture(scope="function")
    def keyring_with_one_key(self, empty_keyring):
        keychain = empty_keyring
        keychain.add_private_key(TEST_MNEMONIC_SEED, "")
        return keychain

    @pytest.fixture(scope="function")
    def mnemonic_seed_file(self, tmp_path):
        seed_file = Path(tmp_path) / "seed.txt"
        with open(seed_file, "w") as f:
            f.write(TEST_MNEMONIC_SEED)
        return seed_file

    @pytest.fixture(scope="function")
    def setup_keyringwrapper(self, tmp_path):
        KeyringWrapper.cleanup_shared_instance()
        KeyringWrapper.set_keys_root_path(tmp_path)
        _ = KeyringWrapper.get_shared_instance()
        yield
        KeyringWrapper.cleanup_shared_instance()
        KeyringWrapper.set_keys_root_path(DEFAULT_KEYS_ROOT_PATH)

    @pytest.fixture(scope="function")
    def setup_legacy_keyringwrapper(self, tmp_path, monkeypatch):
        def mock_setup_keyring_file_watcher(_):
            pass

        # Silence errors in the watchdog module during testing
        monkeypatch.setattr(FileKeyring, "setup_keyring_file_watcher", mock_setup_keyring_file_watcher)

        KeyringWrapper.cleanup_shared_instance()
        KeyringWrapper.set_keys_root_path(tmp_path)
        KeyringWrapper.get_shared_instance().legacy_keyring = DummyLegacyKeyring()
        yield
        KeyringWrapper.cleanup_shared_instance()
        KeyringWrapper.set_keys_root_path(DEFAULT_KEYS_ROOT_PATH)

    def test_generate_with_new_config(self, tmp_path, empty_keyring):
        """
        Generate a new config and a new key. Verify that the config has
        the correct xch_target_address entries.
        """

        # Generate the new config
        runner = CliRunner()
        init_result: Result = runner.invoke(cli, ["--root-path", os.fspath(tmp_path), "init"])

        assert init_result.exit_code == 0

        keychain = empty_keyring

        assert len(keychain.get_all_private_keys()) == 0

        # Generate a new key
        runner = CliRunner()
        result: Result = runner.invoke(cli, ["--root-path", os.fspath(tmp_path), "keys", "generate"])

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

        # Generate the new config
        runner = CliRunner()
        init_result: Result = runner.invoke(cli, ["--root-path", os.fspath(tmp_path), "init"])

        assert init_result.exit_code == 0

        keychain = empty_keyring

        assert len(keychain.get_all_private_keys()) == 0

        # Generate the first key
        runner = CliRunner()
        generate_result: Result = runner.invoke(cli, ["--root-path", os.fspath(tmp_path), "keys", "generate"])

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
        result: Result = runner.invoke(cli, ["--root-path", os.fspath(tmp_path), "keys", "generate"])

        assert result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 2

        # Verify that the config's xch_target_address entries have not changed
        config: Dict = load_config(tmp_path, "config.yaml")
        assert config["farmer"]["xch_target_address"] == existing_config["farmer"]["xch_target_address"]
        assert config["pool"]["xch_target_address"] == existing_config["pool"]["xch_target_address"]

    def test_show(self, keyring_with_one_key):
        """
        Test that the `chia keys show` command shows the correct key.
        """

        keychain = keyring_with_one_key

        assert len(keychain.get_all_private_keys()) == 1

        runner = CliRunner()
        result: Result = runner.invoke(show_cmd, [])

        # assert result.exit_code == 0
        assert result.output.find(f"Fingerprint: {TEST_FINGERPRINT}") != 0

    def test_show_mnemonic(self, keyring_with_one_key):
        """
        Test that the `chia keys show --show-mnemonic-seed` command shows the key's mnemonic seed.
        """

        keychain = keyring_with_one_key

        assert len(keychain.get_all_private_keys()) == 1

        runner = CliRunner()
        result: Result = runner.invoke(show_cmd, ["--show-mnemonic-seed"])

        # assert result.exit_code == 0
        assert result.output.find(f"Fingerprint: {TEST_FINGERPRINT}") != 0
        assert result.output.find("Mnemonic: seed (24 secret words):") != 0
        assert result.output.find(TEST_MNEMONIC_SEED) != 0

    def test_add_interactive(self, tmp_path, empty_keyring):
        """
        Test adding a key from mnemonic seed using the interactive prompt.
        """

        runner = CliRunner()
        init_result: Result = runner.invoke(cli, ["--root-path", os.fspath(tmp_path), "init"])

        assert init_result.exit_code == 0

        keychain = empty_keyring

        assert len(keychain.get_all_private_keys()) == 0

        runner = CliRunner()
        result: Result = runner.invoke(
            cli, ["--root-path", os.fspath(tmp_path), "keys", "add"], input=f"{TEST_MNEMONIC_SEED}\n"
        )

        assert result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 1

    def test_add_from_mnemonic_seed(self, tmp_path, empty_keyring, mnemonic_seed_file):
        """
        Test adding a key from a mnemonic seed file using the `--filename` flag.
        """

        runner = CliRunner()
        init_result: Result = runner.invoke(cli, ["--root-path", os.fspath(tmp_path), "init"])

        assert init_result.exit_code == 0

        keychain = empty_keyring

        assert len(keychain.get_all_private_keys()) == 0

        runner = CliRunner()
        result: Result = runner.invoke(
            cli, ["--root-path", os.fspath(tmp_path), "keys", "add", "--filename", os.fspath(mnemonic_seed_file)]
        )

        assert result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 1

    def test_delete(self, tmp_path, empty_keyring, mnemonic_seed_file):
        """
        Test deleting a key using the `--fingerprint` option.
        """

        runner = CliRunner()
        init_result: Result = runner.invoke(cli, ["--root-path", os.fspath(tmp_path), "init"])

        assert init_result.exit_code == 0

        keychain = empty_keyring

        assert len(keychain.get_all_private_keys()) == 0

        runner = CliRunner()
        add_result: Result = runner.invoke(
            cli, ["--root-path", os.fspath(tmp_path), "keys", "add", "--filename", os.fspath(mnemonic_seed_file)]
        )

        assert add_result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 1

        runner = CliRunner()
        result: Result = runner.invoke(
            cli, ["--root-path", os.fspath(tmp_path), "keys", "delete", "--fingerprint", TEST_FINGERPRINT]
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
            keychain.add_private_key(mnemonic, "")

        assert len(keychain.get_all_private_keys()) == 5

        runner = CliRunner()
        result: Result = runner.invoke(delete_all_cmd, [])

        assert result.exit_code == 0
        assert len(keychain.get_all_private_keys()) == 0

    def test_generate_and_print(self):
        """
        Test the `chia keys generate_and_print` command.
        """

        runner = CliRunner()
        result: Result = runner.invoke(generate_and_print_cmd, [])

        assert result.exit_code == 0
        assert result.output.find("Mnemonic (24 secret words):") != 0

    def test_sign(self, keyring_with_one_key):
        """
        Test the `chia keys sign` command.
        """

        message: str = "hello world"
        hd_path: str = "m/12381/8444/0/1"
        runner = CliRunner()
        result: Result = runner.invoke(
            sign_cmd, ["--message", message, "--fingerprint", str(TEST_FINGERPRINT), "--hd_path", hd_path]
        )

        assert result.exit_code == 0
        assert (
            result.output.find(
                (
                    "Public key: 92f15caed8a5495faa7ec25a8af3f223438ef73c974b0aa81e788057b1154870f149739b2c2d0e"
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
        result: Result = runner.invoke(
            sign_cmd, ["--message", message, "--fingerprint", str(TEST_FINGERPRINT), "--hd_path", hd_path]
        )

        assert result.exit_code == 0
        assert (
            result.output.find(
                (
                    "Public key: b5e383b8192dacff662455bdb3bbfc433f678f0d7ff7f118149e0d2ad39aa6d59ac4cb3662acf8"
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
        result: Result = runner.invoke(
            sign_cmd,
            [
                "--message",
                message,
                "--hd_path",
                hd_path,
                "--mnemonic-seed-filename",
                mnemonic_seed_file,
            ],
        )

        assert result.exit_code == 0
        assert (
            result.output.find(
                (
                    "Public key: "
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
        result: Result = runner.invoke(
            verify_cmd, ["--message", message, "--public_key", public_key, "--signature", signature]
        )

        assert result.exit_code == 0
        assert result.output.find("True") == 0

    def test_derive_search(self, tmp_path, keyring_with_one_key):
        """
        Test the `chia keys derive search` command, searching a public and private key
        """

        runner = CliRunner()
        init_result: Result = runner.invoke(cli, ["--root-path", os.fspath(tmp_path), "init"])

        assert init_result.exit_code == 0

        keychain = keyring_with_one_key
        assert len(keychain.get_all_private_keys()) == 1

        runner = CliRunner()
        result: Result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
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

        runner = CliRunner()
        init_result: Result = runner.invoke(cli, ["--root-path", os.fspath(tmp_path), "init"])

        assert init_result.exit_code == 0

        keychain = keyring_with_one_key
        assert len(keychain.get_all_private_keys()) == 1

        runner = CliRunner()
        result: Result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
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

    def test_derive_search_failure(self, tmp_path, keyring_with_one_key):
        """
        Test the `chia keys derive search` command with a failing search.
        """

        runner = CliRunner()
        init_result: Result = runner.invoke(cli, ["--root-path", os.fspath(tmp_path), "init"])

        assert init_result.exit_code == 0

        keychain = keyring_with_one_key
        assert len(keychain.get_all_private_keys()) == 1

        runner = CliRunner()
        result: Result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
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
        )

        assert result.exit_code != 0

    def test_derive_search_hd_path(self, tmp_path, empty_keyring, mnemonic_seed_file):
        """
        Test the `chia keys derive search` command, searching under a provided HD path.
        """

        runner = CliRunner()
        init_result: Result = runner.invoke(cli, ["--root-path", os.fspath(tmp_path), "init"])

        assert init_result.exit_code == 0

        keychain = empty_keyring
        assert len(keychain.get_all_private_keys()) == 0

        runner = CliRunner()
        result: Result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
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

        runner = CliRunner()
        init_result: Result = runner.invoke(cli, ["--root-path", os.fspath(tmp_path), "init"])

        assert init_result.exit_code == 0

        keychain = keyring_with_one_key
        assert len(keychain.get_all_private_keys()) == 1

        runner = CliRunner()
        result: Result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
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

    def test_derive_child_keys(self, tmp_path, keyring_with_one_key):
        """
        Test the `chia keys derive child-keys` command, generating a couple of derived keys.
        """

        runner = CliRunner()
        init_result: Result = runner.invoke(cli, ["--root-path", os.fspath(tmp_path), "init"])

        assert init_result.exit_code == 0

        keychain = keyring_with_one_key
        assert len(keychain.get_all_private_keys()) == 1

        runner = CliRunner()
        result: Result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
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

    def test_migration_not_needed(self, tmp_path, setup_keyringwrapper, monkeypatch):
        """
        Test the `chia keys migrate` command when no migration is necessary
        """

        def mock_keychain_needs_migration() -> bool:
            return False

        monkeypatch.setattr(Keychain, "needs_migration", mock_keychain_needs_migration)

        def mock_keychain_get_keys_needing_migration() -> Tuple[List[Tuple[PrivateKey, bytes]], Optional[Keychain]]:
            return [], None

        monkeypatch.setattr(Keychain, "get_keys_needing_migration", mock_keychain_get_keys_needing_migration)

        runner = CliRunner()
        result: Result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "keys",
                "migrate",
            ],
        )

        assert result.exit_code == 0
        assert result.output.find("No keys need migration") != -1

    def test_migration_full(self, tmp_path, setup_legacy_keyringwrapper):
        """
        Test the `chia keys migrate` command when a full migration is needed
        """

        legacy_keyring = KeyringWrapper.get_shared_instance().legacy_keyring

        assert legacy_keyring is not None
        assert len(legacy_keyring.service_dict[DEFAULT_SERVICE]) == 3

        runner = CliRunner()
        init_result: Result = runner.invoke(
            cli,
            ["--root-path", os.fspath(tmp_path), "init"],
        )

        assert init_result.exit_code == 0

        runner = CliRunner()
        result: Result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "keys",
                "migrate",
            ],
            input="n\ny\ny\n",  # Prompts: 'n' = don't set a passphrase, 'y' = begin migration, 'y' = remove legacy keys
        )

        assert result.exit_code == 0
        assert KeyringWrapper.get_shared_instance().using_legacy_keyring() is False  # legacy keyring unset
        assert type(KeyringWrapper.get_shared_instance().keyring) is FileKeyring  # new keyring set
        assert len(Keychain().get_all_public_keys()) == 3  # new keyring has 3 keys
        assert len(legacy_keyring.service_dict[DEFAULT_SERVICE]) == 0  # legacy keys removed

        current_version_str = pkg_resources.get_distribution("chia-blockchain").version
        last_migration_version_str = (
            KeyringWrapper.get_shared_instance().keys_root_path / ".last_legacy_migration"
        ).read_text()
        assert last_migration_version_str == current_version_str  # last migration version set

    def test_migration_incremental(self, tmp_path, keyring_with_one_key, monkeypatch):
        KeyringWrapper.set_keys_root_path(tmp_path)
        KeyringWrapper.cleanup_shared_instance()

        keychain = keyring_with_one_key
        legacy_keyring = DummyLegacyKeyring()

        def mock_get_legacy_keyring_instance() -> Optional[LegacyKeyring]:
            nonlocal legacy_keyring
            return legacy_keyring

        from chia.util import keyring_wrapper

        monkeypatch.setattr(keyring_wrapper, "get_legacy_keyring_instance", mock_get_legacy_keyring_instance)

        assert len(keychain.get_all_private_keys()) == 1
        assert keychain.keyring_wrapper.legacy_keyring is None
        assert legacy_keyring is not None
        assert len(legacy_keyring.service_dict[DEFAULT_SERVICE]) == 3

        runner = CliRunner()
        init_result: Result = runner.invoke(
            cli,
            ["--root-path", os.fspath(tmp_path), "init"],
        )

        assert init_result.exit_code == 0

        runner = CliRunner()
        result: Result = runner.invoke(
            cli,
            [
                "--root-path",
                os.fspath(tmp_path),
                "keys",
                "migrate",
            ],
            input="y\ny\n",  # Prompts: 'y' = migrate keys, 'y' = remove legacy keys
        )

        assert result.exit_code == 0
        assert KeyringWrapper.get_shared_instance().using_legacy_keyring() is False  # legacy keyring is not set
        assert type(KeyringWrapper.get_shared_instance().keyring) is FileKeyring  # new keyring set
        assert len(Keychain().get_all_public_keys()) == 4  # new keyring has 4 keys
        assert len(legacy_keyring.service_dict[DEFAULT_SERVICE]) == 0  # legacy keys removed

        current_version_str = pkg_resources.get_distribution("chia-blockchain").version
        last_migration_version_str = (
            KeyringWrapper.get_shared_instance().keys_root_path / ".last_legacy_migration"
        ).read_text()
        assert last_migration_version_str == current_version_str  # last migration version set

    def test_migration_silent(self, tmp_path, keyring_with_one_key, monkeypatch):
        KeyringWrapper.set_keys_root_path(tmp_path)
        KeyringWrapper.cleanup_shared_instance()

        keychain = keyring_with_one_key
        legacy_keyring = DummyLegacyKeyring()

        def mock_get_legacy_keyring_instance() -> Optional[LegacyKeyring]:
            nonlocal legacy_keyring
            return legacy_keyring

        from chia.util import keyring_wrapper

        monkeypatch.setattr(keyring_wrapper, "get_legacy_keyring_instance", mock_get_legacy_keyring_instance)

        assert len(keychain.get_all_private_keys()) == 1
        assert len(Keychain().get_all_private_keys()) == 1
        assert keychain.keyring_wrapper.legacy_keyring is None
        assert legacy_keyring is not None
        assert len(legacy_keyring.service_dict[DEFAULT_SERVICE]) == 3

        keys_needing_migration, legacy_migration_keychain = Keychain.get_keys_needing_migration()
        assert len(keys_needing_migration) == 3
        assert legacy_migration_keychain is not None

        Keychain.migrate_legacy_keys_silently()

        assert type(KeyringWrapper.get_shared_instance().keyring) is FileKeyring  # new keyring set
        assert len(Keychain().get_all_public_keys()) == 4  # new keyring has 4 keys
        assert len(legacy_keyring.service_dict[DEFAULT_SERVICE]) == 3  # legacy keys still intact

    def test_migration_silent_keys_already_present(self, tmp_path, keyring_with_one_key, monkeypatch):
        KeyringWrapper.set_keys_root_path(tmp_path)
        KeyringWrapper.cleanup_shared_instance()

        keychain = keyring_with_one_key
        pkent_str = keychain.keyring_wrapper.get_passphrase(DEFAULT_SERVICE, f"wallet-{DEFAULT_USER}-0")
        legacy_keyring = DummyLegacyKeyring(populate=False)
        legacy_keyring.set_password(DEFAULT_SERVICE, f"wallet-{DEFAULT_USER}-0", pkent_str)

        def mock_get_legacy_keyring_instance() -> Optional[LegacyKeyring]:
            nonlocal legacy_keyring
            return legacy_keyring

        from chia.util import keyring_wrapper

        monkeypatch.setattr(keyring_wrapper, "get_legacy_keyring_instance", mock_get_legacy_keyring_instance)

        assert len(keychain.get_all_private_keys()) == 1
        assert len(legacy_keyring.service_dict[DEFAULT_SERVICE]) == 1

        keys_needing_migration, legacy_migration_keychain = Keychain.get_keys_needing_migration()
        assert len(keys_needing_migration) == 0
        assert legacy_migration_keychain is not None

        Keychain.migrate_legacy_keys_silently()

        assert type(KeyringWrapper.get_shared_instance().keyring) is FileKeyring  # new keyring set
        assert len(Keychain().get_all_public_keys()) == 1  # keyring has 1 key
        assert len(legacy_keyring.service_dict[DEFAULT_SERVICE]) == 1  # legacy keys still intact

    def test_migration_checked(self, tmp_path, monkeypatch):
        KeyringWrapper.set_keys_root_path(tmp_path)
        KeyringWrapper.cleanup_shared_instance()

        assert Keychain.migration_checked_for_current_version() is False

        dist_version = ""

        class DummyDistribution:
            def __init__(self, version):
                self.version = version

        def mock_get_distribution_version(_) -> DummyDistribution:
            nonlocal dist_version
            return DummyDistribution(dist_version)

        monkeypatch.setattr(pkg_resources, "get_distribution", mock_get_distribution_version)

        dist_version = "1.2.11.dev123"
        assert pkg_resources.get_distribution("chia-blockchain").version == "1.2.11.dev123"

        Keychain.mark_migration_checked_for_current_version()

        last_migration_version_str = (
            KeyringWrapper.get_shared_instance().keys_root_path / ".last_legacy_migration"
        ).read_text()
        assert last_migration_version_str == "1.2.11.dev123"  # last migration version set

        assert Keychain.migration_checked_for_current_version() is True

        dist_version = "1.2.11.dev345"
        assert Keychain.migration_checked_for_current_version() is True  # We don't check the build number
        dist_version = "1.2.10.dev111"
        assert Keychain.migration_checked_for_current_version() is True  # Checked version > current version
        dist_version = "1.3.0.dev100"
        assert Keychain.migration_checked_for_current_version() is False  # Checked version < current version
