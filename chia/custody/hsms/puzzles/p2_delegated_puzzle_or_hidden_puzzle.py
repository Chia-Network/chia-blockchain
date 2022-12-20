"""
Pay to delegated puzzle or hidden puzzle

In this puzzle program, the solution must choose either a hidden puzzle or a
delegated puzzle on a given public key.

The given public key is morphed by adding an offset from the hash of the hidden puzzle
and itself, giving a new so-called "synthetic" public key which has the hidden puzzle
hidden inside of it.

If the hidden puzzle path is taken, the hidden puzzle and original public key will be revealed
which proves that it was hidden there in the first place.

This roughly corresponds to bitcoin's taproot.

Note:

p2_delegated_puzzle_or_hidden_puzzle is essentially the "standard coin" in chia.
DEFAULT_HIDDEN_PUZZLE_HASH from this puzzle is used with
calculate_synthetic_secret_key in the wallet's standard pk_to_sk finder.

This is important because it allows sign_coin_spends to function properly via the
following mechanism:

- A 'standard coin' coin exists in the blockchain with some puzzle hash.

- The user's wallet contains a primary sk/pk pair which are used to derive to one
  level a set of auxiliary sk/pk pairs which are used for specific coins. These
  can be used for signing in AGG_SIG_ME, but the standard coin uses a key further
  derived from one of these via calculate_synthetic_secret_key as described in
  https://chialisp.com/docs/standard_transaction. Therefore, when a wallet needs
  to find a secret key for signing based on a public key, it needs to try repeating
  this derivation as well and see if the BLSPublicKey (pk) associated with any of the
  derived secret keys matches the pk requested by the coin.

- Python code previously appeared which was written like:

    delegated_puzzle_solution = Program.to((1, condition_args))
    solutions = Program.to([[], delegated_puzzle_solution, []])

  In context, delegated_puzzle_solution here is any *chialisp program*, here one
  simply quoting a list of conditions, and the following argument is the arguments
  to this program, which here are unused. Secondly, the actual arguments to the
  p2_delegated_puzzle_or_hidden_puzzle are given. The first argument determines
  whether a hidden or revealed puzzle is used. If the puzzle is hidden, then what
  is required is a signature given a specific synthetic key since the key cannot be
  derived inline without the puzzle. In that case, the first argument is this key.
  In most cases, the puzzle will be revealed, and this argument will be the nil object,
  () (represented here by an empty python list).

  The second and third arguments are a chialisp program and its corresponding
  arguments, which will be run inside the standard coin puzzle. This interacts with
  sign_coin_spend in that the AGG_SIG_ME condition added by the inner puzzle asks the
  surrounding system to provide a signature over the provided program with a synthetic
  key whose derivation is within. Any wallets which intend to use standard coins in
  this way must try to resolve a public key to a secret key via this derivation.
"""

import hashlib

from hsms.bls12_381 import BLSPublicKey, BLSSecretExponent

from hsms.streamables import bytes32, Program

from .load_clvm import load_clvm
from .p2_conditions import puzzle_for_conditions

DEFAULT_HIDDEN_PUZZLE = Program.from_bytes(
    bytes.fromhex("ff0980")
)  # this puzzle `(=)` always fails

DEFAULT_HIDDEN_PUZZLE_HASH = DEFAULT_HIDDEN_PUZZLE.tree_hash()

MOD = load_clvm("p2_delegated_puzzle_or_hidden_puzzle.cl")

SYNTHETIC_MOD = load_clvm("calculate_synthetic_public_key.cl")


def calculate_synthetic_offset(
    public_key: BLSPublicKey, hidden_puzzle_hash: bytes32
) -> BLSSecretExponent:
    blob = hashlib.sha256(bytes(public_key) + hidden_puzzle_hash).digest()
    offset = Program.to(blob).as_int()
    assert offset == int(Program.to(blob))
    return BLSSecretExponent.from_int(offset)


def calculate_synthetic_public_key(
    public_key: BLSPublicKey, hidden_puzzle_hash: bytes32
) -> BLSPublicKey:
    r = SYNTHETIC_MOD.run([bytes(public_key), hidden_puzzle_hash])
    return BLSPublicKey.from_bytes(r.as_atom())


def calculate_synthetic_secret_key(
    secret_key: BLSSecretExponent, hidden_puzzle_hash: bytes32
) -> BLSSecretExponent:
    public_key = secret_key.public_key()
    synthetic_offset = calculate_synthetic_offset(public_key, hidden_puzzle_hash)
    synthetic_secret_key = secret_key + synthetic_offset
    return synthetic_secret_key


def puzzle_for_synthetic_public_key(synthetic_public_key: BLSPublicKey) -> Program:
    return MOD.curry(bytes(synthetic_public_key))


def puzzle_for_public_key_and_hidden_puzzle_hash(
    public_key: BLSPublicKey, hidden_puzzle_hash: bytes32
) -> Program:
    synthetic_public_key = calculate_synthetic_public_key(
        public_key, hidden_puzzle_hash
    )
    return puzzle_for_synthetic_public_key(synthetic_public_key)


def puzzle_for_public_key_and_hidden_puzzle(
    public_key: BLSPublicKey, hidden_puzzle: Program
) -> Program:
    return puzzle_for_public_key_and_hidden_puzzle_hash(
        public_key, hidden_puzzle.tree_hash()
    )


def puzzle_for_pk(public_key: BLSPublicKey) -> Program:
    return puzzle_for_public_key_and_hidden_puzzle_hash(
        public_key, DEFAULT_HIDDEN_PUZZLE_HASH
    )


def solution_for_delegated_puzzle(
    delegated_puzzle: Program, solution: Program
) -> Program:
    return Program.to([[], delegated_puzzle, solution])


def solution_for_hidden_puzzle(
    hidden_public_key: BLSPublicKey,
    hidden_puzzle: Program,
    solution_to_hidden_puzzle: Program,
) -> Program:
    return Program.to([hidden_public_key, hidden_puzzle, solution_to_hidden_puzzle])


def solution_for_conditions(conditions) -> Program:
    delegated_puzzle = puzzle_for_conditions(conditions)
    return solution_for_delegated_puzzle(delegated_puzzle, Program.to(0))
