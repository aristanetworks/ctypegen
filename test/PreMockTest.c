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

#include <stdio.h>
#include <assert.h>
#include <unistd.h>

/*
 * Testing for the "pre" mock type. We preEntry calls preF with *ipval == 22,
 * but we expect it to run through the python wrapper, which changes *ipval to
 * 42.
 */
int
preF( int ival, const char * sval, int * ipval ) {
   assert( *ipval == 42 ); // should have been changed by the mock
   printf( "preF(%d, %s, %p(%d))\n", ival, sval, ipval, *ipval );
   *ipval = 24;
   return 43;
}

void
preEntry() {
   int val = 22;
   preF( 0, "hello world", &val );
   assert( val == 24 ); // make sure the actual function is called.
}

void
preRecurse( int val ) {
   if ( val > 1 )
      preRecurse( val - 1 );
   // do something non-trivial after the recursive call to prevent the compiler
   // optimising the recursive tail call.
   getpid();
}

void
preRecurseEntry( int recursionCount ) {
   preRecurse( recursionCount );
}
