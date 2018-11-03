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

#include <Python.h>

#include <iostream>
#include <deque>
#include <memory>
#include <set>
#include <sstream>
#include <vector>

#include <libpstack/elf.h>
#include <libpstack/dwarf.h>

static std::set<Dwarf::Tag> namespacetags = {
   Dwarf::DW_TAG_structure_type,
   Dwarf::DW_TAG_namespace,
   Dwarf::DW_TAG_class_type,
   Dwarf::DW_TAG_union_type,
};

static std::string
dieName(const Dwarf::DIE &die)
{
   const auto &name = die.attribute(Dwarf::DW_AT_name);
   if (name.valid())
      return std::string(name);
   std::ostringstream os;
   os << "anon_" << die.getOffset();
   return os.str();
}

template <typename container> static void
getFullName(const Dwarf::DIE &die, container &fullname, bool leaf = true)
{
   if (die.getParentOffset() != 0) {
      const auto &parent = die.getUnit()->offsetToDIE(die.getParentOffset());
      getFullName(parent, fullname, false);
   }
   if (leaf || namespacetags.find(die.tag()) != namespacetags.end()) {
      fullname.push_back(dieName(die));
   }
}

template<typename T>
static Dwarf::DIE
findDefinition( const Dwarf::DIE &die,
      Dwarf::Tag tag,
      typename T::iterator first,
      typename T::iterator end )
{
   const auto &nameA = die.attribute(Dwarf::DW_AT_name);
   const bool sameName = nameA.valid() && std::string(nameA) == *first;

   if (end - first == 1) {
      const auto &declA = die.attribute( Dwarf::DW_AT_declaration );
      if ( nameA.valid() && sameName && !bool( declA ) && tag == die.tag()  )
         return die;
   }
   switch (die.tag()) {
      case Dwarf::DW_TAG_namespace:
      case Dwarf::DW_TAG_structure_type:
      case Dwarf::DW_TAG_class_type:
         if ( !sameName )
            return Dwarf::DIE();
         first++;
         // FALLTHROUGH

      case Dwarf::DW_TAG_compile_unit:
         for ( const auto c : die.children() ) {
            const auto ischild = findDefinition<T>( c, tag, first, end );
            if (ischild)
               return ischild;
         }
         break;
      default:
         break;
   }
   return Dwarf::DIE();
}

