/*
   Copyright 2021 Arista Networks.

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

#ifndef TEST_MACROS_H
#define TEST_MACROS_H

#define A 42
#define B (32 + A)
#define C (32 + B)
#define HELLO "hello world"

// macros with args, including those that use other macros
#define ADD(a, b) (a+b)
#define ADD_42(a) ADD(42, a)

#endif // TEST_MACROS_H

