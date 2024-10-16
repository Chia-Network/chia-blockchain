from __future__ import annotations

import time
from pathlib import Path
from secrets import token_bytes
from typing import Any, Dict, List, Optional, Tuple, Union

import pytest
from typing_extensions import override

from chia._tests.cmds.cmd_test_utils import TestRpcClients, TestWalletRpcClient, run_cli_command_and_assert
from chia._tests.cmds.wallet.test_consts import FINGERPRINT_ARG, STD_TX, STD_UTX
from chia.rpc.wallet_request_types import (
    CreateNewDAOWalletResponse,
    DAOAddFundsToTreasuryResponse,
    DAOCloseProposalResponse,
    DAOCreateProposalResponse,
    DAOExitLockupResponse,
    DAOFreeCoinsFromFinishedProposalsResponse,
    DAOSendToLockupResponse,
    DAOVoteOnProposalResponse,
)
from chia.types.blockchain_format.sized_bytes import bytes32
from chia.util.bech32m import encode_puzzle_hash
from chia.util.ints import uint8, uint32, uint64
from chia.wallet.conditions import ConditionValidTimes, parse_timelock_info
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.transaction_type import TransactionType
from chia.wallet.util.tx_config import TXConfig
from chia.wallet.util.wallet_types import WalletType

# DAO Commands


