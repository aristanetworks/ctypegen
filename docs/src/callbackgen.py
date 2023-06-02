from ctypes import * # pylint: disable=wildcard-import
from CTypeGenRun import * # pylint: disable=wildcard-import
# pylint: disable=unnecessary-pass,protected-access



Callback = CFUNCTYPE( c_int, c_int
      , c_int
      )

def decorateFunctions( lib ):
   lib.callme.restype = c_int
   lib.callme.argtypes = [
      c_int,
      c_int,
      Callback ]


functionTypes = {
   'callme': CFUNCTYPE( c_int, c_int
      , c_int
      , Callback
      ),
}


if __name__ == "__main__":
   test_classes()
