#!/usr/bin/env python3
# Copyright 2020 Arista Networks.
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
import CMock.helpers
import ctypes
import sys

#  Get our libFOpenTest library with the fopen_test function to call
if len( sys.argv ) >= 2:
   mocklib = sys.argv[ 1 ]
else:
   mocklib = "libFOpenTest.so"

# Generate type info for "fopen_test"
module, resolver = generate( mocklib,
                             "ptrgen.py",
                             [],
                             [ "fopen_test", ] )

dll = ctypes.CDLL( mocklib )
module.decorateFunctions( dll )

# We'll mock fopen/fopen64 from libc.
libc, _ = CMock.helpers.getLibc()
openFiles = []

# redirect all fopen and fopen64 calls to open /dev/zero
def impl( name, mode, func ):
   global openFiles
   openFiles.append( name )
   return func( b"/dev/zero", mode )

# Mock both fopen64 and fopen
@CMock.Mock( libc.fopen, method=CMock.GOT )
def fopen( name, mode ):
   return impl( name, mode, fopen.realfunc )

@CMock.Mock( libc.fopen64, method=CMock.GOT )
def fopen64( name, mode ):
   return impl( name, mode, fopen64.realfunc )

# Verify that if we open /dev/null, the open gets redirected to /dev/zero,
# and we read 100 bytes of nul chars, rather than no bytes (as we would
# from /dev/null)
dll.fopen_test( b"/dev/null", b"\0" * 100, 100 )
