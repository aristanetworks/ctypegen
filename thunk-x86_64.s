//  Copyright (c) 2019 Arista Networks, Inc.  All rights reserved.
//  Arista Networks, Inc. Confidential and Proprietary.
//

/*
    "PRE" mocks allow us to call a python function before the C function
    it "mocks".  We do this by having a third "thunk" function, which
    calls both, and put the address of that function in the GOT.

    This is a bit tricky, because the contents of the stack and registers
    are set up with the args to the second function when we land in the
    thunk, so we can't push anything or modify any registers before
    invoking the python function if we want to provide access to the
    args to the mock. So, we need to manipulate the slot on the stack
    containing the return address from the thunk.

    Each (64-bit) PRE thunk consists of two contiguous pages of memory,
    the first is executable, the second is writeable. The second page is
    used to store the addresses of the two functions we want to call,
    and a stack to save argument-passing registers and the eventual
    return while the first thunk executes.  We grow the stack from the
    end of the data page towards the code page, so that if we overflow,
    we'll reliably fault.

*/

# offsets into the second page. We have 2048 4-byte words of memory in our 8k,
# use the end of the page for structured data, and the rest as a stack for return
# addresses

.set STACKP,1020 * 8
.set GOTENT,1021 * 8 # location of the GOT entry we're thunking.
.set CALLBACK1,1022 * 8
.set CALLBACK2,1023 * 8

/*
x86_64 ABI:

We don't have many free registers to play with.

rax  - potentially count of args in varargs
rbx  - callee saved
rcx  - arg #4
rdx  - arg #3
rsi  - arg #2
rdi  - arg #1
rbp  - calle saved (poss. frame pointer)
rsp  - stack pointer
r8   - arg #5
r9   - arg #6
r10  - chain pointer
r11  - temporary
r12  - callee-saved
r13  - callee-saved
r14  - callee-saved
r15  - callee-saved

So, we have r11, and everything else needs to be preserved.
*/



cmock_thunk_function:

	# We need to preserve rax, and also the return address, hence an
	# extra register beyond %r11, which we use to hold on to our thunk's
	# stack frame. Having rax under the return address makes it easier
	# to restore before the call into the first callback (where we need to
	# have popped the original return address off the machine stack)
	pop %r11
	push %rax
	push %r11

	call .next
.next:  .set offset,.next - cmock_thunk_function
	pop %r11

	# Create a frame on the stack, and point r11 at it.
	subq $72, STACKP - offset(%r11)
	mov STACKP - offset (%r11), %r11

	# save what we need - return address, args, chain pointer, RAX

	pop %rax		# return address.
	mov %rax, (%r11)

	mov %rdi, 8(%r11)
	mov %rsi, 16(%r11)
	mov %rdx, 24(%r11)
	mov %rcx, 32(%r11)
	mov %r8, 40(%r11)
	mov %r9, 48(%r11)
	mov %r10, 56(%r11)

	pop %rax		# restore RAX for storage, and for callee.
	mov %rax, 64(%r11)

	call .next4
.next4:  .set offset4,.next4 - cmock_thunk_function
	pop %r11

	# Machine stack now contains no return address (it's in thunk stack)
	call *CALLBACK1 - offset4 (%r11)

	call .next2
.next2:  .set offset2,.next2 - cmock_thunk_function
	pop %r11

	mov STACKP - offset2 (%r11), %r11

	mov 8(%r11), %rdi
	mov 16(%r11), %rsi
	mov 24(%r11), %rdx
	mov 32(%r11), %rcx
	mov 40(%r11), %r8
	mov 48(%r11), %r9
	mov 56(%r11), %r10
	mov 64(%r11), %rax

	call .next3
.next3:  .set offset3,.next3 - cmock_thunk_function
	pop %r11

	# return address to our caller is on-stack - jump to the second callee.
	call *CALLBACK2 - offset3(%r11)

	call .next5
.next5:  .set offset5,.next5 - cmock_thunk_function
	pop %r11
	sub $offset5, %r11

	# We can use the argument registers now - don't need to preserve them
	mov GOTENT(%r11), %rdi
	mov (%rdi), %rsi
	cmp %rsi, %r11
	je .noupdate
	mov %rsi, CALLBACK2(%r11)
	mov %r11, (%rdi)

.noupdate:
	addq $72, STACKP (%r11)
	mov STACKP (%r11), %r11

	mov -72(%r11), %r11
	push %r11
	ret

cmock_thunk_end:
	.globl cmock_thunk_function
	.globl cmock_thunk_end
	.size cmock_thunk_function,cmock_thunk_end-cmock_thunk_function
