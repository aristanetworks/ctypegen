// Copyright (c) 2021 Arista Networks, Inc.  All rights reserved.
// Arista Networks, Inc. Confidential and Proprietary.

#ifndef TEST_MACROS_H
#define TEST_MACROS_H

#define A 42
#define B (32 + A)
#define C (32 + B)
#define HELLO "hello world"

// macros with args, including those that use other macros
#define ADD(a, b) (a+b)
#define ADD_42(a) ADD(42, a)

#endif // TEST_MACROS_H

