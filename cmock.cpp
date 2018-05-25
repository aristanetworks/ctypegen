/*
   Copyright 2018 Arista Networks.

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
#include <map>

#include <string.h>
#include <assert.h>

#include <unistd.h>
#include <link.h>
#include <elf.h>
#include <fcntl.h>

#include <sys/mman.h>

#if __WORDSIZE == 32
#define ELF_R_SYM( reloc ) ELF32_R_SYM( reloc )
#else
#define ELF_R_SYM( reloc ) ELF64_R_SYM( reloc )
#endif

/*
 * protect the memory from p thru p + len to be as provided in perms. page-aligns
 * things , and calls mprotect
 */
static void
protect( int perms, void *p, size_t len ) {
   uintptr_t start = ( uintptr_t )p;
   uintptr_t end = start + len;
   uintptr_t start_page = start - start % getpagesize();
   uintptr_t end_page = end - end % getpagesize();
   // This should not fail. If it does, we've real problems doing this style mock.
   int rc = mprotect( ( void * )start_page, end_page - start_page + getpagesize(),
         perms );
   if ( rc != 0 ) {
      std::clog << "mprotect failed: " << rc << ": " << strerror( errno )
          << std::endl;
      abort();
   }
}

/*
 * We have two separate mocking implementations - one that overwrites all GOT
 * entries, and one that scribbles over the prelude of the function we're
 * mocking out.
 */

/* Our GOT-based mock.
 * This is the version of the mocking system as originally conceived -
 * overwrite the GOT entries that the PLT refers to with the pythons stubs.
 * This doesn't work for shared libraries that have relocations in them (i.e.,
 * shared libraries that are not compiled as -fPIC
 */

struct GOTMock {
   PyObject_HEAD
   std::map<ElfW( Addr ), void *> replaced;
   void *callback;
   const char *function;
   GOTMock( const char *name_, void *callback_, void *handle_ );
   void processLibrary( ElfW( Dyn ) *dynamic, ElfW( Addr ) loadaddr,
         const char *function, void *thunk );
   static void handleAddend( const ElfW( Rel ) &rel ) { }
   static void handleAddend( const ElfW( Rela ) &rela ) {
      assert( rela.r_addend == 0 );
   }
   template <typename reltype> void
      findGotEntries( ElfW( Addr ) loadaddr, const reltype *relocs, size_t reloclen,
            const ElfW( Sym ) *symbols, const char *strings);
   void enable();
   void disable();
};

/*
 * Our function-code-stomping version. This _only_ works on i386
 * It is useful for when shared libraries are not compiled as PIC.
 * This is never needed on x86_64, because it does not generally
 * support non-PIC content in shared libraries. ( call instructions can't
 * be resolved at runtime, as they take a 32-bit relative offset )
 */
struct StompMock {
   PyObject_HEAD
   // the i386 assembler to stomp over the function's prelude to enable the mock.
   char enable[ 5 ];

   // the original code that was contained in the 5 bytes above.
   char disable[ 5 ];

   void *location; // the location in memory where we should do our stomping.
   StompMock( const char *name, void *callback, long handle );
   void setState( bool );
};

/*
 * Construct a mock for function called name_, to call function callback_
 * if invoked from library handle (or any library, if handle == 0)
 */
GOTMock::GOTMock( const char *name_, void *callback_, void *handle )
   : callback( callback_ )
   , function( name_ )
{
   if ( handle == 0 ) {
      // Override function in all libraries.
      for ( auto map = _r_debug.r_map; map; map = map->l_next )
         processLibrary( map->l_ld, map->l_addr, function, callback );
   } else {
      auto map = static_cast<link_map *>( handle );
      processLibrary( map->l_ld, map->l_addr, function, callback );
   }
   enable();
}

/*
 * Locate GOT entries that refer to our function by name. This is templated to work
 * for ELF Rela and Rel locations. handleAddend is overloaded for each, and can
 * handle the addend parts for rela, if we ever care about them
 */
template <typename reltype> void
GOTMock::findGotEntries( ElfW( Addr ) loadaddr,
        const reltype *relocs,
        size_t reloclen,
        const ElfW( Sym ) *symbols,
        const char *strings) {
   for ( int i = 0;; ++i ) {
      if ( ( char * )( relocs + i ) >= ( char * )relocs + reloclen )
         break;
      auto &reloc = relocs[ i ];
      auto symidx = ELF_R_SYM( reloc.r_info );
      auto &sym = symbols[ symidx ];
      const char *name = strings + sym.st_name;
      // If we find the funciton we want, update the GOT entry with ptr to our code.
      if ( strcmp( name, function ) == 0 ) {
         ElfW( Addr ) loc = reloc.r_offset + loadaddr;
         void **addr = reinterpret_cast<void **>( loc );
         handleAddend( reloc );
         replaced[ loc ] = *addr;
      }
   }
}

