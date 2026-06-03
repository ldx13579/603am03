#ifndef SYNC_H
#define SYNC_H

#include <windows.h>
#include <process.h>

typedef CRITICAL_SECTION  Mutex;
typedef CONDITION_VARIABLE CondVar;
typedef HANDLE            Thread;

void mutex_init(Mutex *m);
void mutex_destroy(Mutex *m);
void mutex_lock(Mutex *m);
void mutex_unlock(Mutex *m);

void cond_init(CondVar *cv);
void cond_wait(CondVar *cv, Mutex *m);
void cond_signal(CondVar *cv);
void cond_broadcast(CondVar *cv);

Thread thread_create(unsigned (__stdcall *func)(void *), void *arg);
void   thread_join(Thread t);

#endif
