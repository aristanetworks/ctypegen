# CTypeGen
CTypeGen generates the python "ctypes" boilerplate code to allow you call
C functions from python's ctypes, and inspect and construct C structure
types from python.

It also includes a mocking framework that allows you to mock out functions called
by your C code and intercept them with python code instead.

## Building

This package depends on the `pstack` project [here](http://github.com/peadar/pstack)

pstack is configured as a submodule for this repository.

You'll need cmake, and a C++20-capable compiler to generate `pstack` and `CTypeGen`

To build:
```
$ git clone http://github.com/aristanetworks/ctypegen
$ cd ctypegen
$ git submodule update
$ make
$ sudo make install
$ make test
```

## Generating Boilerplate
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

There are a number of examples run as part of the tests.

## Mocking

There is an example of how to use this in test/MockTest.py. Basic usage is given
a shared library "lib" with function "f":

``` 
int f( int ival, const char * sval, int * ipval );
```

(that you will have decorated with ctypegen above), you can do this:

```
@CMock.Mock( lib.f, lib, method=CMock.GOT )
def mockedF( i, s, iptr ):
   print( "mocked function! got args: i(%s)=%d, s(%s)=%s, iptr(%s)=%s" %
          ( type( i ), i, type( s ), s, type( iptr ), iptr[ 0 ] ) )
   iptr[ 0 ] = 101
   return 100
```

Any function in your DLL that calls "f", will now call the python function
mockedF instead.

### Details

The mocking code is somewhat experimental, but has been successfully used
for testing in Arista. There are two distinct forms of mock functions,
specified with the "method" argument (defaults to GOT on 64-bit, STOMP
on 32-bit)

The mocking code uses ctypes's ability to create valid C function pointers
from python code. Internally, python uses libffi to do this, but once we have
the ability to create such pointers, we can pass them to C code to call.

GOT mocks use the "global offset table" used by the ELF dynamic
linker. This GOT is used as a table of indirections to use when calling
functions that are potentially provided by shared libraries other than
the ELF object the caller is in. This can also include global symbols
that are defined in that shared library that maybe "interposed" by other
libraries at runtime. (Eg, if you have function "f" in your executable
or shared object, but "f" is provided by a library that is loaded before
the executable is resolved, then the version from the library is used,
not the version in your executable.)

On 32-bit i386, it's more common to see shared libraries that have
not been compiled and linked as position-independent code (because
the runtime linker can be more forgiving, and fix up function offsets
in-place, which is costly in memory). On those platforms, we can use
"STOMP" mocks.  These mocks work by overwriting the text of the function
you want to mock out with a stub that calls the mock code.

STOMP mocks have a number of restrictions - the function you call cannot
be smaller than the stub code that gets written.

In both cases, the ctypes/libffi derived function pointer we can extract
from python is used as the target for the mocked function, and is used
to overwrite the GOT or the target of the call instruction the STOMP
mock adds.

For GOT mocks, we also provide the ability to call the original function
from the mocked one (this isn't possible for STOMP mocks, as the original
function has been tampered with)

For example, from tests/ChainTest.{c,py}, given:
```
int
mockme( int one, int two, int three ) {
   printf( "mockme(%d, %d, %d)\n", one, two, three );
   return one;
}

int
callme( int one, int two, int three ) {
   return mockme( one, two, three );
}
```

We can write this function to wrap the call to "mockme" in "lib"

```
@CMock.Mock( lib.mockme, lib, method=CMock.GOT )
def mocked( one, two, three ):
   print( "I mock you: %d %d %d" % ( one, two, three ) )
   rc = mocked.realfunc( three, two, one )
   assert rc == three
   return two
```

You can also use CMock as a context manager. For example:

```
   def mockSend( sock, buf, size ):
      log_write_to_socket( sock, buf, size )
      return mockSend.realfunc( sock, buf, size )

   with CMock.mocked( self.libc.sendmsg, mockSend ):
      libhttp.get("http://www.arista,com/") # invokes send(2)

```

In this case, within the context of the "with" statement, the system
call "send" will be Directed through "mockSend", which can log the data
written to the socket, and eventually call the original function
( Context manager is courtesy of lpenz@ )

## Links
There are some slides from a presentation on this package
[here](https://aristanetworks.github.io/ctypegen)
