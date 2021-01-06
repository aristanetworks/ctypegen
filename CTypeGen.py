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
# CTypeGen generates boilerplate code using python's ctype package to
# interact with C libraries. See Aid 3558, aka go/ctypegen for the gorey details.

from __future__ import absolute_import, division, print_function
import datetime
import io
import os.path
import imp
import inspect
import sys
import ctypes
import keyword
from collections import defaultdict

# the following modules are dynamically generated inside the C extension.
# pylint should ignore them
import libCTypeGen # pylint: disable=import-error

tags = libCTypeGen.tags
attrs = libCTypeGen.attrs

# python3 doesn't have basestring
try:
   baseString = basestring # pylint: disable=basestring-builtin
except NameError:
   baseString = str

try:
   dict.iteritems
except AttributeError:
   # Python 3
   def itervalues( d ):
      return iter( d.values() )

   def iteritems( d ):
      return iter( d.items() )
else:
   # Python 2
   def itervalues( d ):
      return d.itervalues()

   def iteritems( d ):
      return d.iteritems()

# Add explicit dependency on CTypeGen runtime - we need this when we run the
# sanity check on the generated file.
# pkgdeps: import CTypeGenRun

def asPythonId( s ):
   ''' convert an identifier from debug data into a valid DWARF id '''
   repls = {
         u":" : u"_cn",
         u"<" : u"_lt",
         u">" : u"_gt",
         u"(" : u"_lp",
         u")" : u"_rp",
         u"-" : u"_dash",
         u"=" : u"_eq",
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
   if keyword.iskeyword( out ):
      out = out + "_"
   return out

def pad( indent ):
   ''' Return a padding string with the given number of spaces - useful for
   formatting'''
   return u"".ljust( indent )

def deref( die ):
   ''' Remove any CV-qualifiers and dereference any typedefs from a DIE until
   we get down to its unqualified, non-typedef'd type
   '''
   qualifiers = set( [ tags.DW_TAG_const_type,
                         tags.DW_TAG_volatile_type,
                         tags.DW_TAG_typedef,
                         tags.DW_TAG_restrict_type ]
                         )
   while die is not None and die.tag() in qualifiers:
      die = die.DW_AT_type
   return die

def isVoid( die ):
   ''' return true if a DIE represents some qualified or typedef'd "void" '''
   return deref( die ) is None

class Type( object ):
   ''' An object representing a Dwarf Type. Mostly a wrapper around a DIE. Subclassed
   for structures, unions, functions, etc'''

   __slots__ = [
         "resolver", "die", "_name", "spec", "defdie", "defined"
   ]

   def __init__( self, resolver, die ):
      self.resolver = resolver
      self._name = "::".join( die.fullname() ) if die else "void"
      self.spec = None
      self.die = die
      self.defdie = None
      self.defined = False

   def definition( self ):
      if self.defdie:
         return self.defdie
      if not self.die.DW_AT_declaration:
         self.defdie = self.die
         return self.defdie
      for d in self.resolver.dwarves:
         self.defdie = d.findDefinition( self.die )
         if self.defdie:
            return self.defdie
      self.resolver.errorfunc( "failed to find definition for %s - "
                               "will fall back to using declaration" %
                               "::".join( self.die.fullname() ) )
      self.defdie = self.die
      return self.defdie

   def applyHints( self, spec ):
      self.spec = spec

   def dieComment( self ):
      if self.pyName() == self.name():
         return u""
      return u"# DIE %s" % self.name()

   def pyName( self ):
      ''' Remove non-python characters from this type's name'''
      return asPythonId( self.name() )

   def declare( self, out ):
      ''' Write to out any info required to refer to this type.'''
      self.resolver.defineType( self, out )

   def define( self, out ):
      ''' Write to out any info required to instantiate this type.'''
      return True

   def baseType( self ):
      ''' Return the type that this type derives - eg, pointers and
      arrays are pointers to and arrays of their base type. Typedefs
      and consts modify their base types'''

      baseDie = self.definition().DW_AT_type
      if baseDie:
         return self.resolver.dieToType( baseDie )
      return None

   def size( self ):
      ''' The size of the type, as reported via DWARF '''
      return self.definition().DW_AT_byte_size

   def hasName( self ):
      return self._name is not None

   def name( self ):
      assert self._name
      if self.resolver.pkgname is not None:
         return u'%s.%s' % ( self.resolver.pkgname, self._name )
      return self._name

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

   def params( self ):
      ''' return all formal parameters to the function defined herein '''
      return [ child for child in self.die
            if child.tag() == tags.DW_TAG_formal_parameter ]

   def define( self, out ):
      rtype = self.baseType()
      if rtype:
         self.resolver.defineType( rtype, out )
      for child in self.params():
         self.resolver.defineType(
               self.resolver.dieToType( child.DW_AT_type ), out )
      return True

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
               self.resolver.dieToType( child.DW_AT_type ).ctype() )
      result.write( u")" )
      return result.getvalue()

