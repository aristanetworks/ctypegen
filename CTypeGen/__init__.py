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
import ast
import functools
import operator

from collections import defaultdict

import CTypeGen.expression

# the following modules are dynamically generated inside the C extension.
# pylint should ignore them
import libCTypeGen # pylint: disable=import-error

tags = libCTypeGen.tags
attrs = libCTypeGen.attrs

# Provide aliases for tag names so users don't have to delve into libCTypeGen
ELEMENT_STRUCT = tags.DW_TAG_structure_type
ELEMENT_UNION = tags.DW_TAG_union_type
ELEMENT_CLASS = tags.DW_TAG_class_type
ELEMENT_ENUM = tags.DW_TAG_enumeration_type
ELEMENT_TYPEDEF = tags.DW_TAG_typedef

TAGGED_ELEMENTS = set( [
   ELEMENT_STRUCT,
   ELEMENT_UNION,
   ELEMENT_CLASS,
   ELEMENT_ENUM,
] )

# python3 doesn't have basestring
try:
   baseString = basestring # pylint: disable=basestring-builtin
   PY3=False
except NameError:
   baseString = str
   PY3=True

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
         u"'" : u"_quot",
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

tagPrefixes = {
      tags.DW_TAG_structure_type: "struct_",
      tags.DW_TAG_union_type: "union_",
      tags.DW_TAG_enumeration_type: "enum_",
      }

def flatName( die, withTag=True ):
   ''' A DIE's "flatname" is just the concatenation of its name and enclosed
   scopes with "::", similar to the C++ name. We also give tagged types a
   prefix, like "struct_", to disambiguate them from non-tagged types. Eg: a
   typedef and a struct can have different types, but the same name. '''
   tagPrefix = tagPrefixes.get( die.tag(), "" ) if withTag else ""
   return "%s%s" % ( tagPrefix, "::".join( die.fullname() ) )

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
         "resolver", "die", "defdie", "defined", "declared"
   ]

   def __lt__( self, rhs ):
      return self.die.fullname() < rhs.die.fullname()

   def alignment( self ):
      base = self.baseType()
      return base.alignment() if base else 1

   def __init__( self, resolver, die ):
      self.resolver = resolver
      self.die = die
      self.defdie = None
      self.defined = False
      self.declared = False

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
      pass

   def dieComment( self ):
      if self.pyName() == self.name():
         return u""
      return u"# DIE %s" % self.name()

   def pyName( self, withTag=True ):
      ''' Remove non-python characters from this type's name'''
      return asPythonId( self.name( withTag ) )

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

   def name( self, withTag=True ):
      return flatName( self.die, withTag )

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

   def name( self, withTag=True ):
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

class ExternalType( Type ):
   ''' Any type that appears in one of the existing import modules.
   '''
   def __init__( self, resolver, die, module ):
      super( ExternalType, self ).__init__( resolver, die )
      self.module = module

   def pyName( self, withTag=True ):
      ''' Prefix the pyName with the name of the imported package. '''
      return "%s.%s" % ( self.module.__name__,
                         super( ExternalType, self ).pyName( withTag ) )

class FunctionDefType( FunctionType ):
   ''' A type representing a function declaration. We use these DIEs to
   generate the restype and argtypes fields for ctypes, so we can call
   them with type-safety. '''

   def writeLibUpdates( self, indent, stream ):
      """Write function's prototype to stream"""
      base = self.baseType()
      obj = self.die.object()

      name = self.die.DW_AT_linkage_name
      if name is None:
         name = self.die.name()
      names = []

      # Find all dynamic symbols at the address of this function,
      # and decorate them with the type of the function.
      if self.die.DW_AT_low_pc is not None:
         dynNames = obj.dynaddrs().get( self.die.DW_AT_low_pc )
         if dynNames is not None:
            names += dynNames

      # External functions that get inlined in the translation units may not
      # have a DW_AT_low_pc, so if we have a dynamic symbol that is an exact
      # name match, then use that too.
      if self.die.DW_AT_external and obj.symbol( name ) is not None:
         names += [ name ]

      for linkername in sorted( set( names ) ):
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
      self.pre_pads = []

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
      self.pre_pads = []


# Try and detect empty base classes. If a member is an inheritance type, and
# all it's members are in turn inheritance types, and none have any real data
# members at all, then we ignore the inheritance. (otherwise, we'd pad out the
# type by the sizeof the object, which will be 1, even though it will not
# contribute to the size of the subclass

def isEmptyBase( member ):
   if member.die.tag() != tags.DW_TAG_inheritance:
      return False

   memberType = member.type()
   if isinstance( memberType, ExternalType ):
      return False # give up

   if isinstance( memberType, Typedef ):
      return isEmptyBase(
            memberType.resolver.dieToType( memberType.die.DW_AT_type ) )

   for submember in memberType.members:
      if not isEmptyBase( submember ):
         return False
   return True

def die_size( die ):
   if die.DW_AT_byte_size is not None:
      return die.DW_AT_byte_size

   # clang sometimes doesn't present a size for pointer types. (specifically,
   # for __va_list_tag, which appears to be builtin rather than declared
   # anywhere in a header). We assume that if a pointer doesn't have an
   # explicit size, then its size is the same as the size of a pointer-to-void
   if die.tag() == tags.DW_TAG_pointer_type:
      return ctypes.sizeof( ctypes.c_void_p )

   baseSize = die_size( die.DW_AT_type )
   if die.tag() == tags.DW_TAG_array_type:
      dims = getArrayDimensions( die )
      return functools.reduce( operator.mul, dims, baseSize )
   return baseSize

