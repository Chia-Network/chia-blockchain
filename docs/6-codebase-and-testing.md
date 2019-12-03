
## Reference client networking

The reference client can launch any one of the following servers:
full node, timelord, farmer, harvester, or introducer.

The `ChiaServer` class can be used to start a listening server, or to connect to other clients.
Once running, each connection goes through an asynchronous pipeline in `server.py`, where connections are mapped to messages, which are handled by the correct function, and mapped to outbound messages.

This mapping through multiple async generators is handled through the aiter library, which is a utility for python asynchronous generators.

When a protocol message arrives, it's function string is read, and the appropriate python function gets called.
The api_request parses the function data into a python object (from CBOR/streamable format).
All api functions are asynchronous generator, which means they can yield any numbner of responses in an asynchronous manner.

For example, a block message may trigger a block message to other peers, as well as messages to a timelord or farmer.

API functions yield OutboundMessages, which can be converted into Messages based on delivery.


```python
class Message:
    # Function to call
    function: str
    # Message data for that function call
    data: Any

class OutboundMessage:
    # Type of the peer, 'farmer', 'harvester', 'full_node', etc.
    peer_type: NodeType
    # Message to send
    message: Message
    delivery_method: Delivery
```

Delivery types include broadcast, response, broadcast_to_others, etc. Therefore, an api function can yield one outbound message with a broadcast type, which gets mapped into one message for each peer.

A  `PeerConnections` object is maintained by the server, which contains all active connections, as well as a Peers object for peers that we know of.
Periodically, the full node connects to an introducer to ask for peers, which the full node can connect to, if it does not have enough.

Furthermore, an on_connect function can be passed to start_server or start_client, which can trigger events on conection.

## Full Sync

Full sync is the process by which a node catches up to a tip of the blockchain that is many blocks in the future.
This may happen due to an accidental reorganization, a node going offline, or simply a node starting up for the first time.

The full sync process has a few steps:
1. The node waits for block messages from peers, to determine the heaviest (most weight) tip it can find
2. The node requests all headers up to the best tip, and finds where it diverged from it's saved tips
3. The node requests headers, a few at a time, from random nodes, from the fork point to the best tip
4. The node requests blocks, a few at a time, from random nodes, from the fork point to the tip
5. The node validates blocks as they come, and adds them to the blockchain

Full sync will take a long time for nodes just joining the system, especially since all blocks must be fully validated (including the proofs of time).
When the sync is done, our node may be behind, and therefore start another sync.
If the node is only a few blocks behind, a series of `RequestBlock` messages will be send instead, to just download the missing blocks.


## State and persistance

The reference implementation uses a mongodb database for persistance.
The database is only used by the full node, and it's only used to store full blocks that have been validated, and blocks that are downloaded during sync.
The sync blocks collection is cleared after sync is done.

The rest of the state is kept in memory in database.py.
On launch of the full node, blockchain.py is loaded with the current block database.


## Blockchain class

The Blockchain class represents the current state of where we think the blockchain is.
It maintains a list of three tips, which are the connected blocks with the highest weight, along with a height_to_hash map, to easily look up blocks using the height, a reference to the database to fetch blocks, and a map of all current headers.

Blocks only get added to the persistant database after they have been fully verified as connected blocks.
