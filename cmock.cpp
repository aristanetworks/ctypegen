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

#ifdef __clang__
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wregister"
#endif
#include <Python.h>
#ifdef __clang__
#pragma GCC diagnostic pop
#endif
#include <iostream>
#include <map>
#include <memory>

#include <string.h>
#include <assert.h>

#include <unistd.h>
#include <link.h>
#include <elf.h>
#include <fcntl.h>
#include <cxxabi.h>

#include <sys/mman.h>
#include <regex.h>

#if __WORDSIZE == 32
#define ELF_R_SYM( reloc ) ELF32_R_SYM( reloc )
typedef Elf32_Sym Elf_Sym;
typedef Elf32_Dyn Elf_Dyn;
typedef Elf32_Ehdr Elf_Ehdr;
typedef Elf32_Shdr Elf_Shdr;
#else
#define ELF_R_SYM( reloc ) ELF64_R_SYM( reloc )
typedef Elf64_Sym Elf_Sym;
typedef Elf64_Dyn Elf_Dyn;
typedef Elf64_Ehdr Elf_Ehdr;
typedef Elf64_Shdr Elf_Shdr;
#endif

// https://flapenguin.me/elf-dt-gnu-hash
struct gnu_hash_table {
   uint32_t nbuckets;
   uint32_t symoffset;
   uint32_t bloom_size;
   uint32_t bloom_shift;
#if 0
    uint64_t bloom[bloom_size]; /* uint32_t for 32-bit binaries */
    uint32_t buckets[nbuckets];
    uint32_t chain[];
#endif
};

static inline const long *
gnu_hash_bloom( const gnu_hash_table * table, size_t idx ) {
   const long * ptr = ( const long * )( table + 1 );
   return ptr + idx;
}

static inline const uint32_t *
gnu_hash_bucket( const gnu_hash_table * table, size_t idx ) {
   return ( const uint32_t * )gnu_hash_bloom( table, table->bloom_size ) + idx;
}

static inline const uint32_t *
gnu_hash_chain( const gnu_hash_table * table, size_t idx ) {
   return gnu_hash_bucket( table, table->nbuckets ) + idx - table->symoffset;
}

/*
 * protect the memory from p thru p + len to be as provided in perms. page-aligns
 * things , and calls mprotect
 */