def die_bit_offset( die ):
   ''' return the bit offset of the bitfield, relative to the lowest address
   of the memory object it occupies '''

   if die.DW_AT_data_bit_offset is not None:
      return die.DW_AT_data_bit_offset
   if die.DW_AT_bit_offset is not None:

      size = die_size( die )

      # XXX: litte-endian specific
      return \
            die.DW_AT_data_member_location * 8 + \
            size * 8 - \
            die.DW_AT_bit_size - \
            die.DW_AT_bit_offset
   return None

class MemberType( Type ):
   ''' A struct, class  or union type - anything that has fields. '''
   __slots__ = [

           "alignment_",
           "anonMembers",
           "base",
           "members",
           "mixins",
           "packed",
           "unalignedPtrs",
           "superCount",

           ]

   def alignment( self ):
      return self.alignment_

   def __init__( self, resolver, die ):
      ''' MemberTypes can accept fieldHints - these are the names of types to
      assign to known fields. If those  are found in the type, then the
      types of the named members will be renamed as appropriate. This is useful
      for anonymous structures, etc, used within struct definitions for their
      fields. '''
      super( MemberType, self ).__init__( resolver, die )
      self.members = []
      self.anonMembers = set()
      self.alignment_ = 0
      self.base = self.ctype_subclass()
      self.mixins = []
      self.packed = False
      self.unalignedPtrs = False
      self.superCount = 0

   def findMembers( self ):
      if self.members:
         return
      self.superCount = 0
      anon_field = 0

      for field in self.definition():
         tag = field.tag()
         if field.DW_AT_external:
            continue
         if tag == tags.DW_TAG_inheritance:
            member = Member( field, self.resolver )
            member.setName( u"__super__%d" % self.superCount )
            self.superCount += 1
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
      super( MemberType, self ).applyHints( spec )
      self.findMembers()
      fieldHints = spec.fieldHints or []

      self.packed = spec.pack
      if spec.base is not None:
         self.base = spec.base
      if spec.mixins is not None:
         self.mixins = spec.mixins
      if spec.unalignedPtrs is not None:
         self.unalignedPtrs = spec.unalignedPtrs

      for member in self.members:
         if member.name() in fieldHints:
            hint = fieldHints[ member.name() ]

            # give a name for a member's type. Useful for anon structs/unions/enums.
            if hint.typename:
               typedesc = hint.typename
               # Allow a simple string for this.
               if not isinstance( typedesc, PythonType ):
                  typedesc = PythonType( typedesc, None )
               # we now know the C name for this type.
               typedesc.cName = member.type().name()

               memberTypeDIE = member.die.DW_AT_type
               typ = self.resolver.dieToType( memberTypeDIE )

               # Now that we have a DIE name for the hint, we can register it
               # with the resolver to have hints applied later.
               self.resolver.applyHintToType( typedesc, typ )

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

      out.write( u'\n' )
      # TestableCtypeClass is a mixin defined in CTypeGenRun, and
      # provides methods on the # generated class to do some consistency
      # checking. The generated code will perform these tests if run as
      # a stand-alone program.
      out.write( u'class %s( %s, TestableCtypeClass' % ( self.pyName(), self.base ) )
      for mixin in self.mixins:
         out.write( ', %s' % mixin )
      out.write( u' ):\n' )
      if self.dieComment():
         out.write( u"   %s\n" % self.dieComment() )
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
      if self.unalignedPtrs:
         out.write( u"%s.allow_unaligned = True\n" % self.pyName() )
      else:
         unaligned = [ m.pyName() for m in self.members if m.allowUnalignedPtr ]
         if unaligned:
            out.write( u"%s.allow_unaligned = %s\n" % ( self.pyName(), unaligned ) )

      self.alignment_ = 1
      packComment = "explicitly requested by type hint"

      if self.members:
         # We must set _pack_ before _fields_, because due to a limitation of ctypes,
         # so accumulate fields in _fields_pre, first as we calculate what to do
         # about packing. 9quoting the 'p' below stops pylint gagging on this file.)
         out.write( u"%s._fields_pre = [ # \x70ylint: disable=protected-access\n" %
               self.pyName() )

         # the bit offset expected for the next field in a bitfield assuming it
         # fits in the current datatype
         expected_bit_offset = 0

         # The expected end location (in bits) of the current data object.
         expected_end = 0

         for memnum, member in enumerate( self.members ):
            if isEmptyBase( member ):
               continue
            fieldOffset = member.die.DW_AT_data_member_location # might be None

            # Make sure we actually have a proper definition of the type for
            # this field. For example, clang++ will not generate the debug info
            # for std::string by default, and we are left with an incomplete
            # type for strings. ctypes has no way of directly controlling the
            # offset for a field, so we need to give the field a type of the
            # correct size, at least - if we don't find a definition for the
            # field's type, then we just make it an array of characters of the
            # appropriate size.
            if not member.type().defined:
               fieldAlignment = 1
               if memnum + 1 < len( self.members ):
                  nextOffset = self.members[ memnum + 1 ].die. \
                          DW_AT_data_member_location
                  size = nextOffset - ( fieldOffset or 0 )
               else:
                  size = self.die.DW_AT_byte_size - ( fieldOffset or 0 )
               typstr = "c_char * %d" % size
               self.resolver.errorfunc(
                     "padded %s:%s (no definition for %s)" % (
                        self.name( withTag=False ), member.name(),
                        member.type().name() ) )
            else:
               fieldAlignment = member.type().alignment()
               typstr = member.ctype()

            # The alignment of this structure/union is the same as the "most
            # aligned" member.
            if fieldAlignment > self.alignment_:
               assert fieldAlignment % self.alignment_ == 0
               self.alignment_ = fieldAlignment

            # Try and handle some of the evil bitfield stuff.
            # Anonymous bitfields don't appear anywhere in the DIE tree
            # that is generated by gcc. We just get gaps in the offsets
            # If we see such a discontinuity, we add a "pre_pads" entry
            # into the field, so when we render it, we can add bitfields
            # into the generated python. Note we may need more than one
            # pad, for example:
            # struct field {
            #    uint32_t a: 16;
            #    uint32_t : 16;
            #    uint32_t : 8
            #    uint32_t b : 16;
            # }
            #
            # In this case,  we need padding for both the first :16 (to move us
            # to the next uint32_t data object), and another :8 (to move us to
            # the correct offset within this data object. we don't try and deal
            # with anonymous bitfields taking up entire data objects before
            # non-bitfield fields.

            fieldDie = member.die
            off = die_bit_offset( fieldDie )
            if off is not None and member.ctypeOverride is None:
               while off >= expected_end:
                  # this field occupies a new data object
                  if fieldDie.DW_AT_bit_size <= expected_end - expected_bit_offset:
                     # This field was preceded by an anonymous one (otherwise,
                     # it'd have been able to fit in the available space.)
                     # Insert padding to consume the remainder of this field
                     padding = expected_end - expected_bit_offset
                     member.pre_pads.append( padding )
                     out.write( u"   ( \"%s\", %s, %d ),\n" %
                        ( "%s_prepad_%d" % ( member.pyName(), expected_end ),
                           typstr, padding ) )
                  # Move on to the next data object.
                  expected_bit_offset = expected_end
                  expected_end = expected_bit_offset + die_size( fieldDie ) * 8

               # add padding for any anonymous fields preceding this one in the
               # same data object.
               diff = off - expected_bit_offset
               if diff != 0:
                  member.pre_pads.append( diff )
                  out.write( u"   ( \"%s\", %s, %d ),\n" %
                     ( "%s_prepad_%d" % ( member.pyName(), expected_end ),
                        typstr, diff ) )

               # The next bitfield in this data object will be directly after
               # this one
               expected_bit_offset = off + fieldDie.DW_AT_bit_size

               out.write( u"   ( \"%s\", %s, %d ),\n" %
                     ( member.pyName(), typstr, member.bit_size() ) )
            else:
               # Regular, non-bitfield member.
               out.write( u"   ( \"%s\", %s ),\n" % ( member.name(), typstr ) )
               byteoff = fieldDie.DW_AT_data_member_location or 0
               if self.definition().tag() != tags.DW_TAG_union_type:
                  # Full data object - if the next object is a bitfield, it'll
                  # appear right after this object.
                  expected_bit_offset = ( byteoff + die_size( fieldDie ) ) * 8
                  expected_end = expected_bit_offset


            # If this field looks unaligned, then the entire type is "packed".
            if fieldOffset is not None and fieldAlignment and not self.packed and \
                  fieldOffset % fieldAlignment != 0:
               self.packed=True
               packComment = "field %s, required alignment %d, offset %d" % (
                       member.name(), fieldAlignment, fieldOffset )

         expected_end //= 8
         residue = expected_end % self.alignment()
         if residue:
            expected_end += self.alignment() - residue

         # If the expected ending position is less than actual ending position,
         # The structure is bigger than we estimated, so it's got some padding
         # at the end. It's probably an unnamed bitfield, but just pad it with
         # characters.
         #
         # We skip the case of a type with no non-inheritance members. For C++,
         # that's probably an empty base type, like a traits type. Adding padding
         # will just make it the wrong size for the "empty base class optimization"
         actual_size = self.definition().DW_AT_byte_size
         if self.definition().tag() != tags.DW_TAG_union_type and \
               expected_end < actual_size and \
               len( self.members ) != self.superCount:
            out.write( u"   ( \"__trailing_pad\", (c_char * %d)),\n" % (
               actual_size - expected_end ) )

         out.write( u"]\n" )

         # If the size of the entire object is not a multiple of the alignment
         # we calculated the type must be packed.
         sz = self.definition().DW_AT_byte_size
         if not self.packed and sz is not None and sz % self.alignment_ != 0:
            self.packed=True
            packComment = "total size %d, field alignment requirement %d" % (
                    sz, self.alignment_ )

         # If this type is packed, then let ctypes know, and set its alignment
         # to 1, because packed types don't need to be aligned in structures.
         if self.packed:
            out.write( u"%s._pack_ = 1 # %s\n" % ( self.pyName(), packComment ) )
            self.alignment_ = 1

         if self.anonMembers:
            out.write( u"%s._anonymous_ = (\n" % self.pyName() )
            for fieldDie in sorted( self.anonMembers ):
               out.write( u"   \"%s\",\n" % fieldDie.pyName() )
            out.write( u"   )\n" )

         # Now that we've worked out what to do with the "pack" field, we can
         # finally assign to the type's _fields_
         out.write( u"%s._fields_ = %s._fields_pre\n" %
               ( self.pyName(), self.pyName() ) )

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

         for _ in member.pre_pads:
            # if we're adding our own padding in front of this member (for anon
            # bitfields), include the padding in the offsets table as "-1". We
            # don't expect anything to access it anyway.
            out.write( u"%s%s" % ( sep, -1 ) )
            sep = u", " if memberCount % 10 != 0 else u",\n    "
            memberCount += 1

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
   __slots__ = [ "nameless" ]

   def __init__( self, resolver, die  ):
      super( EnumType, self ).__init__( resolver, die )
      self.nameless = self.resolver.namelessEnums

   def applyHints( self, spec ):
      if spec.nameless_enum is not None:
         self.nameless = spec.nameless_enum

   def define( self, out ):
      rtype = self.baseType()
      if rtype:
         self.resolver.defineType( rtype, out )
      indent = ''

      out.write( u"class %s( %s ):\n" % ( self.pyName(), self.intType() ) )
      out.write( u'%s_ctypegen_have_definition = True\n' % pad( 3 ) )
      if not self.nameless:
         indent = pad( 3 )
      else:
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
            if self.nameless:
               self.resolver.defined.add( name )
      if childcount == 0:
         out.write( u"%spass\n" % indent )

      out.write( u"\n\n" )
      return True

   def intType( self ):
      typ = self.definition().DW_AT_type
      if typ is None:
         return "c_uint"
      primitive = self.resolver.dieToType( self.definition().DW_AT_type )
      return primitive.pyName()