class FunctionDefType( FunctionType ):
   ''' A type representing a function declaration. We use these DIEs to
   generate the restype and argtypes fields for ctypes, so we can call
   them with type-safety. '''

   def writeLibUpdates( self, indent, stream ):
      """Write function's prototype to stream"""
      base = self.baseType()
      name = self.die.DW_AT_linkage_name
      if name is None:
         name = self.name()
      dynNames = self.die.object().dynnames().get( name )
      if dynNames is None:
         self.resolver.errorfunc( "cannot provide access to %s - "
                                  " not in dynamic symbol table" % self.name() )
         return

      for linkername in dynNames:
         if keyword.iskeyword( linkername ):
            self.resolver.errorfunc( "cannot provide access to %s - "
                  "its dynamic name %s is a python keyword" %
                  ( self.name(), linkername ) )
            continue

         stream.write( u"%sif hasattr(lib, '%s'):\n" % (
                       pad( indent ), linkername ) )
         indent += 3
         stream.write( u"%slib.%s.restype = %s\n" %
              ( pad( indent ), linkername, base.ctype() if base else "None" ) )
         args = []

         for child in self.params():
            baseType = self.resolver.dieToType( child.DW_AT_type )
            args.append( baseType.ctype() )

         stream.write( u"%slib.%s.argtypes = " % ( pad( indent ), linkername ) )
         if args:
            sep = u"["
            for arg in args:
               stream.write( u"%s\n%s%s" % ( sep, pad( indent + 3 ), arg ) )
               sep = ","
            stream.write( u" ]\n\n" )
         else:
            stream.write( u"[]\n\n" )
         indent -= 3

class Member( object ):
   ''' A single member in a struct, union, class etc. '''
   def __init__( self, die, resolver ):
      self.resolver = resolver
      self._name = None
      self.ctypeOverride = None
      self.die = die
      self.allowUnalignedPtr = False

   def __lt__( self, other ):
      return self.name() < other.name() if isinstance( other, Member ) else False

   def setName( self, name ):
      self._name = name

   def name( self ):
      if self._name:
         return self._name
      return self.die.DW_AT_name

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
      return self.die.DW_AT_bit_size

   def isStatic( self ):
      return self.die.tag() == tags.DW_TAG_member and \
            self.die.DW_AT_member_location is None

   def type( self ):
      return self.resolver.dieToType( self.die.DW_AT_type )

   def setCType( self, ctype ):
      self.ctypeOverride = ctype

