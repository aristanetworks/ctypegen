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
from ctypes import CDLL, POINTER, byref
import sys
from CTypeGen import generateAll
import CMock
import libCTypeGen

if len( sys.argv ) >= 2:
   sanitylib = sys.argv[ 1 ]
else:
   sanitylib = "./libGreedyTest.so"

warnCount = 0
warnings = []

module, generator = generateAll( sanitylib, "GreedyTest.py", skipTypes=[ "__unknown__" ] )

dll = CDLL( sanitylib )
module.decorateFunctions( dll )

f = dll.create_f( 42 )
assert isinstance( f, POINTER( module.f ) )
assert f[ 0 ].input == 42
assert f[ 0 ].inputx2 == 42 * 2
assert isinstance( f[ 0 ].g, POINTER( module.g ) )
assert f[ 0 ].g[ 0 ].inputx3 == 42 * 3
assert f[ 0 ].g[ 0 ].inputx4 == 42 * 4
assert module.Globals( dll ).global42.value == 42

# Check that our two packed structures are properly detected as being packed.

# We are testing for the _pack_ field directly, so pylint: disable=protected-access
assert module.PackedStructWithEndPadding._pack_ == 1
assert module.PackedStructWithInternalPadding._pack_ == 1
# pylint: enable=protected-access

# ... and that one of our non-packed structures has no "pack" flag.
assert not hasattr( module.g, "_pack_" )

classWithMethods = module.LookInside_cn_cn_ClassWithMethods()
classWithMethods.field1 = 42
classWithMethods.field2 = 24
func = CMock.mangleFunc( dll, "LookInside::ClassWithMethods::returnsPassedArgument" )
assert func.argtypes is not None
res = func( byref( classWithMethods ), 100 )
assert res == 100

func = CMock.mangleFunc( dll,
      "LookInside::ClassWithMethods::addField1AndField2ToArgument" )
assert func.argtypes is not None
res = func( byref( classWithMethods ), 100 )
assert res == 100 + 24 + 42

debug = libCTypeGen.open( sanitylib )

die = None

def findDIE( d, name ):
   if d.name() == name:
      return d
   for c in d:
      found = findDIE( c, name )
      if found:
         return found
   return None

u = None
for u in debug.units():
   die = findDIE( u.root(), "returnsPassedArgument" )
   if die:
      break
assert die is not None
die = die.parent()
assert die.name() == "ClassWithMethods"
die = die.parent()
assert die.name() == "LookInside"
die = die.parent()
assert die.tag() == libCTypeGen.tags.DW_TAG_compile_unit
shouldBeNone = die.parent()
assert shouldBeNone is None

# die.unit() should compare equal to u, but is not the same instance.
assert u == die.unit()
assert u is not die.unit()
