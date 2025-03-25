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

import sys
from ctypes import CDLL, CFUNCTYPE, c_void_p, cast
import site
import glob
import _CMock
import _ctypes
import os
import traceback

# We need to look inside ctypes a bit, so, pylint: disable=protected-access

GOT = 1    # GOT mock: use the GOT table to hook the target function with the mock
STOMP = 2  # STOMP mock: overwrite the start of the target function to call the mock
PRE = 3    # PRE mock: GOT mock, but after mock call, call the original function too.

# we need to load the _CTypeGen library as a CDLL, so we can call an
# entry point in it through ctypes, to convert a python function into a
# C pointer-to-function.
cmockCdll = CDLL( _CMock.__file__ )
cmockCdll.cfuncTypeToPtrToFunc.restype = c_void_p
cmockCdll.cfuncTypeToPtrToFunc.argtypes = [ c_void_p ]

def exceptionWrapper( method ):
   ''' If an exception is raised during the processing of the python mock
   function, ctypes/ffi will just ignore the exception. That's exactly the
   opposite of what we want - as we regularly want to do things like assert
   from callbacks. So, wrap the mock functions to ensure that if any exception
   is raised, we print the error, and then abort, rather than ignoring, and
   just returning. '''
   def handler( *kwargs ):
      try:
         rc = method( *kwargs )
      except Exception as ex: # see above - pylint: disable=broad-except
         sys.stderr.write(
               "python exception while running mock function. Exception details:\n" )
         traceback.print_exception( None, ex, ex.__traceback__ )
         sys.stderr.flush()
         os.abort()
      return rc
   return handler


class mocked:
   def __init__( self, function, python, library=None, method=GOT ):
      # ensure a reference to "function" lives as long as the mock
      self.function = function
      check_ctypes_decorations( function )
      linkername = function.__name__
      callbackReturnType = None if method == PRE else function.restype

      if callbackReturnType and issubclass( callbackReturnType, _ctypes._Pointer ):
         callbackReturnType = c_void_p
      callbackType = CFUNCTYPE( callbackReturnType, *function.argtypes,
                                use_errno=True )
      self.callback = callbackType( exceptionWrapper( python ) )
      callbackForC = cmockCdll.cfuncTypeToPtrToFunc( self.callback )
      handle = library._handle if library else 0
      if method == GOT:
         self.mock = _CMock.GOTMock( linkername, callbackForC, handle )
         # "realfunc" only works for GOT mocks: STOMP mocks would just recurse
         # infinitely.
         self.realfunc = cast( self.mock.realfunc(), callbackType )
      elif method == STOMP:
         self.mock = _CMock.StompMock( linkername, callbackForC, handle )
      elif method == PRE:
         self.mock = _CMock.PreMock( linkername, callbackForC, handle )
      else:
         assert False, "Unknown mock method %s" % method

   def enable( self ):
      self.mock.enable()

   def disable( self ):
      self.mock.disable()

   def __enter__( self ):
      self.enable()
      return self

   def __exit__( self, *kwargs ):
      self.disable()

class Mock:
   ''' A decorator to have a python function replace a C function in a process
   Pass it a reference to the funciton, and the library in which you want to
   find and mock it. The function handle should have already had restype and
   argtypes set on it correctly, and the python "mock" function you decorate
   should conform to that. CTypeGen can do this with decorateFunctions '''

   # Default method to GOT for 64 bit, STOMP for 32 bit
   def __init__( self, function, library=None,
         method=( GOT if sys.maxsize > 2**32 else STOMP ) ):
      self.method = method
      self.function = function
      self.library = library
      self.realfunc = None

   def __call__( self, python ):
      mock = mocked( self.function, python, self.library, self.method )
      mock.enable()
      return mock

def mangleFunc( lib, mangledname, restype=None, argtypes=None ):
   mangled = _CMock.mangle( lib._handle, mangledname )
   assert len( mangled ) == 1, \
         "regex must match exactly one symbol in %s" % lib._name
   func = getattr( lib, mangled[ 0 ][ 1 ] )
   if restype is not None:
      func.restype = restype
   if argtypes is not None:
      func.argtypes = argtypes
   return func

def mangleData( lib, ctype, mangledname ):
   mangled = _CMock.mangle( lib._handle, mangledname )
   assert len( mangled ) == 1, \
         "regex must match exactly one symbol in %s" % lib._name
   return ctype.in_dll( lib, mangled[ 0 ][ 1 ] )

def check_ctypes_decorations( function ):
   ''' verify that someone has actually added a list of argument types to
   the ctypes function object. Otherwise, nothing will work
   '''
   try:
      iter( function.argtypes )
   except TypeError:
      sys.stderr.write( "no argument type information provided for function %s. "
                        "Provide 'argtypes' manually, or generate with "
                        "CTypeGen\n" % function.__name__ )
      raise
