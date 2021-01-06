#!/usr/bin/env python
# Copyright (c) 2020 Arista Networks, Inc.  All rights reserved.
# Arista Networks, Inc. Confidential and Proprietary.

from __future__ import absolute_import, division, print_function
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
