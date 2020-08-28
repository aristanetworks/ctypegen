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

#include <limits>
#include <typeinfo>
#include <cstdint>
#include <iostream>

template< typename T >
struct EnumToFit {
   enum E {
      start = std::numeric_limits< T >::min(),
      end = std::numeric_limits< T >::max()
   };
   E e;
   EnumToFit() {
      std::cout << typeid( T ).name() << ": start=" << E::start << ", end=" << E::end
                << std::endl;
   }
};
EnumToFit< int8_t > s8t;
EnumToFit< uint8_t > u8t;
EnumToFit< int16_t > s16t;
EnumToFit< uint16_t > u16t;
EnumToFit< int32_t > s32t;
EnumToFit< uint32_t > u32t;
EnumToFit< int64_t > s64t;
EnumToFit< uint64_t > u64t;

enum AllBits {
#define BIT( x ) _##x = 1ULL << x
   BIT( 0 ),
   BIT( 1 ),
   BIT( 2 ),
   BIT( 3 ),
   BIT( 4 ),
   BIT( 5 ),
   BIT( 6 ),
   BIT( 7 ),
   BIT( 8 ),
   BIT( 9 ),
   BIT( 10 ),
   BIT( 11 ),
   BIT( 12 ),
   BIT( 13 ),
   BIT( 14 ),
   BIT( 15 ),
   BIT( 16 ),
   BIT( 17 ),
   BIT( 18 ),
   BIT( 19 ),
   BIT( 20 ),
   BIT( 21 ),
   BIT( 22 ),
   BIT( 23 ),
   BIT( 24 ),
   BIT( 25 ),
   BIT( 26 ),
   BIT( 27 ),
   BIT( 28 ),
   BIT( 29 ),
   BIT( 30 ),
   BIT( 31 ),
   BIT( 32 ),
   BIT( 33 ),
   BIT( 34 ),
   BIT( 35 ),
   BIT( 36 ),
   BIT( 37 ),
   BIT( 38 ),
   BIT( 39 ),
   BIT( 40 ),
   BIT( 41 ),
   BIT( 42 ),
   BIT( 43 ),
   BIT( 44 ),
   BIT( 45 ),
   BIT( 46 ),
   BIT( 47 ),
   BIT( 48 ),
   BIT( 49 ),
   BIT( 50 ),
   BIT( 51 ),
   BIT( 52 ),
   BIT( 53 ),
   BIT( 54 ),
   BIT( 55 ),
   BIT( 56 ),
   BIT( 57 ),
   BIT( 58 ),
   BIT( 59 ),
   BIT( 60 ),
   BIT( 61 ),
   BIT( 62 ),
   BIT( 63 )
};
AllBits allBits;
