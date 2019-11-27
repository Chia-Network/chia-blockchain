
## Reference client networking

The reference client can launch any one of the following servers:
full node, timelord, farmer, harvester, or introducer.

The `ChiaServer` class can be used to start a listening server, or to connect to other clients.
Once running, each connection goes through an asynchronous pipeline in `server.py`, where connections are mapped to messages, which are handled by the correct function, and mapped to outbound messages.

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


## Reference client testing