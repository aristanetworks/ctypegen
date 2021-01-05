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
namespace LookInside {

class ClassWithMethods {
   int field1;
   int addField1AndField2ToArgument( int );

 public:
   int field2;
   int returnsPassedArgument( int );
};

int
ClassWithMethods::returnsPassedArgument( int arg ) {
   return arg;
}

int
ClassWithMethods::addField1AndField2ToArgument( int arg ) {
   return field1 + field2 + arg;
}

} // namespace LookInside
