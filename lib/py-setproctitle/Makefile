# Oh, makefile, help me with the python3 craze :D
#
# Copyright (c) 2010-2016 Daniele Varrazzo <daniele.varrazzo@gmail.com>

MKDIR = mkdir -p
RM = rm -f

# Customize these to select the Python to build/test
PYTHON ?= python
PYCONFIG ?= python-config
PY2TO3 ?= 2to3

# PYVER value is 2 or 3
PYVER := $(shell $(PYTHON) -c "import sys; print(sys.version_info[0])")
ROOT_PATH := $(shell pwd)

PYINC := $(shell $(PYCONFIG) --includes)
PYLIB := $(shell $(PYCONFIG) --ldflags) -L$(shell $(PYCONFIG) --prefix)/lib

BUILD_DIR = build/lib.$(PYVER)

.PHONY: build check py3 clean

ifeq (2,$(PYVER))

build:
	$(PYTHON) setup.py build --build-lib $(BUILD_DIR)

check: build tests/pyrun2
	PYTHONPATH=`pwd`/$(BUILD_DIR):$$PYTHONPATH \
	ROOT_PATH=$(ROOT_PATH) \
	$(PYTHON) `which nosetests` -v -s -w tests

tests/pyrun2: tests/pyrun.c
	$(CC) $(PYINC) -o $@ $< $(PYLIB)

else

build: py3
	$(PYTHON) py3/setup.py build --build-lib $(BUILD_DIR)

check: build tests/pyrun3
	PYTHONPATH=$(BUILD_DIR):$$PYTHONPATH \
	ROOT_PATH=$(ROOT_PATH) \
	$(PYTHON) py3/tests/setproctitle_test.py -v

py3:
	$(MKDIR) py3
	$(MKDIR) py3/src
	$(MKDIR) py3/tests
	for f in *.rst setup.py COPYRIGHT MANIFEST.in src/*.c src/*.h tests/*.py tests/*.c; do cp -v $$f py3/$$f; done
	# setup.py should be executable with python3 as distribute
	# currenlty doesn't seem to try to convert it
	$(PY2TO3) -w --no-diffs py3/tests

tests/pyrun3: tests/pyrun.c
	$(CC) $(PYINC) -o $@ $< $(PYLIB)

endif

sdist:
	$(PYTHON) setup.py sdist --formats=gztar,zip

clean:
	$(RM) -r py3 build dist tests/pyrun2 tests/pyrun3 setproctitle.egg-info
