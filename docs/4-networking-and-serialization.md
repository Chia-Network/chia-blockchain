# Networking and Serialization

## Introduction

The Chia protocol is an asynchronous peer to peer protocol running on top of TCP on port 8444, where all nodes act as both clients and servers, and can maintain long term connections with other peers.

Every message in the Chia protocol starts with 4 bytes, which is the encoded length in bytes of the dictionary, followed by a CBOR encoding of the following dictionary:


```json
{
    f: "function_name",
    d: cbor_encoded_message
}
```

where f is the desired function to call, and data is a CBOR encoded message.
For example, for a RequestBlock Chia protocol message, f is "request_block", while d is a CBOR encoded RequestBlock message.

Chia protocol messages have a max length of `(4 + 2^32 - 1) = 4294967299` bytes, or around 4GB.

## CBOR serialization

[CBOR](https://cbor.io/) is a serialization format (Concise Binary Object Representation, RFC 7049), which optimizes for
small code size and small message size.
All protocol messages use CBOR, but objects which are hashable, such as blocks, headers, proofs, etc, are serialized to bytes using a more simple steramable format, and transmitted in that way.


## Streamable Format
The streamable format is designed to be deterministic and easy to implement, to prevent consensus issues.

The primitives are:
* Sized ints serialized in in big endian format, i.e uint64
* Sized bytes serialized in big endian format, i.e bytes32
* BLSPublic keys serialized in bls format
* BLSSignatures serialized in bls format

An item is one of:
* streamable
* primitive
* List[item]
* Optional[item]

A streamable is an ordered group of items.

1. An streamable with fields 1..n is serialized by appending the serialization of each field.
2. A List is serialized into a 4 byte size prefix (number of items) and the serialization of each item
3. An Optional is serialized into a 1 byte prefix of 0x00 or 0x01, and if it's one, it's followed by the serialization of the item

This format can be implemented very easily, and allows us to hash objects like headers and proofs of space,
without complex serialization logic.

Most objects in the Chia protocol are stored and trasmitted using the streamable format.

## Handshake

All peers in the Chia protocol (whether they are farmers, full nodes, timelords, etc) act as both servers and clients (peers).
As soon as a connection is initiated between two peers, both send a Handshake message, and a HandshakeAck message to complete the handshake.


```Python
class Handshake:
    network_id: str      # 'testnet' or 'mainnet'
    version: str         # Protocol version
    node_id: bytes32     # Unique node_id
    server_port: uint16  # Listening port
    node_type: NodeType  # Node type (farmer, full node, etc)
```

After the handshake is completed, both peers can send Chia protocol messages, and disconnect at any time by sending an EOF.

## Ping Pong

Ping pong messages are periodic messages to be sent to peers, to ensure the other peer is still online.
A ping message contains a nonce, which is returned in the pong message.

If a node does not head from a peer node for a certain time (greater than the ping interval), then the node will disconnect and remove the peer from the active peer list.

## Introducer

For a new peer to join the decentralized network, they must choose s subset of all online nodes to connect to.

To facilitate this process, a number of introducer nodes will be run by Chia and other users, which will crawl the network and support one protocol message: GetPeers.
The introducer will then return a random subset of known recent peers that the calling node will attempt to connect to.

The plan is to switch to DNS and a more decentralized approach of asking different peers for their peers.