class MemberType( Type ):
   ''' A struct, class  or union type - anything that has fields. '''
   __slots__ = [ "members", "anonMembers" ]

   def __init__( self, resolver, die ):
      ''' MemberTypes can accept fieldHints - these are the names of types to
      assign to known fields. If those  are found in the type, then the
      types of the named members will be renamed as appropriate. This is useful
      for anonymous structures, etc, used within struct definitions for their
      fields. '''
      super( MemberType, self ).__init__( resolver, die )
      self.members = []
      self.anonMembers = set()

   def findMembers( self ):
      if self.members:
         return
      superCount = 0
      anon_field = 0
      for field in self.definition():
         tag = field.tag()
         if field.DW_AT_external:
            continue
         if tag == tags.DW_TAG_inheritance:
            member = Member( field, self.resolver )
            member.setName( u"__super__%d" % superCount )
            superCount += 1
            self.members.append( member )
         elif tag == tags.DW_TAG_member:
            member = Member( field, self.resolver )
            if field.DW_AT_name is None:
               anon_field += 1
               member.setName( u"__anon__member__%d" % anon_field )
               self.anonMembers.add( member )
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
            self.resolver.errorfunc( "unhandled field %s of type %d in %s " %
                                     ( field.name(), field.tag(), self.name() ) )

   def applyHints( self, spec ):
      ''' For fields with anonymous types, provide python names as hinted by caller
      '''
      super( MemberType, self ).applyHints( spec )
      self.findMembers()
      fieldHints = spec.fieldHints
      if fieldHints is None:
         return
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
               typedesc.type = member.type()

               memberTypeDIE = member.die.DW_AT_type
               typ = self.resolver.dieToType( memberTypeDIE )
               typ.applyHints( typedesc )
               # add to names we'll define later
               self.resolver.requiredTypes.append( typedesc )

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

      base = self.ctype_subclass() if self.spec is None or self.spec.base is None \
            else self.spec.base

      out.write( u'\n' )
      # TestableCtypeClass is a mixin defined in CTypeGenRun, and
      # provides methods on the # generated class to do some consistency
      # checking. The generated code will perform these tests if run as
      # a stand-alone program.
      out.write( u'class %s( %s, TestableCtypeClass' % ( self.pyName(), base ) )
      if self.spec and self.spec.mixins:
         for mixin in self.spec.mixins:
            out.write( ', %s' % mixin )
      out.write( u' ):\n' )
      if self.dieComment():
         out.write( u"   %s\n" % self.dieComment() )
      if self.spec and self.spec.pack:
         out.write( u"   _pack_ = 1\n" )
      else:
         out.write( u"   pass\n" )
      out.write( u'\n' )

   def define( self, out ):
      ''' Define a type: we need to render the fields now, so something else
      can include an object of this type, or access a field '''
      if self.definition().DW_AT_declaration:
         return False
      self.findMembers()
      self.resolver.declareType( self, out ) # make sure we're declared first.

      # Make sure the types of all fields are defined, so we can instantiate them
      for m in self.members:
         self.resolver.defineType( m.type(), out )

      out.write( u"\n" )
      out.write( u"%s._ctypegen_native_size = %d\n" % ( self.pyName(),
                                                          self.size() ) )
      out.write( u"%s._ctypegen_have_definition = True\n" % self.pyName() )

      # Indicate any fields we'll intentionally allow to have unaligned
      # pointers in them.
      unaligned = [ m.pyName() for m in self.members if m.allowUnalignedPtr ]
      if unaligned:
         out.write( u"%s.allow_unaligned = %s\n" % ( self.pyName(), unaligned ) )

      # quoting the 'p' below stops pylint gagging on this file.
      if self.members:
         out.write( u"%s._fields_ = [ # \x70ylint: disable=protected-access\n" %
               self.pyName() )
         for memnum, member in enumerate( self.members ):
            # First make sure we actually have a proper definition of the type
            # for this field. For example, clang++ will not generate the debug
            # info for std::string by default, and we are left with an
            # incomplete type for strings. ctypes has no way of directly
            # controlling the offset for a field, so we need to give the field
            # a type of the correct size, at least - if we don't find a
            # definition for the field's type, then we just make it an array
            # of characters of the appropriate size.
            if not member.type().defined:
               myOffset = member.die.DW_AT_data_member_location or 0
               if memnum + 1 < len( self.members ):
                  nextOffset = self.members[ memnum + 1 ].die. \
                          DW_AT_data_member_location
                  size = nextOffset - myOffset
               else:
                  size = self.die.DW_AT_byte_size - myOffset
               typstr = "c_char * %d" % size
               self.resolver.errorfunc(
                     "padded %s:%s (no definition for %s)" % (
                        self.name(), member.name(), member.type().name() ) )

            else:
               typstr = member.ctype()
            if member.bit_size():
               out.write( u"   ( \"%s\", %s, %d ),\n" %
                     ( member.pyName(), typstr, member.bit_size() ) )
            else:
               out.write( u"   ( \"%s\", %s ),\n" % ( member.name(), typstr ) )
         out.write( u"]\n" )
      if self.anonMembers:
         out.write( u"%s._anonymous_ = (\n" % self.pyName() )
         for field in sorted( self.anonMembers ):
            out.write( u"   \"%s\",\n" % field.pyName() )
         out.write( u"   )\n" )
      out.write( u"\n" )
      return True

class StructType( MemberType ):
   ''' A member type for a structure (or class) '''

   __slots__ = []

   def ctype_subclass( self ):
      return u"Structure"

   def define( self, out ):
      if not super( StructType, self ).define( out ):
         return False
      out.write( u"%s._ctypegen_offsets = [ " % self.pyName() )
      sep = u""

      memberCount = 0
      lastOffset = -1
      for member in self.members:
         memberOffset = member.die.DW_AT_data_member_location
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
      return True

class UnionType( MemberType ):
   ''' Member type for a union '''
   __slots__ = []

   def ctype_subclass( self ):
      return u"Union"

   def define( self, out ):
      if not super( UnionType, self ).define( out ):
         return False
      if not self.members and self.die.DW_AT_byte_size is not None:
         out.write( u"%s._fields_ = [('__broken_transparent_union', c_void_p)]\n"
                 % self.pyName() )
      return True

