#ifndef FAULT_H
#define FAULT_H

#include "common.h"
#include <stdbool.h>

#define FAULT_BASE_BACKOFF_MS 100

typedef struct {
    double       failure_probability;
    int          max_retries;
    int          base_backoff_ms;
    bool         enabled;
    unsigned int seed;
} FaultConfig;

typedef struct {
    bool failed;
    int  retry_count;
    bool final_success;
    int  total_backoff_ms;
} FaultResult;

void        fault_config_init(FaultConfig *fc, double prob, int max_retries);
void        fault_set_seed(FaultConfig *fc, unsigned int seed);
bool        fault_should_fail(FaultConfig *fc);
FaultResult fault_execute_step(FaultConfig *fc);

#endif
