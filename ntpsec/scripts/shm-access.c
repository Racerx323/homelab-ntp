/* Linux SysV IPC metadata only. Never create, attach, remove or write a segment. */
#define _GNU_SOURCE
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/shm.h>
#include <unistd.h>

static void fail(const char *message) {
    fprintf(stderr, "%s: %s\n", message, strerror(errno));
    exit(1);
}

static unsigned long long number(const char *s) {
    char *end;
    errno = 0;
    unsigned long long n = strtoull(s, &end, 10);
    if (errno || !*s || *s == '-' || *end) { errno = EINVAL; fail("integer"); }
    return n;
}

static void report(int id, const struct shmid_ds *s) {
    printf("{\"shmid\":%d,\"key\":%u,\"seq\":%u,\"size\":%zu,"
           "\"cpid\":%d,\"cuid\":%u,\"cgid\":%u,\"uid\":%u,\"gid\":%u,"
           "\"mode\":%u,\"ctime\":%lld,\"nattch\":%llu}\n", id,
           (unsigned)s->shm_perm.__key, (unsigned)s->shm_perm.__seq,
           s->shm_segsz, s->shm_cpid, s->shm_perm.cuid, s->shm_perm.cgid,
           s->shm_perm.uid, s->shm_perm.gid, (unsigned)s->shm_perm.mode,
           (long long)s->shm_ctime, (unsigned long long)s->shm_nattch);
}

int main(int argc, char **argv) {
    if (argc < 3) { errno = EINVAL; fail("arguments"); }
    unsigned long long n = number(argv[2]);
    if (n > INT_MAX) { errno = EINVAL; fail("shmid"); }
    int id = (int)n;
    struct shmid_ds s;
    if (shmctl(id, IPC_STAT, &s)) fail("IPC_STAT");
    if (argc == 3 && !strcmp(argv[1], "inspect")) { report(id, &s); return 0; }
    /* Expected identity/permissions followed by the validated ntp gid. */
    if (argc != 14 || (strcmp(argv[1], "grant") && strcmp(argv[1], "restore"))) {
        errno = EINVAL; fail("operation");
    }
    unsigned long long actual[] = {(unsigned)s.shm_perm.__key, s.shm_perm.__seq,
        s.shm_segsz, s.shm_cpid, s.shm_perm.cuid, s.shm_perm.cgid,
        s.shm_perm.uid, s.shm_perm.gid, s.shm_perm.mode, s.shm_ctime};
    for (size_t i = 0; i < sizeof(actual)/sizeof(actual[0]); i++) {
        if (number(argv[i+3]) != actual[i]) { errno = ESTALE; fail("SHM identity/metadata drift"); }
    }
    unsigned long long gid = number(argv[13]);
    int grant = !strcmp(argv[1], "grant");
    if (geteuid() || !gid || gid >= UINT_MAX || s.shm_nattch ||
        s.shm_perm.__key != 0x4e545030 || s.shm_segsz != 96 ||
        s.shm_perm.cuid || s.shm_perm.cgid || s.shm_perm.uid ||
        (grant ? (s.shm_perm.gid || s.shm_perm.mode != 0600) :
                 (s.shm_perm.gid != gid || s.shm_perm.mode != 0660))) {
        errno = EPERM; fail("unattached root-owned NTP0 permission boundary");
    }
    s.shm_perm.gid = grant ? (gid_t)gid : 0;
    s.shm_perm.mode = grant ? 0660 : 0600;
    if (shmctl(id, IPC_SET, &s)) fail("IPC_SET");
    if (shmctl(id, IPC_STAT, &s)) fail("IPC_STAT after set");
    report(id, &s);
    return 0;
}
