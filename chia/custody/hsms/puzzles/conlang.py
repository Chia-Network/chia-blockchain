AGG_SIG_UNSAFE = 49
AGG_SIG_ME = 50

# the conditions below reserve coin amounts and have to be accounted for in output totals

CREATE_COIN = 51
RESERVE_FEE = 52

# the conditions below deal with announcements, for inter-coin communication

# coin announcements
CREATE_COIN_ANNOUNCEMENT = 60
ASSERT_COIN_ANNOUNCEMENT = 61

# puzzle announcements
CREATE_PUZZLE_ANNOUNCEMENT = 62
ASSERT_PUZZLE_ANNOUNCEMENT = 63

# the conditions below let coins inquire about themselves

ASSERT_MY_COIN_ID = 70
ASSERT_MY_PARENT_ID = 71
ASSERT_MY_PUZZLEHASH = 72
ASSERT_MY_AMOUNT = 73

# the conditions below ensure that we're "far enough" in the future

# wall-clock time
ASSERT_SECONDS_RELATIVE = 80
ASSERT_SECONDS_ABSOLUTE = 81

# block index
ASSERT_HEIGHT_RELATIVE = 82
ASSERT_HEIGHT_ABSOLUTE = 83
