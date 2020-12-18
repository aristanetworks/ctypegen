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

.PHONY: all test install clean

PYTHON ?= $(shell which python) # default to whatever interpreter is installed there.

all: build CMock/libc.py

build:
	env CFLAGS="-g --std=c++14" PYTHONPATH=$(PWD) $(PYTHON) ./setup.py build
install:
	env CFLAGS="-g --std=c++14" PYTHONPATH=$(PWD) $(PYTHON) ./setup.py install
test:
	env PYTHONPATH=$(PWD) make -C test

dbghelper.o: CFLAGS=-O0 -g -fPIC
libdbghelper.so: dbghelper.o
	$(CC) -g --shared -o $@ $^


# Generate helpers for libc.
CMock/libc.py: libdbghelper.so
	env PYTHONPATH=$$PWD $(PYTHON) ./generateLibc.py /lib64/libc.so.6 $@ || \
		echo "you can probably ignore errors above from generateLibc.py"
clean:
	rm -rf build __pycache__ core libc.py libdbghelper.so *.o
	make -C test clean
