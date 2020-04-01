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
#include <stdlib.h>

struct g {
   int inputx3;
   int inputx4;
};

struct f {
   int input;
   int inputx2;
   struct g * g;
};

int global42 = 42;

struct f *
create_f( int input ) {
   struct f * f = malloc( sizeof *f );
   f->input = input;
   f->inputx2 = input * 2;
   f->g = malloc( sizeof *f->g );
   f->g->inputx3 = f->input * 3;
   f->g->inputx4 = f->input * 4;
   return f;
};
