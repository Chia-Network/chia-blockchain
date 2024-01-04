from __future__ import annotations

from enum import Enum


class SigningMode(Enum):
    # Cipher suites used for BLS signatures defined at:
    # https://datatracker.ietf.org/doc/html/draft-irtf-cfrg-bls-signature-05#name-ciphersuites

    # CHIP-0002 signs the result of sha256tree(cons("Chia Signed Message", message)) using the
    # BLS message augmentation scheme
    CHIP_0002 = "BLS_SIG_BLS12381G2_XMD:SHA-256_SSWU_RO_AUG:CHIP-0002_"

    # Same as above but with the message specified as a string of hex characters
    CHIP_0002_HEX_INPUT = "BLS_SIG_BLS12381G2_XMD:SHA-256_SSWU_RO_AUG:CHIP-0002_HEX"

    # Standard BLS signatures used by Chia use the BLS message augmentation scheme
    # https://datatracker.ietf.org/doc/html/draft-irtf-cfrg-bls-signature-05#name-sign
    BLS_MESSAGE_AUGMENTATION_UTF8_INPUT = "BLS_SIG_BLS12381G2_XMD:SHA-256_SSWU_RO_AUG:utf8input_"

    # Same as above but with the message specified as a string of hex characters
    BLS_MESSAGE_AUGMENTATION_HEX_INPUT = "BLS_SIG_BLS12381G2_XMD:SHA-256_SSWU_RO_AUG:hexinput_"

    # Use for verifying signatures made with Tangem cards
    CHIP_0002_P2_DELEGATED_CONDITIONS = "BLS_SIG_BLS12381G2_XMD:SHA-256_SSWU_RO_AUG:CHIP-0002_P2_DELEGATED_PUZZLE"


# https://github.com/Chia-Network/chips/blob/80e4611fe52b174bf1a0382b9dff73805b18b8c6/CHIPs/chip-0002.md#signmessage
CHIP_0002_SIGN_MESSAGE_PREFIX = "Chia Signed Message"
