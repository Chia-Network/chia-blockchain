MIN_FEE_RATE = 0  # Value of first bucket
INITIAL_STEP = 100  # First bucket after zero value
MAX_FEE_RATE = 40000000  # Mojo per 1000 cost unit
INFINITE_FEE_RATE = 1000000000

STEP_SIZE = 1.05  # bucket increase by 1.05

# Track confirm delays up to 10 block for short horizon
SHORT_BLOCK_PERIODS = 10
SHORT_SCALE = 1

# Track confirm delays up to 60 block for medium horizon
MED_BLOCK_PERIODS = 30
MED_SCALE = 2

# Track confirm delays up to 600 block for long horizon
LONG_BLOCK_PERIODS = 120
LONG_SCALE = 5

SHORT_DECAY = 0.962
MED_DECAY = 0.9952
LONG_DECAY = 0.99931

HALF_SUCCESS_PCT = 0.6  # Require 60 % success rate for target confirmations
SUCCESS_PCT = 0.85  # Require 85 % success rate for target confirmations
DOUBLE_SUCCESS_PCT = 0.95  # Require 95 % success rate for target confirmations
SUFFICIENT_FEETXS = 0.1  # Require an avg of 0.1 tx in the combined feerate bucket per block to have stat significance

FEE_ESTIMATOR_VERSION = "0.0.1"
