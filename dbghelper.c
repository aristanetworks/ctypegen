/*
   Copyright 2020 Arista Networks.

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

// This library just provides a helper for ctypegen to find definitions of
// types that are not otherwise used in libc. generateLibc includes the debug
// information generated by the defintions in here.
// We also grab lots of macros from these files for general use.
#define _GNU_SOURCE

#include <sys/auxv.h>
#include <sys/dir.h>
#include <sys/fcntl.h>
#include <sys/file.h>
#include <sys/ioctl.h>
#if defined(__i386__ ) || defined(__x86_64__)
// for systems with separate IO space.
#include <sys/io.h>
#endif
#include <sys/ipc.h>
#include <sys/mman.h>
#include <sys/mount.h>
#include <sys/param.h>
#include <sys/poll.h>
#include <sys/select.h>
#include <sys/signal.h>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/syslog.h>
#include <sys/sysmacros.h>
#include <sys/types.h>
#include <sys/ucontext.h>
#include <sys/un.h>
#include <sys/wait.h>
#include <linux/perf_event.h>

#include <ctype.h>
#include <elf.h>
#include <limits.h>
#include <paths.h>
#include <pthread.h>
#include <pty.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <syscall.h>
#include <termio.h>
#include <termios.h>
#include <time.h>
#include <unistd.h>
#include <unwind.h>
#include <utmp.h>
#include <utmpx.h>
#include <wchar.h>

ucontext_t * dbg_uctx_p;
