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

# CTypeGen generates boilerplate code using python's ctype package to
# interact with C libraries. See Aid 3558, aka go/ctypegen for the gorey details.

import PyDwarfWrapper
import datetime
import io
import imp
import inspect
import libCTypeGen

attrs = libCTypeGen.attrs
tags = libCTypeGen.tags

# python3 doesn't have basestring
try:
   baseString = basestring
except NameError:
   baseString = str

# Add explicit dependency on CTypeGen runtime - we need this when we run the
# sanity check on the generated file.
# pkgdeps: import CTypeGenRun

def error( txt ):
   ''' Print message to stdout. We use this for writing errors, and allow
   it to be overridden for testing.
   '''
   print( "error: %s" % txt )

def asPythonId( s ):
   ''' convert an identifier from debug data into a valid DWARF id '''
   repls = {
         u":" : u"_cn",
         u"<" : u"_lt",
         u">" : u"_gt",
         u"(" : u"_lp",
         u")" : u"_rp",
         u"*" : u"_ptr",
         u" " : u"_sp",
         u"," : u"_comma",
         u"&" : u"_amp",
         u"[" : u"_lbrack",
         u"]" : u"_rbrack",
         }
   if s is None:
      return None
   prevWasEscaped = False
   output = io.StringIO()
   for c in s:
      if c in repls:
         output.write( repls[ c ] )
         prevWasEscaped = True
      else:
         if prevWasEscaped:
            output.write( u"_" )
         output.write( c )
         prevWasEscaped = False
   out = output.getvalue()
   output.close()
   return out

def pad( indent ):
   ''' Return a padding string with the given number of spaces - useful for
   formatting'''
   return u"".ljust( indent )

class Type( object ):
   ''' An object representing a Dwarf Type. Mostly a wrapper around a DIE. Subclassed
   for structures, unions, functions, etc'''

   def __init__( self, resolver, die ):
      self.resolver = resolver
      self.die = die
      self._name = die[ attrs.DW_AT_name ]

   def dieComment( self ):
      if self.pyName() == self.name():
         return u""
      return u"# DIE %s::%s" % ( self.die.die.scope(), self.name() )

   def pyName( self ):
      ''' Remove non-python characters from this type's name'''
      scope = self.die.die.scope()
      if scope:
         name = scope + "::" + self.name()
      else:
         name = self.name()
      return asPythonId( name )

   def declare( self, out ):
      ''' Write to out any info required to refer to this type.'''
      self.resolver.defineType( self, out )

   def define( self, out ):
      ''' Write to out any info required to instantiate this type.'''
      pass

   def baseType( self ):
      ''' Return the type that this type derives - eg, pointers and
      arrays are pointers to and arrays of their base type. Typedefs
      and consts modify their base types'''

      baseDie = self.die.getBaseType()
      if baseDie:
         return self.resolver.dieToType( baseDie )

   def size( self ):
      ''' The size of the type, as reported via DWARF '''
      return self.die[ attrs.DW_AT_byte_size ]

   def hasName( self ):
      return self._name is not None

   def name( self ):
      ''' Return the name of the structure - if there's no name in the DWARF
      info, we fabricate one based on the type descriptors offset in the DWARF. '''
      if self._name:
         res = self._name
      else:
         res = u"anon_%s" % self.die.key()

      if self.resolver.pkgname is not None:
         return u'%s.%s' % ( self.resolver.pkgname, res )
      return res

   def ctype( self ):
      ''' Return the string representing the ctype type for this type.
      for types that we've generated code for, the ctype name is the
      name of the generated python # type. (eg, struct Foo in C creates
      a class Foo in python, making Foo a valid ctype name.)
      '''
      return self.pyName()

   def writeLibUpdates( self, indent, stream ):
      raise Exception( "writeLibUpdates not supported for this type" )

class VoidType( Type ):
   ''' A type representing void '''
   def __init__( self, resolver ):
      super( VoidType, self ).__init__( resolver, None )

   def name( self ):
      return u"void"