def _align( _32, _64 ):
   return _32 if ctypes.sizeof( ctypes.c_void_p ) == 4 else _64

class PrimitiveType( Type ):
   ''' Primitive types from DWARF/C: key is the C name. value is a tuple.
   The tuple contains the name of the ctypes equivalent type, the alignment of
   that type.
   '''
   _slots__ = []


   baseTypes = {
         u"long long unsigned int" : ( u"c_ulonglong", _align(4, 8) ),
         u"unsigned long long" : ( u"c_ulonglong", _align(4, 8) ),
         u"long long int" : ( u"c_longlong", _align(4, 8) ),
         u"long long" : ( u"c_longlong", _align(4, 8) ),
         u"long unsigned int" : ( u"c_ulong", _align(4, 8) ),
         u"unsigned long" : ( u"c_ulong", _align( 4, 8 ) ),
         u"sizetype" : ( u"c_ulong", _align( 4, 8 ) ),
         u"short unsigned int" : ( u"c_ushort", _align( 2, 2 ) ),
         u"unsigned short" : ( u"c_ushort", _align( 2, 2 ) ),
         u"unsigned int" : ( u"c_uint", _align( 4, 4 ) ),
         u"unsigned char" : ( u"c_ubyte", _align( 1, 1 ) ),
         u"char16_t" : ( u"c_short", _align( 2, 2 ) ),
         u"signed char" : ( u"c_byte", _align( 1, 1 ) ),
         u"char" : ( u"c_char", _align( 1, 1 ) ),
         u"long int" : ( u"c_long", _align( 4, 8 ) ),
         u"long" : ( u"c_long", _align( 4, 8 ) ),
         u"int" : ( u"c_int", _align( 4, 4 ) ),
         u"short int" : ( u"c_short", _align( 2, 2 ) ),
         u"short" : ( u"c_short", _align( 2, 2 ) ),
         u"__ARRAY_SIZE_TYPE__": ( u"c_ulong", _align( 4, 8 ) ),
         u"float" : ( u"c_float", _align( 4, 4 ) ),
         u"_Bool" : ( u"c_bool", _align( 1, 1 ) ),
         u"bool" : ( u"c_bool", _align( 1, 1 ) ),
         u"double" : ( u"c_double", _align( 4, 8 ) ),
         u"long double" : ( u"c_longdouble", _align( 4, 16 ) ),
         # ctypes has no type for 128 bit floats - do our best.
         # There are no 128-bit ints on 32-bit
         u"_Float128" : ( u"c_longdouble", _align( 16, 16 ) ),
         u"__float128" : ( u"c_longdouble", _align( 16, 16 ) ),
         u"__int128" : ( u"(c_longlong * 2)", _align( None, 16 ) ),
         u"__int128 unsigned" : ( u"(c_ulonglong * 2)", _align( None, 16 ) ),
         u"wchar_t" : ( u"c_wchar", _align( 4, 4 ) ),
         u"char32_t" : ( u"c_int", _align( 4, 4 ) ),
   }

   def alignment( self ):
      name = self.die.DW_AT_name
      if not name in PrimitiveType.baseTypes:
         raise Exception( "no python ctype for primitive C type %s" % name )
      align = PrimitiveType.baseTypes[ name ][ 1 ]
      if align is None:
         if die.DW_AT_encoding == 0x3: # Complex float.
             return die.DW_AT_byte_size / 2
         raise Exception( "no python ctype for primitive C type %s " 
                          "on this architecture" % name )
      return align

   def name( self, withTag=True ):
      return self.ctype()

   def ctype( self ):
      name = self.die.DW_AT_name
      if not name in PrimitiveType.baseTypes:
         defn = self.definition()
         if defn.DW_AT_encoding == 0x3: # Complex float.
            if defn.DW_AT_byte_size == 32:
               return u'(c_longdouble * 2 )'
            if defn.DW_AT_byte_size == 16:
               return u'(c_double * 2 )'
            return u'(c_float * 2 )'

         raise Exception( "no python ctype for primitive C type %s" % name )
      return PrimitiveType.baseTypes[ name ][ 0 ]


def getArrayDimensions( die ):
   dimensions = []
   for child in reversed( [ c for c in die ] ):
      if child.tag() == tags.DW_TAG_subrange_type:
         if child.DW_AT_count is not None:
            dimensions.append( child.DW_AT_count )
         elif child.DW_AT_upper_bound is not None:
            dimensions.append( child.DW_AT_upper_bound + 1 )
         else:
            dimensions.append( 0 )
   return dimensions


class ArrayType( Type ):
   __slots__ = [ "dimensions" ]

   def __init__( self, resolver, die ):
      ''' Find all the array's dimensions so we can calculate size, and ctype '''
      super( ArrayType, self ).__init__( resolver, die )
      self.dimensions = getArrayDimensions( self.definition() )

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

   def alignment( self ):
      return ctypes.sizeof( ctypes.c_void_p )

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
         if t not in r.types:
            r.defineTypes.add( t )
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
      # We must therefore declare the base type first, then declare ourselves,
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

class TypeResolver( object ):

   ''' Construct a python file with a set of Ctypes derived from a
   DWARF-annotated binary '''

   __slots__ = [

         "allHintedTypes",    # any type with a hint - used to create alias names
         "applyHints",        # types we need to apply hints to map from type to hint
         "deepInspect",       # we wish to agressively find types through pointers
         "defineTypes",       # Types we want to define.
         "dwarves",           # The DWARF objects we want to search
         "errorfunc",         # function to call if there's an error
         "errors",            # Errors generated by default error function
         "existingTypes",     # Set of existing CTypegen-generated modules to search
         "functions",         # Functions we've found
         "functionsFilter",   # called to check if we should render a function
         "globalsFilter",     # called to check if we should render a global variable
         "namelessEnums",     # Enum values should not be enclosed in their own class
         "namespaceFilter",   # Called to determine if we should explore a namespace
         "pkgname",           # The name of the package we generate.
         "producers",         # list of distinct producers that contribute to DWARF
         "types",             # All the types we have found
         "typesFilter",       # called to see if we should render a type
         "variables",         # All the variables we want to render
         "defined",

   ]

   def __init__( self, dwarves, typeHints, functions, existingTypes, errorfunc,
                 globalVars, deepInspect, namelessEnums, namespaceFilter ):

      self.dwarves = dwarves

      self.types = {} # index by DIE fullname, then tag.
      self.variables = {} # index by DIE fullname
      self.functions = {} # index by DIE fullname
      self.defineTypes = set()

      self.pkgname = None
      self.existingTypes = existingTypes if existingTypes else []
      self.errorfunc = errorfunc if errorfunc else self.error
      self.errors = 0
      self.producers = set()
      self.applyHints = {}
      self.allHintedTypes = {}
      self.defined = set()

      allNamespaces = set()

      def addNamespace( name ):
         if len( name ) > 1:
            for i in range( 1, len( name ) ):
               allNamespaces.add( name [ :i ] )

      # if we have callable functions for finding things, we can't skip any
      # namespaces. Otherwise, we can optimise by ignoring namespaces we know
      # from the start we don't care about.
      wildcardNamespace = False

      hintsByTypename = {}

      if callable( typeHints ):
         self.typesFilter = typeHints
         wildcardNamespace = True
      else:
         for hint in typeHints:
            if not isinstance( hint, PythonType ):
               hint = PythonType( hint )
            name = tuple( hint.cName.split( "::" ) )
            hintsByTypename[ name ] = hint
            addNamespace( name )

         self.typesFilter = lambda die: die.fullname() in hintsByTypename

      self.deepInspect = deepInspect
      self.namelessEnums = namelessEnums

      # Add all the names we're interested in if supplied with lists, otherwise
      # set appropriate callbacks if the supplied args are callable.

      if callable( globalVars ):
         self.globalsFilter = globalVars
         wildcardNamespace = True
      elif globalVars:
         globalVars = [
               ( n if isinstance( n, tuple ) else tuple( ( n.split( "::" ) ) ) )
                  for n in globalVars ]

         self.globalsFilter = lambda die: die.fullname() in globalVars
         for k in globalVars:
            self.variables[ k ] = None
            addNamespace( k )

      else:
         self.globalsFilter = lambda die: False # no globals

      if callable( functions ):
         self.functionsFilter = functions
         wildcardNamespace = True
      elif functions:
         functions = [ ( n if isinstance( n, tuple ) else
            tuple( ( n.split( "::" ) ) ) ) for n in functions ]
         self.functionsFilter = lambda die: die.fullname() in functions
         for n in functions:
            self.functions[ n ] = None
            addNamespace( n )
      else:
         self.functionsFilter = lambda die: False # no functions

      if namespaceFilter is None:
         if wildcardNamespace:
            self.namespaceFilter = lambda die: True
         else:
            self.namespaceFilter = lambda die: die.fullname() in allNamespaces
      else:
         self.namespaceFilter = namespaceFilter

      for dwarf in self.dwarves:
         for u in dwarf.units():
            self.enumerateDIEs( u.root(), self.examineDIE )

      # We should now have DIEs for everything we care about. For hints the
      # user has given by type name, find the appropriate type for the hint,
      # and register the fact we need to apply that hint to that type.  The
      # same has already been done for a type filter function that returns a
      # PythonType object.
      for name, hint in hintsByTypename.items():
         types = self.types.get( name )
         if types:
            for tag, typ in types.items():
               if hint.elements is None or tag in hint.elements:
                  self.applyHintToType( hint, typ )
         else:
            self.errorfunc( "no type found for %s" % hint.cName )

      # Iterate over all hints that need to be applied
      # For things like anonymous structures where the hint provides a nested
      # hint for a field, we may register more hints to apply, so we repeat the
      # process until an iteration provides no more work to do.
      while True:
         toApply = self.applyHints
         if not toApply:
            break
         self.applyHints = {}
         for typ, hint in toApply.items():
            typ.applyHints( hint )

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
      tag = die.tag()
      name = die.fullname()
      if name not in self.types:
         self.types[ name ] = {}
      bytag = self.types[ name ]
      if tag in bytag:
         return bytag[ tag ]

      # No existing type for this DIE. If we have an existing structure/union
      # type, then take it from one of the existing modules we've imported if
      # that module has the definition. We avoid this for anonymous dies -
      # their names are unique within the context of a single library, but they
      # may collide with names in other libraries, even though it would never
      # make sense to cross-reference from a type in one DSO to an anonymous
      # one in another.
      if die.DW_AT_name is not None:
         pyIdent = asPythonId( flatName( die ) )
         for existingSet in self.existingTypes:
            existingType = getattr( existingSet, pyIdent, None )
            existingModule = getattr(existingType, '__module__', None )
            defined = getattr(existingType, '_ctypegen_have_definition', False )
            if existingModule == existingSet.__name__ and defined:
               newType = ExternalType( self, die, existingSet )
               bytag[ tag ] = newType
               return newType

      newType = typeFromTag[ die.tag() ]( self, die )
      bytag[ tag ] = newType
      return newType

   def applyHintToType( self, hint, typ ):
      self.allHintedTypes[ typ ] = hint
      self.applyHints[ typ ] = hint

   def declareType( self, typ, out ):
      ''' Idempotent wrapper for Type.declare '''
      if typ is None:
         return

      if typ.declared:
         return
      if typ.resolver != self: # This type came from a different module - use as is
         return
      typ.declare( out )
      typ.declared = True

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

      typ.defined = typ.define( out )
      assert typ.defined is not None # typ.define should return a bool.
      if typ.defined:
         self.defined.add( typ.pyName() )
      return typ.defined

   def examineDIE( self, handle, die ):
      ''' Find any potentially interesting dwarf DIEs
      '''

      tag = die.tag()
      if tag == tags.DW_TAG_compile_unit or tag == tags.DW_TAG_partial_unit:
         # Just decend compile units without affecting any namespace scope
         producer = die.DW_AT_producer
         if producer is not None:
            self.producers.add( producer )
         return True

      # Don't automatically generate anything for unnamed types, because the
      # caller can't reference them reliable. The exception is enums, which
      # might provide useful identifiers.
      if die.DW_AT_name is None and tag != tags.DW_TAG_enumeration_type:
         return False

      if tag == tags.DW_TAG_variable:
         if ( self.globalsFilter( die )
              and self.variables.get( die.fullname() ) is None ):
            self.variables[ die.fullname() ] = die
         return False

      # Only consider definitions, not declarations.
      if die.DW_AT_declaration:
         return False

      if tag == tags.DW_TAG_subprogram:
         if self.functions.get( die.fullname() ) is None and \
               self.functionsFilter( die ):
            self.functions[ die.fullname() ] = die
         return False

      if tag in TypeResolver.typeDieTags:
         res = self.typesFilter( die )
         if res:
            typ = self.dieToType( die )
            if isinstance( res, PythonType ):
               self.applyHintToType( res, typ )
            self.defineTypes.add( typ )
         # Type DIEs are also namespaces - deal with namespaces for return
         # below.

      # If its a struct or namespace, and we're interested in any DIEs inside
      # the namespace, descend it.
      if tag in TypeResolver.namespaceDieTags:
         if self.namespaceFilter( die ):
            return True
      return False

   def error( self, txt ):
      self.errors += 1
      sys.stderr.write( "error: %s\n" % txt )

   def enumerateDIEs( self, die, func ):
      if func( self, die ):
         for child in die:
            self.enumerateDIEs( child, func )

   def write( self, stream ):
      ''' Actually write the python file to a stream '''
      stream.write(
u'''from ctypes import * # pylint: disable=wildcard-import
from CTypeGenRun import * # pylint: disable=wildcard-import
# pylint: disable=unnecessary-pass,protected-access


''' )

      for pkg in self.existingTypes:
         stream.write( u"import %s\n" % pkg.__name__ )
      stream.write( u"\n" )

      # Define any types needed by variables or functions, as they may
      # contribute to self.types.

      for name, die in iteritems( self.variables ):
         if die is None:
            self.errorfunc( "variable %s not found" % name )
         else:
            self.defineType( self.dieToType( die.DW_AT_type ), stream )

      for name, die in iteritems( self.functions ):
         if die:
            self.dieToType( die ).define( stream )
         else:
            self.errorfunc( "function %s not found" % name )

      while True:
         # As we define types, in "deepInspect" mode, we may get new types added
         # for each iteration. We keep going until there are no more types.
         types = self.defineTypes
         self.defineTypes = set()
         if not types:
            break
         for t in types:
            self.defineType( t, stream )

      # For any PythonType hints, if the cName != the desired python name, then
      # add an assignment to make them equivalent. This happens for types
      # defined in other, existing, modules too, so we can give them names in
      # this module.
      for typ, hint in sorted( self.allHintedTypes.items() ):
         if hint.pythonName != typ.ctype():
            stream.write( u'%s = %s # python hint differs from ctype\n' % (
                          hint.pythonName, typ.ctype() ) )

      # If tagged types don't conflict with untagged, we can make aliases without
      # the tag prefix
      for name, byTag in self.types.items():
         if len( byTag ) == 1:
            for tag, typ in byTag.items():
               if not isinstance( typ, ExternalType ) and \
                        typ.defined and tag in TAGGED_ELEMENTS:
                  stream.write( "%s = %s # unambiguous name for tagged type\n" % (
                              typ.pyName( False ), typ.pyName( True ) ) )

      # Now write out a class definition containing an entry for each global
      # variable.
      stream.write( u"class Globals(object):\n" )
      stream.write( u"%sdef __init__(self, dll):\n" % pad( 3 ) )

      for _, die in sorted( self.variables.items() ):
         if die is None:
            continue
         t = self.dieToType( die.DW_AT_type )

         cname = die.DW_AT_linkage_name
         if cname is None:
            cname = die.DW_AT_name
         pyName = asPythonId( "::".join( die.fullname() ) )

         stream.write( u"%sself.%s = ( %s ).in_dll( dll, '%s' )\n" %
               ( pad( 6 ), pyName, t.ctype(), cname ) )

      stream.write( u"%spass" % pad( 6 ) )

      ctypesProtos = {}

      stream.write( u'\ndef decorateFunctions( lib ):\n' )

      for _, die in sorted( self.functions.items() ):
         if not die:
            continue
         t = self.dieToType( die )
         t.writeLibUpdates( 3, stream )
         ctypesProtos[ t.pyName() ] = t.ctype()

      stream.write( u'   pass\n' )

      if ctypesProtos:
         stream.write( u"\nfunctionTypes = {\n" )
         for funcName, proto in ctypesProtos.items():
            stream.write( u"   '%s': %s,\n" % ( funcName, proto ) )
         stream.write( u"}" )

      stream.write( u'\n\n' )

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
   ''' Hints for a type the user wants rendered '''

   __slots__ = [

         "base",          # name for the class's base type (instead of
                          # ctypes.Structure, for example)
         "cName",         # name of the C type to find.
         "elements",      # set of DIE tags this applies to (eg,  DW_TAG_structure )
         "fieldHints",    # hints to recursively apply to member fields
         "mixins",        # extra base classes to add to the class definition
         "nameless_enum", # don't put enum values in their own class
         "pack",          # pack this structure.
         "pythonName",    # The name to assign this type in python.
         "unalignedPtrs", # Type can contain unaligned pointers

         ]

   def __init__( self, pythonName, cName=None, base=None, pack=False,
           mixins=None, nameless_enum=None, elements=None, unalignedPtrs=False ):
      if not PY3 and isinstance( pythonName, str ):
         # This is py2 compat code, so pylint: disable=unicode-builtin
         pythonName = unicode( pythonName, 'utf-8' )
      self.pythonName = asPythonId( pythonName )
      self.cName = cName if cName is not None else pythonName
      self.fieldHints = {}
      self.pack = pack
      self.base = base
      self.mixins = mixins
      self.nameless_enum = nameless_enum
      self.elements = elements
      self.unalignedPtrs = unalignedPtrs

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
      handle = lib._handle # pylint: disable=protected-access
      libname = ctypes.cast( handle, ctypes.POINTER( LinkMap ) )[ 0 ].name
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
      namelessEnums=False, namespaceFilter=None, macroFiles=None, trailer=None ):
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
                         namespaceFilter, macroFiles, trailer )

