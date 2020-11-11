#!/usr/bin/env python
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
from __future__ import absolute_import, division, print_function

import re
import ctypes
import CTypeGen
import libCTypeGen
import sys
from libCTypeGen import tags

if len( sys.argv ) >= 2:
   mocklib = sys.argv[ 1 ]
else:
   mocklib = "libEnumTest.so"

dll = ctypes.CDLL( mocklib )

# The variables we are interested in for testFullRange below are named, eg,
# s16t, u32t, s64t Our regex puts "s" or "u" in group 1, and the bitcount (8,
# 16, 32) in group 2. We also use this to filter the global variables we want
# access to when generating the ctypes code.
regex = re.compile( r"([su])([0-9]+)t" )
module, resolver = CTypeGen.generate( "libEnumTest.so", "EnumGenerated.py",
        types=lambda name, space, die: True,
        functions=lambda name, space, die: False,
        globalVars=lambda name, space, die: regex.match( name ) )

dwarf = libCTypeGen.open( "libEnumTest.so" )
globvars = module.Globals( dll )

def testFullRange( name, match ):
   # Test that we size enum types correctly and give appropriate values for
   # extremes of the size range of the enum.
   #
   # The support library for this test, libEnumTest.so defines a structure
   # template that in turn contains an enum. That enum has start and end
   # enumerators that have the min and max values for the template type. We
   # compile this with -fshort-enums, so the compiler generates the minimum
   # sized type for the enum.
   #
   # The library instantiates this structure for a variety of sized integer
   # types, from int8_t to int32_t and unsigned equivalents.
   #
   # The test asserts that the min and max values of one of these enums is as
   # per the expected min/max value for that number of bits given a a 2's
   # compliment, and that the underlying ctypes integer type is the correct
   # size for the range.
   # interpretation.

   bits = int( match.group( 2 ) )
   signed = match.group( 1 ) == 's'
   enumeration = getattr( globvars, name ).e

   # Assert that the min/max values are what's expected for that bit length and
   # signedness, assuming two's compliment representation
   if signed:
      assert enumeration.start == -( 1 << bits - 1 )
      assert enumeration.end == ( 1 << bits - 1 ) - 1
   else:
      assert enumeration.start == 0
      assert enumeration.end == ( 1 << bits ) - 1
   assert ctypes.sizeof( type( enumeration ).__bases__[ 0 ] ) == bits // 8

def testAllBits():
   # This test checks that an enum with values for all powers of 2 from 0 to 63
   # have the correct enumerator value. This ensures we don't run into sign
   # issues with the form used to represent the value in the DIE
   us = [ u for u in dwarf.units() ]
   bitsTested = set()
   for enum in us[ 0 ].root():
      if enum.tag() == tags.DW_TAG_enumeration_type and enum.name() == "AllBits":
         for enumerator in enum:
            if enumerator.tag() == tags.DW_TAG_enumerator:
               bitsTested.add( enumerator )
               assert enumerator.DW_AT_const_value == \
                     1 << int( enumerator.name()[ 1 : ] )
         break
   assert len( bitsTested ) == 64

for var in dir( globvars ):
   m = regex.match( var )
   if m is not None:
      testFullRange( var, m )

testAllBits()
