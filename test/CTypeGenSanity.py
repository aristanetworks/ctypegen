#!/usr/bin/env python
# Copyright 2017 Arista Networks.
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
from ctypes import c_char, CDLL, c_void_p, c_long, c_int, cast, sizeof
from ctypes import POINTER, c_char_p, c_ulong
import sys

from CTypeGen import generate, PythonType, generateOrThrow

if len(sys.argv) >= 2:
   sanitylib = sys.argv[1]
else:
   sanitylib = ".libs/libCTypeSanity.so"

types = [
      PythonType( u"Foo" )
         .field( u"anEnum", typename=u"TheEnum" )
         .field( u"anonymousStructField", typename=u"AnonymousStructType" )
         .field( u"anArrayField", typename=u"ArrayFieldType" ),
      PythonType( "NoSuchType" ), # make sure we get a warning for notype.
      PythonType( u"BigNum" ),
      PythonType( u"AnonEnumWithTypedef" ),
      PythonType( u"NamespacedLeaf", "Outer::Inner::Leaf" ),
      PythonType( u"GlobalLeaf", "Leaf" ),
      PythonType( u"NameSharedWithStructAndTypedef" ),
]

functions = [
      "make_foo",
      "print_foo",
      "void_return_func",
      "nosuch_func", # make sure we get a warning for the non-existent function
      "test_qualifiers", # make sure restrict, volatile, etc, work
]

globalVars = [
       "ExternalStrings",
       "ExternalStruct",
       "NoSuchGlobal",
       "nameSharedWithStructAndTypedef",
]

warnCount = 0
warnings = []

def clearWarnings():
   global warnCount
   global warnings
   warnCount = 0
   warnings = []

def testwarning( txt ):
   global warnCount
   print( "warning: %s" % txt )
   warnCount += 1
   warnings.append( txt )

# test some common error cases:
# Test non-existent file
module, generator = generate(
      "/nosuchfile",
      "CTypeSanity.py",
      types,
      functions,
      errorfunc=testwarning,
      globalVars=globalVars )

assert warnCount == 1
assert "No such file" in warnings[ 0 ]
clearWarnings()

# Test filename not a string.
module, generator = generate(
      42,
      "CTypeSanity.py",
      types,
      functions,
      errorfunc=testwarning,
      globalVars=globalVars )

assert warnCount == 1
assert "requires a list of ELF images" in warnings[ 0 ]
clearWarnings()

# Test file is not an ELF image
module, generator = generate(
      "Makefile",
      "CTypeSanity.py",
      types,
      functions,
      errorfunc=testwarning,
      globalVars=globalVars )

assert warnCount == 1
assert "not an ELF" in warnings[ 0 ]
clearWarnings()

# Now actually generate the module, complete with warnings
module, generator = generateOrThrow(
      [ sanitylib ],
      "CTypeSanity.py",
      types,
      functions,
      errorfunc=testwarning,
      globalVars=globalVars )
assert warnCount == 3
for warning in warnings:
   assert "nosuch" in warning.lower() # expect three warnings about missing things
clearWarnings()

dll = CDLL( sanitylib )
module.decorateFunctions( dll )
theCTypes = dll.make_foo()

s = ( c_char * 1024 )()
dll.print_foo( theCTypes, s, 1024 )
theMap = eval( s.value ) # We generate the text, so safe to pylint: disable=eval-used

def compareObjects( indent, asMap, asCtypes ):
   for k, v in asMap.items():
      cval = asCtypes.__getattribute__( k )
      if hasattr( cval, "value" ):
         cval = cval.value
      print ( "%scompare %s: %s/%s" % ( ' ' * indent, k, v, cval ) )
      if isinstance( v, dict ):
         compareObjects( indent + 4, v, cval )
      elif isinstance( v, float ):
         assert abs( v - cval ) < 0.005
      elif isinstance( cval, bytes ):
         try:
            assert str( cval, 'utf-8' ) == v # python 3
         except TypeError:
            assert cval == v # python 2
      else:
         assert cval == v or cast( cval, c_void_p ).value == v

compareObjects( 0, theMap, theCTypes.contents )

print("Make sure calling the function pointer works correctly.")
bytwo = theCTypes.contents.aFuncPtr( 4 )
assert bytwo == 8
assert module.TheEnum.One == 1
assert module.TheEnum.Two == 2

print("Make sure 64-bit values are generated properly.")
assert theCTypes.contents.bigEnum.value == module.BigNum.Big

# We should be able to create some structures that are declared within
# existing structures, or C++ namespaces.
module.Foo_cn_cn_InANamespace()
module.AProperCplusplusNamespace_cn_cn_AStructureInTheCplusplusNamespace()

assert module.AnonEnumWithTypedef.AETD_1 == 0
assert module.AnonEnumWithTypedef.AETD_2 == 1

# Test global variable access
glob = module.Globals( dll )
assert glob.ExternalStrings[ 3 ] == b"three"
assert glob.ExternalStruct.x == 42

# Two dimensional array sizes: the python declaration here lists the dimensions
# non-obviously reversed wrt the C one
array = module.Foo().aTwoDimensionalArrayOfLong

assert sizeof( array[ 0 ] ) == 13 * sizeof( c_long ) # minor axis - 13 elements
assert sizeof( array ) == 17 * sizeof( array[ 0 ] ) # major axis - 17 elements

print ("Verify we can specify and disambiguate namespaced and unnamespaced types")
globl = module.GlobalLeaf()
namespaced = module.NamespacedLeaf()
globl.atGlobalScope = 1
namespaced.inNamespace = 3


print("Verify CFUNCTYPE generation")
assert set( module.functionTypes ) == { "make_foo",
                                        "print_foo",
                                        "void_return_func",
                                        "test_qualifiers" }

# pylint: disable=protected-access
methodType = module.functionTypes[ "make_foo" ]
assert methodType.__class__.__name__ == "PyCFuncPtrType"
assert methodType._restype_ == POINTER( module.Foo )
assert methodType._argtypes_ == ()

methodType = module.functionTypes[ "print_foo" ]
assert methodType.__class__.__name__ == "PyCFuncPtrType"
assert methodType._restype_ == c_int
assert methodType._argtypes_ == ( POINTER( module.Foo ),
                                  c_char_p,
                                  c_ulong )

methodType = module.functionTypes[ "void_return_func" ]
assert methodType.__class__.__name__ == "PyCFuncPtrType"
assert methodType._restype_ is None
assert methodType._argtypes_ == ()
