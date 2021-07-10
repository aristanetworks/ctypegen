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
#define _GLIBCXX_DEBUG

#include <stdlib.h>
#include <iostream>
#include <stdint.h>
#include <string.h>
#include <sstream>
#include <stdio.h>
#include "macrosanity.h"

/*
 * This test helper defines a C structure, a function to create a  populated
 * instance of it, and one to stringify it. We populate it with some verifiable
 * data, and make sure that the generated python code can interrogate it
 * correctly.
 */

struct Bar {
   int x;
   int y;
};

union Baz {
   struct Bar bar;
   int64_t notbar;
};

enum BigNum {
   Small = 1,
   Big = 0x123400000000 // test values > 2^32
};

int
bytwo( int arg ) {
   return arg * 2;
}

namespace AProperCplusplusNamespace {
struct AStructureInTheCplusplusNamespace {
   int x;
};
} // namespace AProperCplusplusNamespace

typedef enum {
   AETD_1,
   AETD_2,
   AETD_3,
} AnonEnumWithTypedef;

// Tests for global variables
const char * ExternalStrings[] = {
   "zero",
   "one",
   "two",
   "three",
   "four",
   "five",
   "six",
   "seven",
};

struct AnotherStruct {
   int x;
};
AnotherStruct ExternalStruct = { .x = 42 };

struct WithAnonStructUnion {
   int field1;

   struct {
      int field2;
      float field3;
   };
   int field4;
   union {
      int field5;
      float field6;
   };
   int field7;
};

struct Foo {
   std::string aCppString;
   int anInt;
   char aChar;
   long aLong;
   bool aBool;
   double aDouble;
   char aOneDimensionalArrayOfChar[ 17 ];
   long aTwoDimensionalArrayOfLong[ 17 ][ 13 ];
   struct Bar aNestedStructure;
   struct Bar * aNestedStructurePointer;
   union Baz aNestedUnion;
   struct Foo * next;
   intptr_t anIntPtr;
   size_t aSizeT;
   const char * aCString;
   enum { Zero, One, Two, Three } anEnum;
   struct InANamespace {
      int foo;
   };
   InANamespace anInstanceOfInANamespace;
   enum BigNum bigEnum;
   int ( *aFuncPtr )( int );

   // first int:
   int aBitFieldPart1 : 10;
   int aBitFieldPart2 : 5;
   int : 17;

   // second int:
   int : 9;                     // 0 : need to fake this with pre-padding for ctypes.
   int aBitFieldPart3 : 6;      // 9
   int : 2;                     // 15
   int aBitFieldPart4 : 8;      // 17
   int : 2;                     // 25

   // third int.
   int aBitFieldPart5 : 22;

   AProperCplusplusNamespace::AStructureInTheCplusplusNamespace
      aCplusplusNamespacedField;
   AnonEnumWithTypedef anonEnumField;
   WithAnonStructUnion anonMemberField;
   char emptyArray[ 0 ];
};

typedef struct Foo Foo_t;

template< typename DataType >
struct Field {
   const char * name;
   const DataType & data;
   Field( const char * name_, const DataType & data_ )
         : name( name_ ), data( data_ ) {}
};

template< typename DataType >
Field< DataType >
make_field( const char * name, const DataType & data ) {
   return Field< DataType >( name, data );
}

template< typename DataType >
std::ostream &
operator<<( std::ostream & os, const Field< DataType > & t ) {
   return os << "\"" << t.name << "\":" << t.data;
}

template<>
std::ostream &
operator<<( std::ostream & os, const Field< char * > & t ) {
   return os << "\"" << t.name << "\": \"" << t.data << "\"";
}

template<>
std::ostream &
operator<<( std::ostream & os, const Field< char > & t ) {
   return os << "\"" << t.name << "\": \"" << t.data << "\"";
}

template<>
std::ostream &
operator<<( std::ostream & os, const Field< bool > & t ) {
   return os << "\"" << t.name << "\": " << ( t.data ? "True" : "False" );
}

template<>
std::ostream &
operator<<( std::ostream & os, const Field< const char * > & t ) {
   return os << "\"" << t.name << "\": \"" << t.data << "\"";
}

