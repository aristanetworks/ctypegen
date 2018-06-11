#! /usr/bin/env python
from CTypeGen import generate
import paths

generate([ paths.libc ], "libcgen.py", [], ["_IO_fgets", "_IO_puts"])
generate([ paths.testme ], "testmegen.py", [], ["functionToTest"])

