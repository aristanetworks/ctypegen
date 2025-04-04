/*
   Copyright 2017 Arista Networks.

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

       Unless required by applicable law or agreed to in writing, software
       distributed under the License is distributed on an "AS IS" BASIS,
       WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
       See the License for the specific language governing permissions and
       limitations under the License.
*/

#ifdef __clang__
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wregister"
#endif
#define PY_SSIZE_T_CLEAN 1
#include <Python.h>
#ifdef __clang__
#pragma GCC diagnostic pop
#endif
#include <structmember.h>

#include <iostream>
#include <memory>
#include <set>
#include <sstream>
#include <vector>

#include <libpstack/elf.h>
#include <libpstack/dwarf.h>
#include <libpstack/stringify.h>

using namespace pstack;
namespace {

/*
 * descriptors for the types implemented here.
 */
static PyTypeObject elfObjectType = { PyObject_HEAD_INIT( 0 ) 0 };
static PyTypeObject unitsType = { PyObject_HEAD_INIT( 0 ) 0 };
static PyTypeObject unitsIteratorType = { PyObject_HEAD_INIT( 0 ) 0 };
static PyTypeObject dwarfEntryType = { PyObject_HEAD_INIT( 0 ) 0 };
static PyTypeObject dwarfEntryIteratorType = { PyObject_HEAD_INIT( 0 ) 0 };
static PyTypeObject dwarfTagsType = { PyObject_HEAD_INIT( 0 ) 0 };
static PyTypeObject dwarfBaseTypeEncodingsType = { PyObject_HEAD_INIT( 0 ) 0 };
static PyTypeObject dwarfAttrsType = { PyObject_HEAD_INIT( 0 ) 0 };
static PyTypeObject unitType = { PyObject_HEAD_INIT( 0 ) 0 };

static PyObject * attrnames; // attribute name -> value mapping
static PyObject * attrvalues; // attribute value -> name mapping
static PyObject * tagnames;

// These are the DWARF tags for DIEs that introduce a new namespace in C/C++
static std::set< Dwarf::Tag > namespacetags = {
   Dwarf::DW_TAG_structure_type,
   Dwarf::DW_TAG_namespace,
   Dwarf::DW_TAG_class_type,
   Dwarf::DW_TAG_union_type,
};

} // namespace

