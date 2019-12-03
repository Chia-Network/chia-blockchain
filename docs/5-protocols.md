# Protocol Messages
The Chia protocol is composed of a few different sub protocols.
All of the protocol messages are sent CBOR encoded, and their constituent members are Streamable items.
1. Harvester protocol (harvester <-> farmer)
2. Farmer protocol (farmer <-> full node)
3. Timelord protocol (timelord <-> full node)
4. Peer protocol (full node <-> full node)
5. Pool protocol (pool <-> farmer)
6. Wallet protocol (wallet/light client <-> full node)

## Harvester protocol (harvester <-> farmer)

```Python
class HarvesterHandshake:
    pool_pubkeys: List[PublicKey]
```

This is the handshake between farmer and harvester.
A farmer sends this message to harvesters, to initialize them and tell them which
pool public keys are acceptable to use.

A farmer can be connected to multiple harvesters, but a harvester should only have one farmer connection.
The harvester can start using plots which have this pool associated with them.


```Python
class NewChallenge:
    challenge_hash: bytes32
```
Message to notify the harvester of a new challenge.
The harvester looks up the challenge in each of the plots, and computes the quality.
This requires around 7 disk seeks for each quality.
Each plot is expected to have one proof of space on average, so for 50 plots, a harvester would have around 50 qualities.


```Python
class ChallengeResponse:
    challenge_hash: bytes32
    quality: bytes32
    plot_size: uint8
```
The harvester sends a response to the farmer, with `ChallengeResponse` for each of the qualities found.

After receiving a `ChallengeResponse`, farmers can use the quality to compute the expected time required to finalize a block with this proof of space.
If this time is lower than a threshold (a small constant times expected block size) which means the proof of space is very good, the farmer can request the entire proof of space from the harvester through ```RequestProofOfSpace```.


```Python
class RequestProofOfSpace:
    quality: bytes32
```
The farmer requests the entire proof of space from the harvester, which will require more disk seeks (around 50).
This is done only for proofs with high quality.



```Python
class RespondProofOfSpace:
    quality: bytes32
    proof: ProofOfSpace
```
The harvester responds with the requested proof of space.
The farmer can now choose to request a partial for this proof (to send to a pool), or if the proof is extremely good,
to make a block.
In order to make a block the farmer must request a block header from the full node using `RequestHeader` (which is in the farmer protocol), and then get a signature from the harvester using `RequestHeaderSignature`.


```Python
class RequestHeaderSignature:
    quality: bytes32
    header_hash: bytes32
```
The farmer requests a header signature for a header with the given hash.
The harvester signs the header using the locally stored private key.
This allows farmers to store their private keys in a more distributed way, with each harvester machine storing keys along with the plots.


```Python
class RespondHeaderSignature:
    quality: bytes32
    header_hash_signature: PrependSignature
```
The harvester responds with a BLS prepend signature on the header hash.


```Python
class RequestPartialProof:
    quality: bytes32
    farmer_target_hash: bytes32
```
The farmer requests a partial proof to be used for claiming pool rewards.
These are sent much more often than `RequestHeaderSignature`, since pool partials happen more often than good blocks.
The harvester signs that farmer target hash (target of funds) with the plot private key.


```Python
class RespondPartialProof:
    quality: bytes32
    farmer_target_signature: PrependSignature
```
The harvester responds with the signature, which the farmer can then send to the pool to claim funds.

## Farmer Protocol (farmer <-> full node)

```Python
class ProofOfSpaceFinalized:
    challenge_hash: bytes32
    height: uint32
    weight: uint64
    quality: bytes32
    difficulty: uint64
```
This message allows full nodes to notify farmers when new blocks get finalized with a proof of time (and therefore added to the blockchain).

The farmers will ignore old blocks using the weight, but for new blocks they can check the harvesters for high quality proofs, and proceed accordingly.
The height allows farmers to use the right coinbase transaction.
The difficulty allows farmers to calculate how many iterations their proofs of space will take, to decide whether or not to fetch the proofs and propagate them.


```Python
class ProofOfSpaceArrived:
    weight: uint64
    quality: bytes32
```
A notification from a full node to a farmer, notifying the farmer of new proofs of space at a specific height.
If the farmer's proofs are much worse at his height, there is no need to attempt to propagate them.


```Python
class RequestHeaderHash:
    challenge_hash: bytes32
    coinbase: CoinbaseInfo
    coinbase_signature: PrependSignature
    fees_target_puzzle_hash: bytes32
    proof_of_space: ProofOfSpace
```
The farmer requests a header hash from the full node,
after finding a proof of space that is worth propagating (relatively close to block time).
The coinbase transaction must be signed by the pool public key that is in the proof of space.
The `fees_target_puzzle_hash` is the farmer's own target.

On receipt of this message, the full node checks the request for validity, creates a block body and header (technically `HeaderData`), stores it, and returns the header hash using the following message.

```Python
class HeaderHash:
    pos_hash: bytes32
    header_hash: bytes32
```
This is a response to `RequestHeaderHash`, and contains the hash of a `HeaderData` object.
The farmer can send this to the harvester to fetch the signature.


```Python
class HeaderSignature:
    pos_hash: bytes32
    header_hash: bytes32
    header_signature: PrependSignature
```
The farmer sends the signature of the header hash with the plot private key to the full node.

