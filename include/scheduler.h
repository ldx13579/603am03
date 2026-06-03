#ifndef SCHEDULER_H
#define SCHEDULER_H

#include "common.h"
#include "garage.h"

#define NUM_ENTRANCES       3
#define HORIZONTAL_WEIGHT   2
#define VERTICAL_WEIGHT     5
#define UTILIZATION_WEIGHT  3

typedef struct {
    int entrance_id;
    int ground_position;
} EntranceConfig;

ErrorCode scheduler_assign_spot(const Garage *g, VehicleSize size,
                                int entrance_id, const EntranceConfig entrances[],
                                SpotLocation *out);
int scheduler_calc_score(int entrance_ground_pos, int spot_level, int spot_position);

#endif