extern "C" {

// clang-format off
// The formatter does not like the PyObject_HEAD macros in the start of python
// objects - they look like types preceding a field name. Disable while
// we define our structure types.

/*
 * Python representaiton of a loaded ELF object and it's DWARF debug data.
 */

typedef struct {
   PyObject_HEAD
   Elf::Object::sptr obj;
   Dwarf::Info::sptr dwarf;
   PyObject *dynaddrs; // dict mapping address to list-of-dynamic name
   int fileId;
} PyElfObject;

// Give each file loaded a unique ID to ensure anonymous names are unique
static std::map< const Dwarf::Info *, PyElfObject * > openFiles;
static int nextFileId = 1;

/*
 * Python representaiton of the "Units" collection from an object.
 * This provides a forward iterator over the units of the object.
 */
typedef struct {
   PyObject_HEAD
   Dwarf::Units units;
} PyUnits;

/*
 * Python representation of an iterator over the child DIEs of a parent DIE
 */
typedef struct {
   PyObject_HEAD
   Dwarf::DIE::Children::const_iterator begin;
   Dwarf::DIE::Children::const_iterator end;
} PyDwarfEntryIterator;

/*
 * Python representation of an iterator over the Units in an object.
 */
typedef struct {
   PyObject_HEAD
   Dwarf::Units::iterator begin;
   Dwarf::Units::iterator end;
} PyDwarfUnitIterator;

/*
 * Python representaiton of a DWARF Unit
 */
typedef struct {
   PyObject_HEAD
   Dwarf::Unit::sptr unit;
} PyDwarfUnit;

/*
 * Python representaiton of a DWARF information entry. (a DIE)
 */
typedef struct {
   PyObject_HEAD
   Dwarf::DIE die;
   PyObject * fullName;
} PyDwarfEntry;

/*
 * Tabulate objects, members, and init functions for "attrs" and "types" objects
 * inside the libCTypeGen namespace that can be used to access the DWARF attribute
 * and tags values symbolically.
 */
typedef struct {
   PyObject_HEAD
#define DWARF_ATTR( name, value ) int name;
#include <libpstack/dwarf/attr.h>
#undef DWARF_ATTR
} PyDwarfAttrsObject;

typedef struct {
   PyObject_HEAD
#define DWARF_TAG( name, value ) int name;
#include <libpstack/dwarf/tags.h>
#undef DWARF_TAG
} PyDwarfTagsObject;

typedef struct {
   PyObject_HEAD
#define DWARF_ATE( name, value ) int name;
#include <libpstack/dwarf/encodings.h>
#undef DWARF_ATE
} PyDwarfBaseTypeEncodingsObject;

// clang-format on

struct PyMemberDef attr_members[] = {
#define DWARF_ATTR( name, value )                                                   \
   { ( char * )#name,                                                               \
     T_INT,                                                                         \
     offsetof( PyDwarfAttrsObject, name ),                                          \
     0,                                                                             \
     ( char * )#name },
#include <libpstack/dwarf/attr.h>
#undef DWARF_ATTR
   { NULL }
};

struct PyMemberDef tag_members[] = {
#define DWARF_TAG( name, value )                                                    \
   { ( char * )#name,                                                               \
     T_INT,                                                                         \
     offsetof( PyDwarfTagsObject, name ),                                           \
     0,                                                                             \
     ( char * )#name },
#include <libpstack/dwarf/tags.h>
#undef DWARF_TAG
   { NULL }
};

struct PyMemberDef ate_members[] = {
#define DWARF_ATE( name, value )                                                    \
   { ( char * )#name,                                                               \
     T_INT,                                                                         \
     offsetof( PyDwarfBaseTypeEncodingsObject, name ),                              \
     0,                                                                             \
     ( char * )#name },
#include <libpstack/dwarf/encodings.h>
#undef DWARF_ATE
   { NULL }
};
}

namespace {
/*
 * Return the name of a DIE.
 * If the DIE has a name attribute, that's returned.
 * If not, we fabricate an anonymous name based on the DIEs offset.
 */
static std::string
dieName( const Dwarf::DIE & die ) {
   const Dwarf::DIE::Attribute & name = die.attribute( Dwarf::DW_AT_name );
   if ( name.valid() )
      return std::string( name );

   std::ostringstream os;
   auto it = openFiles.find(die.getUnit()->dwarf);
   // We may not have an open file if we have a separate DWZ splitdwarf object.
   // For such a split image, we'll only have one for all units, so just use a
   // large fixed ID.
   int id = it != openFiles.end() ? it->second->fileId : 1000000;

   os << "anon_" << id << "_" << die.getOffset();
   switch ( die.tag() ) {
    case Dwarf::DW_TAG_structure_type:
      os << "_struct";
      break;
    case Dwarf::DW_TAG_class_type:
      os << "_class";
      break;
    case Dwarf::DW_TAG_union_type:
      os << "_union";
      break;
    case Dwarf::DW_TAG_enumeration_type:
      os << "_enum";
      break;
    default:
      break;
   }
   return os.str();
}

/*
 * For DIE nested in namespaces, construct a sequence in a std container for
 * it's name and containing namespaces, from outer to inner.
 */
template< typename container >
static void
getFullName( const Dwarf::DIE & die, container & fullname, bool leaf = true ) {
   auto spec = die.attribute( Dwarf::DW_AT_specification );
   if ( spec.valid() ) {
      return getFullName( Dwarf::DIE( spec ), fullname, leaf );
   }
   if ( die.getParentOffset() != 0 ) {
      const Dwarf::DIE & parent =
         die.getUnit()->offsetToDIE( Dwarf::DIE(), die.getParentOffset() );
      getFullName( parent, fullname, false );
   }
   if ( leaf || namespacetags.find( die.tag() ) != namespacetags.end() ) {
      fullname.push_back( dieName( die ) );
   }
}

/*
 * DIEs with the DW_AT_declaration attribute set are indicative of an incomplete
 * type (eg, "struct foo;". Typedefs can refer to such DIEs, in which case
 * we need to find the actual definition to fulfill the output of the typedef.
 * "findDefinition" finds a defining DIE (one with no DW_AT_declaration attribute)
 * for a declaration DIE with the same name/scope.
 *
 * arguments:
 * die: the node of the tree we wish to search.
 * tag: the tag of the original DIE
 * first/end: the remaining scopes in the DIEs name (when die is the root node, these
 * are the name of the DIE we want split into its component namespaces)
 */
template< typename T >
static Dwarf::DIE
findDefinition( const Dwarf::DIE & die,
                Dwarf::Tag tag,
                typename T::iterator first,
                typename T::iterator end ) {
   const auto & nameA = die.attribute( Dwarf::DW_AT_name );
   const bool sameName = nameA.valid() && std::string( nameA ) == *first;

   if ( end - first == 1 ) {
      /*
       * We've decended all the namespaces - this is the leaf of the name.  We
       * have a match if its the right name, if the DIE we're looking at is not
       * a declaration, and it's also got the same type as what we're looking
       * for.
       */
      const auto & declA = die.attribute( Dwarf::DW_AT_declaration );
      if ( sameName && !bool( declA ) && tag == die.tag() )
         return die;
   }

   /*
    * If the current DIE is a namespace, and the name matches the next namesspace
    * we are intereted in, then descend down it.
    */
   switch ( die.tag() ) {
    case Dwarf::DW_TAG_namespace:
    case Dwarf::DW_TAG_structure_type:
    case Dwarf::DW_TAG_class_type:
      if ( !sameName )
         return Dwarf::DIE();
      first++;
      if ( end == first )
         return Dwarf::DIE();
      // FALLTHROUGH

    case Dwarf::DW_TAG_compile_unit:
      // Compile units are a bit special - we just fall into them, but they don't
      // consume a namespace.
      for ( const auto &c : die.children() ) {
         const auto ischild = findDefinition< T >( c, tag, first, end );
         if ( ischild )
            return ischild;
      }
      break;
    default:
      break;
   }
   return Dwarf::DIE();
}

/*
 * Convert C++ string to python string.
 */
static PyObject *
makeString( const std::string & s ) {
   return PyUnicode_FromString( s.c_str() );
}

/* Get a reference to python's true or false values. */
static PyObject *
pythonBool( bool cbool ) {
   PyObject * pybool = cbool ? Py_True : Py_False;
   Py_INCREF( pybool );
   return pybool;
};

/* Implement a basic "rich compare" given a long difference between two values */
static PyObject *
richCompare( long diff, int op ) {
   switch ( op ) {
    case Py_EQ:
      return pythonBool( diff == 0 );
    case Py_NE:
      return pythonBool( diff != 0 );
    case Py_GT:
      return pythonBool( diff > 0 );
    case Py_GE:
      return pythonBool( diff >= 0 );
    case Py_LT:
      return pythonBool( diff < 0 );
    case Py_LE:
      return pythonBool( diff <= 0 );
    default:
      Py_INCREF( Py_NotImplemented );
      return Py_NotImplemented;
   }
}

} // namespace

extern "C" {

static int
attr_init( PyObject * object, PyObject * args, PyObject * kwds ) {
   auto attrs = ( PyDwarfAttrsObject * )object;
#define DWARF_ATTR( name, value ) attrs->name = value;
#include <libpstack/dwarf/attr.h>
#undef DWARF_ATTR
   return 0;
};

static PyObject *
make_attrnames() {
   auto namedict = PyDict_New();
#define DWARF_ATTR( name, value )                                                   \
   {                                                                                \
      auto v = makeString( #name );                                                 \
      auto k = PyLong_FromLong( value );                                            \
      PyDict_SetItem( namedict, k, v );                                             \
      Py_DECREF( k );                                                               \
      Py_DECREF( v );                                                               \
   }

#include <libpstack/dwarf/attr.h>
#undef DWARF_ATTR
   return namedict;
};

static PyObject *
make_attrvalues() {
   auto valuedict = PyDict_New();
#define DWARF_ATTR( name, value )                                                   \
   {                                                                                \
      auto val = PyLong_FromLong( value );                                          \
      PyDict_SetItemString( valuedict, #name, val );                                \
      Py_DECREF( val );                                                             \
   }
#include <libpstack/dwarf/attr.h>
#undef DWARF_ATTR
   return valuedict;
};

static PyObject *
make_tagnames() {
   auto namedict = PyDict_New();
#define DWARF_TAG( name, value )                                                    \
   {                                                                                \
      auto k = PyLong_FromLong( value );                                            \
      auto v = makeString( #name );                                                 \
      PyDict_SetItem( namedict, k, v );                                             \
      Py_DECREF( k );                                                               \
      Py_DECREF( v );                                                               \
   }
#include <libpstack/dwarf/tags.h>
#undef DWARF_TAG
   return namedict;
};

static int
tags_init( PyObject * object, PyObject * args, PyObject * kwds ) {
   auto tags = ( PyDwarfTagsObject * )object;
#define DWARF_TAG( name, value ) tags->name = value;
#include <libpstack/dwarf/tags.h>
#undef DWARF_TAG
   return 0;
};

static int
ates_init( PyObject * object, PyObject * args, PyObject * kwds ) {
   auto ates = ( PyDwarfBaseTypeEncodingsObject * )object;
#define DWARF_ATE( name, value ) ates->name = value;
#include <libpstack/dwarf/encodings.h>
#undef DWARF_ATE
   return 0;
};

static PyObject *
makeUnit( const Dwarf::Unit::sptr & unit ) {
   PyDwarfUnit * value = PyObject_New( PyDwarfUnit, &unitType );
   new ( &value->unit ) Dwarf::Unit::sptr( unit );
   return ( PyObject * )value;
}

static PyObject *
unit_compare( PyObject * lhso, PyObject * rhso, int op ) {
   if ( Py_TYPE( rhso ) != &unitType ) {
      Py_INCREF( Py_NotImplemented );
      return Py_NotImplemented;
   }

   auto * lhs = ( PyDwarfUnit * )lhso;
   auto * rhs = ( PyDwarfUnit * )rhso;

   auto diff = lhs->unit->dwarf->elf.get() - rhs->unit->dwarf->elf.get();
   if ( !diff )
      diff = lhs->unit->offset - rhs->unit->offset;
   return richCompare( diff, op );
}

static void
unit_free( PyObject * o ) {
   PyDwarfUnit * value = ( PyDwarfUnit * )o;
   value->unit.std::shared_ptr< Dwarf::Unit >::~shared_ptr();
   unitType.tp_free( o );
}

static PyObject *
makeFullnameR( const Dwarf::DIE & die, int depth ) {
   auto spec = die.attribute( Dwarf::DW_AT_specification );
   if ( spec.valid() ) {
      return makeFullnameR( Dwarf::DIE( spec ), depth );
   }
   auto poff = die.getParentOffset();
   PyObject *tuple;
   bool thisCounts = depth == 0 || namespacetags.find( die.tag() ) != namespacetags.end();
   int nextDepth = thisCounts ? depth  + 1 : depth;
   if (poff != 0) {
      tuple = makeFullnameR( die.getUnit()->offsetToDIE( Dwarf::DIE(), poff ), nextDepth );
   } else {
      tuple = PyTuple_New( nextDepth );
   }
   if ( thisCounts ) {
      int idx = PyTuple_Size( tuple ) - depth - 1;
      assert(idx >= 0 && idx < PyTuple_Size( tuple ));
      PyTuple_SET_ITEM( tuple, idx, makeString( dieName( die ) ) );
   }
   return tuple;
}

static PyObject *
makeFullname( const Dwarf::DIE & die ) {
   return makeFullnameR( die, 0);
}

static PyObject *
makeEntry( const Dwarf::DIE & die ) {
   PyDwarfEntry * value = PyObject_New( PyDwarfEntry, &dwarfEntryType );
   new ( &value->die ) Dwarf::DIE( die );
   value->fullName = nullptr;
   return ( PyObject * )value;
}

static PyObject *
unit_root( PyObject * self, PyObject * args ) {
   PyDwarfUnit * unit = ( PyDwarfUnit * )self;
   return makeEntry( unit->unit->root() );
}

struct PythonMacros : public Dwarf::MacroVisitor {
   Dwarf::Unit::csptr unit;
   PyObject *callback;
   PythonMacros(const Dwarf::Unit::csptr &unit_, PyObject *callback_) :
      unit { unit_ }, callback { callback_ } {}

   bool define( int line, const std::string &definition ) override {
      PyObject *o = PyObject_CallMethod( callback, (char *)"define", (char *)"is",
                                         line, definition.c_str() );
      if ( !o )
         return false;
      Py_DECREF( o );
      return true;
   }

   bool undef( int line, const std::string &definition ) override {
      PyObject *o = PyObject_CallMethod( callback, (char *)"undef",
                                         (char *)"is", line, definition.c_str() );
      if ( !o )
         return false;
      Py_DECREF( o );
      return true;
   }

   bool startFile( int line, const std::string &dir, const Dwarf::FileEntry &ent )
                   override {
      PyObject *o = PyObject_CallMethod( callback, (char *)"startFile",
                                         (char *)"iss", line, dir.c_str(),
                                         ent.name.c_str() );
      if ( !o )
         return false;
      Py_DECREF( o );
      return true;
   }

   bool endFile() override {
      PyObject *o = PyObject_CallMethod( callback, (char *)"endFile", NULL );
      if ( !o )
         return false;
      Py_DECREF( o );
      return true;
   }
};

static PyObject *
unit_macros( PyObject * self, PyObject * args ) {
   auto unit = ( ( PyDwarfUnit * )self )->unit;

   PyObject *callback;
   if ( !PyArg_ParseTuple( args, "O", &callback ) )
      return nullptr;

   const Dwarf::Macros *macros = unit->getMacros();
   if ( macros != nullptr ) {
      PythonMacros visitor( unit, callback );
      if ( !macros->visit( *unit, &visitor ) )
         return nullptr;
   }
   Py_RETURN_NONE;
}

static PyObject *
unit_purge( PyObject * self, PyObject * args ) {
   PyDwarfUnit * unit = ( PyDwarfUnit * )self;
   unit->unit->purge();
   Py_RETURN_NONE;
}

static pstack::Context context;

static PyObject *
elf_open( PyObject * self, PyObject * args ) {
   try {
      const char * image;
      Py_ssize_t imagelen;
      if ( !PyArg_ParseTuple( args, "s#", &image, &imagelen ) )
         return nullptr;
      auto dwarf = context.getDwarf( image );
      auto &it = openFiles[ dwarf.get()];
      if ( it != nullptr ) {
         // We already have a handle on this file - return the existing object.
         Py_INCREF( it );
         return (PyObject *)it;
      }
      auto obj = dwarf->elf;
      PyElfObject * val = PyObject_New( PyElfObject, &elfObjectType );
      new ( &val->obj ) std::shared_ptr< Elf::Object >( obj );
      new ( &val->dwarf ) std::shared_ptr< Dwarf::Info >( dwarf );
      val->dynaddrs = nullptr;

      // DW_AT_linker_name attributes refer to the name of the symbol in .symtabv
      // We are more interested in the name for dynamic linking - so we can decorate
      // its types, and refer to it for mocking. These maps allow us to convert from
      // a DW_AT_linker_name to an address, and from there to a list of candidate
      // dynamic symbols at that address. They don't always match up, because of
      // aliases, weak bindings, etc.
      it = val;
      val->fileId = nextFileId++;
      return ( PyObject * )val;
   } catch ( const std::exception & ex ) {
      PyErr_SetString( PyExc_RuntimeError, ex.what() );
      return nullptr;
   }
}

static PyObject *
elf_verbose( PyObject * self, PyObject * args ) {
   int verbosity;
   if ( !PyArg_ParseTuple( args, "I", &verbosity ) )
      return nullptr;
   context.verbose = verbosity;
   Py_RETURN_NONE;
}

static PyObject *
elf_units( PyObject * self, PyObject * args ) {
   try {
      PyElfObject * elf = ( PyElfObject * )self;
      PyUnits * units = PyObject_New( PyUnits, &unitsType );
      new ( &units->units ) Dwarf::Units( elf->dwarf->getUnits() );
      return ( PyObject * )units;
   } catch ( const std::exception & ex ) {
      PyErr_SetString( PyExc_RuntimeError, ex.what() );
      return nullptr;
   }
}

static PyObject *
elf_soname( PyObject * self, PyObject * args ) {
   try {
      PyElfObject * pyelf = ( PyElfObject * )self;

      auto &elf = pyelf->dwarf->elf;

      // Grab the PT_DYNAMIC header.
      for ( auto &segment : elf->getSegments( PT_DYNAMIC ) ) {
         OffsetReader dynReader("dynamic segment", elf->io, segment.p_offset,
                                segment.p_filesz);
         constexpr Elf::Off NOT_FOUND = std::numeric_limits<Elf::Off>::max();
         Elf::Off soname = NOT_FOUND;
         Elf::Off strtab = NOT_FOUND;

         for (const auto &i : ReaderArray<Elf::Dyn>(dynReader)) {
            switch (i.d_tag) {
               case DT_STRTAB:
                  strtab = i.d_un.d_ptr;
                  break;
               case DT_SONAME:
                  soname = i.d_un.d_ptr;
                  break;
            }
         }
         if (soname == NOT_FOUND || strtab == NOT_FOUND)
            continue;

         auto strings = elf->getSegmentForAddress(strtab);
         if (strings == nullptr)
            continue;
         return makeString( elf->io->readString(
                  strings->p_offset + strtab + soname - strings->p_vaddr ) );
      }
      Py_RETURN_NONE;
   } catch ( const std::exception & ex ) {
      PyErr_SetString( PyExc_RuntimeError, ex.what() );
      return nullptr;
   }
}


/*
 * Returns a dict mapping names from .symtab (debug symbols) to a list of names
 * in .dynsym (used for linking). The Dwarf tree matches what's in the debug
 * table, but the dynamic section can name things a little differently
 */

static PyObject *
elf_dynaddrs( PyObject * self, PyObject * args ) {
   PyElfObject * pyelf = ( PyElfObject * )self;
   if ( pyelf->dynaddrs == nullptr ) {
      pyelf->dynaddrs = PyDict_New();
      std::map< Elf::Addr, PyObject * > addr2dynname;
      auto obj = pyelf->dwarf->elf;

      auto dynsyms = obj->dynamicSymbols();
      // First, create mapping from addr to list-of-dynamic-name
      if (dynsyms) {
         auto start = dynsyms->begin();
         for ( auto symi = start; symi != dynsyms->end(); ++symi) {
            const auto & sym = *symi;
            if ( sym.st_shndx == SHN_UNDEF )
               continue;
            auto veridx = obj->versionIdxForSymbol(symi - start);
            if ( veridx.isHidden() )
               continue;
            auto name = dynsyms->name( sym );
            if (name == "")
               continue;
            auto & list = addr2dynname[ sym.st_value ];
            if ( list == nullptr ) {
               list = PyList_New( 0 );
            }
            auto str = makeString( dynsyms->name( sym ) );
            PyList_Append( list, str );
            Py_DECREF( str ); // PyList_Append doesn't steal a ref, so release ours.
         }
      }

      for ( auto &&[addr, list] : addr2dynname ) {
         auto key = PyLong_FromLong( addr );
         PyDict_SetItem( pyelf->dynaddrs, key, list );
         // PyDict_SetItem doesn't steal references.
         Py_DECREF( key );
         Py_DECREF( list );
      }
   }
   Py_INCREF( pyelf->dynaddrs );
   return pyelf->dynaddrs;
}

static PyObject *
elf_symbol( PyObject * self, PyObject * args ) {
   PyElfObject * pyelf = ( PyElfObject * )self;
   const char *name = nullptr;
   if ( !PyArg_ParseTuple( args, "s", &name ) ) {
      return nullptr;
   }
   auto [sym,idx] = pyelf->dwarf->elf->findDynamicSymbol(name);
   if ( sym.st_shndx == SHN_UNDEF )
      Py_RETURN_NONE;
   return PyLong_FromLong ( sym.st_value );
}

static PyObject *
elf_findDefinition( PyObject * self, PyObject * args ) {
   PyDwarfEntry * die;
   PyElfObject * elf = ( PyElfObject * )self;
   if ( !PyArg_ParseTuple( args, "O", &die ) )
      return nullptr;
   std::vector< std::string > namelist;
   getFullName( die->die, namelist );
   for ( const auto & u : elf->dwarf->getUnits() ) {
      const auto & top = u->root();
      const auto & defn = findDefinition< std::vector< std::string > >(
         top, die->die.tag(), namelist.begin(), namelist.end() );
      if ( defn )
         return makeEntry( defn );
   }
   Py_INCREF( Py_None );
   return Py_None;
}

static PyObject *
elf_flush( PyObject * self, PyObject * args ) {
   try {
      PyElfObject * elf = ( PyElfObject * )self;
      context.flush( elf->obj );
   } catch ( std::exception & ex ) {
      PyErr_SetString( PyExc_RuntimeError, ex.what() );
      return nullptr;
   }
   Py_RETURN_NONE;
}

static void
elf_free( PyObject * o ) {
   PyElfObject * pye = ( PyElfObject * )o;
   openFiles.erase( pye->dwarf.get() );
   pye->obj.std::shared_ptr< Elf::Object >::~shared_ptr< Elf::Object >();
   pye->dwarf.std::shared_ptr< Dwarf::Info >::~shared_ptr< Dwarf::Info >();
   if ( pye->dynaddrs != nullptr )
      Py_DECREF( pye->dynaddrs );
   elfObjectType.tp_free( o );
}

static int
units_asnumber_bool( PyObject * o ) {
   PyUnits * pye = ( PyUnits * )o;
   return pye->units.begin() == pye->units.end() ? 0 : 1;
};


static void
units_free( PyObject * o ) {
   PyUnits * pye = ( PyUnits * )o;
   pye->units.Units::~Units();
   unitsType.tp_free( o );
}

static PyObject *
entry_type( PyObject * self, PyObject * args ) {
   PyDwarfEntry * ent = ( PyDwarfEntry * )self;
   return PyLong_FromLong( ent->die.tag() );
}

static PyObject *
entry_object( PyObject * self, PyObject * args ) {
   PyDwarfEntry * ent = ( PyDwarfEntry * )self;
   PyElfObject * pyelf = openFiles[ ent->die.getUnit()->dwarf ];
   Py_INCREF( pyelf );
   return ( PyObject * )pyelf;
}

static PyObject *
entry_unit( PyObject * self, PyObject * args ) {
   PyDwarfEntry * ent = ( PyDwarfEntry * )self;
   return makeUnit( ent->die.getUnit() );
}

static PyObject *
entry_parent( PyObject * self, PyObject * args ) {
   PyDwarfEntry * ent = ( PyDwarfEntry * )self;
   if ( ent->die.getParentOffset() != 0 ) {
      auto parent = ent->die.getUnit()->offsetToDIE( Dwarf::DIE(),
                                                     ent->die.getParentOffset() );
      return makeEntry( parent );
   }
   Py_RETURN_NONE;
}

/*
 * DIEs have offsets within their unit, and the units have offsets within the
 * DWARF section they are defined in.
 * We compare two dies by comparing the offsets of their units first, and then
 * the offsets of the DIEs themselves.
 */
static PyObject *
entry_compare( PyObject * lhso, PyObject * rhso, int op ) {
   if ( Py_TYPE( rhso ) != &dwarfEntryType || Py_TYPE( lhso ) != &dwarfEntryType ) {
      Py_INCREF( Py_NotImplemented );
      return Py_NotImplemented;
   }

   PyDwarfEntry * lhs = ( PyDwarfEntry * )lhso;
   PyDwarfEntry * rhs = ( PyDwarfEntry * )rhso;

   size_t diff = lhs->die.getUnit()->offset - rhs->die.getUnit()->offset;
   if ( diff == 0 )
      diff = lhs->die.getOffset() - rhs->die.getOffset();
   return richCompare( op, diff );
}

#if PY_MAJOR_VERSION >= 3
typedef Py_hash_t hashfunc_result;
#else
typedef long hashfunc_result;
#endif
hashfunc_result
entry_hash( PyObject * self ) {
   PyDwarfEntry * ent = ( PyDwarfEntry * )self;
   return hashfunc_result( ent->die.getOffset() ^ ent->die.getUnit()->offset );
}

/*
 * Provide an iterator over the children of a DIE.
 */
static PyObject *
entry_iterator( PyObject * self ) {
   try {
      PyDwarfEntry * ent = ( PyDwarfEntry * )self;
      PyDwarfEntryIterator * it =
         PyObject_New( PyDwarfEntryIterator, &dwarfEntryIteratorType );
      Dwarf::DIE::Children list = ent->die.children();
      new ( &it->begin ) Dwarf::DIE::Children::const_iterator( list.begin() );
      new ( &it->end ) Dwarf::DIE::Children::const_iterator( list.end() );
      return ( PyObject * )it;
   } catch ( const std::exception & ex ) {
      PyErr_SetString( PyExc_RuntimeError, ex.what() );
      return nullptr;
   }
}

/*
 * Provide an iterator over the children of a DIE.
 */
static PyObject *
units_iterator( PyObject * self ) {
   try {
      PyUnits * units = ( PyUnits * )self;
      PyDwarfUnitIterator * it =
         PyObject_New( PyDwarfUnitIterator, &unitsIteratorType );
      new ( &it->begin ) Dwarf::Units::iterator( units->units.begin() );
      new ( &it->end ) Dwarf::Units::iterator( units->units.end() );
      return ( PyObject * )it;
   } catch ( const std::exception & ex ) {
      PyErr_SetString( PyExc_RuntimeError, ex.what() );
      return nullptr;
   }
}

/*
 * Return the local name of the entry
 */
static PyObject *
entry_name( PyObject * self, PyObject * args ) {
   PyDwarfEntry * ent = ( PyDwarfEntry * )self;
   return makeString( dieName( ent->die ) );
}

/*
 * Return the offset of the entry
 */
static PyObject *
entry_offset( PyObject * self, PyObject * args ) {
   PyDwarfEntry * ent = ( PyDwarfEntry * )self;
   return PyLong_FromLong( ent->die.getOffset() );
}

/*
 * Return the name of the file containing the DIE.
 */
static PyObject *
entry_file( PyObject * self, PyObject * args ) {
   PyDwarfEntry * ent = ( PyDwarfEntry * )self;
   std::string txt = stringify( *ent->die.getUnit()->dwarf->elf->io );
   return makeString( txt );
}

static PyObject *
pyAttr( PyDwarfEntry *entry, Dwarf::AttrName name, const Dwarf::DIE::Attribute & attr ) {
   try {
      if ( !attr.valid() )
         Py_RETURN_NONE;

      switch (name) {
         case Dwarf::DW_AT_decl_file: {
            auto idx = intmax_t( attr );
            const std::unique_ptr<pstack::Dwarf::LineInfo> &lines =
               entry->die.getUnit()->getLines();
            return makeString( lines->files[ idx ].name );
         }
         default:
            break;
      }
      switch ( attr.form() ) {
       case Dwarf::DW_FORM_addr:
         return PyLong_FromUnsignedLongLong( uintmax_t( attr ) );

         // Assume "data" types are unsigned, unless we know better (eg,
         // DW_AT_upper_bound is set to 2^31-1/-1 by gcc)
       case Dwarf::DW_FORM_data1:
       case Dwarf::DW_FORM_data2:
       case Dwarf::DW_FORM_data4:
       case Dwarf::DW_FORM_sec_offset:
         if ( name == Dwarf::DW_AT_upper_bound )
            return PyLong_FromLong( intmax_t( attr ) );
         return PyLong_FromUnsignedLong( uintmax_t( attr ) );

       case Dwarf::DW_FORM_sdata:
       case Dwarf::DW_FORM_implicit_const:
         return PyLong_FromLongLong( intmax_t( attr ) );

       case Dwarf::DW_FORM_udata:
       case Dwarf::DW_FORM_data8:
         if ( name == Dwarf::DW_AT_upper_bound )
            return PyLong_FromLongLong( intmax_t( attr ) );
         return PyLong_FromUnsignedLongLong( uintmax_t( attr ) );

       case Dwarf::DW_FORM_strx1:
       case Dwarf::DW_FORM_strx2:
       case Dwarf::DW_FORM_strx3:
       case Dwarf::DW_FORM_strx4:
       case Dwarf::DW_FORM_strx:
       case Dwarf::DW_FORM_GNU_strp_alt:
       case Dwarf::DW_FORM_string:
       case Dwarf::DW_FORM_strp:
       case Dwarf::DW_FORM_line_strp:
         return makeString( std::string( attr ) );

       case Dwarf::DW_FORM_ref1:
       case Dwarf::DW_FORM_ref2:
       case Dwarf::DW_FORM_ref4:
       case Dwarf::DW_FORM_ref8:
       case Dwarf::DW_FORM_ref_udata:
       case Dwarf::DW_FORM_GNU_ref_alt:
       case Dwarf::DW_FORM_ref_addr:
         return makeEntry( Dwarf::DIE( attr ) );
       case Dwarf::DW_FORM_flag_present:
         Py_RETURN_TRUE;
       case Dwarf::DW_FORM_flag:
         if ( bool( attr ) ) {
            Py_RETURN_TRUE;
         } else {
            Py_RETURN_FALSE;
         }
       default:
         std::clog << "no handler for form " << attr.form() << "\n";
         break;
      }
      Py_RETURN_NONE;
   } catch ( const std::exception & ex ) {
      PyErr_SetString( PyExc_RuntimeError, ex.what() );
      return nullptr;
   }
}

/*
 * Get an attribute in the DIE
 * To make it easy to use for python, we convert the integer index to a DWARF
 * attribute name. (The "attrs" object in the module contains the numeric values for
 * the named DWARF attrs.)
 *
 * We use this for both the indexing operation on the DIe, and explicitly with the
 * getattr method
 */
static PyObject *
entry_getattr_idx( PyObject * self, Py_ssize_t idx ) {
   const auto pyEntry = ( PyDwarfEntry * )self;
   auto name = Dwarf::AttrName( idx );
   const Dwarf::DIE::Attribute & attr = pyEntry->die.attribute( name );
   return pyAttr( pyEntry, name, attr );
}

/*
 * Get all the attributes from a DIE as a dict, keyed by the attribute's numerical ID
 */
static PyObject *
entry_get_attrs( PyObject * self, PyObject * args ) {
   auto namedict = PyDict_New();
   const auto entry = reinterpret_cast< PyDwarfEntry * >( self );
   for ( const auto & attr : entry->die.attributes() ) {
      PyDict_SetItem( namedict,
                      PyLong_FromLong( attr.first ),
                      pyAttr( entry, attr.first, attr.second ) );
   }
   return namedict;
}

/*
 * Get all attributes from a DIE as a dict, keyed by the attribute's string name
 */
static PyObject *
entry_get_attrs_by_name( PyObject * self, PyObject * args ) {
   auto namedict = PyDict_New();
   auto entry = reinterpret_cast< PyDwarfEntry * >( self );
   for ( const auto & attr : entry->die.attributes() ) {
      PyObject * attrname =
         PyDict_GetItem( attrnames, PyLong_FromLong( attr.first ) );
      PyDict_SetItem( namedict, attrname, pyAttr(entry, attr.first, attr.second ) );
   }
   return namedict;
}

static PyObject *
entry_getattr( PyObject * self, PyObject * key ) {
   PyObject * value = PyDict_GetItem( attrvalues, key );
   if ( value == nullptr ) {
      // It's not a known DWARF attribute - delegate.
      return PyObject_GenericGetAttr( self, key );
   }
   return entry_getattr_idx( self, PyLong_AsLong( value ) );
}

static void
entry_free( PyObject * self ) {
   auto entry = reinterpret_cast< PyDwarfEntry * >( self );
   entry->die.DIE::~DIE();
   if ( entry->fullName ) {
      Py_DECREF( entry->fullName );
   }
   dwarfEntryType.tp_free( self );
}

/*
 * Return the fully-qualified name of the entry as a tuple, with one item for
 * each namespace
 */
static PyObject *
entry_fullname( PyObject * self, PyObject * args ) {
   PyDwarfEntry * ent = ( PyDwarfEntry * )self;
   if ( ent->fullName == nullptr ) {
      ent->fullName = makeFullname( ent->die );
   }
   Py_INCREF( ent->fullName );
   return ent->fullName;
}

/*
 * Get next DIE in a parent's iterator
 */
static PyObject *
entryiter_iternext( PyObject * self ) {
   PyDwarfEntryIterator * it = ( PyDwarfEntryIterator * )self;
   if ( it->begin == it->end ) {
      PyErr_SetNone( PyExc_StopIteration );
      return nullptr;
   }
   PyObject * rv = makeEntry( *it->begin );
   ++it->begin;
   return rv;
}

static PyObject *
entryiter_iter( PyObject * self ) {
   Py_INCREF( self );
   return self;
}

static void
entryiter_free( PyObject * o ) {
   PyDwarfEntryIterator * it = ( PyDwarfEntryIterator * )o;
   it->begin.Dwarf::DIE::Children::const_iterator::~const_iterator();
   it->end.Dwarf::DIE::Children::const_iterator::~const_iterator();
   elfObjectType.tp_free( o );
}

/*
 * Get next DIE in a parent's iterator
 */
static PyObject *
unititer_next( PyObject * self ) {
   PyDwarfUnitIterator * it = ( PyDwarfUnitIterator * )self;
   if ( it->begin == it->end ) {
      PyErr_SetNone( PyExc_StopIteration );
      return nullptr;
   }
   PyObject * rv = makeUnit( *it->begin );
   ++it->begin;
   return rv;
}

static void
unititer_free( PyObject * o ) {
   PyDwarfUnitIterator * it = ( PyDwarfUnitIterator * )o;
   it->begin.Dwarf::Units::iterator::~iterator();
   it->end.Dwarf::Units::iterator::~iterator();
   unitsIteratorType.tp_free( o );
}

static PyMethodDef ctypegen_methods[] = {
   { "open", elf_open, METH_VARARGS, "open an ELF file to process" },
   { "verbose", elf_verbose, METH_VARARGS, "set verbosity" },
   { 0, 0, 0, 0 }
};

static PyMethodDef elf_methods[] = {
   { "units", elf_units, METH_VARARGS, "get a list of unit-level DWARF entries" },
   { "soname",
     elf_soname,
     METH_VARARGS,
     "get the name of this library as used to locate it at run-time" },
   { "dynaddrs",
     elf_dynaddrs,
     METH_VARARGS,
     "get a mapping of addr->dynamic symbol name" },
   { "symbol", elf_symbol, METH_VARARGS, "get address of symbol" },
   { "findDefinition",
     elf_findDefinition,
     METH_VARARGS,
     "Given a DIE for a declaration, find "
     "a definition DIE with the same name" },
   { "flush",
     elf_flush,
     METH_VARARGS,
     "flush this object from the cache of objects." },
   { 0, 0, 0, 0 }
};

static PyMethodDef units_methods[] = { { 0, 0, 0, 0 } };

static PyNumberMethods units_asnumber = {
#if PY_MAJOR_VERSION >= 3
   .nb_bool = units_asnumber_bool
#else
   .nb_nonzero = units_asnumber_bool
#endif
};

static PyMethodDef unit_methods[] = {
   { "root", unit_root, METH_VARARGS, "get root DIE of a unit" },
   { "purge", unit_purge, METH_VARARGS, "purge any memory used by DIE trees" },
   { "macros", unit_macros, METH_VARARGS, "walk the macros for a unit" },
   { 0, 0, 0, 0 }
};

static PyMethodDef unititer_methods[] = { { 0, 0, 0, 0 } };

static PyMethodDef entry_methods[] = {
   { "tag", entry_type, METH_VARARGS, "get type of a DIE" },
   { "offset", entry_offset, METH_VARARGS, "offset of a DIE in DWARF image" },
   { "file", entry_file, METH_VARARGS, "file containing DIE" },
   { "name", entry_name, METH_VARARGS, "get namespace-local name of a DIE" },
   { "attrs",
     entry_get_attrs,
     METH_VARARGS,
     "get all attributes from a DIE (as a dict)" },
   { "namedattrs",
     entry_get_attrs_by_name,
     METH_VARARGS,
     "get all attributes from a DIE (as a dict)" },
   { "fullname",
     entry_fullname,
     METH_VARARGS,
     "get full name of a DIE (as tuple, with entry for each namesace)" },
   { "object", entry_object, METH_VARARGS, "get ELF object associated with DIE" },
   { "unit", entry_unit, METH_VARARGS, "get DWARF unit associated with DIE" },
   { "parent",
     entry_parent,
     METH_VARARGS,
     "get a DIE's parent DIE (or None for root of unit)" },
   { 0, 0, 0, 0 }
};

static PySequenceMethods entry_sequence = {
   nullptr, nullptr, nullptr, entry_getattr_idx
};

PyMODINIT_FUNC
#if PY_MAJOR_VERSION >= 3
PyInit_libCTypeGen( void )
#else
initlibCTypeGen( void )
#endif
{
#if PY_MAJOR_VERSION >= 3

   static struct PyModuleDef ctypeGenModule = {
      PyModuleDef_HEAD_INIT,
      "libCTypeGen", /* m_name */
      "ELF/DWARF helper library", /* m_doc */
      -1, /* m_size */
      ctypegen_methods, /* m_methods */
      NULL, /* m_reload */
      NULL, /* m_traverse */
      NULL, /* m_clear */
      NULL, /* m_free */
   };

   // Create our python module, and all our types.
   PyObject * module = PyModule_Create( &ctypeGenModule );
#else
   PyObject * module =
      Py_InitModule3( "libCTypeGen", ctypegen_methods, "ELF helpers" );
#endif

   dwarfAttrsType.tp_name = "DWARFAttrs";
   dwarfAttrsType.tp_flags = Py_TPFLAGS_DEFAULT;
   dwarfAttrsType.tp_basicsize = sizeof( PyDwarfAttrsObject );
   dwarfAttrsType.tp_methods = nullptr;
   dwarfAttrsType.tp_doc = "python attribute names";
   dwarfAttrsType.tp_members = attr_members;
   dwarfAttrsType.tp_dealloc = nullptr;
   dwarfAttrsType.tp_init = attr_init;

   dwarfTagsType.tp_name = "DWARFTags";
   dwarfTagsType.tp_flags = Py_TPFLAGS_DEFAULT;
   dwarfTagsType.tp_basicsize = sizeof( PyDwarfTagsObject );
   dwarfTagsType.tp_methods = nullptr;
   dwarfTagsType.tp_doc = "python tag names";
   dwarfTagsType.tp_members = tag_members;
   dwarfTagsType.tp_dealloc = nullptr;
   dwarfTagsType.tp_init = tags_init;

   dwarfBaseTypeEncodingsType.tp_name = "DWARFBaseTypeEncodings";
   dwarfBaseTypeEncodingsType.tp_flags = Py_TPFLAGS_DEFAULT;
   dwarfBaseTypeEncodingsType.tp_basicsize =
      sizeof( PyDwarfBaseTypeEncodingsObject );
   dwarfBaseTypeEncodingsType.tp_methods = nullptr;
   dwarfBaseTypeEncodingsType.tp_doc = "python attribute encoding names";
   dwarfBaseTypeEncodingsType.tp_members = ate_members;
   dwarfBaseTypeEncodingsType.tp_dealloc = nullptr;
   dwarfBaseTypeEncodingsType.tp_init = ates_init;

   elfObjectType.tp_name = "libCTypeGen.ElfObject";
   elfObjectType.tp_flags = Py_TPFLAGS_DEFAULT;
   elfObjectType.tp_basicsize = sizeof( PyElfObject );
   elfObjectType.tp_methods = elf_methods;
   elfObjectType.tp_doc = "ELF object";
   elfObjectType.tp_dealloc = elf_free;

   unitsType.tp_name = "libCTypeGen.UnitsCollection";
   unitsType.tp_flags = Py_TPFLAGS_DEFAULT;
   unitsType.tp_basicsize = sizeof( PyUnits );
   unitsType.tp_methods = units_methods;
   unitsType.tp_doc = "ELF object's DWARF units";
   unitsType.tp_dealloc = units_free;
   unitsType.tp_iter = units_iterator;
   unitsType.tp_as_number = &units_asnumber;

   unitsIteratorType.tp_name = "libCTypeGen.UnitsIterator";
   unitsIteratorType.tp_flags = Py_TPFLAGS_DEFAULT;
   unitsIteratorType.tp_basicsize = sizeof( PyDwarfUnitIterator );
   unitsIteratorType.tp_doc = "ELF object's DWARF units iterator";
   unitsIteratorType.tp_methods = unititer_methods;
   unitsIteratorType.tp_iternext = unititer_next;
   unitsIteratorType.tp_dealloc = unititer_free;

   dwarfEntryType.tp_name = "libCTypeGen.DwarfEntry";
   dwarfEntryType.tp_flags = Py_TPFLAGS_DEFAULT;
   dwarfEntryType.tp_basicsize = sizeof( PyDwarfEntry );
   dwarfEntryType.tp_doc = "DWARF DIE object";
   dwarfEntryType.tp_dealloc = entry_free;
   dwarfEntryType.tp_getattro = entry_getattr;
   dwarfEntryType.tp_methods = entry_methods;
   dwarfEntryType.tp_iter = entry_iterator;
   dwarfEntryType.tp_hash = entry_hash;
   dwarfEntryType.tp_richcompare = entry_compare;
   dwarfEntryType.tp_as_sequence = &entry_sequence;

   unitType.tp_name = "libCTypeGen.DwarfUnit";
   unitType.tp_flags = Py_TPFLAGS_DEFAULT;
   unitType.tp_basicsize = sizeof( PyDwarfUnit );
   unitType.tp_doc = "DWARF Unit object";
   unitType.tp_dealloc = unit_free;
   unitType.tp_methods = unit_methods;
   unitType.tp_richcompare = unit_compare;

   dwarfEntryIteratorType.tp_name = "libCTypeGen.DwarfEntryIterator";
   dwarfEntryIteratorType.tp_flags = Py_TPFLAGS_DEFAULT;
   dwarfEntryIteratorType.tp_basicsize = sizeof( PyDwarfEntryIterator );
   dwarfEntryIteratorType.tp_doc = "DWARF DIE object iterator";
   dwarfEntryIteratorType.tp_dealloc = entryiter_free;
   dwarfEntryIteratorType.tp_iter = entryiter_iter;
   dwarfEntryIteratorType.tp_iternext = entryiter_iternext;

   // Add each type to the module.
   struct {
      const char * name;
      PyTypeObject * type;
   } types[] = {
      { "DwarfTags", &dwarfTagsType },
      { "DwarfAttrs", &dwarfAttrsType },
      { "DwarfBaseTypeEncodings", &dwarfBaseTypeEncodingsType },
      { "DwarfEntry", &dwarfEntryType },
      { "DwarfEntryIterator", &elfObjectType },
      { "DwarfUnitsIterator", &unitsIteratorType },
      { "DwarfUnits", &unitsType },
      { "DwarfUnit", &unitType },
      { "ElfObject", &elfObjectType },
   };
   for ( auto & descriptor : types ) {
      if ( PyType_Ready( descriptor.type ) == 0 ) {
         Py_INCREF( descriptor.type );
         PyModule_AddObject(
            module, descriptor.name, ( PyObject * )descriptor.type );
      }
   }

   // Add "tags" and "attrs" objects to name DWARF attribute and tag names
   auto tags = PyObject_New( PyObject, &dwarfTagsType );
   tags->ob_type->tp_init( tags, nullptr, nullptr );
   PyModule_AddObject( module, "tags", ( PyObject * )tags );

   auto attrs = PyObject_New( PyObject, &dwarfAttrsType );
   attrs->ob_type->tp_init( attrs, nullptr, nullptr );
   PyModule_AddObject( module, "attrs", ( PyObject * )attrs );

   auto encodings = PyObject_New( PyObject, &dwarfBaseTypeEncodingsType );
   encodings->ob_type->tp_init( encodings, nullptr, nullptr );
   PyModule_AddObject( module, "encodings", ( PyObject * )encodings );

   // add value->string mapping to name attributes and tags
   attrnames = make_attrnames();
   attrvalues = make_attrvalues();
   tagnames = make_tagnames();
   PyModule_AddObject( module, "attrnames", attrnames );
   PyModule_AddObject( module, "tagnames", tagnames );

#if PY_MAJOR_VERSION >= 3
   return module;
#endif
}
}
