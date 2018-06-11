from ctypes import *
import callbackgen

lib = CDLL("./libcallback.so")
callbackgen.decorateFunctions(lib)

def operate(a, b):
    return a * b

print( lib.callme(10, 20, callbackgen.Callback(operate)))
