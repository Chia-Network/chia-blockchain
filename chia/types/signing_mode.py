from __future__ import annotations

from enum import Enum


class SigningMode(Enum):
    # Cipher suites used for BLS signatures defined at:
    # https://datatracker.ietf.org/doc/html/draft-irtf-cfrg-bls-signature-05#name-ciphersuites

    # CHIP-0002 signs the result of sha256tree(cons("Chia Signed Message", message)) using the
    # BLS message augmentation scheme
    CHIP_0002 = "BLS_SIG_BLS12381G2_XMD:SHA-256_SSWU_RO_AUG:CHIP-0002_"

    # Standard BLS signatures used by Chia use the BLS message augmentation scheme
    # https://datatracker.ietf.org/doc/html/draft-irtf-cfrg-bls-signature-05#name-sign
    BLS_MESSAGE_AUGMENTATION_UTF8_INPUT = "BLS_SIG_BLS12381G2_XMD:SHA-256_SSWU_RO_AUG:utf8input_"

    # Same as above but with the message specified as a string of hex characters
    BLS_MESSAGE_AUGMENTATION_HEX_INPUT = "BLS_SIG_BLS12381G2_XMD:SHA-256_SSWU_RO_AUG:hexinput_"