class EnumType( Type ):
   __slots__ = []

   def define( self, out ):
      rtype = self.baseType()
      if rtype:
         self.resolver.defineType( rtype, out )
      indent = ''
      if self.spec and ( self.spec.nameless_enum is not None ):
         nameless = self.spec.nameless_enum
      else:
         nameless = self.resolver.namelessEnums

      out.write( u"class %s( %s ):\n" % ( self.pyName(), self.intType() ) )
      if not nameless:
         indent = pad( 3 )
      else:
         out.write( u'%spass\n\n' % pad( 3 ) )
         out.write( u'# Values of %s (nameless enum)\n' % self.pyName() )

      childcount = 0
      for child in self.definition():
         if self.dieComment():
            out.write( u"%s%s\n" % ( indent, self.dieComment() ) )
         if child.tag() == tags.DW_TAG_enumerator:
            childcount += 1
            value = child.DW_AT_const_value
            name = asPythonId( child.DW_AT_name )
            out.write( u"%s%s = %s(%d).value # %s\n" % (
               indent, name, self.intType(), value, hex( value ) ) )
      if childcount == 0:
         out.write( u"%spass\n" % indent )

      out.write( u"\n\n" )
      return True

   def intType( self ):
      primitive = self.resolver.dieToType( self.definition().DW_AT_type )
      return primitive.pyName()

class PrimitiveType( Type ):
   ''' Primitive types from DWARF/C: map to a python ctype primitive '''
   __slots__ = []
   baseTypes = {
         u"long long unsigned int" : u"c_ulonglong",
         u"long long int" : u"c_longlong",
         u"long unsigned int" : u"c_ulong",
         u"short unsigned int" : u"c_ushort",
         u"unsigned short" : u"c_ushort",
         u"unsigned int" : u"c_uint",
         u"unsigned char" : u"c_ubyte",
         u"char16_t" : u"c_short",
         u"signed char" : u"c_byte",
         u"char" : u"c_char",
         u"long int" : u"c_long",
         u"int" : u"c_int",
         u"short int" : u"c_short",
         u"short" : u"c_short",
         u"float" : u"c_float",
         u"_Bool" : u"c_bool",
         u"bool" : u"c_bool",
         u"double" : u"c_double",
         u"long double" : u"c_longdouble",
         u"_Float128" : u"c_longdouble",
         u"__int128" : u"(c_longlong * 2)",
         u"wchar_t" : u"c_wchar",
   }

   def name( self ):
      return self.ctype()

   def ctype( self ):
      name = self.die.DW_AT_name
      if not name in PrimitiveType.baseTypes:
         raise Exception( "no python ctype for primitive C type %s" % name )
      return PrimitiveType.baseTypes[ name ]

class ArrayType( Type ):
   __slots__ = [ "dimensions" ]

   def __init__( self, resolver, die ):
      ''' Find all the array's dimensions so we can calculate size, and ctype '''
      super( ArrayType, self ).__init__( resolver, die )
      self.dimensions = []
      for child in reversed( [ c for c in self.definition() ] ):
         if child.tag() == tags.DW_TAG_subrange_type:
            if child.DW_AT_count is not None:
               self.dimensions.append( child.DW_AT_count )
            elif child.DW_AT_upper_bound is not None:
               self.dimensions.append( child.DW_AT_upper_bound + 1 )
            else:
               self.dimensions.append( 0 )

   def define( self, out ):
      return self.resolver.defineType( self.baseType(), out )

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
   __slots__ = []

   def declare( self, out ):
      self.resolver.declareType( self.baseType(), out )

   def isVoidp( self ):
      return isVoid( self.definition().DW_AT_type )

   def define( self, out ):
      if self.isVoidp():
         return True # We'll just render as c_void_p
      r = self.resolver
      r.declareType( self.baseType(), out )
      # If requested, and we can, define pointed-to types
      if ( r.deepInspect and
          self.baseType() is not None and
          not self.baseType().definition().DW_AT_declaration ):
         t = self.baseType()
         if t not in r.definedTypes:
            r.indirectTypes.add( t )
      return True

   def ctype( self ):
      if self.isVoidp():
         return u"c_void_p"
      baseDie = self.definition().DW_AT_type
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
   __slots__ = []

   def __init__( self, resolver, die ):
      super( Typedef, self ).__init__( resolver, die )
      self.baseType()

   def applyHints( self, spec ):
      super( Typedef, self ).applyHints( spec )
      # a typedef with no base type is a "c_void", so we can't apply hints
      if self.baseType() is not None:
         self.baseType().applyHints( spec )

   def define( self, out ):
      # a typedef may be defined on a declared type, and the declared type
      # may then use the typedef in its definition.
      # We must there fore declare the base type first, then declare ourselves,
      # then define the base type, so our declaration is available while defining
      # the base type.
      self.resolver.declareType( self.baseType(), out )
      self.resolver.declareType( self, out )
      return self.resolver.defineType( self.baseType(), out )

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
      out.write( u'%s = %s%s%s # typedef\n' %
                 ( name, sep, ctype, self.dieComment() ) )

   def size( self ):
      return self.baseType().size()