def test_dao_create(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DAOCreateRpcClient(TestWalletRpcClient):
        async def create_new_dao_wallet(
            self,
            mode: str,
            tx_config: TXConfig,
            dao_rules: Optional[Dict[str, uint64]] = None,
            amount_of_cats: Optional[uint64] = None,
            treasury_id: Optional[bytes32] = None,
            filter_amount: uint64 = uint64(1),
            name: Optional[str] = None,
            fee: uint64 = uint64(0),
            fee_for_cat: uint64 = uint64(0),
            push: bool = True,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> CreateNewDAOWalletResponse:
            if not treasury_id:
                treasury_id = bytes32(token_bytes(32))
            return CreateNewDAOWalletResponse.from_json_dict(
                {
                    "success": True,
                    "transactions": [STD_TX.to_json_dict()],
                    "unsigned_transactions": [STD_UTX.to_json_dict()],
                    "type": WalletType.DAO,
                    "wallet_id": 2,
                    "treasury_id": treasury_id,
                    "cat_wallet_id": 3,
                    "dao_cat_wallet_id": 4,
                }
            )

    inst_rpc_client = DAOCreateRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    command_args = [
        "dao",
        "create",
        FINGERPRINT_ARG,
        "-n test",
        "--attendance-required",
        "1000",
        "--cat-amount",
        "100000",
        "-m0.1",
        "--reuse",
    ]
    # these are various things that should be in the output
    assert_list = ["Successfully created DAO Wallet", "DAO Wallet ID: 2", "CAT Wallet ID: 3", "DAOCAT Wallet ID: 4"]
    run_cli_command_and_assert(capsys, root_dir, command_args, assert_list)

    # Check command raises if proposal minimum is even
    odd_pm_command_args = [
        "dao",
        "create",
        FINGERPRINT_ARG,
        "-n test",
        "--attendance-required",
        "1000",
        "--cat-amount",
        "100000",
        "--proposal-minimum",
        "10",
        "-m0.1",
        "--reuse",
    ]
    extra_assert_list = [
        "Adding 1 mojo to proposal minimum amount",
    ]
    run_cli_command_and_assert(capsys, root_dir, odd_pm_command_args, extra_assert_list)

    # Add wallet for existing DAO
    add_command_args = [
        "dao",
        "add",
        FINGERPRINT_ARG,
        "-n test",
        "-t",
        bytes32(token_bytes(32)).hex(),
        "--filter-amount",
        "1",
    ]
    run_cli_command_and_assert(capsys, root_dir, add_command_args, assert_list)


def test_dao_treasury(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    class DAOCreateRpcClient(TestWalletRpcClient):
        async def dao_get_treasury_id(
            self,
            wallet_id: int,
        ) -> Dict[str, str]:
            return {"treasury_id": "0xCAFEF00D"}

        async def dao_get_treasury_balance(self, wallet_id: int) -> Dict[str, Union[str, bool, Dict[str, int]]]:
            if wallet_id == 2:
                return {"success": True, "balances": {"xch": 1000000000000, "0xCAFEF00D": 10000000}}
            else:
                return {"success": True, "balances": {}}

        async def dao_add_funds_to_treasury(
            self,
            wallet_id: int,
            funding_wallet_id: int,
            amount: uint64,
            tx_config: TXConfig,
            fee: uint64 = uint64(0),
            reuse_puzhash: Optional[bool] = None,
            push: bool = True,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> DAOAddFundsToTreasuryResponse:
            return DAOAddFundsToTreasuryResponse([STD_UTX], [STD_TX], STD_TX.name, STD_TX)

        async def dao_get_rules(
            self,
            wallet_id: int,
        ) -> Dict[str, Dict[str, int]]:
            return {"rules": {"proposal_minimum": 100}}

        @override
        async def get_transaction(self, transaction_id: bytes32) -> TransactionRecord:
            return TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=bytes32(b"2" * 32),
                amount=uint64(10),
                fee_amount=uint64(1),
                confirmed=True,
                sent=uint32(10),
                spend_bundle=None,
                additions=[],
                removals=[],
                wallet_id=uint32(1),
                sent_to=[("peer1", uint8(1), None)],
                trade_id=None,
                type=uint32(TransactionType.INCOMING_TX.value),
                name=bytes32(token_bytes()),
                memos=[],
                valid_times=parse_timelock_info(tuple()),
            )

    inst_rpc_client = DAOCreateRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client

    get_id_args = ["dao", "get_id", FINGERPRINT_ARG, "-i 2"]
    get_id_asserts = ["Treasury ID: 0xCAFEF00D"]
    run_cli_command_and_assert(capsys, root_dir, get_id_args, get_id_asserts)

    get_balance_args = ["dao", "balance", FINGERPRINT_ARG, "-i 2"]
    get_balance_asserts = ["XCH: 1.0", "0xCAFEF00D: 10000.0"]
    run_cli_command_and_assert(capsys, root_dir, get_balance_args, get_balance_asserts)

    no_balance_args = ["dao", "balance", FINGERPRINT_ARG, "-i 3"]
    no_balance_asserts = ["The DAO treasury currently has no funds"]
    run_cli_command_and_assert(capsys, root_dir, no_balance_args, no_balance_asserts)

    add_funds_args = ["dao", "add_funds", FINGERPRINT_ARG, "-i 2", "-w 1", "-a", "10", "-m 0.1", "--reuse"]
    add_funds_asserts = [
        "Transaction submitted to nodes",
    ]
    run_cli_command_and_assert(capsys, root_dir, add_funds_args, add_funds_asserts)

    rules_args = ["dao", "rules", FINGERPRINT_ARG, "-i 2"]
    rules_asserts = "proposal_minimum: 100"
    run_cli_command_and_assert(capsys, root_dir, rules_args, rules_asserts)


def test_dao_proposals(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DAOCreateRpcClient(TestWalletRpcClient):
        async def dao_get_proposals(
            self,
            wallet_id: int,
            include_closed: bool = True,
        ) -> Dict[str, Union[bool, int, List[Any]]]:
            proposal = {
                "proposal_id": "0xCAFEF00D",
                "amount_voted": uint64(10),
                "yes_votes": uint64(10),
                "passed": True,
                "closed": True,
            }
            proposal_2 = {
                "proposal_id": "0xFEEDBEEF",
                "amount_voted": uint64(120),
                "yes_votes": uint64(100),
                "passed": True,
                "closed": False,
            }
            return {
                "success": True,
                "proposals": [proposal, proposal_2],
                "proposal_timelock": 5,
                "soft_close_length": 10,
            }

        async def dao_parse_proposal(
            self,
            wallet_id: int,
            proposal_id: str,
        ) -> Dict[str, Union[bool, Dict[str, Any]]]:
            if proposal_id == "0xCAFEF00D":
                puzhash = bytes32(b"1" * 32).hex()
                asset_id = bytes32(b"2" * 32).hex()
                proposal_details: Dict[str, Any] = {
                    "proposal_type": "s",
                    "xch_conditions": [{"puzzle_hash": puzhash, "amount": 100}],
                    "asset_conditions": [
                        {"asset_id": asset_id, "conditions": [{"puzzle_hash": puzhash, "amount": 123}]}
                    ],
                }
            elif proposal_id == "0xFEEDBEEF":
                proposal_details = {
                    "proposal_type": "u",
                    "dao_rules": {
                        "proposal_timelock": 10,
                        "soft_close_length": 50,
                    },
                }
            else:
                proposal_details = {
                    "proposal_type": "s",
                    "mint_amount": 1000,
                    "new_cat_puzhash": bytes32(b"x" * 32).hex(),
                }
            proposal_state = {
                "state": {
                    "passed": False,
                    "closable": False,
                    "closed": False,
                    "total_votes_needed": 10,
                    "yes_votes_needed": 20,
                    "blocks_needed": 30,
                }
            }
            proposal_dict = {**proposal_state, **proposal_details}
            return {"success": True, "proposal_dictionary": proposal_dict}

        async def dao_vote_on_proposal(
            self,
            wallet_id: int,
            proposal_id: str,
            vote_amount: int,
            tx_config: TXConfig,
            is_yes_vote: bool,
            fee: uint64 = uint64(0),
            push: bool = True,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> DAOVoteOnProposalResponse:
            return DAOVoteOnProposalResponse([STD_UTX], [STD_TX], STD_TX.name, STD_TX)

        async def dao_close_proposal(
            self,
            wallet_id: int,
            proposal_id: str,
            tx_config: TXConfig,
            fee: uint64 = uint64(0),
            self_destruct: bool = False,
            reuse_puzhash: Optional[bool] = None,
            push: bool = True,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> DAOCloseProposalResponse:
            return DAOCloseProposalResponse([STD_UTX], [STD_TX], STD_TX.name, STD_TX)

        async def dao_create_proposal(
            self,
            wallet_id: int,
            proposal_type: str,
            tx_config: TXConfig,
            additions: Optional[List[Dict[str, Any]]] = None,
            amount: Optional[uint64] = None,
            inner_address: Optional[str] = None,
            asset_id: Optional[str] = None,
            cat_target_address: Optional[str] = None,
            vote_amount: Optional[int] = None,
            new_dao_rules: Optional[Dict[str, uint64]] = None,
            fee: uint64 = uint64(0),
            reuse_puzhash: Optional[bool] = None,
            push: bool = True,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> DAOCreateProposalResponse:
            return DAOCreateProposalResponse([STD_UTX], [STD_TX], bytes32([0] * 32), STD_TX.name, STD_TX)

        async def get_wallets(self, wallet_type: Optional[WalletType] = None) -> List[Dict[str, Union[str, int]]]:
            return [{"id": 1, "type": 0}, {"id": 2, "type": 14}]

        @override
        async def get_transaction(self, transaction_id: bytes32) -> TransactionRecord:
            return TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=bytes32(b"2" * 32),
                amount=uint64(10),
                fee_amount=uint64(1),
                confirmed=True,
                sent=uint32(10),
                spend_bundle=None,
                additions=[],
                removals=[],
                wallet_id=uint32(1),
                sent_to=[("peer1", uint8(1), None)],
                trade_id=None,
                type=uint32(TransactionType.INCOMING_TX.value),
                name=bytes32(b"x" * 32),
                memos=[],
                valid_times=parse_timelock_info(tuple()),
            )

    # List all proposals
    inst_rpc_client = DAOCreateRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    list_args = ["dao", "list_proposals", FINGERPRINT_ARG, "-i 2"]
    # these are various things that should be in the output
    list_asserts = [
        "Proposal ID: 0xCAFEF00D",
        "Status: OPEN",
        "Votes for: 10",
        "Votes against: 0",
        "Proposal ID: 0xFEEDBEEF",
        "Status: CLOSED",
        "Votes for: 100",
        "Votes against: 20",
        "Proposals have 10 blocks of soft close time.",
    ]
    run_cli_command_and_assert(capsys, root_dir, list_args, list_asserts)

    # Show details of specific proposal
    parse_spend_args = ["dao", "show_proposal", FINGERPRINT_ARG, "-i 2", "-p", "0xCAFEF00D"]
    address = encode_puzzle_hash(bytes32(b"1" * 32), "xch")
    asset_id = bytes32(b"2" * 32).hex()
    parse_spend_asserts = [
        "Type: SPEND",
        "Status: OPEN",
        "Passed: False",
        "Closable: False",
        "Total votes needed: 10",
        "Yes votes needed: 20",
        "Blocks remaining: 30",
        "Proposal XCH Conditions",
        f"Address: {address}",
        "Amount: 100",
        "Proposal asset Conditions",
        f"Asset ID: {asset_id}",
        f"Address: {address}",
        "Amount: 123",
    ]
    run_cli_command_and_assert(capsys, root_dir, parse_spend_args, parse_spend_asserts)

    parse_update_args = ["dao", "show_proposal", FINGERPRINT_ARG, "-i2", "-p", "0xFEEDBEEF"]
    parse_update_asserts = [
        "Type: UPDATE",
        "proposal_timelock: 10",
        "soft_close_length: 50",
    ]
    run_cli_command_and_assert(capsys, root_dir, parse_update_args, parse_update_asserts)

    parse_mint_args = ["dao", "show_proposal", FINGERPRINT_ARG, "-i2", "-p", "0xDABBAD00"]
    parse_mint_asserts = [
        "Type: MINT",
        "Amount of CAT to mint: 1000",
        f"Address: {encode_puzzle_hash(bytes32(b'x' * 32), 'xch')}",
    ]
    run_cli_command_and_assert(capsys, root_dir, parse_mint_args, parse_mint_asserts)

    # Vote on a proposal
    vote_args = ["dao", "vote", FINGERPRINT_ARG, "-i 2", "-p", "0xFEEDBEEF", "-a", "1000", "-n", "-m 0.1", "--reuse"]
    vote_asserts = ["Transaction submitted to nodes"]
    run_cli_command_and_assert(capsys, root_dir, vote_args, vote_asserts)

    # Close a proposal
    close_args = ["dao", "close_proposal", FINGERPRINT_ARG, "-i 2", "-p", "0xFEEDBEEF", "-d", "-m 0.1", "--reuse"]
    close_asserts = ["Transaction submitted to nodes"]
    run_cli_command_and_assert(capsys, root_dir, close_args, close_asserts)

    # Create a spend proposal
    address = encode_puzzle_hash(bytes32(b"x" * 32), "xch")
    spend_args = [
        "dao",
        "create_proposal",
        "spend",
        FINGERPRINT_ARG,
        "-i 2",
        "-t",
        address,
        "-a",
        "10",
        "-v",
        "1000",
        "--asset-id",
        "0xFEEDBEEF",
        "-m 0.1",
        "--reuse",
    ]
    proposal_asserts = ["Successfully created proposal", f"Proposal ID: {bytes32([0] * 32).hex()}"]
    run_cli_command_and_assert(capsys, root_dir, spend_args, proposal_asserts)

    bad_spend_args = [
        "dao",
        "create_proposal",
        "spend",
        FINGERPRINT_ARG,
        "-i 2",
        "-t",
        address,
        "-v",
        "1000",
        "--asset-id",
        "0xFEEDBEEF",
        "-m 0.1",
        "--reuse",
    ]
    proposal_asserts = ["Successfully created proposal", f"Proposal ID: {bytes32([0] * 32).hex()}"]
    with pytest.raises(ValueError) as e_info:
        run_cli_command_and_assert(capsys, root_dir, bad_spend_args, proposal_asserts)
    assert e_info.value.args[0] == "Must include a json specification or an address / amount pair."

    # Create an update proposal
    update_args = [
        "dao",
        "create_proposal",
        "update",
        FINGERPRINT_ARG,
        "-i 2",
        "-v",
        "1000",
        "--proposal-timelock",
        "4",
        "-m 0.1",
        "--reuse",
    ]
    run_cli_command_and_assert(capsys, root_dir, update_args, proposal_asserts)

    # Create a mint proposal
    mint_args = [
        "dao",
        "create_proposal",
        "mint",
        FINGERPRINT_ARG,
        "-i 2",
        "-v",
        "1000",
        "-a",
        "100",
        "-t",
        address,
        "-m 0.1",
        "--reuse",
    ]
    run_cli_command_and_assert(capsys, root_dir, mint_args, proposal_asserts)


def test_dao_cats(capsys: object, get_test_cli_clients: Tuple[TestRpcClients, Path]) -> None:
    test_rpc_clients, root_dir = get_test_cli_clients

    # set RPC Client
    class DAOCreateRpcClient(TestWalletRpcClient):
        async def dao_send_to_lockup(
            self,
            wallet_id: int,
            amount: uint64,
            tx_config: TXConfig,
            fee: uint64 = uint64(0),
            reuse_puzhash: Optional[bool] = None,
            push: bool = True,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> DAOSendToLockupResponse:
            return DAOSendToLockupResponse([STD_UTX], [STD_TX], STD_TX.name, [STD_TX])

        async def dao_free_coins_from_finished_proposals(
            self,
            wallet_id: int,
            tx_config: TXConfig,
            fee: uint64 = uint64(0),
            reuse_puzhash: Optional[bool] = None,
            push: bool = True,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> DAOFreeCoinsFromFinishedProposalsResponse:
            return DAOFreeCoinsFromFinishedProposalsResponse([STD_UTX], [STD_TX], STD_TX.name, STD_TX)

        async def dao_exit_lockup(
            self,
            wallet_id: int,
            tx_config: TXConfig,
            coins: Optional[List[Dict[str, Union[str, int]]]] = None,
            fee: uint64 = uint64(0),
            reuse_puzhash: Optional[bool] = None,
            push: bool = True,
            timelock_info: ConditionValidTimes = ConditionValidTimes(),
        ) -> DAOExitLockupResponse:
            return DAOExitLockupResponse([STD_UTX], [STD_TX], STD_TX.name, STD_TX)

        @override
        async def get_transaction(self, transaction_id: bytes32) -> TransactionRecord:
            return TransactionRecord(
                confirmed_at_height=uint32(0),
                created_at_time=uint64(int(time.time())),
                to_puzzle_hash=bytes32(b"2" * 32),
                amount=uint64(10),
                fee_amount=uint64(1),
                confirmed=True,
                sent=uint32(10),
                spend_bundle=None,
                additions=[],
                removals=[],
                wallet_id=uint32(1),
                sent_to=[("peer1", uint8(1), None)],
                trade_id=None,
                type=uint32(TransactionType.INCOMING_TX.value),
                name=bytes32(b"x" * 32),
                memos=[],
                valid_times=parse_timelock_info(tuple()),
            )

    inst_rpc_client = DAOCreateRpcClient()  # pylint: disable=no-value-for-parameter
    test_rpc_clients.wallet_rpc_client = inst_rpc_client
    lockup_args = ["dao", "lockup_coins", FINGERPRINT_ARG, "-i 2", "-a", "1000", "-m 0.1", "--reuse"]
    lockup_asserts = ["Transaction submitted to nodes"]
    run_cli_command_and_assert(capsys, root_dir, lockup_args, lockup_asserts)

    release_args = ["dao", "release_coins", FINGERPRINT_ARG, "-i 2", "-m 0.1", "--reuse"]
    # tx_id = bytes32(b"x" * 32).hex()
    release_asserts = ["Transaction submitted to nodes"]
    run_cli_command_and_assert(capsys, root_dir, release_args, release_asserts)

    exit_args = ["dao", "exit_lockup", FINGERPRINT_ARG, "-i 2", "-m 0.1", "--reuse"]
    exit_asserts = ["Transaction submitted to nodes"]
    run_cli_command_and_assert(capsys, root_dir, exit_args, exit_asserts)