class FunctionType( Type ):
   ''' A type representing a function as pointed to by a
   pointer-to-function. We treat such pointers differently to other
   pointers in PointerType, and avoid rendering the outer POINTER(),
   which is implied in ctypes for function types. Note this means objects of
   this type don't actually appear as fields in a structure. '''
   def __init__( self, resolver, die ):
      super( FunctionType, self ).__init__( resolver, die )

   def params( self ):
      ''' return all formal parameters to the function defined herein '''
      return [ child for child in self.die.iter_children()
            if child.tag() == tags.DW_TAG_formal_parameter ]

   def define( self, out ):
      rtype = self.baseType()
      if rtype:
         self.resolver.defineType( rtype, out )
      for child in self.params():
         self.resolver.defineType(
               self.resolver.dieToType( child.getBaseType() ), out )

   def size( self ):
      raise Exception( "functions don't have sizes : %s" % self.name() )

   def ctype( self ):
      result = io.StringIO()
      result.write( u"CFUNCTYPE( " )
      rtype = self.baseType()
      if rtype:
         result.write( rtype.ctype() )
      else:
         result.write( u"None" )

      for child in self.params():
         result.write( u", %s\n      " %
               self.resolver.dieToType( child.getBaseType() ).ctype() )
      result.write( u")" )
      return result.getvalue()

class FunctionDefType( FunctionType ):
   ''' A type representing a function declaration. We use these DIEs to
   generate the restype and argtypes fields for ctypes, so we can call
   them with type-safety. '''

   def __init__( self, resolver, die ):
      super( FunctionDefType, self ).__init__( resolver, die )

   def writeLibUpdates( self, indent, stream ):
      """Write function's prototype to stream"""
      base = self.baseType()
      if base is not None:
         stream.write( u"%slib.%s.restype = %s\n" %
               ( pad( indent ), self.name(), base.ctype() ) )
      args = []
      for child in self.params():
         baseType = self.resolver.dieToType( child.getBaseType() )
         args.append( baseType.ctype() )
      stream.write( u"%slib.%s.argtypes = " % ( pad( indent ), self.name() ) )
      if len( args ):
         sep = u"["
         for arg in args:
            stream.write( u"%s\n%s%s" % ( sep, pad( indent + 3 ), arg ) )
            sep = ","
         stream.write( u" ]\n\n" )
      else:
         stream.write( u"[]\n\n" )

class Member( object ):
   ''' A single member in a struct, union, class etc. '''
   def __init__( self, die, resolver ):
      self.die = die
      self.resolver = resolver
      self._name = None
      self.ctypeOverride = None
      self.allowUnalignedPtr = False

   def setName( self, name ):
      self._name = name

   def name( self ):
      if self._name:
         return self._name
      return self.die[ attrs.DW_AT_name ]

   def pyName( self ):
      return asPythonId( self.name() )

   def ctype( self ):
      if self.ctypeOverride != None:
         return self.ctypeOverride
      return self.type().ctype()

   def size( self ):
      return self.type().size()

   def bit_offset( self ):
      if self.ctypeOverride != None:
         return None
      return self.die.bit_offset()

   def bit_size( self ):
      if self.ctypeOverride != None:
         return None
      return self.die[ attrs.DW_AT_bit_size ]

   def isStatic( self ):
      return self.die.tag() == tags.DW_TAG_member and \
            self.die[ attrs.DW_AT_member_location ] is None

   def type( self ):
      return self.resolver.dieToType( self.die.getBaseType() )

   def setCType( self, ctype ):
      self.ctypeOverride = ctype

