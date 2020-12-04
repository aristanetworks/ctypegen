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
#include <iostream>



namespace A { namespace Cpp { namespace Namespace {
int withAFunction(int a, int b) {
   return a * b;
}
} } }



extern "C" {
/*
 * This is the underlying C++ implementation of our function, "f", that
 * we will mock.
 */
int
f( int ival, const char * sval, int * ipval ) {
   std::cout << "the real f(" << ival << ", " << sval << ", " << ipval << ")" << std::endl;
   *ipval = 2;
   return 1;
}

int
g( int ival, const char * sval ) {
   std::cout << "this is the real g " << ival << "/" << sval << "\n";
   return 42;
}

}
