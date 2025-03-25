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

    This is a bit tricky, because the contents of the stack are set up
    with the args to the second function when we land in the thunk, so
    we can't push anything before invoking the python function if we want
    to provide access to the args to the mock. So, we need to manipulate
    the slot on the stack containing the return address from the thunk.

    Each PRE thunk consists of two contiguous pages of memory, the first is
    executable, the second is writeable. The second page is used to store the
    addresses of the two functions we want to call, and a stack to save the
    return address for the second while the first executes.  We grow the stack
    from the end of the data page towards the code page, so that if we
    overflow, we'll reliably fault.
*/

# offsets into the second page. We have 2048 4-byte words of memory in our 8k,
# use the end of the page for structured data, and the rest as a stack for return
# addresses

.set STACKP,2044 * 4
.set GOTENT,2045 * 4 # location of the GOT entry we're thunking.
.set CALLBACK1,2046 * 4
.set CALLBACK2,2047 * 4

cmock_thunk_function:
	# get a pointer to the thunk into eax, and the thunk stack pointer in ecx
	call .next
.next:
.set offset,.next - cmock_thunk_function
	pop %eax
	mov STACKP - offset (%eax), %ecx

	# pop our return address from machine stack, and push to our thunk's stack
	pop %edx
	mov %edx, (%ecx)
	sub $4, %ecx
	mov %ecx, STACKP - offset (%eax)

	# We're running without this function's return address on the machine stack
	# now - we can call our callbacks. eax will be trashed after each call,
	# so we have to re-calculate after each call
	call *CALLBACK1 - offset (%eax)

	call .next2
.next2:
.set offset2,.next2 - cmock_thunk_function
	pop %eax

	call *CALLBACK2 - offset2(%eax)


	call .next3
.next3:
.set offset3,.next3 - cmock_thunk_function
	pop %edx
	sub $offset3, %edx

	# The second call was to the "real" function, except in the event
	# that the GOT entry was still pointing to the PLT thunk. In that case,
	# We've successfully called the dynamic linker as well as our intended
	# function, but the GOT entry has been overwritten.
	# The new GOT entry is the actual function we want to call: we want
	# to replace that with ourselves, and replace our original callback
	# with the one the dynamic linker just resolved on our behalf
	push %eax # need an extra register.
	mov GOTENT(%edx), %ecx # pointer to GOT entry in ECX
	mov (%ecx), %eax # Newly resolved function in EAX
	cmp %eax, %edx
	je .noupdate
	mov %eax, CALLBACK2(%edx)
	mov %edx, (%ecx)

.noupdate:
	pop %eax
	# Now recover the original return address from the stack, and recover.
	mov STACKP (%edx), %ecx
	add $4, %ecx
	mov %ecx, STACKP(%edx)
	mov (%ecx), %edx
	push %edx
	ret
cmock_thunk_end:
	.globl cmock_thunk_function
	.globl cmock_thunk_end
	.size cmock_thunk_function,cmock_thunk_end-cmock_thunk_function