class ModifierType( Type ):
   ''' Modifier types represent things like volatile, const, etc. These
   don't really have an effect on ctypes, but we render them for
   documentation purposes. '''

   __slots__ = []

   def size( self ):
      return self.baseType().size()

   def ctype( self ):
      return self.baseType().ctype()

   def declare( self, out ):
      self.resolver.declareType( self.baseType(), out )

   def define( self, out ):
      return self.resolver.defineType( self.baseType(), out )

class ConstType( ModifierType ):
   __slots__ = []

   def ctype( self ):
      base = self.baseType()
      name = base.ctype() if base is not None else u"c_void_p"
      return u"CONST( %s )" % name

class VolatileType( ModifierType ):
   __slots__ = []

   def ctype( self ):
      return u"VOLATILE( %s )" % self.baseType().ctype()

class RestrictType( ModifierType ):
   __slots__ = []

   def ctype( self ):
      return u"RESTRICT( %s )" % self.baseType().ctype()

typeFromTag = {
      tags.DW_TAG_typedef : Typedef,
      tags.DW_TAG_pointer_type : PointerType,
      tags.DW_TAG_reference_type : PointerType, # just pretend.
      tags.DW_TAG_rvalue_reference_type : PointerType, # just pretend.
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
      tags.DW_TAG_unspecified_type : PointerType,
      tags.DW_TAG_ptr_to_member_type : PointerType,
}

class Namespace( object ):
   ''' We use the Namespace object to limit our scanning of the entire DIE tree
   Each name we are looking for (type, global, function) is in a namespace.
   We don't decend into namespaces if we're not interested in them

   Each namespace contains a list of types, variables, and functions that
   we want defined in that namespace, and also a set of subordinate namespaces
   we are also interested in.
   '''

   __slots__ = [ "types", "variables", "functions",
         "subspaces", "parent", "name_", "resolver" ]

   def __init__( self, parent, resolver, name ):

      class NamespaceDict( defaultdict ):
         def __init__( self, namespace ):
            super( NamespaceDict, self ).__init__()
            self.namespace = namespace

         def __missing__( self, key ):
            ns = self.namespace
            newspace = Namespace( ns, ns.resolver, key )
            self[ key ] = newspace
            return newspace

      class TypesDict( defaultdict ):
         def __missing__( self, key ):
            newtype = PythonType( key )
            self[ key ] = newtype
            return newtype

      self.types = TypesDict()
      self.variables = {}
      self.functions = {}
      self.subspaces = NamespaceDict( self )
      self.parent = parent
      self.name_ = name
      self.resolver = resolver

   def recurse( self, func ):
      func( self )
      for subns in itervalues( self.subspaces ):
         subns.recurse( func )

   def depth( self ):
      if self.parent is None:
         return 0
      else:
         return 1 + self.parent.depth()

   def name( self ):
      if self.parent:
         if self.parent.parent:
            return self.parent.name() + "::" + self.name_
         return self.name_
      return None

   def addToSet( self, nameList, accessor ):
      ''' add namelist (a list specifying a scoped name) to the namespace.  If
      the name is of length > 1, then the leaf object exists in a sub-namespace
      of this one: we recursively ensure that the immediate namespace exists,
      and pass the suffix of the list down to that namespace.

      When we reach the leaf, the item to add may be a variable, function or
      type - the accessor provides a way to extract the correct list from the
      leaf namespace, and the value to insert.

      For vars and functions, we just insert a None object. For types,
      we leave a pointer to the "spec", i.e., PythonType.
      '''

      thisName = nameList[ 0 ]
      if len( nameList ) == 1:
         container, value = accessor( self )
         if thisName in container:
            self.resolver.errorfunc( "duplicate name: %s" % thisName )
         else:
            container[ thisName ] = value
      else:
         self.subspaces[ thisName ].addToSet( nameList[ 1 : ], accessor )

   def addType( self, spec ):
      self.addToSet( spec.cName.split( "::" ), lambda ns: ( ns.types, spec ) )

   def addVar( self, fqn ):
      self.addToSet( fqn.split( "::" ), lambda ns: ( ns.variables, None ) )

   def addFunc( self, fqn ):
      self.addToSet( fqn.split( "::" ), lambda ns: ( ns.functions, None ) )