class MemberType( Type ):
   ''' A struct, class  or union type - anything that has fields. '''
   def __init__( self, resolver, die ):
      ''' MemberTypes can accept fieldHints - these are the names of types to
      assign to known fields. If those  are found in the type, then the
      types of the named members will be renamed as appropriate. This is useful
      for anonymous structures, etc, used within struct definitions for their
      fields. '''
      super( MemberType, self ).__init__( resolver, die )
      self.members = []
      superCount = 0
      for field in self.die.iter_children():
         tag = field.tag()
         if field[ attrs.DW_AT_external ]:
            continue
         if tag == tags.DW_TAG_inheritance:
            member = Member( field, resolver )
            member.setName( u"__super__%d" % superCount )
            superCount += 1
            self.members.append( member )
         elif tag == tags.DW_TAG_member:
            member = Member( field, resolver )
            self.members.append( member )

         # Ignore things that don't contribute to the CType definition -
         # nested type definitions, class methods, etc.
         elif tag in [
               tags.DW_TAG_structure_type,
               tags.DW_TAG_class_type,
               tags.DW_TAG_union_type,
               tags.DW_TAG_typedef,
               tags.DW_TAG_enumeration_type,
               tags.DW_TAG_subprogram,
               tags.DW_TAG_template_type_param,
               tags.DW_TAG_template_value_param,
               tags.DW_TAG_const_type,
               tags.DW_TAG_imported_declaration,
               0x4107, # DW_TAG_GNU_template_parameter_pack
               ]:
            # structs/classes can include definitions of nested structs and classes.
            # Ignore these for now ( but types of fields can reference them )
            pass
         else:
            resolver.error( "unhandled field %s of type %d in %s " %
                  ( field.name(), field.tag(), self.name() ) )

   def applyHints( self, fieldHints ):
      ''' For fields with anonymous types, provide python names as hinted by caller
      '''
      for member in self.members:
         if member.name() in fieldHints:
            hint = fieldHints[ member.name() ]

            # give a name for a member's type. Useful for anon structs/unions/enums.
            if hint.typename:
               typedesc = hint.typename
               # Allow a simple string for this.
               if not isinstance( typedesc, PythonType ):
                  typedesc = PythonType( typedesc, None )
               typedesc.cName = member.type().name()
               self.resolver.addExplicitType( typedesc, member.die.getBaseType() )

            # Provide an alternative name for a field in a struct.
            if hint.name:
               member.setName( hint.name )

            # Provide a string to represent the ctype to use. This is useful
            # for working around the packing bugs with bit-fields in ctypes.
            if hint.typeOverride:
               member.setCType( hint.typeOverride )

            member.allowUnalignedPtr = hint.allowUnaligned

   def ctype_subclass( self ):
      ''' Returns the name of the ctype it represents, Struct or Union '''
      raise Exception( "no ctype_subclass available for type" )

   def declare( self, out ):
      ''' Declare a structure - we don't need to know the fields to
      declare it (think forward reference) '''

      base = self.ctype_subclass()
      user = None

      if self.name() in self.resolver.explicitTypes:
         user = self.resolver.explicitTypes[ self.name() ]
         if user.base:
            base = user.base

      out.write( u'\n' )
      # TestableCtypeClass is a mixin defined in CTypeGenRun, and
      # provides methods on the # generated class to do some consistency
      # checking. The generated code will perform these tests if run as
      # a stand-alone program.
      out.write( u'class %s( %s, TestableCtypeClass' % ( self.pyName(), base ) )
      if user and user.mixins:
         for mixin in user.mixins:
            out.write( ', %s' % mixin )
      out.write( u' ):\n' )
      if self.dieComment():
         out.write( u"   %s\n" % self.dieComment() )
      if user and user.pack:
         out.write( u"   _pack_ = 1\n" )
      else:
         out.write( u"   pass\n" )
      out.write( u'\n' )

   def define( self, out ):
      ''' Define a type: we need to render the fields now, so something else
      can include an object of this type, or access a field '''
      assert not self.die[ attrs.DW_AT_declaration ] and self.name()
      self.resolver.declareType( self, out ) # make sure we're declared first.

      # Make sure the types of all fields are defined, so we can instantiate them
      for m in self.members:
         self.resolver.defineType( m.type(), out )

      out.write( u"\n" )
      out.write( u"%s.native_size = %d\n" % ( self.pyName(), self.size() ) )
      out.write( u"%s.have_definition = True\n" % self.pyName() )

      # Indicate any fields we'll intentionally allow to have unaligned
      # pointers in them.
      unaligned = [ m.pyName() for m in self.members if m.allowUnalignedPtr ]
      if unaligned:
         out.write( u"%s.allow_unaligned = %s\n" % ( self.pyName(), unaligned ) )

      # quoting the 'p' below stops pylint gagging on this file.
      out.write( u"%s._fields_ = [ # \x70ylint: disable=protected-access\n" %
            self.pyName() )
      for member in self.members:
         if member.bit_size():
            out.write( u"   ( \"%s\", %s, %d ),\n" %
                  ( member.pyName(), member.ctype(), member.bit_size() ) )
         else:
            out.write( u"   ( \"%s\", %s ),\n" % ( member.name(), member.ctype() ) )
      out.write( u"]\n\n" )

