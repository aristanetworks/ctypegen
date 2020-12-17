#!/usr/bin/python
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

from __future__ import absolute_import, division, print_function
from CTypeGen import generate
import sys

# These don't render properly - packed structures, bitfield issues, etc.
broken = set( [

#      "cached_data",
#      "DIR",
#      "__dirstream",
#      "epoll_data",
#      "epoll_event", # packed
#      "hashentry",
#      "in6addrinfo",
#      "_IO_FILE_complete",
#      "_IO_FILE_complete_plus",
#      "printf_info",
#      "printf_spec",
#      "pthread",
#      "stackblock",
#      "timex",
#      "_Unwind_Exception",

       ] )


#      "__SOCKADDR_ARG", # "Transparent union" - gcc outputs no fields for it.
#      "__WAIT_STATUS", # "Transparent union" - gcc outputs no fields for it.
#      "wait3", # Takes transparent union, __WAIT_STATUS as arg.
#      "__wait3", # Takes transparent union, __WAIT_STATUS as arg.
#      "accept4", # Takes tranparent union, __SOCKADDR_ARG as arg.
#      "__recvfrom_chk", # Takes tranparent union, __SOCKADDR_ARG as arg.

def haveDyn( die ):
   ''' Filter for functions that are in the .dynsym section - we can't call
   other functions anyway, and CTypeGen will just generate a warning if they
   appear. '''
   obj = die.object()
   name = die.DW_AT_linkage_name
   if name is None:
      name = die.name()
   return name in obj.dynnames()

generate(
      [ "./libdbghelper.so", sys.argv[ 1 ] ],
      sys.argv[ 2 ],
      types=lambda name, space, die: name not in broken,
      functions=lambda name, space, die: name not in broken and haveDyn( die ) )
