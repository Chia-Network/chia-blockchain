from __future__ import annotations

import logging
import traceback
from collections.abc import Mapping
from enum import IntEnum
from functools import lru_cache
from typing import Any, cast

from chia_rs import ConsensusConstants, VDFInfo, VDFProof
from chia_rs.sized_bytes import bytes32, bytes100
from chia_rs.sized_ints import uint8, uint64

from chia.types.blockchain_format.classgroup import ClassgroupElement

log = logging.getLogger(__name__)

try:
    from chiavdf import create_discriminant, verify_n_wesolowski

    _has_classic = True
except ImportError:
    _has_classic = False

try:
    from chia_vdf_verify import create_discriminant_bytes, verify_n_wesolowski_bytes

    _has_rust = True
except ImportError:
    _has_rust = False

__all__ = ["VDFInfo", "VDFProof", "apply_vdf_verifier_config", "set_vdf_mode"]

_vdf_mode: str = "classic"


def set_vdf_mode(mode: str) -> None:
    """Select VDF verification backend: ``classic``, ``rust``, or ``both`` (must be installed)."""
    global _vdf_mode
    m = mode.lower().strip()
    if m not in {"classic", "rust", "both"}:
        raise ValueError(f"Invalid vdf_verifier mode {mode!r}; expected classic, rust, or both")
    if m == "classic" and not _has_classic:
        raise RuntimeError('VDF mode "classic" requires chiavdf, which is not installed or failed to import')
    if m == "rust" and not _has_rust:
        raise RuntimeError('VDF mode "rust" requires chia_vdf_verify, which is not installed or failed to import')
    if m == "both" and not (_has_classic and _has_rust):
        raise RuntimeError(
            'VDF mode "both" requires both chiavdf and chia_vdf_verify; '
            f"chiavdf={_has_classic}, chia_vdf_verify={_has_rust}"
        )
    _vdf_mode = m


def apply_vdf_verifier_config(config: Mapping[str, Any]) -> None:
    """Read ``full_node.vdf_verifier`` from a merged root config and call :func:`set_vdf_mode`."""
    fn = config.get("full_node")
    if not isinstance(fn, Mapping):
        set_vdf_mode("classic")
        return
    raw = fn.get("vdf_verifier", "classic")
    if not isinstance(raw, str):
        raise TypeError(f"full_node.vdf_verifier must be a string, got {type(raw).__name__}")
    set_vdf_mode(raw)


@lru_cache(maxsize=200)
def get_discriminant(challenge: bytes32, size_bites: int) -> int:
    if not _has_classic:
        raise RuntimeError("chiavdf is not available")
    return int(create_discriminant(challenge, size_bites), 16)


@lru_cache(maxsize=1024)
def get_discriminant_bytes(challenge: bytes32, size_bites: int) -> bytes:
    """Return discriminant as bytes (sign+magnitude). Cached per (challenge, size_bits)."""
    if not _has_rust:
        raise RuntimeError("chia_vdf_verify is not available")
    return cast(bytes, create_discriminant_bytes(challenge, size_bites))


@lru_cache(maxsize=1000)
def _verify_wesolowski_classic(
    disc: int,
    input_el: bytes100,
    output: bytes,
    number_of_iterations: uint64,
    discriminant_size: int,
    witness_type: uint8,
) -> bool:
    if not _has_classic:
        return False
    return bool(
        verify_n_wesolowski(
            str(disc),
            input_el,
            output,
            number_of_iterations,
            discriminant_size,
            witness_type,
        )
    )


@lru_cache(maxsize=1000)
def _verify_wesolowski_rust(
    disc_bytes: bytes,
    input_el: bytes100,
    output: bytes,
    number_of_iterations: uint64,
    discriminant_size: int,
    witness_type: uint8,
) -> bool:
    if not _has_rust:
        return False
    return bool(
        verify_n_wesolowski_bytes(
            disc_bytes,
            input_el,
            output,
            number_of_iterations,
            discriminant_size,
            witness_type,
        )
    )


def validate_vdf(
    proof: VDFProof,
    constants: ConsensusConstants,
    input_el: ClassgroupElement,
    info: VDFInfo,
    target_vdf_info: VDFInfo | None = None,
) -> bool:
    """
    If target_vdf_info is passed in, it is compared with info.
    """
    if target_vdf_info is not None and info != target_vdf_info:
        tb = traceback.format_stack()
        log.error(f"{tb} INVALID VDF INFO. Have: {info} Expected: {target_vdf_info}")
        return False
    if proof.witness_type + 1 > constants.MAX_VDF_WITNESS_SIZE:
        return False
    try:
        witness_bundle = info.output.data + bytes(proof.witness)
        bits = constants.DISCRIMINANT_SIZE_BITS
        iters = info.number_of_iterations
        wt = proof.witness_type
        inp = input_el.data

        if _vdf_mode == "classic":
            disc = get_discriminant(info.challenge, bits)
            return _verify_wesolowski_classic(disc, inp, witness_bundle, iters, bits, wt)

        if _vdf_mode == "rust":
            disc_b = get_discriminant_bytes(info.challenge, bits)
            return _verify_wesolowski_rust(disc_b, inp, witness_bundle, iters, bits, wt)

        # both
        disc = get_discriminant(info.challenge, bits)
        disc_b = get_discriminant_bytes(info.challenge, bits)
        ok_classic = _verify_wesolowski_classic(disc, inp, witness_bundle, iters, bits, wt)
        ok_rust = _verify_wesolowski_rust(disc_b, inp, witness_bundle, iters, bits, wt)
        if ok_classic != ok_rust:
            log.warning(
                "VDF verifier mismatch (classic=%s, rust=%s) challenge=%s iterations=%s",
                ok_classic,
                ok_rust,
                info.challenge.hex(),
                int(iters),
            )
        return ok_classic
    except Exception:
        return False


# Stores, for a given VDF, the field that uses it.
class CompressibleVDFField(IntEnum):
    CC_EOS_VDF = 1
    ICC_EOS_VDF = 2
    CC_SP_VDF = 3
    CC_IP_VDF = 4
