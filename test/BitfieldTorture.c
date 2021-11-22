// Copyright (c) 2021 Arista Networks, Inc.  All rights reserved.
// Arista Networks, Inc. Confidential and Proprietary.

#include <stdint.h>

int main() {}

struct {
   uint32_t :3, a:29;
   uint32_t b: 16, c: 14, :2;
   uint32_t j;
} torture1;

struct {
   uint32_t :32;
   uint32_t :32;
   uint32_t :32;
   uint32_t :32;
   uint32_t :16;
   uint32_t a:4;
} torture2;
