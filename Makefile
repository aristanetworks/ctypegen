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

.PHONY: all check test install clean build-all

PYTHON ?= $(shell which python3) # default to where we find python3

PYTHONPATH = $(PWD):`echo $(PWD)/build/lib*`

all: build-all CMock/libc.py
	echo "Built for $(PYTHON)"

build-all: build-pstack
	env CFLAGS="-g --std=c++20" PYTHONPATH=$(PWD) $(PYTHON) ./setup.py build

install:
	env CFLAGS="-g --std=c++20" PYTHONPATH=$(PWD) $(PYTHON) ./setup.py install

check: test
test:
	PYTHONPATH=$(PYTHONPATH) make -C test
	echo "Tested for $(PYTHON)"

dbghelper.o: CFLAGS=-O0 -g -fPIC -fno-eliminate-unused-debug-types -g3
libdbghelper.so: dbghelper.o
	$(CC) -g --shared -o $@ $^

# Generate helpers for libc.
# Try and force PYTHONPATH to load the just-built version of the C extensions.
CMock/libc.py: libdbghelper.so build-all
	-PYTHONPATH=$(PYTHONPATH) $(PYTHON) ./generateLibc.py libc.so.6 $@ || echo '(Ignore Exception above)'

clean:
	rm -rf build __pycache__ core CMock/libc.py libdbghelper.so *.o
	rm -f CMock/libc.py 
	make -C test clean

build-pstack:
	cd pstack && cmake -DLIBTYPE=STATIC -DCMAKE_BUILD_TYPE=RelWithDebInfo -DCMAKE_INSTALL_PREFIX=/usr/local && make && make check