/*
 * Go over all the offsets in the GOT that refer to us, and patch in our mock.
 */
void
GOTMock::enable() {
   for ( auto &addr : replaced )
      *( void ** )addr.first = callback;
}

/*
 * Go over all the offsets in the GOT that refer to us, and replace the original
 * function.
 */
void
GOTMock::disable() {
    for ( auto &addr : replaced )
        *( void ** )addr.first = addr.second;
}

/*
 * Process a single library's relocation information
 */
void
GOTMock::processLibrary( ElfW( Dyn ) *dynamic, ElfW( Addr ) loadaddr,
      const char *function, void *thunk ) {

   int reltype = -1;
   ElfW( Rel ) *relocs = 0;
   ElfW( Rela ) *relocas = 0;
   ElfW( Word ) reloclen = -1;
   ElfW( Sym ) *symbols = 0;
   const char *strings = 0;

   for ( auto i = 0; dynamic[ i ].d_tag != DT_NULL; ++i ) {
      auto &dyn = dynamic[ i ];
      switch ( dyn.d_tag ) {
         case DT_PLTREL:
            reltype = dyn.d_un.d_val;
            break;
         case DT_JMPREL:
            relocas = ( ElfW( Rela ) * )( dyn.d_un.d_ptr );
            relocs = ( ElfW( Rel ) * )( dyn.d_un.d_ptr );
            break;
         case DT_PLTRELSZ:
            reloclen = dyn.d_un.d_val;
            break;
         case DT_STRTAB:
            strings = ( char * )( dyn.d_un.d_ptr );
            break;
         case DT_SYMTAB:
            symbols = ( ElfW( Sym ) * )( dyn.d_un.d_ptr );
            break;
      }
   }

   switch ( reltype ) {
      case DT_REL:
         relocas = 0;
         break;
      case DT_RELA:
         relocs = 0;
         break;
      default:
         return;
   }

   if ( relocas )
       findGotEntries( loadaddr, relocas, reloclen, symbols, strings );
   else if ( relocs )
       findGotEntries( loadaddr, relocs, reloclen, symbols, strings );
}

/*
 * Install a stomping mock for function name, to call the mock "callback"
 * "handle" here specifies the library containing the function we want to
 * mock out.
 */
StompMock::StompMock( const char *name, void *callback, long handle ) {
   void *lib = handle ? ( void * )( intptr_t )handle : RTLD_DEFAULT;

   /* find the symbol for this function. */
   location = dlsym( lib, name );
   if ( !location ) {
      std::cerr << "no symbol found for " << name <<  ", handle " << handle
         << ": " << dlerror() << std::endl;
      throw std::exception();
   }

   /*
    * save the first 5 bytes of the function, and generate code for a jmp
    * instruction to the callback.
    */
   unsigned char *insns = ( unsigned char * )location;
   memcpy( disable, insns, 5 );
   enable[ 0 ] = 0xe9;

   // Calculate relative offset of jmp instruction, and insert that into our insn.
   uintptr_t jmploc = ( unsigned char * )callback - ( insns + 5 );
   memcpy( enable + 1, &jmploc, sizeof jmploc );

   /* Enable mocking */
   setState( true );
}

void
StompMock::setState( bool state ) {
   protect( PROT_READ|PROT_WRITE, location, sizeof enable );
   memcpy( location, state ? enable : disable, sizeof enable );
   protect( PROT_READ|PROT_EXEC, location, sizeof enable );
}

/*
 * Python entrypoints and methods
 */

static PyObject *
gotNew( PyTypeObject *subtype, PyObject *args, PyObject *kwds ) {
   auto obj = reinterpret_cast<GOTMock *>( subtype->tp_alloc( subtype, 0 ) );
   const char *name;
   long long callback;
   long long handle;

   PyArg_ParseTuple( args, "sLL", &name, &callback, &handle );
   new ( obj ) GOTMock( name, ( void * )callback, ( void * )handle );
   return reinterpret_cast<PyObject *>( obj );
}

static PyObject *
gotEnable( PyObject *self, PyObject *args ) {
   auto *mock = reinterpret_cast<GOTMock *>( self );
   mock->enable();
   Py_RETURN_NONE;
}

