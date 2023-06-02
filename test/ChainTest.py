#!/usr/bin/env python3
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
'''
This test ensures that calling "realfunc" from the mock works.
We call "callme" from our test library, and it should call "mockme" with the
same args passed to callme, and return the result.
The "real" mockme returns the first arg passed to it.
'''

import CTypeGen
import CMock
import ctypes
import sys

libname = sys.argv[ 1 ] if len( sys.argv ) > 2 else "./libChainTest.so"
module, res = CTypeGen.generate( libname, "chaintest.py",
                                 [], [ "mockme", "callme" ] )

lib = ctypes.CDLL( libname )
module.decorateFunctions( lib )

@CMock.Mock( lib.mockme, lib, method=CMock.GOT )
def mocked( one, two, three ):
   print( "I mock you: %d %d %d" % ( one, two, three ) )
   rc = mocked.realfunc( three, two, one )
   assert rc == three
   return two

callme_res = lib.callme( 1, 2, 3 )
assert callme_res == 2
