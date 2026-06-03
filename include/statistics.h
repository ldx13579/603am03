#ifndef STATISTICS_H
#define STATISTICS_H

#include "common.h"
#include "sync.h"

#define HOURS_PER_DAY 24

typedef struct {
    int park_count_by_hour[HOURS_PER_DAY];
    int retrieve_count_by_hour[HOURS_PER_DAY];
    int movement_count_by_hour[HOURS_PER_DAY];

    int total_parks;
    int total_retrieves;
    int total_movements;
    int total_faults;
    int total_retries;
    int total_failed_after_retry;

    double total_park_time_ms;
    double total_retrieve_time_ms;
    int    park_ops_timed;
    int    retrieve_ops_timed;

    Mutex lock;
} Statistics;

void stats_init(Statistics *s);
void stats_destroy(Statistics *s);
void stats_record_park(Statistics *s, int sim_hour, double duration_ms);
void stats_record_retrieve(Statistics *s, int sim_hour, double duration_ms);
void stats_record_movement(Statistics *s, int sim_hour, int step_count);
void stats_record_fault(Statistics *s, bool retry_succeeded);
void stats_print_summary(const Statistics *s);

#endif