static PyObject *
gotDisable( PyObject *self, PyObject *args )
{
   auto *mock = reinterpret_cast<GOTMock *>( self );
   mock->disable();
   Py_RETURN_NONE;
}

static void
gotFree( PyObject *self ) {
   delete reinterpret_cast<GOTMock *>( self );
}

static PyObject *
stompNew( PyTypeObject *subtype, PyObject *args, PyObject *kwds ) {
   auto obj = reinterpret_cast<StompMock *>( subtype->tp_alloc( subtype, 0 ) );

   const char *name;
   long long callback;
   long long handle;

   PyArg_ParseTuple( args, "sLL", &name, &callback, &handle );
   new ( obj ) StompMock( name, (void *)callback, handle );
   return reinterpret_cast<PyObject *>( obj );
}

static PyObject *
stompEnable( PyObject *self, PyObject *args ) {
   auto *mock = reinterpret_cast<StompMock *>( self );
   mock->setState( true );
   Py_RETURN_NONE;
}

static PyObject *
stompDisable( PyObject *self, PyObject *args ) {
   auto *mock = reinterpret_cast<StompMock *>( self );
   mock->setState( false );
   Py_RETURN_NONE;
   abort();
}

static void
stompFree( PyObject *self ) {
   delete reinterpret_cast<StompMock *>( self );
}

/*
 * Python tables for methods
 */
static PyMethodDef stompMethods[] = {
   { "enable", stompEnable, METH_VARARGS, "enable the mock" },
   { "disable", stompDisable, METH_VARARGS, "disable the mock" },
   { 0, 0, 0, 0 }
};

static PyMethodDef gotMethods[] = {
   { "enable", gotEnable, METH_VARARGS, "enable the mock" },
   { "disable", gotDisable, METH_VARARGS, "disable the mock" },
   { 0, 0, 0, 0 }
};

/*
 * Types for our two mock objects.
 */
static PyTypeObject stompObjectType;
static PyTypeObject gotObjectType;

/*
 * Initialize python library
 */
PyMODINIT_FUNC
#if PY_MAJOR_VERSION >= 3
PyInit_libCTypeMock( void )
#else
initlibCTypeMock( void )
#endif
{
#if PY_MAJOR_VERSION >= 3
   static struct PyModuleDef ctypeMockModule = {
      PyModuleDef_HEAD_INIT,
      "libCTypeMock", /* m_name */
      "CTypeMock C support", /* m_doc */
      -1, /* m_size */
      NULL, /* m_methods */
      NULL, /* m_reload */
      NULL, /* m_traverse */
      NULL, /* m_clear */
      NULL, /* m_free */
   };
   PyObject * module = PyModule_Create( &ctypeMockModule );
#else
   PyObject * module = Py_InitModule3( "libCTypeMock", NULL, "CTypeMock C support" );
#endif

   stompObjectType.tp_name = "Stomp";
   stompObjectType.tp_flags = Py_TPFLAGS_DEFAULT;
   stompObjectType.tp_basicsize = sizeof( StompMock );
   stompObjectType.tp_methods = stompMethods;
   stompObjectType.tp_doc = "A stomping mock";
   stompObjectType.tp_new = stompNew;
   stompObjectType.tp_del = stompFree;
   if ( PyType_Ready( &stompObjectType ) >= 0 ) {
      Py_INCREF( &stompObjectType );
      PyModule_AddObject( module, "StompMock", ( PyObject * )&stompObjectType );
   }

   gotObjectType.tp_name = "GOT";
   gotObjectType.tp_flags = Py_TPFLAGS_DEFAULT;
   gotObjectType.tp_basicsize = sizeof( GOTMock );
   gotObjectType.tp_methods = gotMethods;
   gotObjectType.tp_doc = "A GOT mock";
   gotObjectType.tp_new = gotNew;
   gotObjectType.tp_del = gotFree;
   if ( PyType_Ready( &gotObjectType ) >= 0 ) {
      Py_INCREF( &gotObjectType );
      PyModule_AddObject( module, "GOTMock", ( PyObject * )&gotObjectType );
   }
#if PY_MAJOR_VERSION >= 3
   return module;
#endif

}

/*
 * We use this function from python via ctypes to get the ctypes magic of
 * converting a python function into a C-callable pointer-to-function
 */
extern "C" {
void *
cfuncTypeToPtrToFunc( void *function )
{
   return function;
}
}