class StructType( MemberType ):
   ''' A member type for a structure (or class) '''
   def __init__( self, resolver, die ):
      super( StructType, self ).__init__( resolver, die )

   def ctype_subclass( self ):
      return u"Structure"

   def define( self, out ):
      super( StructType, self ).define( out )
      out.write( u"%s.offsets = [ " % self.pyName() )
      sep = u""

      memberCount = 0
      lastOffset = -1
      for member in self.members:
         memberOffset = member.die[ attrs.DW_AT_data_member_location ]
         # All members of a bitfield have the same member offset, and report
         # their size as the byte size of the whole object.
         # If we've overridden the type on a member, we assume the user
         # knows what they are doing, and will ensure that the succeeding
         # members are correct, and the full object size matches too.

         if memberOffset != lastOffset and member.ctypeOverride is None:
            offset = memberOffset
            lastOffset = offset
         else:
            offset = None
         out.write( u"%s%s" % ( sep, offset ) )
         memberCount += 1
         sep = u", " if memberCount % 10 != 0 else u",\n    "
      out.write( u" ]\n\n" )

class UnionType( MemberType ):
   ''' Member type for a union '''
   def __init__( self, resolver, die ):
      super( UnionType, self ).__init__( resolver, die )

   def ctype_subclass( self ):
      return u"Union"

class EnumType( Type ):
   def __init__( self, resolver, die ):
      super( EnumType, self ).__init__( resolver, die )

   def define( self, out ):
      indent = ''
      explicit_def = self.resolver.explicitTypes.get( self.pyName() )
      nameless = explicit_def and explicit_def.nameless_enum

      if not nameless:
         out.write( u"class %s( %s ):\n" % ( self.pyName(), self.intType() ) )
         indent = u'\t'
      else:
         out.write( u'# Values of %s (nameless enum)\n' % self.pyName() )

      for child in self.die.iter_children():
         if self.dieComment():
            out.write( u"%s%s\n" % ( indent, self.dieComment() ) )
         if child.tag() == tags.DW_TAG_enumerator:
            value = child[ attrs.DW_AT_const_value ]
            name = asPythonId( child[ attrs.DW_AT_name ] )
            out.write( u"%s%s = %s(%d).value # 0x%x\n" % (
               indent, name, self.intType(), value, value ) )
      out.write( u"\n\n" )

   def intType( self ):
      size = self.die[ attrs.DW_AT_byte_size ]
      if size == 4:
         return u"c_uint32"
      if size == 8:
         return u"c_uint64"
      if size == 2:
         return u"c_uint16"
      if size == 1:
         return u"c_byte"
      raise Exception( u"don't know what type to use for %d byte enum" %
            self.size() )

class PrimitiveType( Type ):
   ''' Primitive types from DWARF/C: map to a python ctype primitive '''
   baseTypes = {
         u"long long unsigned int" : u"c_ulonglong",
         u"long long int" : u"c_longlong",
         u"long unsigned int" : u"c_ulong",
         u"short unsigned int" : u"c_ushort",
         u"unsigned int" : u"c_uint",
         u"unsigned char" : u"c_byte",
         u"signed char" : u"c_char",
         u"char" : u"c_char",
         u"long int" : u"c_long",
         u"int" : u"c_int",
         u"short int" : u"c_short",
         u"float" : u"c_float",
         u"_Bool" : u"c_bool",
         u"bool" : u"c_bool",
         u"double" : u"c_double",
         u"long double" : u"c_longdouble",
         u"wchar_t" : u"c_wchar",
   }

   def __init__( self, resolver, die ):
      super( PrimitiveType, self ).__init__( resolver, die )

   def name( self ):
      return self.ctype()

   def ctype( self ):
      name = self.die[ attrs.DW_AT_name ]
      if not name in PrimitiveType.baseTypes:
         raise Exception( "no python ctype for primitive C type %s" % name )
      return PrimitiveType.baseTypes[ name ]

