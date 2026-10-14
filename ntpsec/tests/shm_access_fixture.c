/* Run privileged cases only in a disposable private IPC namespace. */
#define main shm_access_main
#include "../scripts/shm-access.c"
#undef main
#include <assert.h>
#include <sys/wait.h>

static int helper(const char *operation, int id, int drift) {
    struct shmid_ds s;
    assert(shmctl(id, IPC_STAT, &s) == 0);
    unsigned long long values[] = {(unsigned)id, (unsigned)s.shm_perm.__key,
        s.shm_perm.__seq, s.shm_segsz, s.shm_cpid, s.shm_perm.cuid,
        s.shm_perm.cgid, s.shm_perm.uid, s.shm_perm.gid, s.shm_perm.mode,
        s.shm_ctime, 985};
    if (drift) values[2]++;
    char strings[12][32];
    char *args[15] = {"shm-access", (char *)operation};
    for (int i = 0; i < 12; i++) {
        snprintf(strings[i], sizeof(strings[i]), "%llu", values[i]);
        args[i+2] = strings[i];
    }
    args[14] = NULL;
    pid_t pid = fork(); assert(pid >= 0);
    if (!pid) exit(shm_access_main(14, args));
    int status; assert(waitpid(pid, &status, 0) == pid);
    assert(WIFEXITED(status)); return WEXITSTATUS(status);
}

static void attachment(int id, int allowed) {
    pid_t pid = fork(); assert(pid >= 0);
    if (!pid) {
        assert(setgid(985) == 0); assert(setuid(999) == 0);
        int found = shmget(0x4e545030, 96, IPC_CREAT | 0600);
        if (!allowed) { assert(found == -1 && errno == EACCES); exit(0); }
        assert(found == id);
        void *p = shmat(id, NULL, 0); assert(p != (void *)-1);
        assert(*(unsigned char *)p == 0xa5); assert(shmdt(p) == 0);
        exit(0);
    }
    int status; assert(waitpid(pid, &status, 0) == pid);
    assert(WIFEXITED(status) && WEXITSTATUS(status) == 0);
}

int main(int argc, char **argv) {
    int privileged = argc == 2 && !strcmp(argv[1], "--private-root");
    if (privileged) assert(geteuid() == 0);
    int id = shmget(0x4e545030, 96, IPC_CREAT | IPC_EXCL | 0600);
    assert(id >= 0); /* Never reuse or remove someone else's segment. */
    int other = shmget(0x4e545032, 96, IPC_CREAT | IPC_EXCL | 0666);
    assert(other >= 0);
    unsigned char *p = shmat(id, NULL, 0); assert(p != (void *)-1);
    memset(p, 0xa5, 96);
    assert(helper("grant", id, 0) != 0); /* Attached. */
    assert(shmdt(p) == 0);
    assert(helper("grant", id, 1) != 0); /* Replaced/sequence mismatch. */
    assert(helper("grant", other, 0) != 0); /* Other SHM key. */
    if (privileged) {
        attachment(id, 0);
        assert(helper("grant", id, 0) == 0);
        attachment(id, 1); /* Actual late shmget and shmat after credential drop. */
        assert(helper("grant", id, 0) != 0); /* Never grant twice. */
        p = shmat(id, NULL, 0); assert(p != (void *)-1);
        assert(helper("restore", id, 0) != 0); /* Consumers must stop. */
        assert(shmdt(p) == 0);
        struct shmid_ds s; assert(shmctl(id, IPC_STAT, &s) == 0);
        s.shm_perm.mode = 0666; assert(shmctl(id, IPC_SET, &s) == 0);
        assert(helper("restore", id, 0) != 0); /* Do not overwrite permission drift. */
        s.shm_perm.mode = 0660; assert(shmctl(id, IPC_SET, &s) == 0);
        assert(helper("restore", id, 0) == 0);
        attachment(id, 0);
        assert(helper("restore", id, 0) != 0);
    } else {
        assert(geteuid() != 0);
        assert(helper("grant", id, 0) != 0); /* Never bypass root-only guard. */
    }
    p = shmat(id, NULL, 0); assert(p != (void *)-1);
    for (int i = 0; i < 96; i++) assert(p[i] == 0xa5);
    assert(shmdt(p) == 0);
    struct shmid_ds s; assert(shmctl(other, IPC_STAT, &s) == 0);
    assert((s.shm_perm.mode & 0777) == 0666 && s.shm_perm.gid == getgid());
    assert(shmctl(id, IPC_RMID, NULL) == 0);
    int replacement = shmget(0x4e545030, 96, IPC_CREAT | IPC_EXCL | 0600);
    assert(replacement >= 0 && replacement != id);
    assert(shmctl(id, IPC_STAT, &s) == -1);
    assert(shmctl(replacement, IPC_RMID, NULL) == 0);
    assert(shmctl(other, IPC_RMID, NULL) == 0);
    puts("SHM native permission transition and rejection checks passed");
    return 0;
}
