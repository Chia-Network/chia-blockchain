from __future__ import annotations

import itertools
import os
import time
from dataclasses import replace
from functools import cached_property
from pathlib import Path
from threading import Thread
from typing import List, Optional, Sequence, Type, TypeVar

import click
from chia_rs import AugSchemeMPL, G2Element
from hsms.util.byte_chunks import create_chunks_for_blob, optimal_chunk_size_for_max_chunk_size
from segno import QRCode, make_qr

from chia.cmds.cmd_classes import NeedsWalletRPC, chia_command, command_helper, option
from chia.cmds.cmds_util import TransactionBundle
from chia.cmds.wallet import wallet_cmd
from chia.rpc.util import ALL_TRANSPORT_LAYERS
from chia.rpc.wallet_request_types import ApplySignatures, ExecuteSigningInstructions, GatherSigningInfo
from chia.types.spend_bundle import SpendBundle
from chia.wallet.signer_protocol import SignedTransaction, SigningInstructions, SigningResponse, Spend
from chia.wallet.transaction_record import TransactionRecord
from chia.wallet.util.clvm_streamable import ClvmStreamable, clvm_serialization_mode


@wallet_cmd.group("signer", help="Get information for an external signer")
def signer_cmd() -> None:
    pass


@command_helper
class QrCodeDisplay:
    qr_density: int = option(
        "--qr-density",
        "-d",
        type=int,
        help="The maximum number of bytes contained in a single qr code",
        default=100,
        show_default=True,
    )
    rotation_speed: int = option(
        "--rotation-speed",
        "-w",
        type=int,
        help="How many seconds delay between switching QR codes when there are multiple",
        default=2,
        show_default=True,
    )

    def display_qr_codes(self, blobs: List[bytes]) -> None:
        chunk_sizes: List[int] = [optimal_chunk_size_for_max_chunk_size(len(blob), self.qr_density) for blob in blobs]
        chunks: List[List[bytes]] = [
            create_chunks_for_blob(blob, chunk_size) for blob, chunk_size in zip(blobs, chunk_sizes)
        ]
        qr_codes: List[List[QRCode]] = [[make_qr(chunk) for chunk in chks] for chks in chunks]

        for i, qr_code_list in enumerate(qr_codes):
            confirmation: Optional[str] = None

            def _display_qr(index: int, code_list: List[QRCode]) -> None:
                for qr_code in itertools.cycle(code_list):
                    os.system("clear")
                    qr_code.terminal(compact=True)
                    print(f"Displaying QR Codes ({index+1}/{len(qr_codes)})")
                    print("<Press Enter to move to next qr code>")
                    for _ in range(0, self.rotation_speed * 100):
                        time.sleep(0.01)
                        if confirmation is not None:
                            return

            t = Thread(target=_display_qr, args=(i, qr_code_list))
            t.start()
            try:
                confirmation = input("")
            finally:
                confirmation = ""
                t.join()


@command_helper
class TransactionsIn:
    transaction_file_in: str = option(
        "--transaction-file-in",
        "-i",
        type=str,
        help="Transaction file to use as input",
        required=True,
    )

    @cached_property
    def transaction_bundle(self) -> TransactionBundle:
        with open(Path(self.transaction_file_in), "rb") as file:
            return TransactionBundle.from_bytes(file.read())


@command_helper
class TransactionsOut:
    transaction_file_out: str = option(
        "--transaction-file-out",
        "-o",
        type=str,
        help="Transaction filename to use as output",
        required=True,
    )

    def handle_transaction_output(self, output: List[TransactionRecord]) -> None:
        with open(Path(self.transaction_file_out), "wb") as file:
            file.write(bytes(TransactionBundle(output)))


@command_helper
class _SPCompression:
    compression: str = option(
        "--compression",
        "-c",
        type=click.Choice(["none", "chip-TBD"]),
        default="none",
        help="Wallet Signer Protocol CHIP to use for compression of output",
    )


_T_ClvmStreamable = TypeVar("_T_ClvmStreamable", bound=ClvmStreamable)


@command_helper
class SPIn(_SPCompression):
    signer_protocol_input: Sequence[str] = option(
        "--signer-protocol-input",
        "-p",
        type=str,
        help="Signer protocol objects (signatures, signing instructions, etc.) as files to load as input",
        multiple=True,
        required=True,
    )

    def read_sp_input(self, typ: Type[_T_ClvmStreamable]) -> List[_T_ClvmStreamable]:
        final_list: List[_T_ClvmStreamable] = []
        for filename in self.signer_protocol_input:  # pylint: disable=not-an-iterable
            with open(Path(filename), "rb") as file:
                with clvm_serialization_mode(
                    True, ALL_TRANSPORT_LAYERS[self.compression] if self.compression != "none" else None
                ):
                    final_list.append(typ.from_bytes(file.read()))

        return final_list


