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
PYTHON ?= $(shell which python3) # default to whatever interpreter is installed there.
PYTHONPATH ?= $(wildcard ../build/*lib*):..
.PHONY: all check clean check-pre-mock check-mock check-ctypesanity

CXXFLAGS += -g3 -fPIC
CFLAGS += -g3 -fPIC


%-plt.o: %.cpp
	$(CXX) -c -o $@ -fplt $(CXXFLAGS) $^

%-noplt.o: %.cpp
	$(CXX) -c -o $@ -fno-plt $(CXXFLAGS) $^

all: check
CTypeSanity: CTypeSanityC.o CTypeSanity.o
	$(CXX) -shared -o $@ $^

libMockTest-plt.so: MockTest-plt.o MockTestExtern-plt.o
	$(CXX) -shared -o $@ $^
libMockTest-noplt.so: MockTest-noplt.o MockTestExtern-noplt.o
	$(CXX) -shared -o $@ $^

libBitfieldTorture.so: BitfieldTorture.c
	$(CXX) -shared -o $@ $^

libPreMockTest.so: PreMockTest.o PreMockTestExtern.o
	$(CXX) -shared -o $@ $^

libChainTest.so: ChainTest.o ChainTestExtern.o
	$(CXX) -shared -o $@ $^

libFOpenTest.so: FOpenTest.o
	$(CXX) -shared -o $@ $^

libGreedyTest.so: GreedyTest.o GreedyTestCpp.o
	$(CXX) -shared -o $@ $^

libSupply.so: Supply.o
	$(CXX) -shared -o $@ $^

libDemand.so: Demand.o
	$(CXX) -shared -o $@ $^

EnumTest.o: CXXFLAGS=-fshort-enums -fPIC -g
libEnumTest.so: EnumTest.o
	$(CXX) -shared -o $@ $^

check-bins: CTypeSanity libMockTest-plt.so libMockTest-noplt.so \
			libPreMockTest.so libChainTest.so libFOpenTest.so \
			libGreedyTest.so libEnumTest.so libSupply.so libDemand.so \
			libBitfieldTorture.so

check-ctypesanity: check-bins
	$(PYTHON) ./CTypeGenSanity.py ./CTypeSanity

check-mock: check-bins
	$(PYTHON) ./MockTest.py ./libMockTest-noplt.so ./libMockTest-plt.so

check-pre-mock: check-bins
	$(PYTHON) ./PreMockTest.py ./libPreMockTest.so

check-chain: check-bins
	$(PYTHON) ./ChainTest.py ./libChainTest.so

check-greedy: check-bins
	$(PYTHON) ./GreedyTestGen.py ./libGreedyTest.so

check-enum: check-bins
	$(PYTHON) ./EnumTest.py ./libEnumTest.so

check-pointers: check-bins
	$(PYTHON) ./PointersTest.py ./libFOpenTest.so

check-supplydemand: check-bins
	$(PYTHON) ./SupplyDemandGen.py

check-bitfield: check-bins
	$(PYTHON) ./BitfieldTortureGen.py

check: check-mock check-pre-mock check-ctypesanity check-chain  check-pointers \
	check-greedy check-enum check-supplydemand check-bitfield

# i386-only test.
ifeq ($(shell uname -p),i686)
textRelocs.o: CFLAGS=-g3 -m32
libTextRelocs.so: textRelocs.o
	$(CXX) -m32 -shared -o $@ $^
check-textRelocs: libTextRelocs.so
	$(PYTHON) ./TextRelocTest.py ./libTextRelocs.so
check: check-textRelocs
endif

clean:
	rm -f *.o CTypeSanity CTypeSanity.py *.pyc MockTest proggen.py premock.py \
		*.so BitfieldTorture.py chaintest.py Demand.py EnumGenerated.py \
		GreedyTest.py ptrgen.py Supply.py

