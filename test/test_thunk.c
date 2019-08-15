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

#define _POSIX_C_SOURCE 201901
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>

int
f( int a, int b ) {
   printf( "called f(%d, %d)\n", a, b );
   return 24;
}

int
g( int a, int b ) {
   printf( "called g(%d, %d)\n", a, b );
   return 42;
}

typedef int ( *func_t )( int, int );

extern char cmock_thunk_data;
extern char cmock_thunk_end;

int
main() {
   void * buf;
   int rc = posix_memalign( &buf, 4096, 4096 * 2 );
   memcpy( buf, &cmock_thunk_data, &cmock_thunk_end - &cmock_thunk_data );
   void ** bufp = ( void ** )buf;
   bufp[ 0 ] = f;
   bufp[ 1 ] = g;
   bufp[ 2047 ] = &bufp[ 2046 ];
   mprotect( bufp, 4096, PROT_WRITE | PROT_EXEC );
   func_t fp = ( func_t )( bufp + 2 );
   rc = fp( 4, 5 );
   printf( "function returned %d\n", rc );
}
