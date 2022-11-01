# These settings should not be end-user configurable
from __future__ import annotations

INVALID_PROTOCOL_BAN_SECONDS = 10
API_EXCEPTION_BAN_SECONDS = 10
INTERNAL_PROTOCOL_ERROR_BAN_SECONDS = 10  # Don't flap if our client is at fault
