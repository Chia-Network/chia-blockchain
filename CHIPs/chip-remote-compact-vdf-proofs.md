CHIP Number | TBD
:------------|:----
Title | Remote compact VDF proofs for full node sync
Description | Optional full node behavior to fetch pre-compacted challenge-chain VDF witnesses over HTTP and apply them before block validation, replacing peer-to-peer compact VDF gossip for this path.
Author | TBD
Editor | TBD
Comments-URI | TBD
Status | Draft
Category | Informational
Sub-Category | Informative
Created | 2026-06-24
Requires | None
Replaces | None
Superseded-By | None

## Abstract

This CHIP specifies an optional full node optimization that downloads compact VDF proof data from static HTTP files, applies the proofs to incoming blocks before header validation, and persists the compactified block bytes. The on-chain consensus rules are unchanged: compact proofs must already be valid under existing header validation, and block identity (`header_hash`) is unchanged because VDF witnesses are not part of the foliage hash.

The proposal also defines a JSON-lines **compactvdf** file format for publishing compact witnesses in height-indexed chunks, and recommends disabling full-node handling of the legacy peer-to-peer compact VDF protocol messages when using the remote path exclusively.

## Motivation

Chia blocks store large Wesolowski VDF witnesses for compressible challenge-chain fields (`CC_EOS`, `ICC_EOS`, `CC_SP`, `CC_IP`). Timelord bluebox already produces compact witnesses (`witness_type = 0`, `normalized_to_identity = true`) that are consensus-valid replacements for the full proofs.

Today, compactification of historical blocks on full nodes relies primarily on:

1. Timelord bluebox driven by `RequestCompactProofOfTime` messages from the full node, and
2. Peer-to-peer `new_compact_vdf` / `request_compact_vdf` / `respond_compact_vdf` gossip between full nodes.

Both paths are operationally heavy during long sync: many round trips, semaphore-limited handlers, and redundant work when the same compact witnesses could be served from a static archive.

A static **compactvdf** file per 10,000 main-chain heights allows a full node to:

- Prefetch one HTTP object per height range while syncing,
- Apply all matching compact witnesses to a block in memory before `pre_validate_block`,
- Store already-compact blocks in `full_blocks`, reducing database size and future validation cost.

This does not replace timelord bluebox for live chain extension; it complements it for catch-up sync and for operators who publish compact witness archives.

## Backwards Compatibility

**Consensus:** No change. Existing `CompressibleVDFField` values, `VDFProof` wire format, and header validation rules are used as-is. A node that does not implement this CHIP continues to accept blocks with either full or compact witnesses.

**Network:** Full nodes that disable P2P compact VDF handlers no longer participate in compact witness gossip. They remain fully compatible with the chain as long as they can still validate blocks (with full witnesses from peers, or with compact witnesses applied locally from HTTP).

**Configuration:** Disabled by default when `remote_compact_vdf_base_url` is empty. Nodes without the config key behave as today.

**File format:** Entries without `sub_slot_index` remain supported via legacy lookup (candidate enumeration with `validate_vdf`).

## Rationale

### Why HTTP files instead of P2P compact VDF messages

| Approach | Pros | Cons |
|----------|------|------|
| P2P `respond_compact_vdf` | Decentralized, no trusted host | High chatter, hard to cache, easy to spam during sync |
| Static compactvdf files | Cacheable, predictable bandwidth, simple CDN hosting | Requires a publisher; trust in file integrity (mitigated by validation) |

Header validation remains the ultimate check. A malicious archive can at worst cause validation failure; it cannot forge a valid block with an invalid witness.

### Why apply before validation, not after

`header_hash` is `foliage.get_hash()` and does not include VDF proof bytes. Replacing witnesses therefore does not change block identity. The same in-memory `FullBlock` object must be both validated and persisted; applying compact proofs before `pre_validate_block` guarantees the validated bytes match the stored bytes.

### Why omit `vdf_info` from the file

`VDFInfo` (140 bytes: challenge, iterations, output) is already present on the block and is not modified by compactification. The file carries only the new witness plus enough metadata to locate the correct proof slot:

- `header_hash` — block identity
- `field_vdf` — which compressible field (`CompressibleVDFField`)
- `sub_slot_index` — index into `finished_sub_slots` for `CC_EOS` / `ICC_EOS` (omitted for `CC_SP` / `CC_IP`)
- `witness` — bytes for `VDFProof(witness_type=0, witness, normalized_to_identity=true)`

