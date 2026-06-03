#ifndef PATH_PLANNER_H
#define PATH_PLANNER_H

#include "common.h"
#include "garage.h"
#include "logger.h"

ErrorCode planner_find_temp_spot(const Garage *g, int level, int avoid_pos, SpotLocation *out);
ErrorCode planner_assign_spot(const Garage *g, VehicleSize size, SpotLocation *out);
ErrorCode planner_plan_park(Garage *g, SpotLocation target, MovementSequence *seq);
ErrorCode planner_plan_retrieve(Garage *g, int ticket_id, MovementSequence *seq);
int       planner_detect_blockage(const Garage *g, int level, int position, int *blocked_ids, int max_ids);
ErrorCode planner_resolve_blockage(Garage *g, int *blocked_ids, int count, MovementSequence *pre_seq, MovementSequence *post_seq);
ErrorCode planner_execute_restore(Garage *g, const MovementSequence *seq, Logger *logger);

#endif
