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

from ctypes import CDLL, CFUNCTYPE, c_void_p
import libCTypeMock
import site
import glob

GOT = 1
STOMP = 2

# we need to load the libCTypeGen library as a CDLL, so we can call an
# entry point in it through ctypes, to convert a python function into a
# C pointer-to-function.
for sitedir in site.getsitepackages():
   for libName in glob.glob( "%s/libCTypeMock*.so" % sitedir ):
      try:
         cmockCdll = CDLL( libName )
         break
      except:
         pass

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

   def __init__( self, function, inlib=None, forlibs=None, method=GOT ):
      self.forlibs = forlibs
      self.inlib = inlib
      self.callbackType = CFUNCTYPE( function.restype, *function.argtypes )
      self.function = function
      self.method = method

   def __call__( self, toMock ):
      callback = self.callbackType( toMock )
      callbackForC = cmockCdll.cfuncTypeToPtrToFunc( callback )
      if self.method == GOT:
         self.mock = libCTypeMock.GOTMock( self.function.__name__, callbackForC, 0 )
      else:
         self.mock = libCTypeMock.StompMock( self.function.__name__, callbackForC, self.inlib._handle if self.inlib else None)
      toMock.disable = lambda: self.mock.disable()
      toMock.enable = lambda: self.mock.enable()
      callbacks.append( ( callback, toMock ) )
      return toMock