extern "C" {

typedef struct {
   PyObject_HEAD
   std::shared_ptr< Elf::Object > obj;
   std::shared_ptr< Dwarf::Info > dwarf;
} PyElfObject;

typedef struct {
   PyObject_HEAD
   Dwarf::DIE die;
} PyDwarfEntry;

typedef struct {
   PyObject_HEAD
   const Dwarf::Unit *unit;
   Dwarf::DIEIter begin;
   Dwarf::DIEIter end;
} PyDwarfEntryIterator;

static void
pyElfObjectFree( PyObject * o ) {
   PyElfObject * pye = ( PyElfObject * )o;
   pye->obj.std::shared_ptr< Elf::Object >::~shared_ptr< Elf::Object >();
   pye->dwarf.std::shared_ptr< Dwarf::Info >::~shared_ptr< Dwarf::Info >();
}

static void
pyDwarfEntryFree( PyObject * o ) {
}

static void
pyDwarfEntryIteratorFree( PyObject * o ) {
   PyDwarfEntryIterator * it = ( PyDwarfEntryIterator * )o;
   it->begin.Dwarf::DIEIter::~DIEIter();
   it->end.Dwarf::DIEIter::~DIEIter();
}

static PyTypeObject elfObjectType = { PyObject_HEAD_INIT( 0 ) 0 };

static PyTypeObject dwarfEntryType = { PyObject_HEAD_INIT( 0 ) 0 };

static PyTypeObject dwarfEntryIteratorType = { PyObject_HEAD_INIT( 0 ) 0 };

static Dwarf::ImageCache imageCache;
static PyObject *
open( PyObject * self, PyObject * args ) {
   try {
      const char *image;
      if ( !PyArg_ParseTuple( args, "s", &image ) )
            return nullptr;
      PyElfObject *val = PyObject_New( PyElfObject, &elfObjectType );

      new ( &val->obj ) std::shared_ptr<Elf::Object>();
      new ( &val->dwarf ) std::shared_ptr<Dwarf::Info>();

      val->dwarf = imageCache.getDwarf( image );
      val->obj = val->dwarf->elf;
      return ( PyObject * )val;
   }
   catch ( const std::exception &ex ) {
      PyErr_SetString( PyExc_RuntimeError, ex.what() );
      return nullptr;
   }
}

static PyObject *
makeEntry(const Dwarf::DIE &die) {
   PyDwarfEntry * value = PyObject_New( PyDwarfEntry, &dwarfEntryType );
   value->die = die;
   return ( PyObject * )value;
}

static PyObject *
elf_units( PyObject * self, PyObject * args ) {
   try {
      PyElfObject * pye = ( PyElfObject * )self;
      const auto &units = pye->dwarf->getUnits();
      PyObject * result = PyList_New( units.size() );
      size_t i = 0;
      for ( auto unit : units )
         PyList_SetItem( result, i++, makeEntry( *unit->topLevelDIEs().begin() ) );
      return result;
   }
   catch ( const std::exception &ex ) {
      PyErr_SetString( PyExc_RuntimeError, ex.what() );
      return nullptr;
   }
}

static PyObject *
elf_findDefinition( PyObject * self, PyObject * args ) {
   PyDwarfEntry *die;
   PyElfObject *elf = (PyElfObject *)self;
   if ( !PyArg_ParseTuple( args, "O", &die ) )
      return 0;
   std::vector<std::string> namelist;
   getFullName(die->die, namelist);
   for ( const auto &u : elf->dwarf->getUnits() ) {
      for (const auto &tld : u->topLevelDIEs()) {
         const auto &defn = findDefinition<std::vector<std::string>>(
               tld, die->die.tag(), namelist.begin(), namelist.end() );
         if (defn)
            return makeEntry( defn );
      }
   }
   Py_INCREF( Py_None );
   return Py_None;
}

static PyObject *
entry_type( PyObject * self, PyObject * args ) {
   PyDwarfEntry * ent = ( PyDwarfEntry * )self;
   return PyLong_FromLong( ent->die.tag() );
}

static PyObject *
entry_compare( PyObject * lhso, PyObject * rhso, int op ) {
   if ( Py_TYPE( rhso ) != &dwarfEntryType ) {
      Py_INCREF( Py_False );
      return Py_False;
   }

   PyDwarfEntry * lhs = ( PyDwarfEntry * )lhso;
   PyDwarfEntry * rhs = ( PyDwarfEntry * )rhso;


   auto diff = lhs->die.getUnit()->offset - rhs->die.getUnit()->offset;
   if (diff == 0)
       diff = lhs->die.getOffset() - rhs->die.getOffset();

   PyObject *result = Py_NotImplemented;
#define TF(pyname, oper) case pyname: \
                result = ( ( diff oper 0 ) ? Py_True : Py_False ); break
   if (Py_TYPE( rhs ) == Py_TYPE( lhs ) ) {
      switch (op) {
         TF(Py_EQ, ==);
         TF(Py_NE, !=);
         TF(Py_GT, >);
         TF(Py_GE, >=);
         TF(Py_LT, <);
         default:
            break;
      }
   }
#undef TF
   Py_INCREF( result );
   return result;
}


#if PY_MAJOR_VERSION >= 3
static Py_hash_t
#else
static long
#endif
entry_hash( PyObject * self ) {
   PyDwarfEntry * ent = ( PyDwarfEntry * )self;
   return intptr_t( ent->die.getOffset() ^ ent->die.getUnit()->offset );
}

static PyObject *
entry_iterator( PyObject * self ) {
   try {
      PyDwarfEntry * ent = ( PyDwarfEntry * )self;
      PyDwarfEntryIterator * it = PyObject_New( PyDwarfEntryIterator,
               &dwarfEntryIteratorType );
      auto list = ent->die.children();
      new ( &it->begin ) Dwarf::DIEIter(list.begin());
      new ( &it->end ) Dwarf::DIEIter(list.end());
      it->unit = ent->die.getUnit();
      return ( PyObject * )it;
   }
   catch ( const std::exception &ex ) {
      PyErr_SetString( PyExc_RuntimeError, ex.what() );
      return nullptr;
   }
}

static PyObject *
entryiter_iternext( PyObject * self ) {
   PyDwarfEntryIterator * it = ( PyDwarfEntryIterator * )self;
   if ( it->begin == it->end ) {
      PyErr_SetNone( PyExc_StopIteration );
      return nullptr;
   }
   auto rv = makeEntry( *it->begin );
   ++it->begin;
   return rv;
}

static PyObject *
entryiter_iter( PyObject * self ) {
   Py_INCREF( self );
   return self;
}

static PyObject *
makeString( const std::string & s ) {
   return PyUnicode_FromString( s.c_str() );
}

static PyObject *
entry_fullname( PyObject * self, PyObject * args ) {
   std::deque<std::string> namelist;
   PyDwarfEntry * ent = ( PyDwarfEntry * )self;
   const auto &die = ent->die;
   getFullName(die, namelist);
   auto tuple = PyTuple_New(namelist.size());
   size_t i = 0;
   for (const auto &item : namelist) {
      PyTuple_SET_ITEM(tuple, i, makeString(item));
      i++;
   }
   return tuple;
}

static PyObject *
entry_name( PyObject * self, PyObject * args ) {
   PyDwarfEntry * ent = ( PyDwarfEntry * )self;
   return makeString(dieName(ent->die));
}

static PyObject *
entry_offset( PyObject * self, PyObject * args ) {
   PyDwarfEntry * ent = ( PyDwarfEntry * )self;
   return PyLong_FromLong( ent->die.getOffset() );
}

static PyObject *
entry_file( PyObject * self, PyObject * args ) {
   PyDwarfEntry * ent = ( PyDwarfEntry * )self;
   std::string txt = stringify( *ent->die.getUnit()->dwarf->elf->io );
   return makeString( txt );
}

static PyObject *
entry_getattr_idx( PyObject * self, Py_ssize_t idx ) {
   try {
      const auto pyEntry = ( PyDwarfEntry * )self;
      const auto &attr = pyEntry->die.attribute( Dwarf::AttrName( idx ) );
      if (!attr.valid())
         Py_RETURN_NONE;
      switch ( attr.form() ) {
       case Dwarf::DW_FORM_addr:
         return PyLong_FromUnsignedLongLong( uintmax_t( attr ) );
       case Dwarf::DW_FORM_data1:
       case Dwarf::DW_FORM_data2:
       case Dwarf::DW_FORM_data4:
         return PyLong_FromLong( intmax_t( attr ) );
       case Dwarf::DW_FORM_sdata:
       case Dwarf::DW_FORM_data8:
         return PyLong_FromLongLong( intmax_t( attr ) );
       case Dwarf::DW_FORM_udata:
         return PyLong_FromUnsignedLongLong( uintmax_t( attr ) );
       case Dwarf::DW_FORM_GNU_strp_alt:
       case Dwarf::DW_FORM_string:
       case Dwarf::DW_FORM_strp:
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
         std::clog << "no handler for form " << attr.form() << "in attribute "
                   << idx << "\n";
         break;
      }
      Py_RETURN_NONE;
   } catch ( const std::exception &ex ) {
      PyErr_SetString( PyExc_RuntimeError, ex.what() );
      return nullptr;
   }
}

static PyObject *
entry_getattr( PyObject * self, PyObject * args ) {
   unsigned attrId;
   if ( !PyArg_ParseTuple( args, "I", &attrId ) )
      return 0;
   return entry_getattr_idx( self, attrId );
}

static PyMethodDef GenTypeMethods[] = {
   { "open", open, METH_VARARGS, "open an ELF file to process" }, { 0, 0, 0, 0 }
};

static PyMethodDef elfMethods[] = {
   { "units", elf_units, METH_VARARGS, "get a list of unit-level DWARF entries" },
   { "findDefinition", elf_findDefinition, METH_VARARGS,
      "Given a DIE for a declaration, find a definition DIE with the same name" },
   { 0, 0, 0, 0 }
};

static PyMethodDef entryMethods[] = {
   { "tag", entry_type, METH_VARARGS, "get type of a DIE" },
   { "offset", entry_offset, METH_VARARGS, "offset of a DIE in DWARF image" },
   { "file", entry_file, METH_VARARGS, "file containing DIE" },
   { "getattr", entry_getattr, METH_VARARGS, "get specific attribute of a DIE" },
   { "name", entry_name, METH_VARARGS, "get full name of a DIE" },
   { "fullname", entry_fullname, METH_VARARGS, "get full name of a DIE" },
   { 0, 0, 0, 0 }
};

static PySequenceMethods entry_sequence = {
   nullptr,
   nullptr,
   nullptr,
   entry_getattr_idx
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
      GenTypeMethods, /* m_methods */
      NULL, /* m_reload */
      NULL, /* m_traverse */
      NULL, /* m_clear */
      NULL, /* m_free */
   };

   static struct PyModuleDef tagsModule = {
      PyModuleDef_HEAD_INIT,
      "libCTypeGen.tags", /* m_name */
      "DWARF tag constants", /* m_doc */
      -1, /* m_size */
      NULL, /* m_methods */
      NULL, /* m_reload */
      NULL, /* m_traverse */
      NULL, /* m_clear */
      NULL, /* m_free */
   };

   static struct PyModuleDef attrsModule = {
      PyModuleDef_HEAD_INIT,
      "libCTypeGen.attrs", /* m_name */
      "DWARF attribute constants", /* m_doc */
      -1, /* m_size */
      NULL, /* m_methods */
      NULL, /* m_reload */
      NULL, /* m_traverse */
      NULL, /* m_clear */
      NULL, /* m_free */
   };

   PyObject * module = PyModule_Create( &ctypeGenModule );
   PyObject * tags = PyModule_Create( &tagsModule );
   PyObject * attrs = PyModule_Create( &attrsModule );
#else
   PyObject * module =
      Py_InitModule3( "libCTypeGen", GenTypeMethods, "ELF helpers" );
   PyObject * tags = Py_InitModule3( "libCTypeGen.tags", 0, "ELF constants" );
   PyObject * attrs = Py_InitModule3( "libCTypeGen.attrs", 0, "ELF constants" );
#endif

   elfObjectType.tp_name = "libCTypeGen.ElfObject";
   elfObjectType.tp_flags = Py_TPFLAGS_DEFAULT;
   elfObjectType.tp_basicsize = sizeof( PyElfObject );
   elfObjectType.tp_methods = elfMethods;
   elfObjectType.tp_doc = "ELF object";
   elfObjectType.tp_dealloc = pyElfObjectFree;
   elfObjectType.tp_new = PyType_GenericNew;

   dwarfEntryType.tp_name = "libCTypeGen.DwarfEntry";
   dwarfEntryType.tp_flags = Py_TPFLAGS_DEFAULT;
   dwarfEntryType.tp_basicsize = sizeof( PyDwarfEntry );
   dwarfEntryType.tp_doc = "DWARF DIE object";
   dwarfEntryType.tp_dealloc = pyDwarfEntryFree;
   dwarfEntryType.tp_new = PyType_GenericNew;
   dwarfEntryType.tp_methods = entryMethods;
   dwarfEntryType.tp_iter = entry_iterator;
   dwarfEntryType.tp_hash = entry_hash;
   dwarfEntryType.tp_richcompare = entry_compare;
   dwarfEntryType.tp_as_sequence = &entry_sequence;

   dwarfEntryIteratorType.tp_name = "libCTypeGen.DwarfEntryIterator";
   dwarfEntryIteratorType.tp_flags = Py_TPFLAGS_DEFAULT;
   dwarfEntryIteratorType.tp_basicsize = sizeof( PyDwarfEntryIterator );
   dwarfEntryIteratorType.tp_doc = "DWARF DIE object iterator";
   dwarfEntryIteratorType.tp_dealloc = pyDwarfEntryIteratorFree;
   dwarfEntryIteratorType.tp_new = PyType_GenericNew;
   dwarfEntryIteratorType.tp_iter = entryiter_iter;
   dwarfEntryIteratorType.tp_iternext = entryiter_iternext;

   if ( PyType_Ready( &elfObjectType ) >= 0 ) {
      Py_INCREF( &elfObjectType );
      PyModule_AddObject( module, "ElfObject", ( PyObject * )&elfObjectType );
   }
   if ( PyType_Ready( &dwarfEntryType ) >= 0 ) {
      Py_INCREF( &dwarfEntryType );
      PyModule_AddObject( module, "DwarfEntry", ( PyObject * )&dwarfEntryType );
   }
   PyModule_AddObject( module, "tags", tags );
   PyModule_AddObject( module, "attrs", attrs );

#define DWARF_TAG( name, value )                                                    \
   PyModule_AddObject( tags, #name, PyLong_FromLong( value ) );
#include <libpstack/dwarf/tags.h>
#undef DWARF_TAG

#define DWARF_ATTR( name, value )                                                   \
   PyModule_AddObject( attrs, #name, PyLong_FromLong( value ) );
#include <libpstack/dwarf/attr.h>
#undef DWARF_TAG
#if PY_MAJOR_VERSION >= 3
   return module;
#endif
}
}