class TypeResolver( object ):

   ''' Construct a python file with a set of Ctypes derived from a
   DWARF-annotated binary '''

   __slots__ = [
         "dwarves",
         "typesByDieKey",
         "declaredTypes",
         "definedTypes",
         "pkgname",
         "existingTypes",
         "errorfunc",
         "errors",
         "rootNamespace",
         "requiredTypes",
         "deepInspect",
         "namelessEnums",
         "indirectTypes",
         "typesFilter",
         "functionsFilter",
         "globalsFilter",
         "namespaceFilter",
   ]

   def __init__( self, dwarves, requiredTypes, functions, existingTypes, errorfunc,
                 globalVars, deepInspect, namelessEnums, namespaceFilter ):

      self.dwarves = dwarves
      self.typesByDieKey = {}
      self.declaredTypes = {}
      self.definedTypes = {}
      self.pkgname = None
      self.existingTypes = existingTypes if existingTypes else []
      self.errorfunc = errorfunc if errorfunc else self.error
      self.errors = 0
      self.rootNamespace = Namespace( None, self, None )
      if callable( requiredTypes ):
         self.typesFilter = requiredTypes
         self.requiredTypes = []
      else:
         self.typesFilter = lambda name, namespace, die: name in namespace.types
         self.requiredTypes = [ r if isinstance( r, PythonType ) else PythonType( r )
                                for r in requiredTypes ]
         for n in self.requiredTypes:
            self.rootNamespace.addType( n )

      self.deepInspect = deepInspect
      self.namelessEnums = namelessEnums
      self.indirectTypes = set()

      # Add all the names we're interested in if supplied with lists, otherwise
      # set appropriate callbacks if the supplied args are callable.

      if callable( globalVars ):
         self.globalsFilter = globalVars
      else:
         self.globalsFilter = lambda name, namespace, die: \
                 name in namespace.variables
         if globalVars:
            for n in globalVars:
               self.rootNamespace.addVar( n )

      if callable( functions ):
         self.functionsFilter = functions
      else:
         self.functionsFilter = lambda name, namespace, die: \
                                    name in namespace.functions
         if functions:
            for n in functions:
               self.rootNamespace.addFunc( n )

      self.namespaceFilter = namespaceFilter
      try:
         for dwarf in self.dwarves:
            for u in dwarf.units():
               self.enumerateDIEs( u.root(), self.examineDIE, self.rootNamespace )
      except StopIteration:
         pass

      # We should now have DIEs for everything we care about. Go through and apply
      # hints
      for i in self.requiredTypes:
         if i.type is None:
            self.errorfunc( "no type for %s" % i.pythonName )
            continue
         i.type.applyHints( i )

   # These are the named types we can generate definitions for
   typeDieTags = (
         tags.DW_TAG_structure_type,
         tags.DW_TAG_class_type,
         tags.DW_TAG_union_type,
         tags.DW_TAG_enumeration_type,
         tags.DW_TAG_typedef,
         tags.DW_TAG_base_type,
         )

   # These are DIEs that represent namespaces of some sort (struct, union, namespace)
   namespaceDieTags = (
           tags.DW_TAG_namespace,
           tags.DW_TAG_structure_type,
           tags.DW_TAG_class_type,
   )

   def dieToType( self, die ):
      ''' Convert a DWARF DIE to a Type object '''

      if die is None:
         return VoidType( self )

      key = self.dieKey( die )

      if key in self.typesByDieKey:
         return self.typesByDieKey[ key ]

      for existingSet in self.existingTypes:
         if key in existingSet.definedTypes:
            return existingSet.definedTypes[ key ]

      newType = typeFromTag[ die.tag() ]( self, die )

      self.typesByDieKey[ key ] = newType
      return newType

   def declareType( self, typ, out ):
      ''' Idempotent wrapper for Type.declare '''
      if typ is None:
         return

      key = self.dieKey( typ.die )
      if key in self.declaredTypes:
         return
      if typ.resolver != self: # This type came from a different module - use as is
         return
      self.declaredTypes[ key ] = typ
      typ.declare( out )

   def defineType( self, typ, out ):
      ''' Idempotent wrapper for Type.define '''
      if typ is None or typ.die is None:
         return True
      if typ.defined:
         return True
      if typ.resolver != self: # This type came from a different module - use as is
         return True
      if isVoid( typ.definition() ):
         self.errorfunc( "%s is 'void' - cannot output definition" % typ.name() )
         return True

      key = self.dieKey( typ.die )
      if key not in self.definedTypes:
         self.definedTypes[ key ] = typ
         typ.defined = typ.define( out )
      assert typ.defined is not None # typ.define should return a bool.
      return typ.defined

   def dieKey( self, die ):
      return ( die.tag(), die.fullname() )

   def examineDIE( self, handle, die, namespace ):
      ''' Find any potentially interesting dwarf DIEs

      Returns:
        Namespace: None if we are not interested in the child DIEs, or the
        namespace associated with this DIE if we are.

      '''

      tag = die.tag()
      if tag == tags.DW_TAG_compile_unit or tag == tags.DW_TAG_partial_unit:
         # Just decend compile units without affecting any namespace scope
         return namespace

      if die.DW_AT_name is None:
         return None # Ignore anything without its own name

      name = die.name()

      if tag == tags.DW_TAG_variable:
         if ( self.globalsFilter( name, namespace, die )
              and namespace.variables.get( name ) is None ):
            namespace.variables[ name ] = die
         return None

      # Only consider definitions, not declarations.
      if die.DW_AT_declaration:
         return None

      if tag == tags.DW_TAG_subprogram:
         if ( namespace.functions.get( name ) is None
               and self.functionsFilter( name, namespace, die ) ):
            namespace.functions[ name ] = die
         return None

      if tag in TypeResolver.typeDieTags:
         if ( self.typesFilter( name, namespace, die )
               and namespace.types[ name ].type is None ):
            namespace.types[ name ].type = self.dieToType( die )

      # If its a struct or namespace, and we're interested in any DIEs inside
      # the namespace, descend it.
      if tag in TypeResolver.namespaceDieTags:
         if self.namespaceFilter( name, namespace, die ):
            return namespace.subspaces[ name ]
      return None

   def error( self, txt ):
      self.errors += 1
      sys.stderr.write( "error: %s\n" % txt )

   def enumerateDIEs( self, die, func, ctx ):
      ctx = func( self, die, ctx )
      if ctx is not None:
         for child in die:
            self.enumerateDIEs( child, func, ctx )

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

      def doNSTypes( ns ):
         # Define types we wanted.
         for spec in itervalues( ns.types ):
            self.defineType( spec.type, stream )

         # Define types for variables we wanted.
         for name, die in iteritems( ns.variables ):
            if die is None:
               self.errorfunc( "variable %s not found in namespace %s" %
                               ( name, ns.name() ) )
            else:
               self.defineType( self.dieToType( die.DW_AT_type ), stream )

         # define function types we wanted.
         for name, die in iteritems( ns.functions ):
            if die:
               self.dieToType( die ).define( stream )
            else:
               self.errorfunc( "function %s not found" % name )

      self.indirectTypes = set()
      self.rootNamespace.recurse( doNSTypes )
      while True:
         indirectTypes = self.indirectTypes
         if not indirectTypes:
            break
         sys.stderr.write( "defining %d more types for deep inspection\n" %
                           len( indirectTypes ) )
         self.indirectTypes = set()
         for t in sorted( indirectTypes ):
            self.defineType( t, stream )

      # Now write out a class definition containing an entry for each global
      # variable.
      stream.write( u"class Globals(object):\n" )
      stream.write( u"%sdef __init__(self, dll):\n" % pad( 3 ) )

      def doGlobalVars( ns ):
         for name, die in iteritems( ns.variables ):
            if die is None:
               continue
            t = self.dieToType( die.DW_AT_type )
            stream.write( u"%sself.%s = ( %s ).in_dll( dll, '%s' )\n" %
                  ( pad( 6 ), name, t.ctype(), name ) )

      self.rootNamespace.recurse( doGlobalVars )

      stream.write( u"%spass" % pad( 6 ) )

      ctypesProtos = {}

      stream.write( u'\ndef decorateFunctions( lib ):\n' )

      def doFunctions( ns ):
         for die in itervalues( ns.functions ):
            if not die:
               continue
            t = self.dieToType( die )
            t.writeLibUpdates( 3, stream )
            ctypesProtos[ t.pyName() ] = t.ctype()

      self.rootNamespace.recurse( doFunctions )
      stream.write( u'   pass\n' )

      if ctypesProtos:
         stream.write( u"\nfunctionTypes = {\n" )
         for funcName, proto in ctypesProtos.items():
            stream.write( u"   '%s': %s,\n" % ( funcName, proto ) )
         stream.write( u"}" )

      stream.write( u'\n\n' )

      # If the python typename is different to the C type name, then just use
      # an assignment.
      for spec in self.requiredTypes:
         if spec.type is None:
            continue
         if spec.pythonName != spec.type.ctype():
            stream.write( u'%s = %s\n' %
                  ( spec.pythonName, spec.type.ctype() ) )

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

   __slots__ = [
         "pythonName", "cName", "fieldHints", "pack", "base", "mixins",
         "nameless_enum", "type"
         ]

   def __init__( self, pythonName, cName=None, base=None, pack=False,
           mixins=None, nameless_enum=None ):
      self.pythonName = pythonName
      self.cName = cName if cName is not None else pythonName
      self.fieldHints = {}
      self.pack = pack
      self.base = base
      self.mixins = mixins
      self.nameless_enum = nameless_enum
      self.type = None

   def field( self, field, typename=None, name=None, typeOverride=None,
         allowUnaligned=False ):
      ''' Add a Hint to the type for a specific field. This is intended for
      method-chaining use.'''
      self.fieldHints[ field ] = Hint( typename, name, typeOverride, allowUnaligned )
      return self

   def __eq__( self, other ):
      return self.cName == other.cName

   def __hash__( self ):
      return hash( self.cName )

