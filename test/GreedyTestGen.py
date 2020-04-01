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
from __future__ import print_function
from ctypes import CDLL, POINTER
import sys
from CTypeGen import generate

if len( sys.argv ) >= 2:
   sanitylib = sys.argv[ 1 ]
else:
   sanitylib = "./libGreedyTest.so"

warnCount = 0
warnings = []

module, generator = generate(
      sanitylib,
      "GreedyTest.py",
      types=lambda name, space, die: True,
      functions=lambda name, space, die: True,
      globalVars=lambda name, space, die: True )

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
