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
from __future__ import absolute_import, division, print_function

import sys
import ctypes
from CTypeGen import generate
import CMock
import gc

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
# We use RTLD_GLOBAL so the mocking framework does not need to be passed the
# handle to the dlopen'd library to find the symbol for the named function
lib = ctypes.CDLL( mocklib, ctypes.RTLD_GLOBAL )
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

print( "Check that disabling an already disabled context manager does not"
      "interfere with another." )
one = CMock.mocked( lib.f, pythonF )
two = CMock.mocked( lib.f, pythonF )
with two:
   one.disable()
   checkMocked()

print( "Check context manager in a loop with GC" )
for gcIters in range(4):
   with CMock.mocked( lib.f, pythonF ) as mock:
      # Invoke gc every second iteration - this tests that the garbage
      # collection of a context manager created in a previous iteration of the
      # loop does not interfere with the current context manager. (This is a
      # special case of test above where we don't want an "old" mock to
      # interfere with a live one when it's garbage collected)
      if gcIters % 2 == 1:
         gc.collect()
      checkMocked()
      mock.disable()
      checkNotMocked()
      mock.enable()
      checkMocked()
   checkNotMocked()

print( "check mocked member function" )
# Uses the same logic as mockedF above - make sure we can call instance methods
# as if they were C functions.

class MockObject( object ):
   def method( self, ival, sval, ipval ):
      self.callcount += 1
      if self.actuallyMock:
         ipval[ 0 ] = 101
         return 100
      else:
         return self.mock.realfunc( ival, sval, ipval )

   def __init__( self ):
      self.actuallyMock = False
      self.callcount = 0
      self.mock = CMock.mocked( lib.f, self.method )
      checkNotMocked() # it's not enabled.
      self.mock.enable()
      checkNotMocked() # it's enabled, but the mock function will check behaviour
      self.actuallyMock = True
      checkMocked() # It's enabled, and should do its work
      self.mock.disable()
      checkNotMocked() # it's disabled again.
      assert self.callcount == 2

MockObject()

print( "checking we can re-enable the mock" )
mockedF.enable()
checkMocked()

# Test STOMP mocks - mock out "g" called by "entry_g". The real g return 42,
# the mocked one returns 99, and entry_g asserts g returns whatever is psased
# to entry_g

print( "checking STOMP mock" )

@CMock.Mock( lib.g, method=CMock.STOMP )
def mockedG( i, s ):
   print( "this is the mocked g %d/%s" % ( i, s ) )
   assert( s == b"forty-two" and i == 42 )
   return 99

lib.entry_g( 99 )
mockedG.disable()
lib.entry_g( 42 )

print( "check calls to C++ functions via name demangling" )
function = CMock.mangleFunc( lib, "A::Cpp::Namespace::withAFunction",
      ctypes.c_int, [ ctypes.c_int, ctypes.c_int ] )
called = 0

@CMock.Mock( function )
def mockedIt( a, b ):
   global called
   called += 1
   assert a == 42 and b == 42
   return a + b

rc = lib.callCpp( 42, 42 )
assert called == 1
assert rc == 42 + 42 # Mock function returns sum of arguments.
mockedIt.disable()
rc = lib.callCpp( 42, 42 )
assert rc == 42 * 42 # Real function returns product of arguments.

print( "Tests complete" )
