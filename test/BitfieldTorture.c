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

#include <stdint.h>

int main() {}

struct {
   uint32_t :3, a:29;
   uint32_t b: 16, c: 14, :2;
   uint32_t j;
} torture1;

struct {
   uint32_t :32;
   uint32_t :32;
   uint32_t :32;
   uint32_t :32;
   uint32_t :16;
   uint32_t a:4;
} torture2;