When `sub_slot_index` is present, lookup is O(1) and does not run `validate_vdf` at apply time; cryptographic verification happens once in header validation.

### Why disable P2P compact VDF handlers

When remote compact VDF is enabled, serving and requesting compact proofs from peers is redundant and adds load during sync. The reference implementation turns `new_compact_vdf`, `request_compact_vdf`, and `respond_compact_vdf` into no-ops. Timelord `RequestCompactProofOfTime` bluebox for live blocks is unchanged.

## Specification

### Configuration

Add to the `full_node` section of `config.yaml`:

```yaml
full_node:
  # Base URL for compact VDF archives. Files are fetched from:
  #   {remote_compact_vdf_base_url}/compactvdf-{start}to{end}
  # where [start, end] is an inclusive 10,000-block height range.
  # Set to empty string to disable.
  remote_compact_vdf_base_url: ""
```

Default in reference implementation: `https://www.xchos.com/vdfs` (operators may override).

### HTTP object naming and caching

- **Chunk size:** `10_000` blocks (`COMPACT_VDF_HEIGHT_CHUNK_SIZE`).
- **URL for block at height `h`:**
  ```
  {base_url without trailing slash}/compactvdf-{start}to{end}
  ```
  where `start = (h // 10000) * 10000` and `end = start + 9999`.
- **Method:** `GET`
- **Success:** HTTP `200`, body is UTF-8 text (JSON lines).
- **Missing chunk:** HTTP `404` — node proceeds with the uncompacted block.
- **Caching:** Implementations SHOULD cache the parsed entries for the current chunk in memory and evict other chunks when sync height moves to a new range.

### compactvdf file format

JSON Lines (one JSON object per line, UTF-8). Empty lines are ignored. Invalid lines SHOULD be logged and skipped.

#### Entry schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `header_hash` | `bytes32` hex string (`0x…`) | yes | Block header hash |
| `field_vdf` | `uint8` | yes | `CompressibleVDFField` value (see below) |
| `witness` | bytes hex string (`0x…`) | yes | Compact witness bytes |
| `sub_slot_index` | `uint8` | no | Index into `finished_sub_slots` for EOS fields |

Legacy entries may nest witness under `vdf_proof.witness`; parsers SHOULD accept both forms.

#### `field_vdf` values

Matches existing `CompressibleVDFField` in `chia/types/blockchain_format/vdf.py`:

| Value | Name | Proof field updated |
|-------|------|---------------------|
| 1 | `CC_EOS_VDF` | `finished_sub_slots[i].proofs.challenge_chain_slot_proof` |
| 2 | `ICC_EOS_VDF` | `finished_sub_slots[i].proofs.infused_challenge_chain_slot_proof` |
| 3 | `CC_SP_VDF` | `challenge_chain_sp_proof` |
| 4 | `CC_IP_VDF` | `challenge_chain_ip_proof` |

Reward-chain proofs (`reward_chain_slot_proof`, `reward_chain_sp_proof`, `reward_chain_ip_proof`) are **not** in scope; they are not compressible under the existing enum.

#### Compact proof form

Each `witness` is applied as:

```python
VDFProof(uint8(0), witness, normalized_to_identity=True)
```

#### Example lines

```json
{"header_hash":"0xabc…","field_vdf":1,"witness":"0x…","sub_slot_index":0}
{"header_hash":"0xabc…","field_vdf":4,"witness":"0x…"}
```

### Lookup and apply algorithm

For each entry matching `block.header_hash`:

1. `vdf_proof = compact_vdf_proof(entry.witness)`
2. If `sub_slot_index` is set: `vdf_info = vdf_info_for_sub_slot(block, field_vdf, sub_slot_index)`
3. Else: `vdf_info = find_vdf_info_for_proof(block, field_vdf, vdf_proof, constants)` (legacy; uses `validate_vdf` over candidates)
4. If `vdf_info` is `None`, skip entry
5. If `needs_compact_proof(vdf_info, block, field_vdf)` is false, skip (already compact)
6. `block = apply_compact_proof_to_block(block, vdf_info, vdf_proof, field_vdf)` — MUST copy `finished_sub_slots` before mutating sub-slots

Implementations MUST NOT treat a failed lookup as a consensus failure; skip and continue.

