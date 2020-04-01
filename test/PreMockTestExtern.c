/*
   Copyright 2020 Arista Networks.

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
//
#include <unistd.h>
#include <assert.h>
#include <stdio.h>

void mutualRecurse( int val );

int
preF( int ival, const char * sval, int * ipval ) {
   assert( *ipval == 42 ); // should have been changed by the mock
   printf( "preF(%d, %s, %p(%d))\n", ival, sval, ipval, *ipval );
   *ipval = 24;
   return 43;
}

void
preRecurse( int val ) {
   if ( val > 1 )
      mutualRecurse( val - 1 );
   // do something non-trivial after the recursive call to prevent the compiler
   // optimising the recursive tail call.
   getpid();
}