The full node now has an unfinished block, which is a `FullBlock` without a proof of time or challenge.
This unfinished block is propagated to other nodes and timelords if the full node decides that it has a chance to win.


```Python
class ProofOfTimeRate:
    pot_estimate_ips: uint64
```
This is a message from the full node to the farmer to notify of a change in the network's rate of proof of time iterations, so that the farmer can accurately estimate how long the proof of time must be run on top of their proof of space.

## Timelord Protocol (timelord <-> full node)

```Python
class ProofOfTimeFinished:
    proof: ProofOfTime
```
A message from a timelord to a full node with a proof of time.
This is send as soon as the proof of finished, and may contain one of several types of proofs (fast, small, etc).

The full node either creates a `FullBlock` and propagates it, or sends the proof to peers that have the rest of the block already.


```Python
class ChallengeStart:
    challenge_hash: bytes32
    weight: uint64
```
A message from the full node to the timelord to notify the timelord to start working on a proof of time at the current weight.
The timelord will decide whether to start working on this challenge (iterations on the VDF), if she has available machines/cores.

Note that the timelord doesn't yet know how many iterations are necessary.
The number of iterations depends on the proofs of space, which farmers create shortly after the previous block is finished.
The timelord should receive iterations soon after challenge start.


```Python
class ProofOfSpaceInfo:
    challenge_hash: bytes32
    iterations_needed: uint64
```
A message from the full node to the timelord, describing how many iterations must be done for a proof of space.
Multiple of these messages may get sent, one for each proof of space on the challenge.
The timelord can decide how many proofs to actually finalize for each challenge.


## Peer Protocol (full node <-> full node)


```Python
class NewProofOfTime:
    proof: ProofOfTime
```
A new proof of time is received from a peer.
This message gets sent to peers that already have the rest of the block, as soon as a timelord finishes a proof of time.
Recipients can complete the block and broadcast it, or broadcast just the proof of time.

```Python
class UnfinishedBlock:
    block: FullBlock
```
An unfinished block is a block without a proof of time and without a challenge.
This message gets initially sent by nodes connected to farmers, as soon as their proofs of space are created.
It then gets propagated to full nodes, which can notify timelords about the number of iterations.
Unfinished blocks are only propagated if they extend the tips of the blockchain, and if they are sufficiently good (proof of time is expected to be faster than a threshold).


```Python
class RequestBlock:
    header_hash: bytes32
```
A block is requested from a peer.
The full node can search in the database, and send a `Block` message in response.


```Python
class Block:
    block: FullBlock
```
A block is sent to a peer, either as a response to `RequestBlock`, or just propagated as a new block.

The recipient full node, if it has already seen this block, will discard it.

Otherwise, it will try to add it to the blockchain.
* In the case of an invalid block, an exception is thrown and the peer can be disconnected.
* In the case of a disconnected block, a block far in the future will trigger a sync, while a block near in the future will trigger a chain of  `RequestBlock` messages.
* In the case of an orphan block (it's valid but does not extend tips), the internal node state is updated but nothing more is done.
* In the case of a block that extends one of the three tips, the block should be broadcast to the network.


```Python
class RequestPeers:
    """
    Return full list of peers
    """
```
A request for a list of peers.
Nodes should respond by sending a Peers message with the peer list.


```Python
class Peers:
    peer_list: List[PeerInfo]
```
A message containing information on peers.
Upon receipt of this message, nodes can update their internal peer list, and optionally request more peers from these nodes.


```Python
class RequestAllHeaderHashes:
    tip_header_hash: bytes32
```
A request for all header hashes from genesis, up to this tip.
If this header hash is present, a node should respond with `AllHeaderHashes`.
This is used to determine at what point our chain has diverged from the future tip, which can be easily
found through a binary search, and requires little bandwidth.


```Python
class AllHeaderHashes:
    header_hashes: List[bytes32]
```
The list of all header hashes up to (and including) the requested tip_header_hash.


```Python
class RequestHeaderBlocks:
    tip_header_hash: bytes32
    heights: List[uint32]
```
A request for header blocks at the given heights, with tip ancestor `tip_header_hash`.
This is used in the sync process, where headers are downloaded from the fork point, to the tip.
There is a limit to how many headers can be requested, which is set by the full node config.


```Python
class HeaderBlocks:
    tip_header_hash: bytes32
    header_blocks: List[HeaderBlock]
```
A response to `RequestHeaderBlocks`, with all the desired header blocks.
This includes proofs of space, proofs of time, challenges, and headers.


```Python
class RequestSyncBlocks:
    tip_header_hash: bytes32
    heights: List[uint32]
```

A request for full blocks at the given heights, with tip ancestor `tip_header_hash`.
This is used in the sync process, after downloading and verifying all the headers.
The full node should retrieve all these blocks, if they exist, and if the number of heights does not exceed the limit.


```Python
class SyncBlocks:
    tip_header_hash: bytes32
    blocks: List[FullBlock]
```
A response to `RequestSyncBlocks`, with all the desired blocks.


```Python
class TransactionId:
    transaction_id: bytes32
```
Propagates a transaction id to a peer, used to broadcast new transactions, while saving bandwitdh.


```Python
class RequestTransaction:
    transaction_id: bytes32
```
Request a transaction from another peer, usually after receiving a new transaction id.


```Python
class NewTransaction:
    transaction: Transaction
```
Broadcast a new transction to a peer.
