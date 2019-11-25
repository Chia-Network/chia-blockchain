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