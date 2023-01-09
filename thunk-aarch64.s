/*
   Copyright 2023 Arista Networks.

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
 * This provides the thunk functionality for aarch64 used by "pre" mocks. The
 * intent of a PRE mock is to run a piece of python code before all calls to an
 * underlying C/C++ function for tracking purposes, as long as the C/C++
 * function is called via the GOT. This implementation is similar to the x86_64
 * one, but simplified by the availability of more temporary registers on ARM,
 * PC-relative instructions, and the link register (and probably a lack of
 * sophistication of my understanding of the things that might go wrong on ARM)
 *
 * A thunk is allocated for each mocked function. A thunk is two pages, and the
 * initial content of the first page is copied from the text of
 * cmock_thunk_function below.
 *
 * The first page is protected as executable, the second page as writeable. We
 * replace the GOT entry for the function we want to mock with a pointer to the
 * thunk (i.e., the executable page), so the rest of the application will call
 * our thunk instead of the intended function when it calls through the GOT. We
 * store the original content of the GOT (function #2) and the pointer to the
 * python code to run (function #1) in the second page of the thunk. The copy
 * of cmock_thunk_function at the start of the thunk then ensures the original
 * python function and the orignal GOT entry are called correctly, getting
 * access to the proper machine state to see their arguments and return what
 * they need to.
 *
 * The writeable page is used from the highest address back to the lowest -
 * this ensures if we overflow, we will overflow into the read-only executable
 * page. the last 4 8-byte values at the bottom of that page are:
 *
 * thunk + 8192 -  8 : pointer to second function to call (nominally the C/C++ func)
 * thunk + 8192 - 16 : pointer to first function to call (nominally python ctypes)
 * thunk + 8192 - 24 : pointer to the original GOT entry for the function
 *                     (where we fetched function #2 from)
 * thunk + 8192 - 32 : pointer to top of the thunk stack.
 *
 * The remainder of the read/write page, from thunk + 8192 - 40 up to thunk +
 * 4096, is the "thunk stack"
 *
 * The thunk stack:
 * We can rely on the second function preserving registers as required by the
 * ABI, but before calling function #1, we must save the register state, as
 * that state includes the arguments we need to pass later to the invocation of
 * function #2. Also, as there may be additional arguments on the machine
 * stack, we must preserve the same machine stack pointer entering both
 * function #1 and #2 as we had entering cmock_thunk_function, so we can't just
 * use the machine stack for temporary storage - instead, we store the state on
 * the "thunk stack" for the duration of function #1's call. aarch64's link
 * register makes preserving the stack pointer a lot easier than it is on intel
 * platforms - we can just store the link register on the thunk stack too, for
 * the duration of both function #1 and #2
 *
 * Lazy resolving of functions complicates things a bit - the pointer we use
 * for the second function may actually be a pointer to the PLT entry - on
 * return from function #2, we check if the GOT entry has changed - this
 * indicates that we actually invoked it via the PLT, and the loader has
 * patched the GOT with the resolved function, so we need to replace the
 * patched GOT entry with our thunk again, but we also hold on to the newly
 * resolved function, so the next invocation will call the function directly,
 * rather than invoking the loader via the PLT again.
 *
 * The function we mock might be recursive, so the thunk stack may have several
 * stack frames. Each thunk looks like this.

                                                       Offset in thunk

ptr-to-thunk-> +----page 0 (rx)----------------+
               |                               |
               | cmock_thunk_function code     |       0
               |                               |
               |                               |
               |                               |
               .                               .
               .           ...                 .
               .                               .
               +---page 1 (rw)-----------------+      4096
               |                               |
               | ( free space )                |
               |                               |
               | top of thunk stack            |<--\   thunk SP
               +-------------------------------|   |
               |                               |   |
               |                               |   |
               | Saved regs for call to        |   |
               | function #1 (or link reg for  |   |
               | function #2)                  |   |
               |                               |   |
               |                               |   |
               +-------------------------------|   |
               | Saved link reg for next inner |   |
               | recursive call to function #2 |   |
               +-------------------------------|   |
               | Saved link reg for outermost  |   |
               | recursive call to function #2 |   |
               +-------------------------------|   |
               | thunk stack pointer           |->-/  8192-32
               | GOT entry pointer             |      8192-24
               | Function 1                    |      8192-16
               | Function 2                    |      8192- 8
               +-------------------------------+      8192


 * Saving registers:
 * The "Procedure Call Standard for the Arm 64-bit Architecture" says:
 * ```
 * A subroutine invocation must preserve the contents of the registers r19-r29 and
 * SP. All 64 bits of each value stored in r19-r29 must be preserved, even when
 * using the ILP32 data model (Beta).  In all variants of the procedure call
 * standard, registers r16, r17, r29 and r30 have special roles. In these roles
 * they are labeled IP0, IP1, FP and LR when being used for holding addresses
 * (that is, the special name implies accessing the register as a 64-bit entity).
 * ```
 *
 * Consequently, we use register x9,x10,x11 freely below. x9 generally points
 * to the thunk, x10 to the top of thunk stack. We use x11 when we are
 * shuffling the GOT entry in the event it gets updated due to lazy resolution
 * on the initial call.
 *
 * Other than than those, we simply save the remaining registers from x0
 * thru x30. x30 is the link register, which we need to preserve across both
 * function #1 and #2, so we save that first.  We restore all registers but
 * the link register after function #1 completes, and restore the link register
 * before returning to the caller.
 */

	.arch armv8-a
	.text
	.align	2

	.global	cmock_thunk_function
	.global	cmock_thunk_end
