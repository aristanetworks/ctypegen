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

// Define mockme in a separate translation unit to avoid clang doing
// interprocedural analysis (even though it calls through the PLT)
//
int mockme( int one, int two, int three );

int
callme( int one, int two, int three ) {
   return mockme( one, two, three );
}
