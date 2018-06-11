#!/usr/bin/env python
from  CTypeGen import generate, PythonType

generate(["libcallback.so"], "callbackgen.py", [PythonType("Callback")], ["callme"])
