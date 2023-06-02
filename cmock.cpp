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
#define PY_SSIZE_T_CLEAN 1
#include <Python.h>
#ifdef __clang__
#pragma GCC diagnostic pop
#endif
#include <iostream>
#include <map>
#include <memory>
#include <sstream>
#include <vector>

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
#define ELF_R_TYPE( reloc ) ELF32_R_TYPE( reloc )
typedef Elf32_Sym Elf_Sym;
typedef Elf32_Dyn Elf_Dyn;
typedef Elf32_Ehdr Elf_Ehdr;
typedef Elf32_Shdr Elf_Shdr;
#else
#define ELF_R_SYM( reloc ) ELF64_R_SYM( reloc )
#define ELF_R_TYPE( reloc ) ELF64_R_TYPE( reloc )
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

extern char cmock_thunk_function[];
extern char cmock_thunk_end[];

namespace {

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

/* This is a cache of the data from /proc/self/maps that gives us the memory
 * protection for each span therein. When iterating over all the shared
 * libraries, and all the relocs therein, we cache this information once.
 */
class MemoryProtection {
   // "ranges" maps the beginning and end of a range, and gives its protection
   // mode. The key to the map is the end of the range, and we store the start
   // in the value. This makes std::map::upper_bound an easy way to find the
   // relevant entry
   struct ProtRange {
      uintptr_t low;
      int prot;
   };
   std::map< uintptr_t, ProtRange > ranges;

