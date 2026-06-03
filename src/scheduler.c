#include "scheduler.h"
#include <stdlib.h>

int scheduler_calc_score(int entrance_ground_pos, int spot_level, int spot_position) {
    if (spot_level == 0) {
        return abs(entrance_ground_pos - spot_position) * HORIZONTAL_WEIGHT;
    }
    int to_lift = abs(entrance_ground_pos - LIFT_COLUMN);
    int from_lift = abs(spot_position - LIFT_COLUMN);
    return (to_lift + from_lift) * HORIZONTAL_WEIGHT + spot_level * VERTICAL_WEIGHT;
}

ErrorCode scheduler_assign_spot(const Garage *g, VehicleSize size,
                                int entrance_id, const EntranceConfig entrances[],
                                SpotLocation *out) {
    int entrance_pos = entrances[entrance_id].ground_position;
    int best_score = 9999;
    int best_level = -1;
    int best_pos = -1;

    for (int level = 0; level < NUM_LEVELS; level++) {
        for (int pos = 0; pos < SPOTS_PER_LEVEL; pos++) {
            if (!garage_is_spot_available(g, level, pos, size)) continue;

            int score = scheduler_calc_score(entrance_pos, level, pos);
            if (score < best_score) {
                best_score = score;
                best_level = level;
                best_pos = pos;
            }
        }
    }

    if (best_level < 0) return ERR_GARAGE_FULL;

    out->level = best_level;
    out->position = best_pos;
    return ERR_OK;
}
