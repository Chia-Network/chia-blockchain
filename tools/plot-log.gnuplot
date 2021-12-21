set term png size 6000, 1000
set output 'block-cost.png'
set xlabel "block height"
set ylabel "cost"
set y2label "duration (s)"

plot "block-chain-stats.log" using 2:3 title "cost" axes x1y1 with points, \
    "block-chain-stats.log" using 2:4 title "runtime" axes x1y2 with points

set output 'block-size.png'
set ylabel "Bytes"
unset y2label

plot "block-chain-stats.log" using 2:6 with points title "block size" axes x1y1

set output 'block-coins.png'
set ylabel "number"
unset y2label

plot 'block-chain-stats.log' using 2:7 title 'removals' with points, \
    'block-chain-stats.log' using 2:10 title 'CREATE\_COIN' with points

set output 'block-fees.png'
set ylabel "number"
unset y2label

plot 'block-chain-stats.log' using 2:8 title 'fees' with points

set output 'block-conditions.png'
set ylabel "number"
unset y2label

plot 'block-chain-stats.log' using 2:9 title 'AGG\_SIG\_UNSAFE' with points, \
    'block-chain-stats.log' using 2:10 title 'AGG\_SIG\_ME' with points, \
    'block-chain-stats.log' using 2:12 title 'RESERVE\_FEE' with points, \
    'block-chain-stats.log' using 2:14 title 'ASSERT\_COIN\_ANNOUNCEMENT' with points, \
    'block-chain-stats.log' using 2:15 title 'CREATE\_PUZZLE\_ANNOUNCEMENT' with points, \
    'block-chain-stats.log' using 2:16 title 'ASSERT\_PUZZLE\_ANNOUNCEMENT' with points, \
    'block-chain-stats.log' using 2:17 title 'ASSERT\_MY\_COIN\_ID' with points, \
    'block-chain-stats.log' using 2:18 title 'ASSERT\_MY\_PARENT\_ID' with points, \
    'block-chain-stats.log' using 2:19 title 'ASSERT\_MY\_PUZZLEHASH' with points, \
    'block-chain-stats.log' using 2:20 title 'ASSERT\_MY\_AMOUNT' with points, \
    'block-chain-stats.log' using 2:21 title 'ASSERT\_SECONDS\_RELATIVE' with points, \
    'block-chain-stats.log' using 2:22 title 'ASSERT\_SECONDS\_ABSOLUTE' with points, \
    'block-chain-stats.log' using 2:23 title 'ASSERT\_HEIGHT\_RELATIVE' with points, \
    'block-chain-stats.log' using 2:24 title 'ASSERT\_HEIGHT\_ABSOLUTE' with points
