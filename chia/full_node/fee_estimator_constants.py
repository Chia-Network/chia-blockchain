# https://github.com/bitcoin/bitcoin/blob/5b6f0f31fa6ce85db3fb7f9823b1bbb06161ae32/src/policy/fees.h
from __future__ import annotations

MIN_FEE_RATE = 0  # Value of first bucket
INITIAL_STEP = 100  # First bucket after zero value
MAX_FEE_RATE = 40000000  # Mojo per 1000 cost unit
INFINITE_FEE_RATE = 1000000000

STEP_SIZE = 1.05  # bucket increase by 1.05

# Track confirm delays up to SHORT_BLOCK_PERIOD blocks for short horizon
SHORT_BLOCK_PERIOD = 12  # 3
SHORT_SCALE = 1

# Track confirm delays up to MED_BLOCK_PERIOD blocks for medium horizon
MED_BLOCK_PERIOD = 24  # 15
MED_SCALE = 2

# Track confirm delays up to LONG_BLOCK_PERIOD blocks for long horizon
LONG_BLOCK_PERIOD = 42  # 15
LONG_SCALE = 24  # 4

SECONDS_PER_BLOCK = 40

SHORT_DECAY = 0.962
MED_DECAY = 0.9952
LONG_DECAY = 0.99931

HALF_SUCCESS_PCT = 0.6  # Require 60 % success rate for target confirmations
SUCCESS_PCT = 0.85  # Require 85 % success rate for target confirmations
DOUBLE_SUCCESS_PCT = 0.95  # Require 95 % success rate for target confirmations
SUFFICIENT_FEE_TXS = 0.1  # Require an avg of 0.1 tx in the combined fee rate bucket per block to have stat significance

FEE_ESTIMATOR_VERSION = 1

OLDEST_ESTIMATE_HISTORY = 6 * 1008