 public:
   MemoryProtection();
   int protectionFor(
      void * arg ) const; // return the protection for the address arg.
};

MemoryProtection::MemoryProtection() {
   // We use fopen/fclose rather than going through the C++ standard library.
   // For now, we excuse the shared libraries for libc, python, and this
   // extension module when enabling mocks, so this module and the python
   // interpreter can safely call functions in those libraries without fear of
   // unexpectedly ending up back in the python interpreter (either directly,
   // or from libc calling one of its own internal functions that have been
   // mocked). We could also excuse libstdc++, but there's no compelling need
   // to do that yet

   FILE * procSelfMaps = fopen( "/proc/self/maps", "r" );
   for ( char buf[ 1024 ]; fgets( buf, sizeof buf, procSelfMaps ); ) {
      std::istringstream ls{ buf };
      std::string prot;
      uintptr_t from, to;
      char _;
      ls >> std::hex >> from >> _ >> to >> prot;
      int protv = 0;
      for ( auto c : prot ) {
         switch ( c ) {
          case 'x':
            protv |= PROT_EXEC;
            break;
          case 'r':
            protv |= PROT_READ;
            break;
          case 'w':
            protv |= PROT_WRITE;
            break;
          default:
            break;
         }
      }
      // Keyed by ending address for std::upper_bound
      ranges[ to ] = { from, protv };
   }
   fclose( procSelfMaps );
}

int
MemoryProtection::protectionFor( void * loc ) const {
   auto pi = uintptr_t( loc );

   auto range = ranges.upper_bound( pi );
   if ( range != ranges.end() && range->second.low <= pi ) {
      return range->second.prot;
   }
   throw std::runtime_error( "no mapping for given address" );
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

// An RAII object to make a specific address range writeable while in scope. It
// also performs a cache flush when making the memory readable again, to ensure
// the instruction cache is up to date with the data writes.
struct MakeWriteable {
   void * start;
   size_t len;
   int origProt;
   MakeWriteable( const MemoryProtection & prot, void * start_, size_t len_ )
         : start( start_ ),
           len( len_ ),
           origProt( prot.protectionFor( start ) ) {
      protect( PROT_READ | PROT_WRITE, start, len );
   }
   ~MakeWriteable() {
      protect( origProt, start, len );
      // Because we've updated the text, we need to ensure the icache and dcache are
      // coherent. This matters for aarch64.
      __builtin___clear_cache( (char *)start, ( char * )start + len );
   }
};

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

template< typename M >
void
enableMock( M * m ) {
   if ( ++m->enableCount == 1 )
      m->enable();
}

template< typename M >
void
disableMock( M * m ) {
   if ( --m->enableCount == 0 )
      m->disable();
}

struct Mock {
   // clang-format off
   PyObject_HEAD
   int enableCount;
   // clang-format on
   Mock() : enableCount{ 0 } {}
};

// This contains the information necessary to refer to an address at a position
// referred to by a relocation. It holds the relocation record from the ELF
// image, the address to be relocated, and the original content of that address
// before we messed with it
class Replacement {
   ElfW( Rela ) relocation;

 public:
   const uintptr_t address; // relocation offset + loadaddr.
   const uintptr_t original; // original content saved from `address`
   // set the address to refer to the specified address, performing whatever
   // activity the relocation type requires.
   void set( const MemoryProtection &, uintptr_t ) const;
   void reset( const MemoryProtection & ); // replace original content.
   Replacement( ElfW( Rela ) rela, uintptr_t address )
         : relocation( rela ),
           address( address ),
           original( *reinterpret_cast< uintptr_t * >( address ) ) {}
};

class GOTMock : protected Mock {
   friend void enableMock< GOTMock >( GOTMock * );
   friend void disableMock< GOTMock >( GOTMock * );

 protected:
   std::vector< Replacement > replacements;
   void * callback;
   void enable();
   void disable();

 public:
   uintptr_t realaddr;
   GOTMock( const char * name_, void * callback_, void * handle_ );
   void processLibrary( const MemoryProtection &,
                        const char *,
                        ElfW( Dyn ) * dynamic,
                        uintptr_t loadaddr,
                        const char * function );
   static ElfW( Rela ) asAddend( const ElfW( Rel ) & rel ) {
      ElfW( Rela ) rela;
      rela.r_offset = rel.r_offset;
      rela.r_info = rel.r_info;

#ifdef __i386__
      // XXX: "-4" below is an assumption, but it's almost certainly correct.
      //
      // From the i386 ABI supplement:
      // ```
      //  The Intel386 architecture uses only Elf32_Rel relocation entries,
      //  the field to be relocated holds the addend.
      // ```
      //
      // i.e., the addend for an i386 relocation is held in the location to be
      // relocated before it is relocated, not in the r_addend field that we'd
      // have for a "rela" relocation. For call instructions, the 4 bytes after
      // the "call" opcode are an address relative to the instruction pointer
      // as it would notionally be just after the call instruction (i.e., the
      // same as the value the call will push on the stack). Hence, the
      // relative offset needs to be adjusted by subtracting 4 from the address
      // of the relocation itself, so the shared object will generally have
      // 0xfffffffc as offset for the call instruction.
      //
      // That value has been lost by the time we look at it when the loader
      // originally resolved things, so just assume -4. If there's ever a
      // reason to, we could map the page from the file, and check there, but
      // it's a lot of work for no practical benefit.
      rela.r_addend = ELF_R_TYPE( rel.r_info ) == R_386_PC32 ? -4 : 0;
#else
      rela.r_addend = 0;
#endif
      return rela;
   }
   static ElfW( Rela ) asAddend( const ElfW( Rela ) & rela ) {
      return rela;
   }

   template< typename reltype >
   int processRelocs( const MemoryProtection &,
                      uintptr_t loadaddr,
                      const reltype * relocs,
                      size_t reloclen,
                      const ElfW( Sym ) * symbols,
                      const char * function,
                      const char * strings );
};

class PreMock : public GOTMock {
   friend void enableMock< PreMock >( PreMock * );
   friend void disableMock< PreMock >( PreMock * );
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
   friend void enableMock< StompMock >( StompMock * );
   friend void disableMock< StompMock >( StompMock * );

   // Store two sets of machine code - one, enableCode, for when the mock is
   // enabled (to jump to the mocking function), and one, disableCode, for when
   // its disabled (the original code that was present in the mocked function).
   // These get copied over the mocked function's prelude to enable/disable the
   // mock.
#ifdef __aarch64__
   // Because ARM instructions are fixed-width, it's easiest to deal with the
   // text as an array of 32-bit values. We need 5 for our jump code for this
   // platform - one to move each 16 bits of the address, and the branch
   // itself.
   using TEXT = uint32_t;
   static constexpr int savecount = 5;
#else
   // For x86, we have variable width instructions, so deal with them as bytes.
   // For 32-bit, we need a single byte for the call opcode, and an address.
   // For 64-bit, we need a move-to-register, and jump-to-register, taking 13
   // bytes total.
   using TEXT = unsigned char;
   static constexpr int savecount = __WORDSIZE == 32 ? 5 : 13;
#endif
   TEXT enableCode[ savecount ];
   TEXT disableCode[ savecount ];

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
   MemoryProtection addressSpace;
   for ( auto map = _r_debug.r_map; map; map = map->l_next )
      processLibrary( addressSpace, map->l_name, map->l_ld, map->l_addr, name_ );
   realaddr = ( uintptr_t )dlsym( handle, name_ );
}

/*
 * Locate relocation entries that refer to our function by name. This is
 * templated to work for ELF Rela and Rel relocations. asAddend is overloaded
 * for each to convert a REL reloc to a RELA reloc.
 */
template< typename reltype >
int
GOTMock::processRelocs( const MemoryProtection & addressSpace,
                        uintptr_t loadaddr,
                        const reltype * relocs,
                        size_t reloclen,
                        const ElfW( Sym ) * symbols,
                        const char * function,
                        const char * strings ) {
   int count = 0;
   for ( int i = 0;; ++i ) {
      if ( ( char * )( relocs + i ) >= ( char * )relocs + reloclen )
         break;
      auto & reloc = relocs[ i ];
      auto symidx = ELF_R_SYM( reloc.r_info );
      auto & sym = symbols[ symidx ];
      const char * name = strings + sym.st_name;
      // If we find the funciton we want, update the GOT entry with ptr to our code.
      if ( strcmp( name, function ) == 0 ) {
         uintptr_t loc = reloc.r_offset + loadaddr;
         replacements.emplace_back( asAddend( reloc ), loc );
         ++count;
      }
   }
   return count;
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

#if defined(__LP64__)
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

constexpr bool
is_abs_reloc( int reloc_type ) {
#if defined( __i386__ )
   return reloc_type == R_386_32 || reloc_type == R_386_JMP_SLOT;
#elif defined( __x86_64__ )
   return reloc_type == R_X86_64_JUMP_SLOT;
#elif defined( __aarch64__ )
   return reloc_type == R_AARCH64_GLOB_DAT || reloc_type == R_AARCH64_JUMP_SLOT;
#else
#error "unsupported architecture"
#endif
}

void
Replacement::set( const MemoryProtection & addressSpace,
                  uintptr_t content ) const {
   MakeWriteable here( addressSpace, ( void * )address, sizeof content );
   auto rtype = ELF_R_TYPE( relocation.r_info );
   if ( is_abs_reloc( rtype ) ) {
      // We deal mostly with absolute relocations, i.e., in the
      // nomenclature of the ELF standard, we have "A"ddend, "S"ymbol and
      // "P"lace, we expect the value at "P" to be assigned the value of "S"
      // the value placed is "S"
      *( uintptr_t * )address = content + relocation.r_addend;
   } else {
      // Deal with other types of relocations, on various platforms, where we
      // need to do something cleverer
#if defined( __i386__ )
      switch ( rtype ) {
       case R_386_PC32:
         *( uintptr_t * )address = content - address + relocation.r_addend;
         break;
       default:
         throw std::runtime_error( "unsupported relocation type" );
      }
#else
      throw std::runtime_error( "unsupported relocation type" );

#endif
   }
}

void
Replacement::reset( const MemoryProtection & addressSpace ) {
   MakeWriteable here( addressSpace, ( void * )address, sizeof original );
   *( uintptr_t * )address = original;
}

/*
 * Go over all the offsets in the GOT that refer to us, and patch in our mock.
 */
void
PreMock::enable() {
   MemoryProtection addressSpace;
   for ( auto & replacement : replacements ) {
      auto code = callbackFor( ( void * )replacement.address,
                               ( void * )replacement.original );
      replacement.set( addressSpace, ( uintptr_t )code );
   }
}

/*
 * Go over all the offsets in the GOT that refer to us, and patch in our mock.
 */
void
GOTMock::enable() {
   MemoryProtection addressSpace;
   for ( auto & replacement : replacements ) {
      replacement.set( addressSpace, ( uintptr_t )callback );
   }
}

/*
 * Go over all the offsets in the GOT that refer to us, and replace the original
 * function.
 */
void
GOTMock::disable() {
   MemoryProtection addressSpace;
   for ( auto & replacement : replacements ) {
      replacement.reset( addressSpace );
   }
}

/*
 * Process a single library's relocation information:
 * Find the DT_REL or DT_RELA relocations, then find
 * relocations for the named function in there.
 */
void
GOTMock::processLibrary( const MemoryProtection & addressSpace,
                         const char * libname,
                         ElfW( Dyn ) * dynamic,
                         uintptr_t loadaddr,
                         const char * function ) {
   int reltype = -1;
   ElfW( Rel ) * jmprel = 0, *rel = 0;
   ElfW( Rela ) * jmprela = 0, *rela = 0;
   ElfW( Word ) jmp_rel_len = -1, rel_len = -1;
   ElfW( Sym ) * symbols = 0;
   const char * strings = 0;
   bool text_relocs = false;

   // don't stub calls from libpython, libc, or ourselves.
   if ( strstr( libname, "libpython" ) )
      return;
   if ( strstr( libname, "libCTypeMock" ) )
      return;
   if ( strstr( libname, "libc." ) )
      return;

   for ( auto i = 0; dynamic[ i ].d_tag != DT_NULL; ++i ) {
      auto & dyn = dynamic[ i ];
      switch ( dyn.d_tag ) {
       case DT_REL:
         rel = ( ElfW( Rel ) * )( dyn.d_un.d_ptr );
         break;
       case DT_RELA:
         rela = ( ElfW( Rela ) * )( dyn.d_un.d_ptr );
         break;
       case DT_RELSZ:
         rel_len = dyn.d_un.d_val;
         break;
       case DT_RELASZ:
         rel_len = dyn.d_un.d_val;
         break;

       case DT_TEXTREL:
         // this is an indicator that there are text relocations present. This
         // should only happen on i386, where you can dynamically link non-PIC
         // code
         text_relocs = true;
         break;

       case DT_PLTREL:
         reltype = dyn.d_un.d_val;
         break;
       case DT_JMPREL:
         jmprela = ( ElfW( Rela ) * )( dyn.d_un.d_ptr );
         jmprel = ( ElfW( Rel ) * )( dyn.d_un.d_ptr );
         break;
       case DT_PLTRELSZ:
         jmp_rel_len = dyn.d_un.d_val;
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
      processRelocs(
         addressSpace, loadaddr, jmprel, jmp_rel_len, symbols, function, strings );
      break;
    case DT_RELA:
      processRelocs(
         addressSpace, loadaddr, jmprela, jmp_rel_len, symbols, function, strings );
      break;
    default:
      break;
   }

   if ( text_relocs ) {
      // We really only will ever see "rel" here - i386 doesn't use rela, and
      // we would not get both in the same ELF file anyway.
      if ( rel ) {
         processRelocs(
            addressSpace, loadaddr, rel, rel_len, symbols, function, strings );
      }
      if ( rela ) {
         processRelocs(
            addressSpace, loadaddr, rela, rel_len, symbols, function, strings );
      }
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
      std::ostringstream os;
      os << "no symbol found for " << name << ", handle " << handle << ": "
         << dlerror() << std::endl;
      throw std::runtime_error( os.str() );
   }

   // Try to ensure the function is big enough to mock - Use dladdr1 to find
   // the symbol, and, if we can, and it has a non-zero size, make sure it's at
   // least as large as our stomp jumping code.
   Dl_info info;
   ElfW(Sym) *sym;
   int rc = dladdr1( location, &info, (void **)&sym, RTLD_DL_SYMENT );
   if ( rc != -1 && sym->st_size && sym->st_size < sizeof enableCode ) {
      std::ostringstream os;
      os << "function '" <<  name << "' is too small (" << sym->st_size
         << " bytes) to mock - it must be at least " << sizeof enableCode;
      throw std::runtime_error( os.str() );
   }

   /*
    * save the first 5 bytes of the function, and generate code for a jmp
    * instruction to the callback.
    */
   memcpy( disableCode, location, sizeof disableCode );
#ifdef __aarch64__
   uintptr_t jmploc = ( uintptr_t )callback;

   // mov x9, (bits 0-15 of jmploc )
   enableCode[0] = 0xd2800000 | ( ( jmploc & 0xffff ) << 5 ) | 9;

   // movk x9, (bits 16-31 of jmploc), LSL#16  (hw=1)
   enableCode[1] = 0xf2800000 | (1 << 21) | ( ( jmploc >> 16 ) & 0xffff ) << 5 | 9;

   // movk x9, (bits 32-47 of jmploc), LSL#32  (hw=2)
   enableCode[2] = 0xf2800000 | (2 << 21) | ( ( jmploc >> 32 ) & 0xffff ) << 5 | 9;

   // movk x9, (bits 48-63 of jmploc), LSL#48 (hw=3)
   enableCode[3] = 0xf2800000 | (3 << 21) | ( ( jmploc >> 48 ) & 0xffff ) << 5 | 9;

   // br x9
   enableCode[4] = 0xd61f0000 |(9 << 5);

#else
   if ( __WORDSIZE == 32 ) {
      enableCode[ 0 ] = 0xe9;
      // Calculate relative offset of jmp instruction, and insert that into our insn.
      uintptr_t jmploc = ( TEXT * )callback - ( TEXT * )location - 5;
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
#endif
}

void
StompMock::setState( bool state ) {
   MemoryProtection addressSpace;
   MakeWriteable here( addressSpace, location, sizeof enableCode );
   memcpy( location, state ? enableCode : disableCode, sizeof enableCode );
}

/*
 * Python glue for each mock type.
 */
template< typename MockType >
static PyObject *
newMock( PyTypeObject * subtype, PyObject * args, PyObject * kwds ) {
   auto obj = reinterpret_cast< MockType * >( subtype->tp_alloc( subtype, 0 ) );

   const char * name;
   Py_ssize_t namelen;
   long long callback;
   long long handle;

   if ( !PyArg_ParseTuple( args, "s#LL", &name, &namelen, &callback, &handle ) )
      return nullptr;
   try {
      new ( obj ) MockType( name, ( void * )callback, ( void * )handle );
      return reinterpret_cast< PyObject * >( obj );
   }
   catch (const std::exception &ex) {
      subtype->tp_free( obj );
      PyErr_SetString( PyExc_RuntimeError, ex.what() );
      return nullptr;
   }
}

template< typename T >
static PyObject *
enableMock( PyObject * self, PyObject * args ) {
   auto * mock = reinterpret_cast< T * >( self );
   try {
      enableMock( mock );
      Py_RETURN_NONE;
   }
   catch (const std::exception &ex) {
      PyErr_SetString( PyExc_RuntimeError, ex.what() );
      return nullptr;
   }
}

template< typename T >
static PyObject *
disableMock( PyObject * self, PyObject * args ) {
   auto * mock = reinterpret_cast< T * >( self );
   try {
      disableMock( mock );
      Py_RETURN_NONE;
   }
   catch (const std::exception &ex) {
      PyErr_SetString( PyExc_RuntimeError, ex.what() );
      return nullptr;
   }
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
   try {
      disableMock( t );
      t->~T();
      typ->tp_free( t );
   }
   catch (const std::exception &ex) {
      PyErr_SetString( PyExc_RuntimeError, ex.what() );
   }
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
   Py_ssize_t regexLen;
   if ( !PyArg_ParseTuple( args, "ks#", &iHandle, &regexText, &regexLen ) ) {
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

   auto processSymbol = [ & ]( const Elf_Sym & sym ) {
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
      auto pyname = PyUnicode_FromString( name );
      auto pydemangled = PyUnicode_FromString( demangled );
      auto tuple = PyTuple_New( 2 );
      PyTuple_SetItem( tuple, 0, pydemangled );
      PyTuple_SetItem( tuple, 1, pyname );
      PyList_Append( list, tuple );
      Py_DECREF( tuple );
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

} // namespace

/*
 * Initialize python library
 */
PyMODINIT_FUNC
PyInit_libCTypeMock( void )
{
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
   populateType< StompMock >(
      module, stompObjectType, "StompMock", "A stomping mock" );
   populateType< GOTMock >(
      module, gotObjectType, "GOTMock", "A GOT hijacking mock" );
   populateType< PreMock >(
      module, preObjectType, "PreMock", "A pre-executing GOT hijacking mock" );

   return module;
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