### Full node integration points

Remote compact VDF apply MUST run **outside** the blockchain mutex and **before** header validation on the same `FullBlock` instance:

| Path | When |
|------|------|
| Live block ingestion | `add_block`, before `pre_validate_block` |
| Batch sync | `validate_blocks` inner loop, after `skip_blocks`, before `prevalidate_blocks` |

`prevalidate_blocks` itself is unchanged from mainline (per-block futures, no apply inside).

### `is_fully_compactified` database flag

When persisting blocks, `full_blocks.is_fully_compactified` SHOULD be computed with the same predicate as header compactness:

- All `challenge_chain_slot_proof` and present `infused_challenge_chain_slot_proof` in finished sub-slots are compact
- `challenge_chain_sp_proof` is compact if present
- `challenge_chain_ip_proof` is compact

Use a shared helper (`is_fully_compactified_header_block`) rather than `FullBlock.is_fully_compactified()` if the rust and python predicates must stay aligned.

### P2P protocol handling (reference behavior)

When relying on remote compact VDF exclusively, full node API handlers for these message types MAY be disabled (no-op):

- `ProtocolMessageTypes.new_compact_vdf` (42)
- `ProtocolMessageTypes.request_compact_vdf` (40)
- `ProtocolMessageTypes.respond_compact_vdf` (41)

Timelord messages (`request_compact_proof_of_time`, `respond_compact_proof_of_time`) are unaffected.

## Reference Implementation

Pull request: [Chia-Network/chia-blockchain#21046](https://github.com/Chia-Network/chia-blockchain/pull/21046)

Implemented in `chia-blockchain` (excluding offline tooling):

| Module | Role |
|--------|------|
| `chia/full_node/compact_vdf_file.py` | `CompactVdfEntry`, parse/apply helpers, `is_fully_compactified_header_block` |
| `chia/full_node/remote_compact_vdf.py` | HTTP fetch, chunk cache, `apply_compact_vdf_entries` |
| `chia/full_node/full_node.py` | Config wiring, `block_with_remote_compact_vdfs`, sync + `add_block` hooks, `_replace_proof` refactor |
| `chia/full_node/full_node_api.py` | P2P compact VDF handlers disabled (no-op) |
| `chia/full_node/block_store.py` | `is_fully_compactified` via shared helper |
| `chia/util/initial-config.yaml` | `remote_compact_vdf_base_url` default |

### Pseudocode (sync path)

```
blocks_to_validate = skip_blocks(...)
for i in range(len(blocks_to_validate)):
    blocks_to_validate[i] = await block_with_remote_compact_vdfs(blocks_to_validate[i])
for block in blocks_to_validate:
    futures.extend(await prevalidate_blocks(blockchain, [block], vs, summaries))
```

### Pseudocode (apply)

```
async def block_with_remote_compact_vdfs(block):
    entries = await fetch_remote_compact_vdf_entries(base_url, block.height)
    return await apply_compact_vdf_entries(constants, block, entries, pool)
```

## Security

**Trust model:** The HTTP publisher is untrusted. Invalid witnesses MUST NOT be persisted as valid blocks because `pre_validate_block` / header validation still runs `validate_vdf` on all proofs.

**Integrity:** Use HTTPS for remote archives. Operators MAY pin URLs or mirror files locally.

**Denial of service:** Missing or corrupt files MUST NOT panic the node; worst case is slower sync with full-size witnesses. Implementations SHOULD bound HTTP timeouts (reference: 30 seconds per chunk).

**Privacy:** Full nodes reveal to the HTTP server which height ranges they fetch (coarse, 10k blocks).

**P2P surface reduction:** Disabling compact VDF gossip removes a class of unsolicited-proof handling during sync; timelord and normal block propagation are unchanged.

## Test Plan

- Parse compactvdf JSON lines (with and without `sub_slot_index`, legacy `vdf_proof` nesting)
- Apply entries to a block with uncompacted CC/ICC/SP/IP proofs; verify `header_hash` unchanged
- Verify compactified block passes `pre_validate_block`
- Verify invalid witness from file fails validation, block not added
- Sync pipeline applies remote proofs before prevalidation futures
- `is_fully_compactified` set correctly in `full_blocks` after apply

## Copyright

Copyright and related rights waived via [CC0](https://creativecommons.org/publicdomain/zero/1.0/).
