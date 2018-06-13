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
from CTypeGen import generate
import CMock
import sys
from ctypes import CDLL

if len(sys.argv) >= 2:
   mocklib = sys.argv[1]
else:
   mocklib = ".libs/libMockTest.so"

# Generate type info for "f", and "entry" so we can call them.
module, resolver = generate( mocklib, "proggen.py", [], [ "f", "entry" ] )

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

# provide a mock our function lib.f in lib.
@CMock.Mock( lib.f, lib, method=CMock.GOT )
def mockedF( i, s, iptr ):
   print( "mocked function! got args: i(%s)=%d, s(%s)=%s, iptr(%s)=%s" %
           ( type( i ), i, type( s ), s, type( iptr ), iptr[ 0 ] ) )
   iptr[ 0 ] = 101
   return 100

print( "checking the mocked behaviour works on installation" )
checkMocked()

print( "checking we can disable the mock" )
mockedF.disable()
checkNotMocked()

print( "checking we can re-enable the mock" )
mockedF.enable()
checkMocked()
