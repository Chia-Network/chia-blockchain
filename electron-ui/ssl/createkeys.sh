#!/bin/bash
sh createca.sh ca
sh createcert.sh farmerclient
sh createcert.sh farmerserver
sh createcert.sh fullnodeclient
sh createcert.sh fullnodeserver
sh createcert.sh harvesterclient
sh createcert.sh harvesterserver
sh createcert.sh timelordclient
sh createcert.sh timelordserver
sh createcert.sh introducerclient
sh createcert.sh introducerserver
