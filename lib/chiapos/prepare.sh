#!/bin/bash
git submodule update --init --recursive
mkdir build -p
cd build
cmake ../