def generateAll( libs, outname, modname=None, macroFiles=None, trailer=None,
      namelessEnums=False, existingTypes=None, skipTypes=None,
      namespaceFilter=None ):
   ''' Simplified "generate" that will generate code for all types, functions,
   and variables in a library '''
   dwarves = getDwarves( libs )

   def externFunc( die ):
      return die.DW_AT_low_pc in die.object().dynaddrs()

   if skipTypes is None:
      skipTypes = []

   def externData( die ):
      name = die.DW_AT_linkage_name if die.DW_AT_linkage_name else die.name()
      return die.object().symbol( name ) is not None

   return generateDwarf( dwarves, outname,
         types=lambda die: die.name() not in skipTypes,
         functions=externFunc,
         globalVars=externData,
         modname=modname,
         macroFiles=macroFiles,
         trailer=trailer,
         namelessEnums=namelessEnums,
         existingTypes=existingTypes,
         namespaceFilter=namespaceFilter )

class MacroCallback( object ):
   def __init__( self, output, interested, resolver ):
      self.filescope = []
      self.interested = interested if callable( interested ) \
                        else lambda f : f in interested
      self.defining = 0
      self.output = output
      self.resolver = resolver

   def define ( self, line, data ):
      if not self.defining:
         return

      firstSpace = data.find( ' ' )
      openParen = data.find( '(' )

      if openParen != -1 and openParen < firstSpace:
         closeParen = data.find( ')', openParen + 1 )
         argStr = data[ openParen : closeParen + 1 ]
         try:
            args = ast.parse( argStr )
            args = args.body[0].value
         except SyntaxError:
            return
         if isinstance( args, ast.Name ):
            macroArgs = [ args.id ]
         elif PY3 and isinstance( args,
               ast.Constant ): # pylint: disable=no-member
            macroArgs = [ args.value ]
         else:
            macroArgs = [
               elt.value
               if PY3 and isinstance( elt, ast.Constant ) # pylint: disable=no-member
               else elt.id for elt in args.elts ]
         name = data[ 0:openParen ]
         value = data[ closeParen + 1: ]
      else:
         # no-arg macro.
         macroArgs = None
         name = data[ 0:firstSpace ]
         value = data[ firstSpace + 1: ]

      if name in self.resolver.defined:
         return

      # If a previous module has defined the macro, avoid the duplication.
      if any( name in other.__dict__ for other in self.resolver.existingTypes ):
         return

      if value == "":
         value = "None"
      else:
         newvalue, names = CTypeGen.expression.clean( value )
         if newvalue is None:
            return
         value = newvalue
         if name == value:
            return
         for n in names:
            if not ( n in self.resolver.defined or macroArgs and n in macroArgs ):
               return

      self.resolver.defined.add( name )

      # some macros may not be evaluatable. For example, casts look like
      # expressions: we have:
      #
      # #define SIG_ERR ((sighandler_t) -1 )
      #
      # If sighandler_t is an int, then this is an arithmentic expression. If
      # its a type, then its a type cast. We don't discriminate when parsing
      # the AST so wrap macros in try/catch
      self.output.write("try:\n")
      if macroArgs is not None:
         self.output.write( "   def %s%s: return %s" % ( name, argStr, value ) )
      else:
         self.output.write( "   %s = %s" % ( name, value ) )
      self.output.write( " # %s:%d\n" % ( self.filescope[ -1 ][ 1 ], line ) )
      self.output.write( "except:\n" )
      self.output.write( "   __ctypegen_failed_macros.append('%s')\n" % name )


   def undef( self, line, data ):
      pass

   def startFile( self, line, dirname, filename ):
      self.filescope.append( ( dirname, filename ) )
      if self.interested( filename ):
         self.defining += 1

   def endFile( self ):
      ( _, filename ) = self.filescope.pop()
      if self.interested( filename ):
         self.defining -= 1