def getlib( libname ):
   if not os.path.exists( libname ):
      # If the file doesn't exist, try and load the library with CDLL/dlopen
      # And use the structure of the link map to work out the path to the file.
      class LinkMap( ctypes.Structure ):
         _fields_ = [
               ( "addr", ctypes.c_void_p ),
               ( "name", ctypes.c_char_p ),
         ]
      lib = ctypes.CDLL( libname )
      libname = ctypes.cast( lib._handle, ctypes.POINTER( LinkMap ) )[ 0 ].name
   return libCTypeGen.open( libname )

def getDwarves( libnames ):
   # Allow libnames to be a single string, or list thereof.
   if isinstance( libnames, baseString ):
      libnames = [ libnames ]
   if not isinstance( libnames, list ) or not isinstance(
         libnames[ 0 ], baseString ):
      return None
   return [ getlib( libname ) for libname in libnames ]

def generate( libnames, outname, types, functions, header=None, modname=None,
      existingTypes=None, errorfunc=None, globalVars=None, deepInspect=False,
      namelessEnums=False,
      namespaceFilter=lambda name, space, die: name in space.subspaces ):
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

   dwarves = getDwarves( libnames )
   if not dwarves:
      errorfunc( "CTypeGen.generate requires a list of ELF images as its first" +
                 " argument" )
      return ( None, None )

   return generateDwarf( dwarves,
                         outname, types, functions, header, modname, existingTypes,
                         errorfunc, globalVars, deepInspect, namelessEnums,
                         namespaceFilter )

def generateAll( libs, outname, modname=None ):
   ''' Simplified "generate" that will generate code for all types, functions,
   and variables in a library '''
   dwarves = getDwarves( libs )

   def allExterns( name, space, die ):
      name = die.DW_AT_linkage_name
      if name is None:
         name = die.name()
      return any( [ name in dwarf.dynnames() for dwarf in dwarves ] )
   return generateDwarf( dwarves, outname, types=lambda x, y, z: True,
         functions=allExterns, globalVars=allExterns, modname=modname,
         namespaceFilter=lambda name, space, die: True )

def generateDwarf( binaries, outname, types, functions, header=None, modname=None,
      existingTypes=None, errorfunc=None, globalVars=None, deepInspect=False,
      namelessEnums=False,
      namespaceFilter=lambda name, space, die: name in space.subspaces ):

   resolver = TypeResolver( binaries, types, functions, existingTypes, errorfunc,
         globalVars, deepInspect, namelessEnums, namespaceFilter )
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

   if modname is None:
      modname = outname.split( "." )[ 0 ]
   mod = imp.load_source( modname, outname )
   mod.test_classes()
   resolver.pkgname = modname
   sys.stderr.write( "generated and tested %s\n" % modname )
   return ( mod, resolver )
