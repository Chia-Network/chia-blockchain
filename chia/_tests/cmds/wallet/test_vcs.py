from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, cast

from chia_rs import Coin

from chia._tests.cmds.cmd_test_utils import TestRpcClients, TestWalletRpcClient, logType, run_cli_command_and_assert
from chia._tests.cmds.wallet.test_consts import FINGERPRINT_ARG, STD_TX, get_bytes32
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint32, uint64
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.tx_config import DEFAULT_TX_CONFIG, TXConfig
from chia.wallet.vc_wallet.vc_store import VCRecord

# VC Commands


def test_vcs_mint(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class VcsMintRpcClient(TestWalletRpcClient):
        async def vc_mint(
            self,
            did_id: bytes32,
            tx_config: TXConfig,
            target_address: Optional[bytes32] = None,
            fee: uint64 = uint64(0),
        ) -> Tuple[VCRecord, List[TransactionRecord]]:
            self.add_to_log("vc_mint", (did_id, tx_config, target_address, fee))

            class FakeVC:
                def __init__(self) -> None:
                    self.launcher_id = get_bytes32(3)

                def __getattr__(self, item: str) -> Any:
                    if item == "vc":
                        return self

            txs = [STD_TX]
            return cast(VCRecord, FakeVC()), txs

    inst_rpc_client = VcsMintRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    did_bytes = get_bytes32(1)
    did_id = encode_puzzle_hash(did_bytes, "did:chia:")
    target_bytes = get_bytes32(2)
    target_addr = encode_puzzle_hash(target_bytes, "xch")
    command_args = ["wallet", "vcs", "mint", FINGERPRINT_ARG, f"-d{did_id}", "-m0.5", f"-t{target_addr}"]
    # these are various things that should be in the output
    assert_list = [
        f"New VC with launcher ID minted: {get_bytes32(3).hex()}",
        f"Transaction {get_bytes32(2).hex()}",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {"vc_mint": [(did_bytes, DEFAULT_TX_CONFIG, target_bytes, 500000000000)]}
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_vcs_get(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class VcsGetRpcClient(TestWalletRpcClient):
        async def vc_get_list(self, start: int = 0, count: int = 50) -> Tuple[List[VCRecord], Dict[str, Any]]:
            class FakeVC:
                def __init__(self) -> None:
                    self.launcher_id = get_bytes32(3)
                    self.coin = Coin(get_bytes32(1), get_bytes32(2), uint64(12345678))
                    self.inner_puzzle_hash = get_bytes32(3)
                    self.proof_hash = get_bytes32(4)

                def __getattr__(self, item: str) -> Any:
                    if item == "vc":
                        return self

            self.add_to_log("vc_get_list", (start, count))
            proofs = {get_bytes32(1).hex(): ["proof here"]}
            records = [cast(VCRecord, FakeVC())]
            return records, proofs

    inst_rpc_client = VcsGetRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = ["wallet", "vcs", "get", FINGERPRINT_ARG, "-s10", "-c10"]
    # these are various things that should be in the output
    assert_list = [
        f"Proofs:\n- {get_bytes32(1).hex()}\n  - proof here",
        f"Launcher ID: {get_bytes32(3).hex()}",
        f"Inner Address: {encode_puzzle_hash(get_bytes32(3), 'xch')}",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {"vc_get_list": [(10, 10)]}
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_vcs_update_proofs(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class VcsUpdateProofsRpcClient(TestWalletRpcClient):
        async def vc_spend(
            self,
            vc_id: bytes32,
            tx_config: TXConfig,
            new_puzhash: Optional[bytes32] = None,
            new_proof_hash: Optional[bytes32] = None,
            provider_inner_puzhash: Optional[bytes32] = None,
            fee: uint64 = uint64(0),
        ) -> List[TransactionRecord]:
            self.add_to_log("vc_spend", (vc_id, tx_config, new_puzhash, new_proof_hash, provider_inner_puzhash, fee))
            return [STD_TX]

    inst_rpc_client = VcsUpdateProofsRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    vc_bytes = get_bytes32(1)
    target_ph = get_bytes32(2)
    new_proof = get_bytes32(3)
    command_args = [
        "wallet",
        "vcs",
        "update_proofs",
        FINGERPRINT_ARG,
        f"-l{vc_bytes.hex()}",
        "-m0.5",
        f"-t{target_ph.hex()}",
        f"-p{new_proof.hex()}",
        "--reuse-puzhash",
    ]
    # these are various things that should be in the output
    assert_list = [
        "Proofs successfully updated!",
        f"Transaction {get_bytes32(2).hex()}",
    ]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "vc_spend": [
            (vc_bytes, DEFAULT_TX_CONFIG.override(reuse_puzhash=True), target_ph, new_proof, None, uint64(500000000000))
        ]
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_vcs_add_proof_reveal(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class VcsAddProofRevealRpcClient(TestWalletRpcClient):
        async def vc_add_proofs(self, proofs: Dict[str, Any]) -> None:
            self.add_to_log("vc_add_proofs", (proofs,))
            return None

    inst_rpc_client = VcsAddProofRevealRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    new_proof = "test_proof"
    command_args = ["wallet", "vcs", "add_proof_reveal", FINGERPRINT_ARG, f"-p{new_proof}"]
    # these are various things that should be in the output
    assert_list = ["Proofs added to DB successfully!"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)

    root_assert_list = ["Proof Hash: 5fdf0dfd1fddc56c0f9f68fdb31390721625321ce79f5606b3d2c6ddebbf2a79"]
    run_cli_command_and_assert(capsys, root_dir, command_args + ["-r"], root_assert_list)

    expected_calls: logType = {"vc_add_proofs": [({new_proof: "1"},)]}
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_vcs_get_proofs_for_root(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class VcsGetProofsForRootRpcClient(TestWalletRpcClient):
        async def vc_get_proofs_for_root(self, root: bytes32) -> Dict[str, Any]:
            self.add_to_log("vc_get_proofs_for_root", (root,))
            return {"test_proof": "1", "test_proof2": "1"}

    inst_rpc_client = VcsGetProofsForRootRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    proof_hash = get_bytes32(1)
    command_args = ["wallet", "vcs", "get_proofs_for_root", FINGERPRINT_ARG, f"-r{proof_hash.hex()}"]
    # these are various things that should be in the output
    assert_list = ["Proofs:", "test_proof", "test_proof2"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)

    expected_calls: logType = {"vc_get_proofs_for_root": [(proof_hash,)]}
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_vcs_revoke(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class VcsRevokeRpcClient(TestWalletRpcClient):
        async def vc_get(self, vc_id: bytes32) -> Optional[VCRecord]:
            self.add_to_log("vc_get", (vc_id,))

            class FakeVC:
                def __init__(self) -> None:
                    self.coin = Coin(get_bytes32(1), get_bytes32(2), uint64(12345678))

                def __getattr__(self, item: str) -> Any:
                    if item == "vc":
                        return self

            return cast(VCRecord, FakeVC())

        async def vc_revoke(
            self,
            vc_parent_id: bytes32,
            tx_config: TXConfig,
            fee: uint64 = uint64(0),
        ) -> List[TransactionRecord]:
            self.add_to_log("vc_revoke", (vc_parent_id, tx_config, fee))
            return [STD_TX]

    inst_rpc_client = VcsRevokeRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    parent_id = get_bytes32(1)
    vc_id = get_bytes32(2)
    command_args = [
        "wallet",
        "vcs",
        "revoke",
        FINGERPRINT_ARG,
        "-m0.5",
        "--reuse-puzhash",
    ]
    # these are various things that should be in the output
    assert_list = ["VC successfully revoked!", f"Transaction {get_bytes32(2).hex()}"]
    run_cli_command_and_assert(capsys, root_dir, command_args + [f"-p{parent_id.hex()}"], assert_list)
    run_cli_command_and_assert(capsys, root_dir, command_args + [f"-l{vc_id.hex()}"], assert_list)
    expected_calls: logType = {
        "vc_get": [(vc_id,)],
        "vc_revoke": [
            (parent_id, DEFAULT_TX_CONFIG.override(reuse_puzhash=True), uint64(500000000000)),
            (parent_id, DEFAULT_TX_CONFIG.override(reuse_puzhash=True), uint64(500000000000)),
        ],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)


def test_vcs_approve_r_cats(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class VcsApproveRCATSRpcClient(TestWalletRpcClient):
        async def crcat_approve_pending(
            self,
            wallet_id: uint32,
            min_amount_to_claim: uint64,
            tx_config: TXConfig,
            fee: uint64 = uint64(0),
        ) -> List[TransactionRecord]:
            self.add_to_log(
                "crcat_approve_pending",
                (
                    wallet_id,
                    min_amount_to_claim,
                    tx_config,
                    fee,
                ),
            )
            return [STD_TX]

    inst_rpc_client = VcsApproveRCATSRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    wallet_id = uint32(2)
    command_args = [
        "wallet",
        "vcs",
        "approve_r_cats",
        FINGERPRINT_ARG,
        f"-i{wallet_id}",
        "-a1",
        "-m0.5",
        "--min-coin-amount",
        "0.000000001",
        "--max-coin-amount",
        "10",
        "--reuse",
    ]
    # these are various things that should be in the output
    assert_list = ["VC successfully approved R-CATs!", f"Transaction {get_bytes32(2).hex()}"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)
    expected_calls: logType = {
        "crcat_approve_pending": [
            (
                wallet_id,
                uint64(1000),
                TXConfig(
                    min_coin_amount=uint64(0),
                    max_coin_amount=uint64(10000),
                    excluded_coin_amounts=[],
                    excluded_coin_ids=[],
                    reuse_puzhash=True,
                ),
                uint64(500000000000),
            )
        ],
        "get_wallets": [(None,)],
    }
    test_rpc_clients.wallet_rpc_client.check_log(expected_calls)