@command_helper
class SPOut(QrCodeDisplay, _SPCompression):
    output_format: str = option(
        "--output-format",
        "-t",
        type=click.Choice(["hex", "file", "qr"]),
        default="hex",
        help="How to output the information to transfer to an external signer",
    )
    output_file: Sequence[str] = option(
        "--output-file",
        "-b",
        type=str,
        multiple=True,
        help="The file(s) to output to (if --output-format=file)",
    )

    def handle_clvm_output(self, outputs: List[ClvmStreamable]) -> None:
        with clvm_serialization_mode(
            True, ALL_TRANSPORT_LAYERS[self.compression] if self.compression != "none" else None
        ):
            if self.output_format == "hex":
                for output in outputs:
                    print(bytes(output).hex())
            if self.output_format == "file":
                if len(self.output_file) == 0:
                    print("--output-format=file specifed without any --output-file")
                    return
                elif len(self.output_file) != len(outputs):
                    print(
                        "Incorrect number of file outputs specified, "
                        f"expected: {len(outputs)} got {len(self.output_file)}"
                    )
                    return
                else:
                    for filename, output in zip(self.output_file, outputs):
                        with open(Path(filename), "wb") as file:
                            file.write(bytes(output))
            if self.output_format == "qr":
                self.display_qr_codes([bytes(output) for output in outputs])


@chia_command(
    signer_cmd,
    "gather_signing_info",
    "Gather the information from a transaction that a signer needs in order to create a signature",
)
class GatherSigningInfoCMD(SPOut, TransactionsIn, NeedsWalletRPC):
    async def run(self) -> None:
        async with self.wallet_rpc() as wallet_rpc:
            spends: List[Spend] = [
                Spend.from_coin_spend(cs)
                for tx in self.transaction_bundle.txs
                if tx.spend_bundle is not None
                for cs in tx.spend_bundle.coin_spends
            ]
            signing_instructions: SigningInstructions = (
                await wallet_rpc.client.gather_signing_info(GatherSigningInfo(spends=spends))
            ).signing_instructions
            self.handle_clvm_output([signing_instructions])


@chia_command(signer_cmd, "apply_signatures", "Apply a signer's signatures to a transaction bundle")
class ApplySignaturesCMD(TransactionsOut, SPIn, TransactionsIn, NeedsWalletRPC):
    async def run(self) -> None:
        async with self.wallet_rpc() as wallet_rpc:
            signing_responses: List[SigningResponse] = self.read_sp_input(SigningResponse)
            spends: List[Spend] = [
                Spend.from_coin_spend(cs)
                for tx in self.transaction_bundle.txs
                if tx.spend_bundle is not None
                for cs in tx.spend_bundle.coin_spends
            ]
            signed_transactions: List[SignedTransaction] = (
                await wallet_rpc.client.apply_signatures(
                    ApplySignatures(spends=spends, signing_responses=signing_responses)
                )
            ).signed_transactions
            signed_spends: List[Spend] = [spend for tx in signed_transactions for spend in tx.transaction_info.spends]
            final_signature: G2Element = G2Element()
            for signature in [sig for tx in signed_transactions for sig in tx.signatures]:
                if signature.type != "bls_12381_aug_scheme":
                    print("No external spot for non BLS signatures in a spend")
                    return
                final_signature = AugSchemeMPL.aggregate([final_signature, G2Element.from_bytes(signature.signature)])
            new_spend_bundle: SpendBundle = SpendBundle(
                [spend.as_coin_spend() for spend in signed_spends], final_signature
            )
            new_transactions: List[TransactionRecord] = [
                replace(self.transaction_bundle.txs[0], spend_bundle=new_spend_bundle, name=new_spend_bundle.name()),
                *(replace(tx, spend_bundle=None) for tx in self.transaction_bundle.txs),
            ]
            self.handle_transaction_output(new_transactions)


@chia_command(signer_cmd, "execute_signing_instructions", "Given some signing instructions, return signing responses")
class ExecuteSigningInstructionsCMD(SPOut, SPIn, NeedsWalletRPC):
    async def run(self) -> None:
        async with self.wallet_rpc() as wallet_rpc:
            signing_instructions: List[SigningInstructions] = self.read_sp_input(SigningInstructions)
            self.handle_clvm_output(
                [
                    signing_response
                    for instruction_set in signing_instructions
                    for signing_response in (
                        await wallet_rpc.client.execute_signing_instructions(
                            ExecuteSigningInstructions(signing_instructions=instruction_set, partial_allowed=True)
                        )
                    ).signing_responses
                ]
            )


@chia_command(wallet_cmd, "push_transactions", "Push a transaction bundle to the wallet to send to the network")
class PushTransactionsCMD(TransactionsIn, NeedsWalletRPC):
    async def run(self) -> None:
        async with self.wallet_rpc() as wallet_rpc:
            await wallet_rpc.client.push_transactions(self.transaction_bundle.txs)
