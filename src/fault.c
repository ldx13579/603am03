#include "fault.h"

static unsigned int lcg_next(unsigned int *seed) {
    *seed = (*seed) * 1103515245u + 12345u;
    return (*seed >> 16) & 0x7FFF;
}

void fault_config_init(FaultConfig *fc, double prob, int max_retries) {
    fc->failure_probability = prob;
    fc->max_retries = max_retries;
    fc->enabled = (prob > 0.0);
    fc->seed = 0;
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

FaultResult fault_execute_step(FaultConfig *fc) {
    FaultResult result = {false, 0, true};

    if (!fc->enabled) return result;

    if (!fault_should_fail(fc)) return result;

    result.failed = true;
    result.final_success = false;

    for (int retry = 0; retry < fc->max_retries; retry++) {
        result.retry_count++;
        if (!fault_should_fail(fc)) {
            result.final_success = true;
            return result;
        }
    }

    return result;
}
