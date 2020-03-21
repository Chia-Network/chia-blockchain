UNAME := $(shell uname)

ifeq ($(UNAME),Linux)
ALL_INSTR := $(shell grep -w avx2 /proc/cpuinfo | grep -w fma | grep -w -q adx \
	&& echo 1 || echo 0)
else
ALL_INSTR := 0
endif

LDFLAGS += -no-pie
LDLIBS += -lgmpxx -lgmp -lboost_system -pthread
CXXFLAGS += -std=c++1z -D VDF_MODE=0 -D ENABLE_ALL_INSTRUCTIONS=$(ALL_INSTR) \
	-no-pie -pthread -march=native
ifeq ($(UNAME),Darwin)
CXXFLAGS += -D CHIAOSX=1
else
OPT_CFLAGS = -O3
endif

.PHONY: all clean

all: vdf_client vdf_bench

clean:
	rm -f *.o vdf_client vdf_bench compile_asm

vdf_client vdf_bench: %: %.o asm_compiled.o
	$(CXX) $(LDFLAGS) -o $@ $^ $(LDLIBS)

vdf_client.o vdf_bench.o: CXXFLAGS += $(OPT_CFLAGS)

asm_compiled.s: compile_asm
	./compile_asm

compile_asm: compile_asm.o
	$(CXX) $(LDFLAGS) -o $@ $^ $(LDLIBS)
