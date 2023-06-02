#!/usr/bin/env python3
# Copyright 2020 Arista Networks.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
#     Unless required by applicable law or agreed to in writing, software
#     distributed under the License is distributed on an "AS IS" BASIS,
#     WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#     See the License for the specific language governing permissions and
#     limitations under the License.

'''
Generate ctypes code for libc. We take the debug information from libc, and
also our dbghelper shared library. Some of the typees that libc exposes via
system calls etc are not actually used within libc, so their definitions are
missing. The helper library uses them, so we can find their definitions in
there. '''

from CTypeGen import generate, PythonType
import sys
import platform

# packing issues differ from platform to platform - these set of types need to
# be explicitly packed, or are somehow broken on their respective
# architectures.

if platform.machine() == "aarch64": # A4NOCHECK want CPU arch, not size.
   platformPacked = []
   platformBroken = [
         "DIR",
         "__dirstream",
         "__prfpregset_t",
         "elf_fpregset_t",
         "fpregset_t",
         "link_map",
         "mcontext_t",
         "prfpregset_t",
         "pthread",
         "rtld_global",
         "sigcontext",
         "struct_user_fpsimd_struct",
         "ucontext_t",
         "user_fpsimd_struct",
         ]

elif platform.machine() == "x86_64": # A4NOCHECK, want CPU arch, not size.
   platformPacked = [
         "epoll_event",
         ]
   platformBroken = [
         "DIR",
         "_Unwind_Exception",
         "__dirstream",
         "epoll_data",
         "helper_file",
         "link_map",
         "pthread",
         "stackblock",
         ]

elif platform.machine() in ( "i386", "i686" ): # A4NOCHECK, want CPU arch, not size
   platformPacked = []
   platformBroken = []

else:
   # may need to be filled in for new archs.
   platformPacked = []
   platformBroken = []

# Types that need to be packed on this platform.
packed = {  ( n, ) for n in [
   ] + platformPacked  }

# Broken types on this platform. The additional types here are broken on any
# platforms we've seen
broken = {  ( n, ) for n in [
      "cached_data",
      "hashentry",
      "in6addrinfo",
      "_IO_FILE_complete",
      "_IO_FILE_complete_plus",
      "_IO_lock_t",
      "printf_info",
      "printf_spec",
      "raise", # python keyword.
       ] + platformBroken  }

def haveDyn( die ):
   ''' Filter for functions that are in the .dynsym section - we can't call
   other functions anyway, and CTypeGen will just generate a warning if they
   appear. '''
   addr = die.DW_AT_low_pc
   return addr is not None and addr in die.object().dynaddrs()

def notBroken( die ):
   fname = die.fullname()
   if fname in packed:
      return PythonType( fname, pack=True, unalignedPtrs=True )
   return die.fullname() not in broken

generate(
      [ "./libdbghelper.so", sys.argv[ 1 ] ],
      sys.argv[ 2 ],
      types=notBroken,
      functions=lambda die: notBroken( die ) and haveDyn( die ),
      macroFiles='dbghelper.c',
      namelessEnums=True,
      )
