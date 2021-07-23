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

/* We need this in a separate translation unit, as C++ doesn't grok "restrict" */
int
test_qualifiers( char * restrict foo1, volatile char * foo2 ) {
   return test_qualifiers( foo1, foo2 );
}

// C allows us to have a tagged type with the same name as an untagged typedef.
// Make sure we can deal with that.

struct DistinctStructAndTypedef {
   int this_is_the_struct;
};

typedef union _DistinctStructAndTypedef {
   int this_is_the_typedef;
} DistinctStructAndTypedef;

struct DistinctStructAndTypedef thisIsTheStruct;
DistinctStructAndTypedef thisIsTheTypedef;
