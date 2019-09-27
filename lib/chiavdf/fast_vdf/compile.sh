#!/bin/bash
cat /proc/cpuinfo | grep -w cmovf | grep -w -q avx
