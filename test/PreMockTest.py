#!/usr/bin/env python
# Copyright 2019 Arista Networks.
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
from __future__ import absolute_import, division, print_function

import sys
from ctypes import CDLL
from CTypeGen import generate
import CMock

if len( sys.argv ) >= 2:
   mocklib = sys.argv[ 1 ]
else:
   mocklib = "libPreMockTest.so"

# Generate type info for "preF", and "preEntry" so we can call them.
module, resolver = generate( mocklib, "premock.py", [],
        [ "preEntry", "preF", "preRecurse", "preRecurseEntry" ] )

# Load the DLL, and decorate the functions with their prototypes.
lib = CDLL( mocklib )
module.decorateFunctions( lib )

# Test our pre-style mocks work. These will be called before the
# original C function, and control will then pass to the original
# function
# We create a mock function that sets a global python variable,
# and modifies an argument to the original.
# The real C function asserts the value is that received from
# The python mock function, and the python code checks the global
# was set.

preCalled = 0

@CMock.Mock( lib.preF, method=CMock.PRE )
def mockedPre( ival, sval, ipval ):
   assert ipval[ 0 ] == 22
   ipval[ 0 ] = 42
   print( "mock pre-call: received ival of 22 replaced with 42" )
   global preCalled
   preCalled += 1

lib.preEntry()
assert preCalled == 1

# There was a bug where the second and successive calls to the function would
# not always be mocked: the first call would actually invoke the dynamic
# linker, which would overwrite our thunk in the GOT with the resolved
# function. Test that bug is fixed.
lib.preEntry()
assert preCalled == 2

# Prove recursive calls work

# The fix for the issue with the dynamic linker overwriting us works by fixing
# up the GOT after the first call of the function finishes. This is unfortunate
# for recursive functions, because the first call doesn't finish before the
# second starts, so make sure to populate the GOT entry properly before testing
# recursion.
lib.preRecurseEntry( 1 )

# x86-64 has 72-byte "stack frames" in the thunk for the moment, and the TOS
# is at index 1019 in the 8kbyte thunk. The second page of the thunk is usable,
# so we have (1019 * 8 - 4096) / 72 = 56.3
recursionDepth = 56

@CMock.Mock( lib.preRecurse, method=CMock.PRE )
def mockedRecurse( ival ):
   global recursionDepth
   sys.stdout.write( "%d, " % ival )
   assert recursionDepth == ival
   recursionDepth -= 1

sys.stdout.write( "recursion depth: " )
lib.preRecurseEntry( recursionDepth )
print( "done" )
assert recursionDepth == 0
