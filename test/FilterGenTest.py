#!/usr/bin/env python
# Copyright 2017 Arista Networks.
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
from __future__ import absolute_import, division, print_function

import CTypeGen

def typeFilter( die ):
   if die.name() == "FilterHint":
      return CTypeGen.PythonType( "FilterAliasApplied" ). \
                  field("anonInnerStruct", CTypeGen.PythonType("InnerStruct"))
   if die.name() == "FilterTrue":
      return True
   return False

module, resolver = CTypeGen.generate( [ "./libFilterTest.so" ], "filter.py",
types=typeFilter, functions=None )

assert not hasattr( module, "FilterFalse" ), "Filter returns False for 'FilterFalse'"
assert hasattr( module, "FilterTrue" ), "Filter returns True for 'FilterTrue'"
assert hasattr( module, "FilterHint" ), "Filter returns a type hint for 'FilterHint'"
assert module.FilterHint is module.FilterAliasApplied, "Hint gives alternate name"
assert hasattr( module, "InnerStruct" ), "Hint specifies a typename for anon struct."

obj = module.InnerStruct()
obj.field = 42


