#!/usr/bin/env arista-python
# Copyright (c) 2021 Arista Networks, Inc.  All rights reserved.
# Arista Networks, Inc. Confidential and Proprietary.

# This test ensures that we reuse the type from the "Supply" module when
# generating the "Demand" module.

from __future__ import absolute_import, division, print_function
import CTypeGen

tortureModule, supplyResolver = CTypeGen.generateAll(
      "./libBitfieldTorture.so", "BitfieldTorture.py" )

