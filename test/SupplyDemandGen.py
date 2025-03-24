#!/usr/bin/env python3
# Copyright 2021 Arista Networks.
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

# This test ensures that we reuse the type from the "Supply" module when
# generating the "Demand" module.

import CTypeGen

supplyModule, supplyResolver = CTypeGen.generateAll( "./libSupply.so", "Supply.py" )

demandModule, demandResolver = CTypeGen.generateAll( "./libDemand.so", "Demand.py",
                                                    existingTypes=[ supplyModule ] )

obj = demandModule.Demand()
# We are checking for reference equality here, not the type hierarchy here, so
# pylint: disable=unidiomatic-typecheck
assert type( obj.supplied ) is supplyModule.Supply
