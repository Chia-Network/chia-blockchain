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

plot "block-chain-stats.log" using 2:8 with points title "block size" axes x1y1

set output 'block-coins.png'
set ylabel "number"
unset y2label

plot 'block-chain-stats.log' using 2:9 title 'removals' with points, \
    'block-chain-stats.log' using 2:10 title 'additions' with points

set output 'block-fees.png'
set ylabel "number"
unset y2label

plot 'block-chain-stats.log' using 2:7 title 'fees' with points

set output 'block-refs.png'
set ylabel "number"
set y2label "duration (s)"

plot 'block-chain-stats.log' using 2:5 title 'num block references' axes x1y1 with points, \
    'block-chain-stats.log' using 2:6 title 'block reference lookup time' axes x1y2 with points
