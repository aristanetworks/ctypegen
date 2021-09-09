#!/usr/bin/env arista-python
# Copyright (c) 2021 Arista Networks, Inc.  All rights reserved.
# Arista Networks, Inc. Confidential and Proprietary.

# This test ensures that we reuse the type from the "Supply" module when
# generating the "Demand" module.

from __future__ import absolute_import, division, print_function
import CTypeGen

supplyModule, supplyResolver = CTypeGen.generateAll( "./libSupply.so", "Supply.py" )

demandModule, demandResolver = CTypeGen.generateAll( "./libDemand.so", "Demand.py",
                                                    existingTypes=[ supplyModule ] )

obj = demandModule.Demand()
# We are checking for reference equality here, not the type hierarchy here, so
# pylint: disable=unidiomatic-typecheck
assert type( obj.supplied ) is supplyModule.Supply
