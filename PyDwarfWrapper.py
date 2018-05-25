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

import libCTypeGen

dwarfattr = libCTypeGen.attrs

_unitCount = 0

class Unit( object ):
   def __init__( self, top ):
      global _unitCount
      self.top = top
      self.unitId = _unitCount
      _unitCount = _unitCount + 1

   def getTopDIE( self ):
      return WrappedDIE( self, self.top )

class DwarfHandle( object ):
   def __init__( self, dwarf ):
      self.dwarf = dwarf
      self.units = []
      for u in self.dwarf.units():
         self.units.append( Unit( u ) )

   def enumerateDIEs( self, wrappedDie, func ):
      self.enumerateUnwrappedDIEs( wrappedDie.unit, wrappedDie.die, func )

   def enumerateUnwrappedDIEs( self, unit, die, func ):
      if func( self, WrappedDIE( unit, die ) ):
         for child in die:
            self.enumerateUnwrappedDIEs( unit, child, func )

   def getUnits( self ):
      return self.units

def getDwarfHandle( filename ):
   return DwarfHandle( libCTypeGen.open( filename ) )

class WrappedDIE( object ):
   def __init__( self, unit, die ):
      self.die = die
      self.unit = unit

   def name( self ):
      return self[ dwarfattr.DW_AT_name ]

   def tag( self ):
      return self.die.tag()

   def __getitem__( self, attr ):
      return self.die.getattr( attr )

   def getBaseType( self ):
      base = self[ dwarfattr.DW_AT_type ]
      if not base:
         return None
      return WrappedDIE( self.unit, base )

   def iter_children( self ):
      return [ WrappedDIE( self.unit, x ) for x in self.die ]

   def key( self ):
      return str( self.unit.unitId ) + "_" + str( self.die.offset() )
