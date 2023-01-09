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

START:
# offsets into the second page. We have 1024 8-byte words of memory in our 8k,
# use the end of the page for structured data, and the rest as a stack for
# return addresses. We use PC-relative addressing, so add "START" for the assembler
.set STACKP,START + 1020 * 8
.set GOTENT,START + 1021 * 8
.set CALLBACK1,START + 1022 * 8
.set CALLBACK2,START + 1023 * 8

cmock_thunk_function:
	# Create a frame on the stack, and point r11 at it.
	subq $72, STACKP(%rip)
	mov STACKP(%rip), %r11

	# save all the registers we need to restore later.
	mov %rax, (%r11)
	mov %rdi, 8(%r11)
	mov %rsi, 16(%r11)
	mov %rdx, 24(%r11)
	mov %rcx, 32(%r11)
	mov %r8, 40(%r11)
	mov %r9, 48(%r11)
	mov %r10, 56(%r11)

	# We need to enter CALLBACK1 and CALLBACK2 with the stack at the same
	# point it was at on entry to cmock_thunk_function - pop the return
	# address off, and store it in our thunk stack.
	pop %rax
	mov %rax, 64(%r11)

        # We just trashed rax - restore from thunk stack for the call to CALLBACK1
	mov (%r11), %rax

	# Machine stack now contains no return address (it's in thunk stack)
	call *CALLBACK1(%rip)

	mov STACKP(%rip), %r11

	# Restore all the registers we previously saved - we can rely on
	# CALLBACK2 to preserve the ABI, so don't need to restore later
	mov (%r11), %rax
	mov 8(%r11), %rdi
	mov 16(%r11), %rsi
	mov 24(%r11), %rdx
	mov 32(%r11), %rcx
	mov 40(%r11), %r8
	mov 48(%r11), %r9
	mov 56(%r11), %r10

	addq $64, STACKP(%rip) # just leave the return address.
	call *CALLBACK2(%rip)

	# Check if the GOT has changed - if so, we need re-insert our own GOT
	# value, and replace our pointer to callback2 with the newly resolved GOT
	# entry. (The GOT should point to this thunk, if not, then the GOT entry
	# previously pointed to a PLT entry that updated the GOT before calling
	# the real function.)
	lea START(%rip), %r11
	# We can use the argument registers now - don't need to preserve them
	mov GOTENT(%rip), %rdi
	mov (%rdi), %rsi
	cmp %rsi, %r11
	je .noupdate
	mov %rsi, CALLBACK2(%rip)
	mov %r11, (%rdi)

.noupdate:
	# Now restore the return address from the thunk frame on to the system
	# and discard the thunk frame from the thunk stack.
	mov STACKP(%rip), %r11
	mov (%r11), %r11
	push %r11
	addq $8, STACKP(%rip)
	ret

cmock_thunk_end:
	.globl cmock_thunk_function
	.globl cmock_thunk_end
	.size cmock_thunk_function,cmock_thunk_end-cmock_thunk_function
