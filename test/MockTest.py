#!/usr/bin/env python
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
from __future__ import print_function

import sys
from ctypes import CDLL
from CTypeGen import generate
import CMock

if len( sys.argv ) >= 2:
   mocklib = sys.argv[ 1 ]
else:
   mocklib = "libMockTest.so"

# Generate type info for "f", and "entry" so we can call them.
module, resolver = generate( mocklib,
                             "proggen.py",
                             [],
                             [ "f", "g", "entry", "entry_g" ] )

# Load the DLL, and decorate the functions with their prototypes.
lib = CDLL( mocklib )
module.decorateFunctions( lib )

# if f is not mocked, we expect the behaviour from the C function
def checkNotMocked():
   lib.entry( 1, 2 )

# if f is mocked, we expect the behaviour from the Python function
def checkMocked():
   lib.entry( 100, 101 )

print( "checking the C implementation does what it should before we poke around" )
checkNotMocked()

# python function used by the mock of lib.f
def pythonF( i, s, iptr ):
   print( "mocked function! got args: i(%s)=%d, s(%s)=%s, iptr(%s)=%s" %
           ( type( i ), i, type( s ), s, type( iptr ), iptr[ 0 ] ) )
   iptr[ 0 ] = 101
   return 100

# provide a mock our function lib.f in lib.
@CMock.Mock( lib.f, lib, method=CMock.GOT )
def mockedF( i, s, iptr ):
   return pythonF( i, s, iptr )

print( "checking the mocked behaviour works on installation" )
checkMocked()

print( "checking we can disable the mock" )
mockedF.disable()
checkNotMocked()

print( "check context manager" )
with CMock.mocked( lib.f, pythonF, method=CMock.GOT ) as mock:
   checkMocked()
   mock.disable()
   checkNotMocked()
   mock.enable()
   checkMocked()
checkNotMocked()

print( "checking we can re-enable the mock" )
mockedF.enable()
checkMocked()

# Test STOMP mocks - mock out "g" called by "entry_g". The real g return 42,
# the mocked one returns 99, and entry_g asserts g returns whatever is psased
# to entry_g

print( "checking STOMP mock" )
@CMock.Mock( lib.g, lib, method=CMock.STOMP )
def mockedG( i, s ):
   print( "this is the mocked g %d/%s" % ( i, s ) )
   assert( s == b"forty-two" and i == 42 )
   return 99

lib.entry_g(99)
mockedG.disable()
lib.entry_g(42)
