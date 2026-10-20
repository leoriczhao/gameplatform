"""Mandatory Linux confinement, installed before importing any game code.

Landlock ABI >= 3 permits reads of the package and Python runtime only.
seccomp defaults to EPERM: no networking, process creation, execution,
signalling other processes, ptrace, mount, or io_uring. Python stubs merely
provide friendly errors; they are not the security boundary.
"""
from __future__ import annotations

import ctypes as C
import errno
import os
from pathlib import Path
import platform
import resource
import sysconfig


class Ruleset(C.Structure):
    _fields_ = [("handled_access_fs", C.c_uint64)]


class PathRule(C.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", C.c_uint64), ("parent_fd", C.c_int32)]


def _check(result: int, operation: str) -> int:
    if result < 0:
        raise OSError(C.get_errno(), f"sandbox {operation} failed")
    return result


def install(game_dir: Path) -> None:
    if platform.system() != "Linux" or platform.machine() not in ("x86_64", "aarch64"):
        raise RuntimeError("UGC requires Linux x86_64/aarch64 with Landlock ABI >= 3")
    libc = C.CDLL(None, use_errno=True)
    sec = C.CDLL("libseccomp.so.2", use_errno=True)
    # These architectures share the generic Landlock syscall numbers.
    abi = libc.syscall(444, 0, 0, 1)
    if abi < 3:
        raise RuntimeError(f"UGC requires Landlock ABI >= 3 (detected {abi}); refusing unsafe execution")
    _check(libc.prctl(38, 1, 0, 0, 0), "no_new_privs")
    _check(libc.prctl(4, 0, 0, 0, 0), "disable dumpability")
    # Limits apply to the worker, never to the multithreaded API process.
    for kind, limit in ((resource.RLIMIT_AS, 2 * 1024**3),
                        (resource.RLIMIT_CPU, 60), (resource.RLIMIT_FSIZE, 0),
                        (resource.RLIMIT_NPROC, 0), (resource.RLIMIT_NOFILE, 64),
                        (resource.RLIMIT_CORE, 0)):
        resource.setrlimit(kind, (limit, limit))

    # Import trusted native runtime before blocking new threads/syscalls.
    import numpy
    if len(list(Path("/proc/self/task").iterdir())) != 1:
        raise RuntimeError("UGC confinement requires a single-threaded worker")
    paths = {game_dir.resolve(), Path(sysconfig.get_path("stdlib")).resolve(),
             Path(numpy.__file__).resolve().parent}
    numpy_libs = Path(numpy.__file__).resolve().parent.parent / "numpy.libs"
    if numpy_libs.exists():
        paths.add(numpy_libs)
    # Loaded extension modules may lazily resolve shared libraries.
    paths.update(Path(p).resolve() for p in ("/lib", "/lib64", "/dev/urandom",
                                           "/etc/ld.so.cache") if Path(p).exists())
    ruleset = Ruleset((1 << 15) - 1)  # all filesystem rights through ABI 3
    fd = _check(libc.syscall(444, C.byref(ruleset), C.sizeof(ruleset), 0), "create ruleset")
    try:
        for path in sorted(paths):
            path_fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
            try:
                rights = (1 << 2) | ((1 << 3) if path.is_dir() else 0)
                rule = PathRule(rights, path_fd)
                _check(libc.syscall(445, fd, 1, C.byref(rule), 0), "add read rule")
            finally:
                os.close(path_fd)
        _check(libc.syscall(446, fd, 0), "restrict filesystem")
    finally:
        os.close(fd)

    sec.seccomp_init.argtypes = [C.c_uint32]
    sec.seccomp_init.restype = C.c_void_p
    sec.seccomp_syscall_resolve_name.argtypes = [C.c_char_p]
    sec.seccomp_syscall_resolve_name.restype = C.c_int
    sec.seccomp_rule_add.argtypes = [C.c_void_p, C.c_uint32, C.c_int, C.c_uint]
    sec.seccomp_load.argtypes = [C.c_void_p]
    sec.seccomp_release.argtypes = [C.c_void_p]
    ctx = sec.seccomp_init(0x00050000 | errno.EPERM)
    if not ctx:
        raise RuntimeError("seccomp_init failed")
    allowed = """
        read write readv writev close close_range fstat newfstatat stat lstat statx
        open openat lseek pread64 getdents64 readlink readlinkat getcwd access faccessat
        faccessat2 mmap mprotect munmap mremap madvise brk
        rt_sigaction rt_sigprocmask rt_sigreturn sigaltstack futex futex_time64
        clock_gettime clock_gettime64 gettimeofday time nanosleep clock_nanosleep
        getrandom getpid getppid gettid getuid geteuid getgid getegid uname
        sched_getaffinity sched_yield getrusage getrlimit restart_syscall
        poll ppoll select pselect6 exit exit_group
    """.split()
    try:
        for name in allowed:
            nr = sec.seccomp_syscall_resolve_name(name.encode())
            if nr >= 0 and sec.seccomp_rule_add(ctx, 0x7FFF0000, nr, 0) != 0:
                raise RuntimeError(f"seccomp rule failed: {name}")
        if sec.seccomp_load(ctx) != 0:
            raise RuntimeError("seccomp_load failed; refusing unsafe execution")
    finally:
        sec.seccomp_release(ctx)
