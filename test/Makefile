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
#
PYTHON ?= python2
.PHONY: all check clean

CXXFLAGS += -g -fPIC
CFLAGS += -g -fPIC

all: check
CTypeSanity: CTypeSanityC.o CTypeSanity.o
	$(CXX) -shared -o $@ $^

MockTest: MockTest.o
	$(CXX) -shared -o $@ $^

check: CTypeSanity MockTest
	$(PYTHON) ./CTypeGenSanity.py ./CTypeSanity
	$(PYTHON) ./MockTest.py ./MockTest

clean:
	rm -f *.o CTypeSanity CTypeSanity.py *.pyc MockTest proggen.py
