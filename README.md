# Chia DNS Seeder
![Alt text](https://www.chia.net/img/chia_logo.svg)

Features:
* Implements peer statistics from the bitcoin-seeder: https://github.com/sipa/bitcoin-seeder
* Runs a mini-DNS server on port 53 and a full node to crawl the network.
* Stores peers and peer statistics into a db, to be persistent between runs.

## Install

```
sh install.sh
. ./activate
chia init
```

## Install ubuntu

It's possible systemd already binds port 53. Special instructions to free port 53 are provided here (points #2 and #3): https://github.com/team-exor/generic-seeder#exclamation-special-instructions-for-ubuntu-users-exclamation


## Configure

In `dns.py`, modify variables `D`, `ns` and `soa_record` according to your domain.

In `crawler.py`, modify `bootstrap_peers` with some reliable initial peers to contact after starting the crawler. Also, modify `minimum_height` with the minimal height
a node must have in order to be relayed as a DNS response.

An example how to set-up A and NS records for your domain using DigitalOcean can be found in this video, from 9:40: https://www.youtube.com/watch?v=DsaxbwwVEXk&t=580s

## Running

```
tmux new -s seeder
. ./activate
cd chia/crawler
python start_crawler.py &
python dns.py &
```

## Stopping

Do `lsof -i:8444` (for crawler) and `lsof -i:53` (for DNS server). Then, do `kill -9 $PID`.
