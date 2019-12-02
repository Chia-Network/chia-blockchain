## Harvester protocol

```Python
class HarvesterHandshake:
    pool_pubkeys: List[PublicKey]
```

This is the handshake between farmer and harvester.
A farmer sends this message to harvesters, to initialize them and tell them which
pool public keys are acceptable to use.
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

Furthermore, if the proof of space is higher than the pool partial threshold, the farmer can request a partial proof through
```RequestPartialProof```.


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


```Python
class RequestHeaderSignature:
    quality: bytes32
    header_hash: bytes32
```


```Python
class RespondHeaderSignature:
    quality: bytes32
    header_hash_signature: PrependSignature
```


```Python
class RequestPartialProof:
    quality: bytes32
    farmer_target_hash: bytes32
```


```Python
class RespondPartialProof:
    quality: bytes32
    farmer_target_signature: PrependSignature
```