# from src.protocols.protocol_message_types import ProtocolMessageTypes
# from src.server.outbound_message import Message
#
# DEFAULT_PER_MINUTE_FREQ_LIMIT = 100
# DEFAULT_PER_MINUTE_SIZE_LIMIT = 10 * 1024 * 1024  # in bytes
# DEFAULT_MAX_SIZE = 1 * 1024 * 1024
#
# override_limits: {
#     "handshake":
#
# }
#
#
# class RateLimiter:
#     def __init__(self):
#         pass
#
#     def message_received(self, message: Message):
#         try:
#             message_type: ProtocolMessageTypes = ProtocolMessageTypes(message.type)
#         except Exception:
#             return
