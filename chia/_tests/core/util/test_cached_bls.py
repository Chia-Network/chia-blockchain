from __future__ import annotations

from chia_rs import AugSchemeMPL, BLSCache

from chia.util.hash import std_hash

LOCAL_CACHE = BLSCache(50000)


def test_cached_bls():
    n_keys = 10
    seed = b"a" * 31
    sks = [AugSchemeMPL.key_gen(seed + bytes([i])) for i in range(n_keys)]
    pks = [sk.get_g1() for sk in sks]

    msgs = [f"msg-{i}".encode() for i in range(n_keys)]
    sigs = [AugSchemeMPL.sign(sk, msg) for sk, msg in zip(sks, msgs)]
    agg_sig = AugSchemeMPL.aggregate(sigs)

    pks_half = pks[: n_keys // 2]
    msgs_half = msgs[: n_keys // 2]
    sigs_half = sigs[: n_keys // 2]
    agg_sig_half = AugSchemeMPL.aggregate(sigs_half)

    assert AugSchemeMPL.aggregate_verify(pks, msgs, agg_sig)

    # Verify with empty cache and populate it
    assert LOCAL_CACHE.aggregate_verify(pks_half, msgs_half, agg_sig_half)
    # Verify with partial cache hit
    assert LOCAL_CACHE.aggregate_verify(pks, msgs, agg_sig)
    # Verify with full cache hit
    assert LOCAL_CACHE.aggregate_verify(pks, msgs, agg_sig)

    # Use a small cache which can not accommodate all pairings
    local_cache = BLSCache(n_keys // 2)
    # Verify signatures and cache pairings one at a time
    for pk, msg, sig in zip(pks_half, msgs_half, sigs_half):
        assert local_cache.aggregate_verify([pk], [msg], sig)
    # Verify the same messages with aggregated signature (full cache hit)
    assert local_cache.aggregate_verify(pks_half, msgs_half, agg_sig_half)
    # Verify more messages (partial cache hit)
    assert local_cache.aggregate_verify(pks, msgs, agg_sig)


def test_cached_bls_repeat_pk():
    n_keys = 400
    seed = b"a" * 32
    sks = [AugSchemeMPL.key_gen(seed) for i in range(n_keys)] + [AugSchemeMPL.key_gen(std_hash(seed))]
    pks = [sk.get_g1() for sk in sks]

    msgs = [(f"msg-{i}").encode() for i in range(n_keys + 1)]
    sigs = [AugSchemeMPL.sign(sk, msg) for sk, msg in zip(sks, msgs)]
    agg_sig = AugSchemeMPL.aggregate(sigs)

    assert AugSchemeMPL.aggregate_verify(pks, msgs, agg_sig)

    assert LOCAL_CACHE.aggregate_verify(pks, msgs, agg_sig)
