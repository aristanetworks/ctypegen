#!/usr/bin/env python3
# Copyright 2023 Arista Networks.
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
This test checks that mocking objects that are called via relocations in the
text segment rather than the GOT are handled.

The "TextRelocs" shared lib is built without -fPIC, and will have text
relocations to deal with the call from entryPoint to doubleIt in
test/textRelocs.c.  After verifying the text relocations are present, we mock
doubleIt here and ensure the result is not doubled, but halved, as per our mock
function
'''
from __future__ import absolute_import, division, print_function
import CMock
import subprocess
from ctypes import CDLL, c_int
import sys

LIBRARY = TextRelocs if len(sys.argv) <= 1 else sys.argv[1]

nonPicLib = CDLL( LIBRARY )
proc = subprocess.Popen( ("readelf -W --dynamic ./%s" % LIBRARY).split( " " ),
      stdout=subprocess.PIPE, universal_newlines=True )

out, err = proc.communicate()
assert "(TEXTREL)" in out # make sure we actually have a text relocation
print("have textrel in %s" % LIBRARY)

nonPicLib.doubleIt.argtypes = [ c_int ]
nonPicLib.entryPoint.argtypes = [ c_int ]

with CMock.mocked( nonPicLib.doubleIt, lambda value: value // 2 ):
   value = nonPicLib.entryPoint( 42 )
   assert value == 21
print("GOT mock worked")
