#include "sync.h"

void mutex_init(Mutex *m) {
    InitializeCriticalSection(m);
}

void mutex_destroy(Mutex *m) {
    DeleteCriticalSection(m);
}

void mutex_lock(Mutex *m) {
    EnterCriticalSection(m);
}

void mutex_unlock(Mutex *m) {
    LeaveCriticalSection(m);
}

void rwlock_init(RWLock *rw) {
    InitializeSRWLock(rw);
}

void rwlock_read_lock(RWLock *rw) {
    AcquireSRWLockShared(rw);
}

void rwlock_read_unlock(RWLock *rw) {
    ReleaseSRWLockShared(rw);
}

void rwlock_write_lock(RWLock *rw) {
    AcquireSRWLockExclusive(rw);
}

void rwlock_write_unlock(RWLock *rw) {
    ReleaseSRWLockExclusive(rw);
}

void cond_init(CondVar *cv) {
    InitializeConditionVariable(cv);
}

void cond_wait(CondVar *cv, Mutex *m) {
    SleepConditionVariableCS(cv, m, INFINITE);
}

void cond_signal(CondVar *cv) {
    WakeConditionVariable(cv);
}

void cond_broadcast(CondVar *cv) {
    WakeAllConditionVariable(cv);
}

Thread thread_create(unsigned (__stdcall *func)(void *), void *arg) {
    return (Thread)_beginthreadex(NULL, 0, func, arg, 0, NULL);
}

void thread_join(Thread t) {
    WaitForSingleObject(t, INFINITE);
    CloseHandle(t);
}