class ArrayType( Type ):
   def __init__( self, resolver, die ):
      ''' Find all the array's dimensions so we can calculate size, and ctype '''
      super( ArrayType, self ).__init__( resolver, die )
      self.dimensions = []
      for child in reversed( die.iter_children() ):
         if child.tag() == tags.DW_TAG_subrange_type:
            upper = child[ attrs.DW_AT_upper_bound ]
            if upper is None:
               self.dimensions.append( 0 )
            else:
               self.dimensions.append( upper + 1 )

   def define( self, out ):
      self.resolver.defineType( self.baseType(), out )

   def ctype( self ):
      text = self.baseType().ctype()
      for d in self.dimensions:
         text = u"%s * %d" % ( text, d )
      return text

   def size( self ):
      size = self.baseType().size()
      for d in self.dimensions:
         size *= d
      return size

class PointerType( Type ):
   def __init__( self, resolver, die ):
      super( PointerType, self ).__init__( resolver, die )
      # Make sure the base type exists.
      self.baseType()

   def declare( self, out ):
      self.resolver.declareType( self.baseType(), out )

   def define( self, out ):
      self.resolver.declareType( self.baseType(), out )

   def ctype( self ):
      baseDie = self.die.getBaseType()
      if not baseDie:
         return u"c_void_p"
      baseCtype = self.baseType().ctype()
      if baseDie.tag() == tags.DW_TAG_subroutine_type:
         return baseCtype
      if baseCtype == u"c_char" or baseCtype == u'CONST( c_char )':
         # XXX: need to be able to tune this
         return u"c_char_p"
      return u"POINTER( %s )" % baseCtype

class Typedef( Type ):
   ''' Typedefs are basic types that alias others. When delcaring/defining, we just
   declare/define the underlying type, and create an alias with a python
   assignment.'''
   def __init__( self, resolver, die ):
      super( Typedef, self ).__init__( resolver, die )
      resolver.dieToType( self.die.getBaseType() )

   def define( self, out ):
      self.resolver.defineType( self.baseType(), out )
      self.resolver.declareType( self, out )

   def declare( self, out ):
      self.resolver.declareType( self.baseType(), out )
      name = self.pyName()
      ctype = self.baseType().ctype()

      if name == ctype:
         return
      if len( name ) + len( ctype ) > 80:
         sep = u' \\\n   '
      else:
         sep = u' '
      out.write( u'%s =%s%s%s\n' % ( name, sep, ctype, self.dieComment() ) )

   def size( self ):
      return self.resolver.dieToType( self.die.getBaseType() ).size()

class ModifierType( Type ):
   ''' Modifier types represent things like volatile, const, etc. These
   don't really have an effect on ctypes, but we render them for
   documentation purposes. '''

   def __init__( self, resolver, die ):
      super( ModifierType, self ).__init__( resolver, die )

   def size( self ):
      return self.baseType().size()

   def ctype( self ):
      return self.baseType().ctype()

   def declare( self, out ):
      self.resolver.declareType( self.baseType(), out )

   def define( self, out ):
      self.resolver.defineType( self.baseType(), out )

class ConstType( ModifierType ):
   def __init__( self, resolver, die ):
      super( ConstType, self ).__init__( resolver, die )

   def ctype( self ):
      base = self.baseType()
      name = base.ctype() if base is not None else u"c_void_p"
      return u"CONST( %s )" % name

class VolatileType( ModifierType ):
   def __init__( self, resolver, die ):
      super( VolatileType, self ).__init__( resolver, die )

   def ctype( self ):
      return u"VOLATILE( %s )" % self.baseType().ctype()

class RestrictType( ModifierType ):
   def __init__( self, resolver, die ):
      super( RestrictType, self ).__init__( resolver, die )

   def ctype( self ):
      return u"RESTRICT( %s )" % self.baseType().ctype()

