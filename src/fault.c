#include "fault.h"
#include <windows.h>
#include <string.h>

static unsigned int lcg_next(unsigned int *seed) {
    *seed = (*seed) * 1103515245u + 12345u;
    return (*seed >> 16) & 0x7FFF;
}

static int get_tick_sec(void) {
    return (int)(GetTickCount64() / 1000);
}

static void monitor_init(FaultMonitor *mon) {
    memset(mon, 0, sizeof(FaultMonitor));
    mon->adaptive_backoff_ms = FAULT_BASE_BACKOFF_MS;
}

static void monitor_record_fault(FaultMonitor *mon) {
    int now = get_tick_sec();
    mon->timestamps[mon->head] = now;
    mon->head = (mon->head + 1) % FAULT_WINDOW_SIZE;
    if (mon->count < FAULT_WINDOW_SIZE) mon->count++;

    int recent = 0;
    int window_start = now - 10;
    for (int i = 0; i < mon->count; i++) {
        if (mon->timestamps[i] >= window_start) recent++;
    }

    if (recent >= 5) {
        mon->adaptive_backoff_ms = mon->adaptive_backoff_ms * 3 / 2;
        if (mon->adaptive_backoff_ms > FAULT_MAX_BACKOFF_MS)
            mon->adaptive_backoff_ms = FAULT_MAX_BACKOFF_MS;
    } else if (recent <= 1) {
        mon->adaptive_backoff_ms = mon->adaptive_backoff_ms * 2 / 3;
        if (mon->adaptive_backoff_ms < FAULT_BASE_BACKOFF_MS)
            mon->adaptive_backoff_ms = FAULT_BASE_BACKOFF_MS;
    }
}

void fault_config_init(FaultConfig *fc, double prob, int max_retries) {
    fc->failure_probability = prob;
    fc->max_retries = max_retries;
    fc->base_backoff_ms = FAULT_BASE_BACKOFF_MS;
    fc->enabled = (prob > 0.0);
    fc->seed = 0;
    monitor_init(&fc->monitor);
}

void fault_set_seed(FaultConfig *fc, unsigned int seed) {
    fc->seed = seed;
}

bool fault_should_fail(FaultConfig *fc) {
    if (!fc->enabled) return false;
    unsigned int r = lcg_next(&fc->seed);
    double roll = (double)r / 32767.0;
    return roll < fc->failure_probability;
}

int fault_get_effective_backoff(FaultConfig *fc) {
    return fc->monitor.adaptive_backoff_ms;
}

FaultResult fault_execute_step(FaultConfig *fc) {
    FaultResult result = {false, 0, true, 0};

    if (!fc->enabled) return result;

    if (!fault_should_fail(fc)) return result;

    result.failed = true;
    result.final_success = false;

    monitor_record_fault(&fc->monitor);

    int effective_base = fc->monitor.adaptive_backoff_ms;

    for (int retry = 0; retry < fc->max_retries; retry++) {
        int backoff = effective_base * (1 << retry);
        if (backoff > FAULT_MAX_BACKOFF_MS) backoff = FAULT_MAX_BACKOFF_MS;
        Sleep(backoff);
        result.total_backoff_ms += backoff;
        result.retry_count++;

        if (!fault_should_fail(fc)) {
            result.final_success = true;
            return result;
        }
    }

    return result;
}
