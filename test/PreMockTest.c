/*
   Copyright 2019 Arista Networks.

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

#include <assert.h>

/*
 * Testing for the "pre" mock type. preEntry calls preF with *ipval == 22, but
 * we expect it to run through the python wrapper, which changes *ipval to 42.
 * Because Clang does IPA between functions (even global functions) in the same
 * unit, we cannot place preF in this file - it's defined in PreMockTestExtern.c
 */
void
preEntry() {
   int val = 22;
   preF( 0, "hello world", &val );
   assert( val == 24 ); // make sure the actual function is called.
}

// GCC >= 8 will not call thru the PLT for directly recursive functions, which
// means we cannot properly mock out the recursive calls. We try our best for
// indirect, mutually recursive functions, though.
//
// Again, clang goes through the PLT, but does interprocedural analysis on
// global functions in the same translation unit, which means we need to put
// this in a separate .c file.
void preRecurse( int val );

void
mutualRecurse( int val ) {
   preRecurse( val );
}

void
preRecurseEntry( int recursionCount ) {
   preRecurse( recursionCount );
}
