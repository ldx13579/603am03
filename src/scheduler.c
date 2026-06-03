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

static int calc_level_occupancy(const Garage *g, int level) {
    int occupied = 0;
    for (int pos = 0; pos < SPOTS_PER_LEVEL; pos++) {
        if (level == 0 && pos == LIFT_COLUMN) continue;
        if (g->spots[level][pos].occupied) occupied++;
    }
    return occupied;
}

static int level_capacity(int level) {
    if (level == 0) return SPOTS_PER_LEVEL - 1;
    return SPOTS_PER_LEVEL;
}

ErrorCode scheduler_assign_spot(const Garage *g, VehicleSize size,
                                int entrance_id, const EntranceConfig entrances[],
                                SpotLocation *out) {
    int entrance_pos = entrances[entrance_id].ground_position;
    int best_score = 9999;
    int best_level = -1;
    int best_pos = -1;

    int level_occ[NUM_LEVELS];
    for (int lv = 0; lv < NUM_LEVELS; lv++) {
        level_occ[lv] = calc_level_occupancy(g, lv);
    }

    for (int level = 0; level < NUM_LEVELS; level++) {
        int cap = level_capacity(level);
        int utilization_penalty = 0;
        if (cap > 0) {
            utilization_penalty = (level_occ[level] * UTILIZATION_WEIGHT * 10) / cap;
        }

        for (int pos = 0; pos < SPOTS_PER_LEVEL; pos++) {
            if (!garage_is_spot_available(g, level, pos, size)) continue;

            int dist_score = scheduler_calc_score(entrance_pos, level, pos);
            int score = dist_score + utilization_penalty;

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
