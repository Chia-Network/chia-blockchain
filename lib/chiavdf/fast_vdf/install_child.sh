#!/bin/bash
set -v

cat /proc/cpuinfo | grep -e MHz -e GHz
cat /proc/cpuinfo | grep flags | head -n 1
enable_all_instructions=0
if cat /proc/cpuinfo | grep -w avx2 | grep -w fma | grep -w -q adx; then
    enable_all_instructions=1
fi
echo "enable_all_instructions: $enable_all_instructions"

if [[ "$OSTYPE" == "linux-gnu" ]]; then
    sudo apt-get install libgmp3-dev -y
    sudo apt-get install libflint-dev -y
    sudo apt install libboost-all-dev
    link_flags="-no-pie -lgmpxx -lgmp -lflint -lpthread -lboost_system"
    compile_flags="-std=c++1z -D VDF_MODE=0 -D ENABLE_ALL_INSTRUCTIONS=$enable_all_instructions -no-pie -march=native"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    link_flags="-no-pie -lgmpxx -lgmp -lflint"
    compile_flags="-std=c++1z -D CHIAOSX=1 -D VDF_MODE=0 -D ENABLE_ALL_INSTRUCTIONS=$enable_all_instructions -no-pie -march=native"
else
    link_flags="-no-pie -lgmpxx -lgmp -lflint"
    compile_flags="-std=c++1z -D VDF_MODE=0 -D ENABLE_ALL_INSTRUCTIONS=$enable_all_instructions -no-pie -march=native"
fi


g++ -o compile_asm.o -c compile_asm.cpp $compile_flags -O0
g++ -o compile_asm compile_asm.o $link_flags
./compile_asm
as -o asm_compiled.o asm_compiled.s
g++ -o vdf_server.o -c vdf_server.cpp $compile_flags -O3
g++ -o vdf_server vdf_server.o asm_compiled.o $link_flags
