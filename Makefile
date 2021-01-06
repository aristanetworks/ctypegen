# Copyright 2018 Arista Networks.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.

.PHONY: all test install clean build-all

PYTHON ?= $(shell which python) # default to whatever interpreter is installed there.
PYTHONPATH = $(PWD):$(wildcard $(PWD)/build/lib*)

all: build-all CMock/libc.py

build-all:
	env CFLAGS="-g --std=c++14" PYTHONPATH=$(PWD) $(PYTHON) ./setup.py build
install:
	env CFLAGS="-g --std=c++14" PYTHONPATH=$(PWD) $(PYTHON) ./setup.py install
test:
	PYTHONPATH=$(PYTHONPATH) make -C test

dbghelper.o: CFLAGS=-O0 -g -fPIC
libdbghelper.so: dbghelper.o
	$(CC) -g --shared -o $@ $^

# Generate helpers for libc.
# Try and force PYTHONPATH to load the just-built version of the C extensions.
CMock/libc.py: libdbghelper.so
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) ./generateLibc.py libc.so.6 $@

clean:
	rm -rf build __pycache__ core libc.py libdbghelper.so *.o
	make -C test clean
