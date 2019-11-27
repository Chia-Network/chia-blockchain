# Chia Block Format

![Chia Blockchain](/docs/assets/block-format.png "Chia block format")

## Trunk and Foliage
Chia's blockchain is based on a trunk and a foliage. The trunk is canonical, and contains proofs of time and proofs of space. The foliage is not canonical, and contains the rest of the block header, block body, and transaction filter. Arrows in the diagram represent hash pointers, a hash of the data pointed to.

Light clients can download the trunk chain and the headers, and only download the body for blocks they are interested in.

## Canonical

The reason why the blockchain is separated into a trunk and a foliage chain is that if the contents of blocks affected the proofs of space for the next block, a computationally powerful attacker could grind by creating many block bodies and seeing which one results in the best proof of space. This would make the consensus algorithm very similar to proof of work.

Since proofs of space depend only on the previous block's proof of space and proof of time, a farmer get's only one proof attempt per block. Technically, the difficulty resets affect the number of iterations, and thus affect the trunk as well. That is why there is a delay in the block number at which difficulty resets come into play.

## Double signing
One of the results of this separation into two chains is that the foliage block can be rewritten.
The farmer that signed to foliage block can also sign an alternative block at the same height, with the
same key.
This problem can be solved by allowing the next block's farmer to submit a proof of the double signature (fraud proof),
which steals the rewards from the previous farmer.

While in the short term, double signatures can happen, clients can just wait for more confirmations, and as long as
one farmer did not double sign a block, such a deep reorg cannot happen.


## Formats

### [Header](/src/types/header.py)
* **header_data**: the contents of the block header.
* **harvester_signature**: BLS prepend signature by the plot public key. A prepend signature is a signature of a message with the the pk prepended to the message.

### [Header data](/src/types/header.py)
* **prev_header_hash** :The hash of the header of the previous block.
* **timestamp**: Unix timestamp of block creation time.
* **filter_hash**: Hash of the transaction filter.
* **body_hash**: Hash of the body.
* **extension data**: hash of any extension data or extension block, useful for future updates.


### [Body](/src/types/body.py)
* **coinbase**: this is the transaction which pays out to the pool.
* **coinbase_signature**: signature by the pool public key.
* **fees_target_info**: this is where the fees will be paid out to (usually the farmer's public key), as well as the fee amount.
* **aggregated_signature**: aggregated BLS signature of all signatures in all transactions of this block.
* **solutions generator**: includes all spends in this block.
* **cost**: the cost of all puzzles.

### [Proof of Time](/src/types/proof_of_time.py)
* **challenge_hash**: the hash of the challenge, used to generate VDF group.
* **number_of_iterations**: the number of iterations that the VDF has to go through.
* **output**: the output of the VDF.
* **witness_type**: proof type of VDF.
* **witness**: VDF proof in bytes.

### [Proof of Space](/src/types/proof_of_space.py)
* **challenge_hash**: the hash of the challenge.
* **pool_pubkey**: public key of the pool, this key's signature is required to spend the coinbase transaction. The pool public key in included in the plot seed, and thus must be chosen before the plotting process. Farmers can solo-farm and use their own key as the pool key.
* **plot_pubkey**: public key of the plotter. This key signs the header, and thus allows the owner of the plot to choose their own blocks, as opposed to pools doing this.
* **size**: sometimes referred to as k, this is the plot size parameter.
* **proof**: proof of space of size k*64 bits.

### [Challenge](/src/types/challenge.py)
* **prev_challenge_hash**: the hash of the previous challenge.
* **proof_of_space_hash**: hash of the proof of space.
* **proof_of_time_output_hash**: hash of the proof of time output.
* **height**: height of the block the block.
* **total_weight**: cumulative difficulty of all blocks from genesis, including this one.
* **total_iters** cumulative VDF iterations from genesis, including this one.


## Block Validation
An unfinished block is considered valid if it passes the following checks:

1. If not genesis, the previous block must exist
2. If not genesis, the timestamp must be >= the average timestamp of last 11 blocks, and less than 2 hours in the future
3. The compact block filter must be correct, according to the body (BIP158)
4. The hash of the proof of space must match header_data.proof_of_space_hash
5. The hash of the body must match header_data.body_hash
6. Extension data must be valid, if any is present
7. If not genesis, the hash of the challenge on top of the last block, must be the same as proof_of_space.challenge_hash
8. If genesis, the challenge hash in the proof of time must be the same as in the proof of space
9. The harvester signature must sign the header_hash, with the key in the proof of space
10. The proof of space must be valid on the challenge
11. The coinbase height must be the previous block's coinbase height + 1
12. The coinbase amount must be correct according to reward schedule
13. The coinbase signature must be valid, according the the pool public key
14. All transactions must be valid
15. Aggregate signature retrieved from transactions must be valid
16. Fees must be valid
17. Cost must be valid

A block is considered valid, if it passes the unfinished block checks, and the following additional checks:

1. The proof of space hash must match the proof of space hash in challenge
2. The number of iterations (based on quality, pos, difficulty, ips) must be the same as in the PoT
3. the PoT must be valid, on a discriminant of size 1024, and the challenge_hash
4. The coinbase height must equal the height in the challenge
5. If not genesis, the challenge_hash in the proof of time must match the challenge on the previous block
6. If not genesis, the height of the challenge on the previous block must be one less than on this block
7. If genesis, the challenge height must be 0
8. If not genesis, the total weight must be the parent weight + difficulty
9. If genesis, the total weight must be starting difficulty
10. If not genesis, the total iters must be parent iters + number_iters
11. If genesis, the total iters must be number iters
