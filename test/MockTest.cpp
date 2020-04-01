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

#include <iostream>
#include <assert.h>

extern "C" {
extern int f( int ival, const char * sval, int * ipval );
extern int g( int ival, const char * sval );
extern void entry( int expect_return, int expect_i );
extern void entry_g( int expect_return );
}

/*
 * This is our function-under-test, that calls "f", and who's behaviour
 * we want to affect. It takes as arguments the values it expects
 * "f" to return, so we can verify if we called the mocked function or the real
 * one.
 * We need to define "f" in a separate translation unit so clang will not do
 * intraprocedural analysis and optimise away parts of "f" (even though it
 * calls it through the PLT)
 */
void
entry( int expect_return, int expect_i ) {
   int i = 1;
   g( 42, "forty-two" );
   int rv = f( i, "hello", &i );
   std::cout << "returned " << rv << ", i is now " << i << std::endl;
   assert( i == expect_i && rv == expect_return );
}

void
entry_g( int expect_return ) {
   int rc = g( 42, "forty-two" );
   assert( rc == expect_return );
}