typeFromTag = {
      tags.DW_TAG_typedef : Typedef,
      tags.DW_TAG_pointer_type : PointerType,
      tags.DW_TAG_subroutine_type : FunctionType,
      tags.DW_TAG_structure_type : StructType,
      tags.DW_TAG_class_type : StructType,
      tags.DW_TAG_union_type : UnionType,
      tags.DW_TAG_base_type : PrimitiveType,
      tags.DW_TAG_array_type : ArrayType,
      tags.DW_TAG_const_type : ConstType,
      tags.DW_TAG_enumeration_type : EnumType,
      tags.DW_TAG_volatile_type : VolatileType,
      tags.DW_TAG_subprogram : FunctionDefType,
      tags.DW_TAG_restrict_type : RestrictType,
}

class TypeResolver( object ):

   ''' Construct a python file with a set of Ctypes derived from a
   DWARF-annotated binary '''

   # These are the named types we can generate definitions for
   typeDieTags = [
         tags.DW_TAG_structure_type,
         tags.DW_TAG_class_type,
         tags.DW_TAG_union_type,
         tags.DW_TAG_enumeration_type,
         tags.DW_TAG_typedef,
         tags.DW_TAG_subprogram,
         ]

   def dieToType( self, die ):
      ''' Convert a DWARF DIE to a Type object '''

      if not die:
         return VoidType( self )

      # If this DIE is a declaration of a type we have a definition for, then
      # upgrade it to the definition DIE before continuing
      diename = die[ attrs.DW_AT_name ]
      if die[ attrs.DW_AT_declaration ] and diename in self.typeDiesByName:
         die = self.typeDiesByName[ diename ]

      # Check our cache of die->Type. We might have it in this module, or in one of
      # the modules we depend on.

      if die.key() in self.typesByDie:
         return self.typesByDie[ die.key() ]
      for existingSet in self.existingTypes:
         if diename in existingSet.definedTypes:
            return existingSet.definedTypes[ diename ]

      newType = typeFromTag[ die.tag() ]( self, die )

      self.typesByDie[ die.key() ] = newType
      return newType

   def dedup( self, typ ):
      ''' If a type is based on a DIE that is not the preferred DIE for that named
      type, then return the canonical type for that name.'''
      if typ is None or not ( typ.resolver == self ):
         return None
      if typ.pyName() is None or typ.pyName() not in self.typeDiesByName:
         return typ
      newDie = self.typeDiesByName[ typ.pyName() ]
      if newDie != typ.die:
         typ = self.dieToType( newDie )
      return typ

   def declareType( self, typ, out ):
      ''' Idempotent wrapper for Type.declare '''
      typ = self.dedup( typ )
      if typ is None:
         return
      if typ.pyName() in self.declaredTypes:
         return
      self.declaredTypes[ typ.pyName() ] = typ
      typ.declare( out )

   def defineType( self, typ, out ):
      ''' Idempotent wrapper for Type.define '''
      typ = self.dedup( typ )
      if typ is None:
         return

      # decl->defn upgrade is now done in dieToType: we don't get declarations here
      assert not typ.die[ attrs.DW_AT_declaration ]
      if typ.pyName() not in self.definedTypes:
         self.definedTypes[ typ.pyName() ] = typ
         typ.define( out )

   def findInterestingDIEs( self, handle, die ):
      ''' Find any potentially interesting dwarf DIEs'''

      tag = die.tag()

      # Don't descend down namespaces for named dies yet - we don't have a coherent
      # approach to namespaces.
      if tag == tags.DW_TAG_namespace:
         return False

      name = die[ attrs.DW_AT_name ]
      if name == None:
         return True

      # Remember all type DIEs. Prefer definitions to declarations but assume
      # multiple DIEs of the same name are for the same type in different
      # translation units.
      if tag in TypeResolver.typeDieTags and \
            ( name not in self.typeDiesByName or
                  self.typeDiesByName[ name ][ attrs.DW_AT_declaration ] ):
         self.typeDiesByName[ name ] = die

      # Find any potentially interesting dwarf entries for defined functions.
      if tag == tags.DW_TAG_subprogram and name in self.functions and \
            not die[ attrs.DW_AT_declaration ]:
         self.functionDiesByName[ name ] = die

      # Find any DIEs for global variables we're interested in
      if tag == tags.DW_TAG_variable and name in self.globalVars:
         self.globalVarDiesByName[ name ] = die
      return True


   def error( self, txt ):
      self.errors += 1
      self.errorfunc( txt )

   def __init__( self, libnames, requiredTypes, functions, existingTypes,
         errorfunc=error, globalVars=None ):
      self.dwarves = [ PyDwarfWrapper.getDwarfHandle( libname )
                       for libname in libnames ]
      self.typesByDie = {}
      self.globalVars = globalVars if globalVars else []
      self.globalVarDiesByName = {}
      self.typeDiesByName = {}
      self.declaredTypes = {}
      self.definedTypes = {}
      self.functionDiesByName = {}
      self.functions = functions
      self.pkgname = None
      self.existingTypes = existingTypes if existingTypes else []
      self.explicitTypes = {}
      self.errorfunc = errorfunc
      self.errors = 0

      # Find all DIEs we are potentially interested in
      for dwarf in self.dwarves:
         for u in dwarf.getUnits():
            dwarf.enumerateDIEs( u.getTopDIE(), self.findInterestingDIEs )

      # Check we found anything the user explicitly asked for.
      for globname in self.globalVars:
         if globname not in self.globalVarDiesByName:
            self.error( "no definition for global variable %s" % globname )

      for fname in self.functions:
         if fname not in self.functionDiesByName:
            self.error( "no definition for function %s" % fname )

      for user in requiredTypes:
         if user.cName not in self.typeDiesByName:
            self.error( "no definition for type '%s'" % user.cName )
         else:
            self.addExplicitType( user )
            if user.fieldHints:
               user.typeDesc.applyHints( user.fieldHints )

   def addExplicitType( self, user, die=None ):
      # Get the type descriptor of a type
      if die is None:
         die = self.typeDiesByName[ user.cName ]
      user.typeDesc = self.dieToType( die )
      typ = user.typeDesc
      while typ.die.tag() == tags.DW_TAG_typedef:
         typ = typ.baseType()
      self.explicitTypes[ typ.name() ] = user

   def write( self, stream ):
      ''' Actually write the python file to a stream '''
      stream.write(
u'''from ctypes import * # pylint: disable=wildcard-import
from CTypeGenRun import * # pylint: disable=wildcard-import
# pylint: disable=unnecessary-pass,protected-access


''' )

      for pkg in self.existingTypes:
         stream.write( u"import %s\n" % pkg.pkgname )
      stream.write( u"\n" )

      # Now define each interesting type - other types will be defined as needed
      for user in self.explicitTypes.values():
         self.defineType( user.typeDesc, stream )

      if self.globalVarDiesByName:
         # Make sure any new types needed for global vars are also defined.
         stream.write( u"# types for globals:\n" )
         for t in self.globalVarDiesByName.values():
            self.defineType( self.dieToType( t.getBaseType() ), stream )
         stream.write( u"# end types for globals\n" )

         # Now write out a class definition containing an entry for each global
         # variable.
         stream.write( u"class Globals(object):\n" )
         stream.write( u"%sdef __init__(self, dll):\n" % pad( 3 ) )
         for name, die in self.globalVarDiesByName.items():
            t = self.dieToType( die.getBaseType() )
            stream.write( u"%sself.%s = ( %s ).in_dll( dll, '%s' )\n" %
                  ( pad( 6 ), name, t.ctype(), name ) )

      for t in self.functionDiesByName.values():
         self.dieToType( t ).define( stream )

      ctypesProtos = {}

      stream.write( u'\ndef decorateFunctions( lib ):\n' )
      if len( self.functionDiesByName ):
         for funcName, t in self.functionDiesByName.items():
            self.dieToType( t ).writeLibUpdates( 3, stream )
            ctypesProtos[ funcName ] = self.dieToType( t ).ctype()
      else:
         stream.write( u'   pass\n' )

      if ctypesProtos:
         stream.write( u"\nfunctionTypes = {\n" )
         for funcName, proto in ctypesProtos.items():
            stream.write( u"   '%s': %s,\n" % ( funcName, proto ) )
         stream.write( u"}" )

      stream.write( u'\n\n' )

      # If the python typename is different to the C type name, then just use
      # an assignment.
      for pytype in self.explicitTypes.values():
         if pytype.cName != pytype.pythonName:
            stream.write( u'%s = %s\n' %
                  ( pytype.pythonName, pytype.typeDesc.ctype() ) )

      # Make the whole shebang test itself when run.
      stream.write( u'\nif __name__ == "__main__":\n' )
      stream.write( u'   test_classes()\n' )

class Hint( object ):
   ''' Hints indicate some modification to a field in a struct/union
   We can currently:
   o override the name of the field
   o give a PythonType to name its type and have ctype data generated for it.
     (This is useful for anonymous types we need to refer to.)
   o Totally override the ctypes declaration for the field. useful to get around
     python bugs with bitfields.
   '''

   def __init__( self, typename=None, name=None, typeOverride=None,
         allowUnaligned=False ):
      self.typename = typename
      self.name = name
      self.typeOverride = typeOverride
      self.allowUnaligned = allowUnaligned

class PythonType( object ):
   ''' Descriptor for types that caller wants rendered in the output '''

   def __init__( self, pythonName, cName=None, base=None, pack=False,
           mixins=None, nameless_enum=False ):
      self.pythonName = pythonName
      self.cName = cName if cName is not None else pythonName
      self.fieldHints = {}
      self.pack = pack
      self.base = base
      self.mixins = mixins
      self.nameless_enum = nameless_enum

   def field( self, field, typename=None, name=None, typeOverride=None,
         allowUnaligned=False ):
      ''' Add a Hint to the type for a specific field. This is intended for
      method-chaining use.'''
      self.fieldHints[ field ] = Hint( typename, name, typeOverride, allowUnaligned )
      return self


def generateOrThrow( binaries, outname, types, functions, header, modname,
      existingTypes, errorfunc, globalVars ):
   '''  External interface to generate code from a set of binaries, into a python
   module.
   Parameters:
      binaries: list of ELF objects to scan for data.
      outname: the name of the python file to create
      types: Array of PythonType objects to render in the python
      functions: Array of function names to generate return and argument
         types for.
      header: text to include at the start of the file - this can do things
         like import other packages, etc.
      modname: the name of the python module (as part of generating the object,
         the module is itself imported. Defaults to the outname with extension
         stripped
      existingTypes: if there are any modules with ctypes already
         present, you can present an array of them here. Any references
         to types in the generated code will be resolved in those modules
         before attempting to render new copies of them. Eg, when generating
         GatedBgpCTypes, we pass GatedBgpTypes first, so the same type instances
         are used in both for the basic gated types.
   '''

   # Allow binaries to be a single string, or list thereof.
   if isinstance( binaries,  baseString ):
      binaries = [ binaries ]
   if not isinstance( binaries, list ) or not isinstance(
         binaries[ 0 ], baseString ):
      errorfunc( "CTypeGen.generate requires a list of ELF images as its first" +
                 " argument" )
      return ( None, None )
   resolver = TypeResolver( binaries, types, functions, existingTypes, errorfunc,
         globalVars )
   with open( outname, 'w' ) as content:

      stack = inspect.stack()
      frame = stack[ 1 ]
      callerSource = frame[ 1 ]

      warning = \
'''# Copyright (c) %d Arista Networks, Inc.  All rights reserved.
# Arista Networks, Inc. Confidential and Proprietary.
#
# DON'T EDIT THIS FILE. It was generated by
# %s
# Please see AID/3558 for details on the contents of this file
#
''' % ( datetime.datetime.now().year, callerSource )

      content.write( warning )
      if header is not None:
         content.write( header )
      resolver.write( content )

   if modname == None:
      modname = outname.split( "." )[ 0 ]
   mod = imp.load_source( modname, outname )
   mod.test_classes()
   resolver.pkgname = modname
   print( "generated and tested %s" % modname )
   return ( mod, resolver )

def generate( binaries, outname, types, functions, header=None, modname=None,
      existingTypes=None, errorfunc=error, globalVars=None ):
   try:
      return generateOrThrow( binaries, outname, types, functions, header,
                modname, existingTypes, errorfunc, globalVars )
   except Exception as e: # pylint: disable=broad-except
      errorfunc( "Fatal error: %s" % e )
      return None, None
