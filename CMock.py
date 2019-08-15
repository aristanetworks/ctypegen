# Copyright 2018 Arista Networks.
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

import sys
from ctypes import CDLL, CFUNCTYPE, c_void_p
import site
import glob
from contextlib import contextmanager
import libCTypeMock

# We need to look inside ctypes a bit, so, pylint: disable=protected-access

GOT = 1    # GOT mock: use the GOT table to hook the target function with the mock
STOMP = 2  # STOMP mock: overwrite the start of the target function to call the mock
PRE = 3    # PRE mock: GOT mock, but after mock call, call the original function too.

# we need to load the libCTypeGen library as a CDLL, so we can call an
# entry point in it through ctypes, to convert a python function into a
# C pointer-to-function.
cmockCdll = None
for sitedir in site.getsitepackages():
   for libName in glob.glob( "%s/libCTypeMock*.so" % sitedir ):
      try:
         cmockCdll = CDLL( libName )
         break
      except OSError:
         pass

if cmockCdll is None:
   cmockCdll = CDLL( "libCTypeMock.so" )
assert cmockCdll
callbacks = []
cmockCdll.cfuncTypeToPtrToFunc.restype = c_void_p
cmockCdll.cfuncTypeToPtrToFunc.argtypes = [ c_void_p ]

class Mock( object ):
   ''' A decorator to have a python function replace a C function in a process
   Pass it a reference to the funciton, and the library in which you want to
   find and mock it. The function handle should have already had restype and
   argtypes set on it correctly, and the python "mock" function you decorate
   should conform to that. CTypeGen can do this with decorateFunctions '''

   def __init__( self, function, inlib=None, forlibs=None, method=None,
           linkername=None ):
      self.forlibs = forlibs
      self.inlib = inlib
      try:
         iter( function.argtypes )
      except TypeError:
         sys.stderr.write( "no argument type information provided for function %s. "
                           "Provide 'argtypes' manually, or generate with "
                           "CTypeGen\n" % function.__name__ )
         raise
      self.callbackType = CFUNCTYPE( None if method == PRE else function.restype,
                                     *function.argtypes )
      self.function = function
      if method is None:
         # Defaults to GOT for 64 bit, STOMP for 32 bits
         self.method = GOT if sys.maxsize > 2**32 else STOMP
      else:
         self.method = method
      self.linkername = linkername
      self.mock = None

   def __call__( self, toMock ):
      if self.linkername is None:
         self.linkername = self.function.__name__
      callback = self.callbackType( toMock )
      callbackForC = cmockCdll.cfuncTypeToPtrToFunc( callback )
      if self.method == GOT:
         self.mock = libCTypeMock.GOTMock( self.linkername, callbackForC, 0 )
      elif self.method == STOMP:
         self.mock = libCTypeMock.StompMock( self.linkername, callbackForC,
                 self.inlib._handle if self.inlib else 0 )
      elif self.method == PRE:
         self.mock = libCTypeMock.PreMock( self.linkername, callbackForC,
                 self.inlib._handle if self.inlib else 0 )
      else:
         assert False, "Unknown mock method %s" % self.method
      toMock.disable = self.mock.disable
      toMock.enable = self.mock.enable
      callbacks.append( ( callback, toMock ) )
      return toMock

@contextmanager
def mocked( function, mock, *args, **kwargs ):
   ''' Context manager for CMocks '''
   mock = Mock( function, *args, **kwargs )( mock )
   yield mock
   mock.disable()
