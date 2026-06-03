#ifndef BILLING_H
#define BILLING_H

#include "common.h"

#define RATE_SMALL_PER_MINUTE  0.20
#define RATE_LARGE_PER_MINUTE  0.35
#define FREE_MINUTES           15
#define MAX_DAILY_FEE_SMALL    60.0
#define MAX_DAILY_FEE_LARGE    100.0

typedef struct {
    int         ticket_id;
    char        plate[16];
    VehicleSize size;
    time_t      entry_time;
    time_t      exit_time;
    int         duration_minutes;
    double      fee;
} BillRecord;

double billing_calculate(VehicleSize size, time_t entry, time_t exit_time);
void   billing_generate_record(const Vehicle *v, BillRecord *record);
void   billing_print_receipt(const BillRecord *record);

#endif