#define FIELD( object, name ) make_field( #name, object.name )
#define STRFIELD( object, name ) make_field( #name, ( char * )object.name )

std::ostream &
operator<<( std::ostream & os, const Bar & bar ) {
   return os << "{\n\t" << FIELD( bar, x ) << ",\n\t" << FIELD( bar, y ) << "\n}";
}

std::ostream &
operator<<( std::ostream & os, const Baz & baz ) {
   return os << "{\n\t" << FIELD( baz, bar ) << ",\n\t" << FIELD( baz, notbar )
             << "\n}";
}

std::ostream &
operator<<( std::ostream & os, const Foo & foo ) {
   return os << "{\n\t" << FIELD( foo, anInt )
             << ",\n\t" << FIELD( foo, aChar )
             << ",\n\t" << FIELD( foo, aLong )
             << ",\n\t" << FIELD( foo, aBool )
             << ",\n\t" << FIELD( foo, aDouble )
             << ",\n\t" << STRFIELD( foo, aOneDimensionalArrayOfChar )
             << ",\n\t" << FIELD( foo, aNestedStructure )
             << ",\n\t" << FIELD( foo, aNestedStructurePointer )
             << ",\n\t" << FIELD( foo, aNestedUnion )
             << ",\n\t" << FIELD( foo, anIntPtr )
             << ",\n\t" << FIELD( foo, aSizeT )
             << ",\n\t" << FIELD( foo, bigEnum )
             << ",\n\t" << FIELD( foo, anEnum )
             << ",\n\t" << FIELD( foo, aCString )
             << ",\n\t" << FIELD( foo, aBitFieldPart1 )
             << ",\n\t" << FIELD( foo, aBitFieldPart2 )
             << ",\n\t" << FIELD( foo, aBitFieldPart3 )
             << ",\n\t" << FIELD( foo, aBitFieldPart4 )
             << ",\n\t" << FIELD( foo, aBitFieldPart5 )
             << "\n}";
}

extern "C" {

void
void_return_func() {}

Foo_t *
make_foo() {
   Foo_t * aFoop = ( Foo * )malloc( sizeof( Foo ) );
   Foo_t & aFoo = *aFoop;
   aFoo.anInt = 3;
   aFoo.aChar = 'a';
   aFoo.aLong = 1234;
   aFoo.aBool = 0;
   aFoo.aDouble = 3.14159265358979;
   aFoo.aNestedStructure.x = 100;
   aFoo.aNestedStructure.y = 200;
   aFoo.aNestedStructurePointer = &aFoo.aNestedStructure;
   aFoo.next = &aFoo;
   aFoo.aNestedUnion.bar.x = 1;
   aFoo.aNestedUnion.bar.y = 2;
   aFoo.anIntPtr = ( intptr_t )&aFoo;
   aFoo.aSizeT = sizeof( Foo );
   aFoo.anEnum = Foo::Three;
   aFoo.bigEnum = Big;
   aFoo.aCString = "hello world";
   aFoo.aFuncPtr = bytwo;
   aFoo.aBitFieldPart1 = 100;
   aFoo.aBitFieldPart2 = 10;
   aFoo.aBitFieldPart3 = 20;
   aFoo.aBitFieldPart4 = 30;
   aFoo.aBitFieldPart5 = 40;
   strcpy( aFoo.aOneDimensionalArrayOfChar, "hello world" );
   return aFoop;
}

int
print_foo( const Foo * foo, char * data, size_t maxlen ) {
   std::ostringstream os;
   os << *foo;
   return snprintf( data, maxlen, "%s", os.str().c_str() );
}
}

namespace Outer {
namespace Inner {
struct Leaf {
   int inNamespace;
};
} // namespace Inner
} // namespace Outer

struct Leaf {
   int atGlobalScope;
};

typedef struct NameSharedWithStructAndTypedef {
   int bang;
} NameSharedWithStructAndTypedef;

NameSharedWithStructAndTypedef nameSharedWithStructAndTypedef;

Outer::Inner::Leaf spacedLeaf;
Leaf globalLeaf;

int
main( int argc, char * argv[] ) {
   std::cout << *make_foo() << "\n";
   return 0;
}
