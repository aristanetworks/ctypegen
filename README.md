# CTypeGen
CTypeGen generates the python "ctypes" boilerplate code to allow you call
C functions from python's ctypes, and inspect and construct C structure
types from python.

## Building
This package depends on the `pstack` project [here](http://github.com/peadar/pstack)

You'll need a C++14-capable compiler to generate `pstack` and `CTypeGen`

You need to build `pstack` with shared libraries enabled, and then make
and install this package. For example

```
$ git clone http://github.com/peadar/pstack
$ git clone http://github.com/aristanetworks/ctypegen
$ cd pstack
$ cmake -DCMAKE_BUILD_TYPE=Release LIBTYPE=SHARED .
$ make
$ sudo make install
$ cd ../CTypeGen
$ make
$ sudo make install
$ make test
```

By default, Python 2 modules are installed. You can pass `PYTHON=python3`
when building to get Python 3 modules:

```
$ make PYTHON=python3
$ sudo make PYTHON=python3 install
$ make PYTHON=python3 test
```

## Using
`CTypeGen` saves you the misery of having to type out boilerplate code
to create and interrogate C structures in python using python's `ctype` package.

For example, in python, given:

```
struct S {
   int i;
   char  c;
};
extern double f(S *s);
```

In order to call `f` from python we would need to do the following

```
class S( Structure ):
   _fields_ = [
        ( "i", c_int ),
        ( "c", c_char ),
   ]
lib = CDLL("libname")
lib.f.restype = c_double
lib.f.argtypes = [ POINTER(S) ]

anS = S()
d = lib.f(anS)

```

`CTypeGen` generates the content for `class S`, and a function to decorate
a CDLL containing the funciton "f" with the argument and return types, all
using the debug information created when you compile your shared library.

Once installed, you can call `CTypeGen.generate()` to do the work,
providing it lists of types and functions you are interested in. Eg:

```
from CTypeGen import *

types = [ PythonType("S") ]
functions = [ "f" ]

CTypeGen.generate(["libname"], "libname.py", types, functions)
```
And you'll magically have libname.py with the boilerplate generated for you.
