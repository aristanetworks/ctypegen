/*
   Copyright 2019 Arista Networks.

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

       Unless required by applicable law or agreed to in writing, software
       distributed under the License is distributed on an "AS IS" BASIS,
       WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
       See the License for the specific language governing permissions and
       limitations under the License.
*/

/*
 * this is a placeholder for building on aarch64. "PRE" (and "STOMP") mocks
 * don't work here yet - "someone" has to work out enough ARM asm to make them.
 *
 * BUG718366
 */

	.arch armv8-a
	.text
	.align	2

	.global	cmock_thunk_function
	.global	cmock_thunk_end
cmock_thunk_function:
	stp	x29, x30, [sp, -16]!
	mov	x29, sp
	adr     x0, .warning
	bl	fputs
	bl	abort
.warning:
        .string	"PRE mocks are not supported on this architecture"
        .align 2
cmock_thunk_end:
