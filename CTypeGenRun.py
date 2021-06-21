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

from __future__ import absolute_import, division, print_function

# We need to look inside ctypes a bit, so do this globally:
# pylint: disable=protected-access
import ctypes

class TestableCtypeClass( object ):
   pass

def CONST( t ):
   return t

def VOLATILE( t ):
   return t

def RESTRICT( t ):
   return t

hasPointersMemo = {}

def hasPointers( t ):
   if t in hasPointersMemo:
      return hasPointersMemo[ t ]

   rv = False
   if isinstance( t, ctypes._Pointer.__class__ ) or t == ctypes.c_void_p:
      # The type is actually a pointer.
      rv = True
   elif hasattr( t, "_fields_" ):
      # note the _fields_ tuple may have 3 values for a bitfield, so we need to
      # unpack it explicitly
      for fieldinfo in t._fields_:
         ftype = fieldinfo[ 1 ]
         if hasPointers( ftype ):
            rv = True
            break

   hasPointersMemo[ t ] = rv
   return rv

errors = []

def addError( text ):
   errors.append( text )

def checkUnalignedPtrs( t ):

   if not hasattr( t, "_fields_" ):
      return # no fields = no alignment problems

   if hasattr( t, "allow_unaligned" ):
      allowed = t.allow_unaligned
   else:
      allowed = []

   for fieldinfo in t._fields_: # note this tuple may have 3 values for a bitfield
      fname, ftype = fieldinfo[ 0 ], fieldinfo[ 1 ]
      alignment = ctypes.alignment( ftype )
      if alignment == 0:
         continue
      field = getattr( t, fname )
      if field.offset % alignment == 0:
         # This field is a aligned
         continue

      if not hasPointers( ftype ):
         # We'll allow unaligned things that aren't pointers
         continue

      # misaligned field that is a/has pointers. This trips up valgrind.
      if fname not in allowed:
         addError( "unaligned ptr field %s in %s: offset=%d [%d]" % (
                     fname, t.__name__, field.offset,
                     field.offset % alignment ) )

def checkSize( cls ):
   ''' If we've defined the class fully, ensure python and DWARF agree on
   the size '''

   if not hasattr( cls, "_ctypegen_have_definition" ):
      return
   if ctypes.sizeof( cls ) == cls._ctypegen_native_size:
      # DWARF and python agree on size.
      return
   if ctypes.sizeof( cls ) == 0 and cls._ctypegen_native_size == 1:
      # empty C++ classes are size 1. We can let this discrepancy slide.
      return
   addError( "type %s has wrong size. expected %d, got %d" % (
               cls.__name__, cls._ctypegen_native_size, ctypes.sizeof( cls ) ) )

def checkOffsets( cls ):
   ''' if we have _fields_ and offsets defined for the class, make sure they
   agree with the dwarf definitions. '''
   if not hasattr( cls, "_fields_" ) or not hasattr( cls, "_ctypegen_offsets" ):
      return

   # pylint: disable=protected-access
   for field, offset in zip( cls._fields_, cls._ctypegen_offsets ):
      if offset is not None:
         ctypesOffset = getattr( cls, field[ 0 ] ).offset
         if ctypesOffset != offset and offset != -1:
            addError( "field %s of %s has offset %d, should be %d" %
                        ( field[ 0 ], str( cls ), ctypesOffset, offset ) )

def test_class( cls ):
   checkOffsets( cls )
   checkSize( cls )
   checkUnalignedPtrs( cls )

def test_classes():
   # pylint: disable=no-member
   for cls in TestableCtypeClass.__subclasses__():
      test_class( cls )
   if errors:
      raise Exception( "\n".join( errors ) )
