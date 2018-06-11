from basic import *
from ctypes import *

lib = CDLL("./libbasic.so")
decorateFunctions(lib)

s_obj = SomeStructure(3, 'q', "hello world")
result = lib.someFunction(byref(s_obj))
print("result: %s, new value for text: %s" %
        (result, str(s_obj.s)) )
