# Bugbot Review Guidance

Use these repository-specific invariants when reviewing pull requests. Prefer
these rules over local reasoning from a narrow diff when they apply.

## Consensus Validation

When reviewing `chia/consensus/**` or `chia/full_node/full_node.py`, remember:

- `ValidationState` contains the sub-slot iterations, difficulty, and previous
  sub-epoch-summary block used for header validation.
- Batch pre-validation intentionally mutates the caller-provided
  `ValidationState` while scheduling blocks, then passes each worker the state
  for that specific block.
- Difficulty and sub-slot-iteration changes are valid only through a
  sub-epoch summary. `validate_finished_header_block()` rejects
  `new_difficulty` or `new_sub_slot_iters` when the finished sub-slot does not
  carry a valid `subepoch_summary_hash`.
- `block_to_block_record()` converts the validated sub-epoch-summary hash into
  `block_rec.sub_epoch_summary_included`.
- The authoritative source for advancing shared validation state after a block
  is `block_rec.sub_epoch_summary_included`, not the raw peer-provided
  `block.finished_sub_slots[0].challenge_chain.new_*` fields.

Do not report stale `ValidationState` across a valid difficulty/SSI transition
unless you can show a valid path where `new_difficulty` or
`new_sub_slot_iters` is accepted while `block_rec.sub_epoch_summary_included`
remains `None`.