static void
protect( int perms, void * p, size_t len ) {
   uintptr_t start = ( uintptr_t )p;
   uintptr_t end = start + len;
   uintptr_t start_page = start - start % getpagesize();
   uintptr_t end_page = end - end % getpagesize();
   // This should not fail. If it does, we've real problems doing this style mock.
   int rc =
      mprotect( ( void * )start_page, end_page - start_page + getpagesize(), perms );
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

template <typename M>
void
enableMock(M *m)
{
   if (++m->enableCount == 1)
      m->enable();
}

template <typename M>
void
disableMock(M *m)
{
   if (--m->enableCount == 0)
      m->disable();
}

struct Mock {
   // clang-format off
   PyObject_HEAD
   // clang-format on
   int enableCount;
   Mock() : enableCount{ 0 } {}
};

class GOTMock : protected Mock {
   friend void enableMock<GOTMock>(GOTMock *);
   friend void disableMock<GOTMock>(GOTMock *);
protected:
   std::map< ElfW( Addr ), void * > replaced;
   void * callback;
   void enable();
   void disable();
public:
   uintptr_t realaddr;
   GOTMock( const char * name_, void * callback_, void * handle_ );
   void processLibrary( const char *,
                        ElfW( Dyn ) * dynamic,
                        ElfW( Addr ) loadaddr,
                        const char * function );
   static void handleAddend( const ElfW( Rel ) & rel ) {}
   static void handleAddend( const ElfW( Rela ) & rela ) {
      assert( rela.r_addend == 0 );
   }
   template< typename reltype >
   void findGotEntries( ElfW( Addr ) loadaddr,
                        const reltype * relocs,
                        size_t reloclen,
                        const ElfW( Sym ) * symbols,
                        const char *function,
                        const char * strings );
};

extern char cmock_thunk_function[];
extern char cmock_thunk_end[];

class PreMock : public GOTMock {
   friend void enableMock<PreMock>(PreMock *);
   friend void disableMock<PreMock>(PreMock *);
   void * callbackFor( void * got, void * func );

   // To deallocate our posix_memalign'ed data, we need to replace
   // the read/execute protection on it with read/write, and free(3)
   // it
   struct RawFree {
      void operator()( void * p ) {
         mprotect( p, 4096, PROT_READ | PROT_WRITE );
         free( p );
      }
   };
   std::map< void *, std::unique_ptr< void, RawFree > > thunks;
protected:
   void enable();
public:
   PreMock( const char * name_, void * callback_, void * handle_ )
         : GOTMock( name_, callback_, handle_ ) {}
};

/*
 * Our function-code-stomping version.
 * It is useful for when shared libraries are not compiled as PIC, and for
 * virtual functions where they are called through a vptr. The non-PIC variant
 * is not useful on x86-64 in the default compilation modek, as non-PIC code
 * can't be put in shared libraries.
 */
class StompMock : protected Mock {
   friend void enableMock<StompMock>(StompMock *);
   friend void disableMock<StompMock>(StompMock *);
   static constexpr int savesize = __WORDSIZE == 32 ? 5 : 13;

   // the assembler to stomp over the function's prelude to enable the mock.
   char enableCode[ savesize ];

   // the original code that was contained in the bytes above.
   char disableCode[ savesize ];
   void * location; // the location in memory where we should do our stomping.

protected:
   void enable() { setState( true ); }
   void disable() { setState( false ); }
public:
   uintptr_t realaddr;
   StompMock( const char * name, void * callback, void * handle );
   void setState( bool );
};

/*
 * Construct a mock for function called name_, to call function callback_
 * Function is looked up with dlsym using handle (which can be RTLD_NEXT)
 */
GOTMock::GOTMock( const char * name_, void * callback_, void * handle )
      : callback( callback_ ) {
   // Override function in all libraries.
   for ( auto map = _r_debug.r_map; map; map = map->l_next )
      processLibrary( map->l_name, map->l_ld, map->l_addr, name_ );
   realaddr = ( uintptr_t )dlsym( handle, name_ );
}

/*
 * Locate GOT entries that refer to our function by name. This is templated to work
 * for ELF Rela and Rel locations. handleAddend is overloaded for each, and can
 * handle the addend parts for rela, if we ever care about them
 */
template< typename reltype >
void
GOTMock::findGotEntries( ElfW( Addr ) loadaddr,
                         const reltype * relocs,
                         size_t reloclen,
                         const ElfW( Sym ) * symbols,
                         const char *function,
                         const char * strings ) {
   for ( int i = 0;; ++i ) {
      if ( ( char * )( relocs + i ) >= ( char * )relocs + reloclen )
         break;
      auto & reloc = relocs[ i ];
      auto symidx = ELF_R_SYM( reloc.r_info );
      auto & sym = symbols[ symidx ];
      const char * name = strings + sym.st_name;
      // If we find the funciton we want, update the GOT entry with ptr to our code.
      if ( strcmp( name, function ) == 0 ) {
         ElfW( Addr ) loc = reloc.r_offset + loadaddr;
         void ** addr = reinterpret_cast< void ** >( loc );
         handleAddend( reloc );
         replaced[ loc ] = *addr;
      }
   }
}

void *
PreMock::callbackFor( void * got, void * func ) {
   auto & thunk = thunks[ got ];
   if ( thunk == nullptr ) {
      void * p;
      int rc = posix_memalign( &p, 4096, 8192 );
      if ( rc != 0 )
         abort();
      thunk.reset( p );
      void ** bufp = ( void ** )p;
      memcpy( p, cmock_thunk_function, cmock_thunk_end - cmock_thunk_function );

#ifdef __LP64__
      bufp[ 1020 ] = &bufp[ 1019 ];
      bufp[ 1021 ] = got;
      bufp[ 1022 ] = callback;
      bufp[ 1023 ] = ( void * )func;
#else
      // the end of the second page contains the addresses of our two functions
      // (indexes 2047 and 2046), the stack pointer (index 2045), and the rest
      // is the stack itself (1024 to 2044). If we overflow the stack, we'll
      // try and write to the read-only executable page, and fault quickly.
      bufp[ 2044 ] = &bufp[ 2043 ];
      bufp[ 2045 ] = got;
      bufp[ 2046 ] = callback;
      bufp[ 2047 ] = ( void * )func;
#endif
      mprotect( bufp, 4096, PROT_READ | PROT_EXEC );
   }
   return thunk.get();
}

/*
 * Go over all the offsets in the GOT that refer to us, and patch in our mock.
 */
void
PreMock::enable() {
   for ( auto & addr : replaced ) {
      auto p = ( void ** )addr.first;
      protect( PROT_READ | PROT_WRITE, p, sizeof callback );
      *p = callbackFor( ( void * )addr.first, ( void * )addr.second );
   }
}

/*
 * Go over all the offsets in the GOT that refer to us, and patch in our mock.
 */
void
GOTMock::enable() {
   for ( auto & addr : replaced ) {
      auto p = ( void ** )addr.first;
      protect( PROT_READ | PROT_WRITE, p, sizeof callback );
      *p = callback;
   }
}

/*
 * Go over all the offsets in the GOT that refer to us, and replace the original
 * function.
 */
void
GOTMock::disable() {
   for ( auto & addr : replaced )
      *( void ** )addr.first = addr.second;
}

/*
 * Process a single library's relocation information:
 * Find the DT_REL or DT_RELA relocations, then find
 * relocations for the named function in there.
 */
void
GOTMock::processLibrary( const char * libname,
                         ElfW( Dyn ) * dynamic,
                         ElfW( Addr ) loadaddr,
                         const char * function ) {
   int reltype = -1;
   ElfW( Rel ) * relocs = 0;
   ElfW( Rela ) * relocas = 0;
   ElfW( Word ) reloclen = -1;
   ElfW( Sym ) * symbols = 0;
   const char * strings = 0;

   for ( auto i = 0; dynamic[ i ].d_tag != DT_NULL; ++i ) {
      auto & dyn = dynamic[ i ];
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
      findGotEntries( loadaddr, relocs, reloclen, symbols, function, strings );
      break;
    case DT_RELA:
      findGotEntries( loadaddr, relocas, reloclen, symbols, function, strings );
      break;
    default:
      break;
   }
}

/*
 * Install a stomping mock for function name, to call the mock "callback"
 * "handle" here specifies the library containing the function we want to
 * mock out.
 */
StompMock::StompMock( const char * name, void * callback, void * handle ) {
   void * lib = handle ? handle : RTLD_DEFAULT;

   /* find the symbol for this function. */
   location = dlsym( lib, name );
   if ( !location ) {
      std::cerr << "no symbol found for " << name << ", handle " << handle << ": "
                << dlerror() << std::endl;
      throw std::exception();
   }

   /*
    * save the first 5 bytes of the function, and generate code for a jmp
    * instruction to the callback.
    */
   unsigned char * insns = ( unsigned char * )location;
   memcpy( disableCode, insns, savesize );
   if ( __WORDSIZE == 32 ) {
      enableCode[ 0 ] = 0xe9;
      // Calculate relative offset of jmp instruction, and insert that into our insn.
      uintptr_t jmploc = ( unsigned char * )callback - ( insns + 5 );
      memcpy( enableCode + 1, &jmploc, sizeof jmploc );
   } else {
      // movabsq <callback>, %r11
      enableCode[ 0 ] = 0x49;
      enableCode[ 1 ] = 0xbb;
      memcpy( enableCode + 2, &callback, sizeof callback );
      // jmp *%r11
      enableCode[ 10 ] = 0x41;
      enableCode[ 11 ] = 0xff;
      enableCode[ 12 ] = 0xe3;
   }
}

void
StompMock::setState( bool state ) {
   protect( PROT_READ | PROT_WRITE, location, sizeof enableCode );
   memcpy( location, state ? enableCode : disableCode, sizeof enableCode );
   protect( PROT_READ | PROT_EXEC, location, sizeof enableCode );
}

/*
 * Python glue for each mock type.
 */
template< typename MockType >
static PyObject *
newMock( PyTypeObject * subtype, PyObject * args, PyObject * kwds ) {
   auto obj = reinterpret_cast< MockType * >( subtype->tp_alloc( subtype, 0 ) );

   const char * name;
   long long callback;
   long long handle;

   if ( !PyArg_ParseTuple( args, "sLL", &name, &callback, &handle ) )
      return nullptr;
   new ( obj ) MockType( name, ( void * )callback, ( void * )handle );
   return reinterpret_cast< PyObject * >( obj );
}

template< typename T >
static PyObject *
enableMock( PyObject * self, PyObject * args ) {
   auto * mock = reinterpret_cast< T * >( self );
   enableMock(mock);
   Py_RETURN_NONE;
}

template< typename T >
static PyObject *
disableMock( PyObject * self, PyObject * args ) {
   auto * mock = reinterpret_cast< T * >( self );
   disableMock(mock);
   Py_RETURN_NONE;
}

template< typename T >
static PyObject *
realfuncMock( PyObject * self, PyObject * args ) {
   auto * mock = reinterpret_cast< T * >( self );
   return PyLong_FromLong( mock->realaddr );
}

template< typename T >
static void
freeMock( PyObject * self ) {
   auto t = reinterpret_cast< T * >( self );
   auto typ = Py_TYPE( self );
   disableMock(t);
   t->~T();
   typ->tp_free( t );
}

/*
 * Types for our two mock objects.
 */
static PyTypeObject stompObjectType;
static PyTypeObject preObjectType;
static PyTypeObject gotObjectType;

template< typename T >
void
populateType( PyObject * module,
              PyTypeObject & pto,
              const char * name,
              const char * doc ) {
   static PyMethodDef methods[] = {
      { "enable", enableMock< T >, METH_VARARGS, "enable the mock" },
      { "disable", disableMock< T >, METH_VARARGS, "disable the mock" },
      { "realfunc", realfuncMock< T >, METH_VARARGS, "get pointer to real method" },
      { 0, 0, 0, 0 }
   };
   pto.tp_name = name;
   pto.tp_flags = Py_TPFLAGS_DEFAULT;
   pto.tp_basicsize = sizeof( T );
   pto.tp_methods = methods;
   pto.tp_doc = doc;
   pto.tp_new = newMock< T >;
   pto.tp_dealloc = freeMock< T >;
   if ( PyType_Ready( &pto ) >= 0 ) {
      Py_INCREF( &pto );
      PyModule_AddObject( module, name, ( PyObject * )&pto );
   }
}

static PyObject *
cmock_mangle( PyObject * self, PyObject * args ) {
   // Given a shared library handle, and RE, return a list of tuples, giving
   // (unmangled, mangled) name in the library.

   const char * regexText;
   unsigned long int iHandle;
   if ( !PyArg_ParseTuple( args, "ks", &iHandle, &regexText ) ) {
      return nullptr;
   }

   // Get the library's link-map
   void * handle = ( void * )iHandle;
   struct link_map * lm;
   int rc = dlinfo( handle, RTLD_DI_LINKMAP, &lm );
   if ( rc != 0 ) {
      PyErr_SetString( PyExc_RuntimeError, dlerror() );
      return nullptr;
   }

   // Find sections we are interested in - symbol table, string table, hash table.
   const Elf_Sym * symbols = nullptr;
   const char * strings = nullptr;
   const uint32_t * hash = nullptr;
   const gnu_hash_table * gnu_hash = nullptr;

   for ( auto dyn = lm->l_ld; dyn->d_tag != DT_NULL; ++dyn ) {
      switch ( dyn->d_tag ) {
       case DT_SYMTAB:
         symbols = ( const Elf_Sym * )dyn->d_un.d_ptr;
         break;
       case DT_STRTAB:
         strings = ( const char * )dyn->d_un.d_ptr;
         break;
       case DT_GNU_HASH:
         gnu_hash = ( const gnu_hash_table * )dyn->d_un.d_ptr;
         break;
       case DT_HASH:
         hash = ( const uint32_t * )dyn->d_un.d_ptr;
         break;
       default:
         break; // don't care about anything else.
      }
   }

   if ( gnu_hash == nullptr && hash == nullptr ) {
      PyErr_SetString( PyExc_RuntimeError, "no symbol hash table found" );
      return nullptr;
   }

   if ( symbols == nullptr ) {
      PyErr_SetString( PyExc_RuntimeError, "no symbol table found" );
      return nullptr;
   }

   if ( strings == nullptr ) {
      PyErr_SetString( PyExc_RuntimeError, "no string table found" );
      return nullptr;
   }

   regex_t regex;
   rc = regcomp( &regex, regexText, REG_EXTENDED | REG_NOSUB );
   if ( rc != 0 ) {
      char buf[ 1024 ];
      regerror( rc, &regex, buf, sizeof buf );
      PyErr_SetString( PyExc_RuntimeError, buf );
      return nullptr;
   }

   size_t outbuf_size = 1024;
   char * demangled = ( char * )malloc( outbuf_size );
   auto list = PyList_New( 0 );

   // Because the section headers are not loaded into the process at runtime,
   // there is no simple marker anywhere in the process to work out where the
   // section table ends/how big it is. The only option is to walk the hash
   // table (either GNU or SYSV). If we find neither version of the hash table,
   // we can't continue.
   //
   // Because we have to process the hash anyway, and because the hash table
   // will automatically filter out undefined and private symbols, we actually
   // process the symbols as we do this walk, rather than just working out how
   // big the "symbols" array is, as it avoids accessing symbols we don't care
   // about. (And, in reality, the symbol indexes are ordered, so the accesses
   // are actually contiguous anyhow.

   auto processSymbol = [&]( const Elf_Sym & sym ) {
      auto tuple = PyTuple_New( 2 );

      assert( sym.st_shndx != SHN_UNDEF );
      auto name = strings + sym.st_name;
      if ( name[ 0 ] != '_' || name[ 1 ] != 'Z' )
         return; // only interested in C++ names.
      int status = 0;

      char * newbuf = abi::__cxa_demangle( name, demangled, &outbuf_size, &status );
      if ( newbuf == nullptr || status != 0 )
         return;
      demangled = newbuf; // __cxa_demangle may pass "demangled" through realloc.
      int rc = regexec( &regex, demangled, 0, nullptr, 0 );
      if ( rc != 0 )
         return;
      PyTuple_SetItem( tuple, 0, PyUnicode_FromString( demangled ) );
      PyTuple_SetItem( tuple, 1, PyUnicode_FromString( name ) );
      PyList_Append( list, tuple );
   };

   if ( gnu_hash != nullptr ) {
      // Walk .gnu_hash
      for ( uint32_t bucket = 0; bucket < gnu_hash->nbuckets; ++bucket ) {
         const uint32_t * bucketword = gnu_hash_bucket( gnu_hash, bucket );
         auto idx = *bucketword;
         if ( idx != 0 ) {
            // Process non-empty chain
            for ( ;; idx++ ) {
               processSymbol( symbols[ idx ] );
               if ( ( *gnu_hash_chain( gnu_hash, idx ) & 1 ) != 0 )
                  break;
            }
         }
      }
   } else {
      // Walk .hash
      uint32_t nbuckets = hash[ 0 ];
      const uint32_t * buckets = hash + 2;
      const uint32_t * chains = buckets + nbuckets;
      for ( uint32_t bucket = 0; bucket < nbuckets; ++bucket )
         for ( int idx = buckets[ bucket ]; idx != STN_UNDEF; idx = chains[ idx ] ) {
            auto & sym = symbols[ idx ];
            if ( sym.st_shndx != SHN_UNDEF )
               processSymbol( sym );
         }
   }
   free( demangled );
   regfree( &regex );
   return list;
}

static PyMethodDef mock_methods[] = {
   { "mangle",
     cmock_mangle,
     METH_VARARGS,
     "convert regex for C++ function to mangled names" },
   { 0, 0, 0, 0 }
};

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
      mock_methods, /* m_methods */
      NULL, /* m_reload */
      NULL, /* m_traverse */
      NULL, /* m_clear */
      NULL, /* m_free */
   };
   PyObject * module = PyModule_Create( &ctypeMockModule );
#else
   PyObject * module =
      Py_InitModule3( "libCTypeMock", mock_methods, "CTypeMock C support" );
#endif
   populateType< StompMock >(
      module, stompObjectType, "StompMock", "A stomping mock" );
   populateType< GOTMock >(
      module, gotObjectType, "GOTMock", "A GOT hijacking mock" );
   populateType< PreMock >(
      module, preObjectType, "PreMock", "A pre-executing GOT hijacking mock" );

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
cfuncTypeToPtrToFunc( void * function ) {
   return function;
}
}
