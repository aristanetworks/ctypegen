#!/usr/bin/env python3
# Copyright 2018 Arista Networks.
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

from setuptools import setup
from setuptools import Extension
from setuptools.command.build_ext import build_ext
from setuptools.command.install import install

import os
import subprocess

class ExtensionBuilder( build_ext ):
    def build_extensions( self ):
        self.compiler.src_extensions.append( ".s" )
        super().build_extensions()

    def run( self ):
        pstackDir = 'pstack'
        pstackBuild = 'pstack/build'
        os.makedirs( pstackBuild, exist_ok=True )
        subprocess.check_call( [ 'cmake', '..', '-DLIBTYPE=STATIC' ],
                              cwd = pstackBuild )
        subprocess.check_call( [ 'cmake', '--build', '.' ], cwd = pstackBuild )
        super().run()

class Installer( install ):
    def run( self ):
        super().run()
        subprocess.check_call( [ 'python3', '-m', 'CMock.generateLibc',
                                f'{self.install_lib}/CMock/libc.py' ] )

with subprocess.Popen( [ "uname", "-m" ], stdout=subprocess.PIPE ) as pipe:
   ( out, err ) = pipe.communicate()
arch = str( out.decode( "utf-8" ) ).strip()
if arch == "i686":
   arch = "i386"

pstack_base = os.getenv( "PSTACK_BASE" )
if pstack_base is None:
   pstack_base = os.getcwd() + "/pstack"
pstack_lib = f"{pstack_base}/build"

pstack_extension_options = {
    'libraries' : [ 'dwelf', 'lzma', 'z', 'debuginfod' ],
    'include_dirs' : [ pstack_base ],
    'library_dirs' : [ pstack_lib ],
    'extra_compile_args' : [ '-std=c++20', '-g' ],
    'language' : 'c++',
}

setup( name="CTypeGen",
        version="0.9",
        packages=[
           "CMock",
           "CTypeGen",
        ],

        py_modules=[
            "CTypeGenRun",
        ],

        ext_modules=[
            Extension( '_CTypeGen', [ 'CTypeGen/CTypeGen.cpp', ],
                      **pstack_extension_options ),
            Extension( '_CMock', [ 'CMock/cmock.cpp', f'CMock/thunk-{arch}.s' ],
                      **pstack_extension_options ),
            Extension( '_dbghelper', [ 'CMock/dbghelper.c' ] )
        ],
        scripts=[
            "ctypegen"
        ],
        cmdclass={
            'build_ext': ExtensionBuilder,
            'install': Installer,
            }
        )