def generateDwarf( binaries, outname, types, functions, header=None, modname=None,
      existingTypes=None, errorfunc=None, globalVars=None, deepInspect=False,
      namelessEnums=False,
      namespaceFilter=None,
      macroFiles=None,
      trailer=None ):

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

      content.write( "__ctypegen_failed_macros = []\n" )
      content.write( "# Macro definitions:\n" )
      if macroFiles is not None:
         macros = MacroCallback( content, macroFiles, resolver )
         for binary in binaries:
            for unit in binary.units():
               unit.macros( macros )
      content.write( "# (end Macro definitions)\n\n" )


      content.write("CTYPEGEN_SONAMES = [\n")
      for b in binaries:
         content.write("\t'%s',\n" % b.soname())
      content.write("]\n")

      content.write("""
# Use this to return a CDLL handle that has functions decorate with type info.
def decoratedLib( idx = 0 ):
      lib = ctypes.CDLL( CTYPEGEN_SONAMES[ idx ] )
      if lib:
         decorateFunctions( lib )
      return lib

""")

      content.write( "CTYPEGEN_producers__ = {\n" )
      for p in sorted( resolver.producers ):
         content.write( "\t\"%s\",\n" % p )
      content.write( "}\n" )

      # Make the whole shebang test itself when run.
      content.write( u'\nif __name__ == "__main__":\n' )
      content.write( u'   test_classes( __ctypegen_failed_macros )\n' )

      if trailer is not None:
         content.write( trailer )

   if modname is None:
      modname = outname.split( "." )[ 0 ]
   mod = imp.load_source( modname, outname )
   # pylint: disable=protected-access
   mod.test_classes( mod.__ctypegen_failed_macros )
   # pylint: enable=protected-access
   resolver.pkgname = modname
   sys.stderr.write( "generated and tested %s\n" % modname )
   return ( mod, resolver )