START:
cmock_thunk_function:
	// get a pointer to the start of the thunk, and the thunk-stack pointer in the thunk
	adr x9, START
	ldr x10, [x9, #(8192-32)] // Get the thunk stack pointer.

	// Now save all the required registers on the stack. Leave X30/LR at
	// the bottom, we don't pop it after the first call.
	stp x29, x30, [ x10, #-16]!
	stp x0, x1, [ x10, #-16]!
	stp x2, x3, [ x10, #-16]!
	stp x4, x5, [ x10, #-16]!
	stp x6, x7, [ x10, #-16]!
	// skip x9, 10, 11, they're temporaries, and we've destroyed their
	// content already, so no point in saving them. (We conseratively save
	// those temporaries we don't trash)
	stp x8, x12, [ x10, #-16]!
	stp x13, x14, [ x10, #-16]!
	stp x15, x16, [ x10, #-16]!
	stp x17, x18, [ x10, #-16]!
	stp x19, x20, [ x10, #-16]!
	stp x21, x22, [ x10, #-16]!
	stp x23, x24, [ x10, #-16]!
	stp x25, x26, [ x10, #-16]!
	stp x27, x28, [ x10, #-16]!

	// Save our thunk stack pointer, and call the first function.
        str x10, [x9, #8192-32 ]
	ldr x10, [x9, #(8192-16)]
	blr x10

	// Re-establish pointer to thunk and pointer to thunk stack.
	adr x9, START
	ldr x10, [x9, #(8192-32)]

	// restore registers (mostly for arguments to function)

	ldp x27, x28, [x10], #16
	ldp x25, x26, [x10], #16
	ldp x23, x24, [x10], #16
	ldp x21, x22, [x10], #16
	ldp x19, x20, [x10], #16
	ldp x17, x18, [x10], #16
	ldp x15, x16, [x10], #16
	ldp x13, x14, [x10], #16

	ldp x8, x12, [x10], #16
	ldp x6, x7, [x10], #16
	ldp x4, x5, [x10], #16
	ldp x2, x3, [x10], #16
	ldp x0, x1, [x10], #16

	ldr x29, [x10] // ... but no decrement - we want to preserve x30 on the stack.

	str x10, [x9, #8192-32 ] // Save the thunk stack pointer.

	ldr x10, [x9, #(8192-8)] // get pointer to second function
	blr x10 // call it

	// get our thunk and thunk-stack pointers back, so we can pop the original LR.
	adr x9, START
	ldr x10, [x9, #(8192-32)]
	ldp x29, x30, [ x10 ], #16 // now restore original link register so we an return
	str x10, [x9, #(8192-32)]

	// finally, look at the GOT - if the pointer there has been updated,
	// then update the second function call to point to the updated
	// function. This stops us constantly undoing the work the dynamic
	// linker does.
	ldr x10, [x9, #(8192-24)]
	ldr x11, [x10]
	cmp x11, x9
	b.eq noupdate

	// GOT was updated during execution - insert ourselves back into the GOT,
	// and replace our idea of what function to call with the now resolved
	// function
	str x11, [x9, #(8192-8)]   // thunk pointer to func #2 = GOT entry value
	str x9, [x10] // GOT entry = this thunk
noupdate:
	// we can now return to the original caller
	ret
cmock_thunk_end:
