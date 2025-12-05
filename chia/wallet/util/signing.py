from __future__ import annotations

from dataclasses import dataclass

from chia_rs import AugSchemeMPL, G1Element, G2Element, PrivateKey
from chia_rs.sized_bytes import bytes32

from chia.types.blockchain_format.program import Program
from chia.types.signing_mode import CHIP_0002_SIGN_MESSAGE_PREFIX, SigningMode
from chia.util.bech32m import decode_puzzle_hash
from chia.util.byte_types import hexstr_to_bytes
from chia.wallet.puzzles import p2_delegated_conditions
from chia.wallet.puzzles.p2_delegated_puzzle_or_hidden_puzzle import puzzle_hash_for_synthetic_public_key
from chia.wallet.wallet_request_types import VerifySignatureResponse

# CHIP-0002 message signing as documented at:
# https://github.com/Chia-Network/chips/blob/80e4611fe52b174bf1a0382b9dff73805b18b8c6/CHIPs/chip-0002.md


def verify_signature(
    *, signing_mode: SigningMode, public_key: G1Element, message: str, signature: G2Element, address: str | None
) -> VerifySignatureResponse:
    """
    Given a public key, message and signature, verify if it is valid.
    :param request:
    :return:
    """
    if signing_mode in {SigningMode.CHIP_0002, SigningMode.CHIP_0002_P2_DELEGATED_CONDITIONS}:
        # CHIP-0002 message signatures are made over the tree hash of:
        #   ("Chia Signed Message", message)
        message_to_verify: bytes = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, message)).get_tree_hash()
    elif signing_mode == SigningMode.BLS_MESSAGE_AUGMENTATION_HEX_INPUT:
        # Message is expected to be a hex string
        message_to_verify = hexstr_to_bytes(message)
    elif signing_mode == SigningMode.BLS_MESSAGE_AUGMENTATION_UTF8_INPUT:
        # Message is expected to be a UTF-8 string
        message_to_verify = bytes(message, "utf-8")
    else:
        raise ValueError(f"Unsupported signing mode: {signing_mode!r}")

    # Verify using the BLS message augmentation scheme
    is_valid = AugSchemeMPL.verify(
        public_key,
        message_to_verify,
        signature,
    )
    if address is not None:
        # For signatures made by the sign_message_by_address/sign_message_by_id
        # endpoints, the "address" field should contain the p2_address of the NFT/DID
        # that was used to sign the message.
        puzzle_hash: bytes32 = decode_puzzle_hash(address)
        expected_puzzle_hash: bytes32 | None = None
        if signing_mode == SigningMode.CHIP_0002_P2_DELEGATED_CONDITIONS:
            puzzle = p2_delegated_conditions.puzzle_for_pk(Program.to(public_key))
            expected_puzzle_hash = bytes32(puzzle.get_tree_hash())
        else:
            expected_puzzle_hash = puzzle_hash_for_synthetic_public_key(public_key)
        if puzzle_hash != expected_puzzle_hash:
            return VerifySignatureResponse(isValid=False, error="Public key doesn't match the address")
    if is_valid:
        return VerifySignatureResponse(isValid=is_valid)
    else:
        return VerifySignatureResponse(isValid=False, error="Signature is invalid.")


@dataclass(kw_only=True, frozen=True)
class SignMessageResponse:
    pubkey: G1Element
    signature: G2Element


def sign_message(secret_key: PrivateKey, message: str, mode: SigningMode) -> SignMessageResponse:
    public_key = secret_key.get_g1()
    if mode == SigningMode.CHIP_0002_HEX_INPUT:
        hex_message: bytes = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, bytes.fromhex(message))).get_tree_hash()
    elif mode == SigningMode.BLS_MESSAGE_AUGMENTATION_UTF8_INPUT:
        hex_message = bytes(message, "utf-8")
    elif mode == SigningMode.BLS_MESSAGE_AUGMENTATION_HEX_INPUT:
        hex_message = bytes.fromhex(message)
    else:
        hex_message = Program.to((CHIP_0002_SIGN_MESSAGE_PREFIX, message)).get_tree_hash()
    return SignMessageResponse(
        pubkey=public_key,
        signature=AugSchemeMPL.sign(secret_key, hex_message),
    )
