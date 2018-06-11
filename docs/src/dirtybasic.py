from ctypes import *

lib = CDLL("./libbasic.so")

class SomeStructure(Structure):
    _fields_ = [
            ('i', c_int),
            ('c', c_char),
            ('s', c_char_p )
            ]
lib.someFunction.restype = c_double
lib.someFunction.argtypes = [ POINTER(SomeStructure) ]

s_obj = SomeStructure(3, 'q', b"hello world")
result = lib.someFunction(byref(s_obj))
print("result: %s, new value for text: %s" %
        (result, str(s_obj.s)) )
