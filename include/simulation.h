#ifndef SIMULATION_H
#define SIMULATION_H

#include "common.h"
#include "garage.h"
#include "state_machine.h"
#include "logger.h"
#include "statistics.h"
#include "fault.h"
#include "scheduler.h"
#include "sync.h"

typedef struct {
    int    num_entrances;
    int    simulation_duration_s;
    double fault_probability;
    int    fault_max_retries;
    int    min_request_interval_ms;
    int    max_request_interval_ms;
} SimConfig;

typedef struct {
    int              entrance_id;
    EntranceConfig   entrance_cfg;
    FaultConfig      fault_cfg;

    Garage          *garage;
    Logger          *logger;
    Statistics      *stats;
    Mutex           *level_locks;
    Mutex           *garage_lock;
    volatile bool   *stop_flag;
    SimConfig       *config;
    EntranceConfig  *all_entrances;
    time_t           sim_start_time;
} EntranceThreadArg;

void sim_config_default(SimConfig *cfg);
void sim_run(SimConfig *cfg);
void sim_print_config(const SimConfig *cfg);

#endif
