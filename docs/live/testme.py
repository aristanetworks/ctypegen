#!/usr/bin/env python

import CMock
import libcgen
import testmegen
from ctypes import *
import paths

libc = CDLL( paths.libc )
libtestme = CDLL( paths.testme )

libcgen.decorateFunctions(libc)
testmegen.decorateFunctions(libtestme)

total = 0

@CMock.Mock(libc._IO_fgets, libc, linkername="fgets")
def fgets(sp, maxlen, file):
    global total
    if total < 10:
        total += 1
        return b'10'
    else:
        return None

@CMock.Mock(libc._IO_puts, libc, linkername="puts")
def puts(sp):
    return 0

print "%d\n" % int(libtestme.functionToTest())
