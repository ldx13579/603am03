#include "path_planner.h"
#include <stdio.h>
#include <string.h>
#include <stdlib.h>

static void add_step(MovementSequence *seq, ActionType action, int param, const char *desc) {
    if (seq->count >= MAX_STEPS) return;
    MovementStep *step = &seq->steps[seq->count];
    step->action = action;
    step->param = param;
    strncpy(step->description, desc, sizeof(step->description) - 1);
    step->description[sizeof(step->description) - 1] = '\0';
    seq->count++;
}

static const int ground_priority[] = {1, 3, 0, 4};
static const int ground_priority_count = (int)(sizeof(ground_priority) / sizeof(ground_priority[0]));
static const int upper_priority[]  = {2, 1, 3, 0, 4};
static const int upper_priority_count = (int)(sizeof(upper_priority) / sizeof(upper_priority[0]));

ErrorCode planner_assign_spot(const Garage *g, VehicleSize size, SpotLocation *out) {
    for (int i = 0; i < ground_priority_count; i++) {
        int pos = ground_priority[i];
        if (garage_is_spot_available(g, 0, pos, size)) {
            out->level = 0;
            out->position = pos;
            return ERR_OK;
        }
    }

    for (int level = 1; level < NUM_LEVELS; level++) {
        for (int i = 0; i < upper_priority_count; i++) {
            int pos = upper_priority[i];
            if (garage_is_spot_available(g, level, pos, size)) {
                out->level = level;
                out->position = pos;
                return ERR_OK;
            }
        }
    }

    return ERR_GARAGE_FULL;
}

int planner_detect_blockage(const Garage *g, int level, int position, int *blocked_ids, int max_ids) {
    int count = 0;

    if (level > 0) {
        const ParkingSpot *ground_lift = &g->spots[0][LIFT_COLUMN];
        if (ground_lift->occupied && count < max_ids) {
            blocked_ids[count++] = ground_lift->vehicle_id;
        }

        const ParkingSpot *upper_lift = &g->spots[level][LIFT_COLUMN];
        if (upper_lift->occupied && position != LIFT_COLUMN && count < max_ids) {
            blocked_ids[count++] = upper_lift->vehicle_id;
        }
    }

    int start = LIFT_COLUMN;
    int end = position;

    if (start != end) {
        int dir = (end > start) ? 1 : -1;
        for (int p = start + dir; p != end; p += dir) {
            if (p < 0 || p >= SPOTS_PER_LEVEL) break;
            if (level == 0 && p == LIFT_COLUMN) continue;
            const ParkingSpot *s = &g->spots[level][p];
            if (s->occupied && count < max_ids) {
                bool already_added = false;
                for (int k = 0; k < count; k++) {
                    if (blocked_ids[k] == s->vehicle_id) {
                        already_added = true;
                        break;
                    }
                }
                if (!already_added) {
                    blocked_ids[count++] = s->vehicle_id;
                }
            }
        }
    }

    return count;
}

ErrorCode planner_find_temp_spot(const Garage *g, int level, int avoid_pos, SpotLocation *out) {
    for (int dist = 1; dist < SPOTS_PER_LEVEL; dist++) {
        int left = avoid_pos - dist;
        int right = avoid_pos + dist;
        if (left >= 0 && !(level == 0 && left == LIFT_COLUMN)) {
            if (!g->spots[level][left].occupied) {
                out->level = level;
                out->position = left;
                return ERR_OK;
            }
        }
        if (right < SPOTS_PER_LEVEL && !(level == 0 && right == LIFT_COLUMN)) {
            if (!g->spots[level][right].occupied) {
                out->level = level;
                out->position = right;
                return ERR_OK;
            }
        }
    }
    for (int lv = 0; lv < NUM_LEVELS; lv++) {
        if (lv == level) continue;
        for (int p = 0; p < SPOTS_PER_LEVEL; p++) {
            if (lv == 0 && p == LIFT_COLUMN) continue;
            if (!g->spots[lv][p].occupied) {
                out->level = lv;
                out->position = p;
                return ERR_OK;
            }
        }
    }
    return ERR_GARAGE_FULL;
}

ErrorCode planner_resolve_blockage(Garage *g, int *blocked_ids, int count,
                                   MovementSequence *pre_seq, MovementSequence *post_seq) {
    char buf[128];
    for (int i = 0; i < count; i++) {
        Vehicle *v = garage_find_vehicle_by_ticket(g, blocked_ids[i]);
        if (!v) continue;

        SpotLocation temp;
        ErrorCode err = planner_find_temp_spot(g, v->level, v->position, &temp);
        if (err != ERR_OK) return ERR_GARAGE_FULL;

        snprintf(buf, sizeof(buf), "临时移出: 车辆[%s] 从(%d层,%d号) -> (%d层,%d号)",
                 v->plate, v->level + 1, v->position + 1, temp.level + 1, temp.position + 1);
        add_step(pre_seq, ACTION_TEMP_MOVE_OUT, blocked_ids[i], buf);

        snprintf(buf, sizeof(buf), "归位: 车辆[%s] 从(%d层,%d号) -> (%d层,%d号)",
                 v->plate, temp.level + 1, temp.position + 1, v->level + 1, v->position + 1);
        add_step(post_seq, ACTION_TEMP_MOVE_BACK, blocked_ids[i], buf);

        v->original_level = v->level;
        v->original_position = v->position;
        g->spots[v->level][v->position].occupied = false;
        g->spots[v->level][v->position].vehicle_id = -1;
        g->spots[temp.level][temp.position].occupied = true;
        g->spots[temp.level][temp.position].vehicle_id = v->id;
        v->level = temp.level;
        v->position = temp.position;
        v->is_temp_moved = true;
    }
    return ERR_OK;
}

ErrorCode planner_plan_park(Garage *g, SpotLocation target, MovementSequence *seq) {
    char buf[128];
    memset(seq, 0, sizeof(MovementSequence));

    if (target.level == 0) {
        int blocked_ids[MAX_STEPS];
        int block_count = planner_detect_blockage(g, 0, target.position, blocked_ids, MAX_STEPS);

        if (block_count > 0) {
            MovementSequence pre_seq = {0};
            MovementSequence post_seq = {0};
            ErrorCode err = planner_resolve_blockage(g, blocked_ids, block_count, &pre_seq, &post_seq);
            if (err != ERR_OK) return err;
            for (int i = 0; i < pre_seq.count; i++) {
                seq->steps[seq->count++] = pre_seq.steps[i];
            }
            /* ground park: no post-restore needed since car fills the spot */
        }

        int offset = target.position - LIFT_COLUMN;
        if (offset < 0) {
            snprintf(buf, sizeof(buf), "车辆驶入, 向左移动 %d 个车位到达(%d层,%d号位)",
                     -offset, 1, target.position + 1);
            add_step(seq, ACTION_MOVE_LEFT, -offset, buf);
        } else if (offset > 0) {
            snprintf(buf, sizeof(buf), "车辆驶入, 向右移动 %d 个车位到达(%d层,%d号位)",
                     offset, 1, target.position + 1);
            add_step(seq, ACTION_MOVE_RIGHT, offset, buf);
        }
        snprintf(buf, sizeof(buf), "车辆停入 第%d层 第%d号车位", 1, target.position + 1);
        add_step(seq, ACTION_UNLOAD_VEHICLE, 0, buf);
    } else {
        int blocked_ids[MAX_STEPS];
        int block_count = planner_detect_blockage(g, target.level, target.position, blocked_ids, MAX_STEPS);

        if (block_count > 0) {
            MovementSequence pre_seq = {0};
            MovementSequence post_seq = {0};
            ErrorCode err = planner_resolve_blockage(g, blocked_ids, block_count, &pre_seq, &post_seq);
            if (err != ERR_OK) return err;

            for (int i = 0; i < pre_seq.count; i++) {
                seq->steps[seq->count++] = pre_seq.steps[i];
            }
        }

        snprintf(buf, sizeof(buf), "载车板装载车辆");
        add_step(seq, ACTION_LOAD_VEHICLE, 0, buf);

        snprintf(buf, sizeof(buf), "升降机上升到第%d层", target.level + 1);
        add_step(seq, ACTION_LIFT_UP, target.level, buf);

        int offset = target.position - LIFT_COLUMN;
        if (offset < 0) {
            snprintf(buf, sizeof(buf), "载车板向左横移 %d 个位置", -offset);
            add_step(seq, ACTION_MOVE_LEFT, -offset, buf);
        } else if (offset > 0) {
            snprintf(buf, sizeof(buf), "载车板向右横移 %d 个位置", offset);
            add_step(seq, ACTION_MOVE_RIGHT, offset, buf);
        }

        snprintf(buf, sizeof(buf), "车辆停入 第%d层 第%d号车位", target.level + 1, target.position + 1);
        add_step(seq, ACTION_UNLOAD_VEHICLE, 0, buf);

        snprintf(buf, sizeof(buf), "升降机下降回第1层");
        add_step(seq, ACTION_LIFT_DOWN, target.level, buf);
    }

    return ERR_OK;
}

ErrorCode planner_plan_retrieve(Garage *g, int ticket_id, MovementSequence *seq) {
    char buf[128];
    memset(seq, 0, sizeof(MovementSequence));

    Vehicle *v = garage_find_vehicle_by_ticket(g, ticket_id);
    if (!v) return ERR_VEHICLE_NOT_FOUND;

    int level = v->level;
    int position = v->position;

    if (level == 0) {
        int blocked_ids[MAX_STEPS];
        int block_count = planner_detect_blockage(g, 0, position, blocked_ids, MAX_STEPS);

        MovementSequence post_seq_ground = {0};
        if (block_count > 0) {
            MovementSequence pre_seq = {0};
            ErrorCode err = planner_resolve_blockage(g, blocked_ids, block_count, &pre_seq, &post_seq_ground);
            if (err != ERR_OK) return err;
            for (int i = 0; i < pre_seq.count; i++) {
                seq->steps[seq->count++] = pre_seq.steps[i];
            }
        }

        int offset = position - LIFT_COLUMN;
        snprintf(buf, sizeof(buf), "从第1层第%d号车位取出车辆", position + 1);
        add_step(seq, ACTION_LOAD_VEHICLE, 0, buf);

        if (offset < 0) {
            snprintf(buf, sizeof(buf), "车辆向右移动 %d 个位置到出口", -offset);
            add_step(seq, ACTION_MOVE_RIGHT, -offset, buf);
        } else if (offset > 0) {
            snprintf(buf, sizeof(buf), "车辆向左移动 %d 个位置到出口", offset);
            add_step(seq, ACTION_MOVE_LEFT, offset, buf);
        }

        snprintf(buf, sizeof(buf), "车辆驶出车库");
        add_step(seq, ACTION_UNLOAD_VEHICLE, 0, buf);

        for (int i = 0; i < post_seq_ground.count; i++) {
            seq->steps[seq->count++] = post_seq_ground.steps[i];
        }
    } else {
        int blocked_ids[MAX_STEPS];
        int block_count = planner_detect_blockage(g, level, position, blocked_ids, MAX_STEPS);

        MovementSequence post_seq = {0};

        if (block_count > 0) {
            MovementSequence pre_seq = {0};
            ErrorCode err = planner_resolve_blockage(g, blocked_ids, block_count, &pre_seq, &post_seq);
            if (err != ERR_OK) return err;

            for (int i = 0; i < pre_seq.count; i++) {
                seq->steps[seq->count++] = pre_seq.steps[i];
            }
        }

        snprintf(buf, sizeof(buf), "升降机上升到第%d层", level + 1);
        add_step(seq, ACTION_LIFT_UP, level, buf);

        int offset = position - LIFT_COLUMN;
        if (offset < 0) {
            snprintf(buf, sizeof(buf), "载车板向左横移 %d 个位置", -offset);
            add_step(seq, ACTION_MOVE_LEFT, -offset, buf);
        } else if (offset > 0) {
            snprintf(buf, sizeof(buf), "载车板向右横移 %d 个位置", offset);
            add_step(seq, ACTION_MOVE_RIGHT, offset, buf);
        }

        snprintf(buf, sizeof(buf), "装载车辆到载车板");
        add_step(seq, ACTION_LOAD_VEHICLE, 0, buf);

        if (offset < 0) {
            snprintf(buf, sizeof(buf), "载车板向右横移 %d 个位置回到升降口", -offset);
            add_step(seq, ACTION_MOVE_RIGHT, -offset, buf);
        } else if (offset > 0) {
            snprintf(buf, sizeof(buf), "载车板向左横移 %d 个位置回到升降口", offset);
            add_step(seq, ACTION_MOVE_LEFT, offset, buf);
        }

        snprintf(buf, sizeof(buf), "升降机下降回第1层");
        add_step(seq, ACTION_LIFT_DOWN, level, buf);

        snprintf(buf, sizeof(buf), "车辆驶出车库");
        add_step(seq, ACTION_UNLOAD_VEHICLE, 0, buf);

        for (int i = 0; i < post_seq.count; i++) {
            seq->steps[seq->count++] = post_seq.steps[i];
        }
    }

    return ERR_OK;
}

ErrorCode planner_execute_restore(Garage *g, const MovementSequence *seq, Logger *logger) {
    for (int i = 0; i < seq->count; i++) {
        const MovementStep *step = &seq->steps[i];
        if (step->action != ACTION_TEMP_MOVE_BACK) continue;

        int vehicle_id = step->param;
        Vehicle *v = NULL;
        for (int j = 0; j < g->vehicle_count; j++) {
            if (g->vehicles[j].id == vehicle_id && g->vehicles[j].is_parked) {
                v = &g->vehicles[j];
                break;
            }
        }
        if (!v || !v->is_temp_moved) continue;

        int target_level = v->original_level;
        int target_pos = v->original_position;
        int cur_level = v->level;
        int cur_pos = v->position;

        if (g->spots[target_level][target_pos].occupied) {
            SpotLocation alt;
            ErrorCode err = planner_find_temp_spot(g, target_level, target_pos, &alt);
            if (err != ERR_OK) {
                if (logger) {
                    logger_record(logger, LOG_ERROR, vehicle_id,
                                  "归位失败: 车牌%s 原位(%d层,%d号)被占且无替代车位",
                                  v->plate, target_level + 1, target_pos + 1);
                }
                continue;
            }
            if (logger) {
                logger_record(logger, LOG_BLOCKAGE, vehicle_id,
                              "归位重定向: 车牌%s 原位(%d层,%d号)被占, 改停(%d层,%d号)",
                              v->plate, target_level + 1, target_pos + 1,
                              alt.level + 1, alt.position + 1);
            }
            target_level = alt.level;
            target_pos = alt.position;
        }

        g->spots[cur_level][cur_pos].occupied = false;
        g->spots[cur_level][cur_pos].vehicle_id = -1;
        g->spots[target_level][target_pos].occupied = true;
        g->spots[target_level][target_pos].vehicle_id = v->id;
        v->level = target_level;
        v->position = target_pos;
        v->is_temp_moved = false;

        if (logger) {
            logger_record(logger, LOG_MOVE, vehicle_id,
                          "归位: 车牌%s 从(%d层,%d号) -> (%d层,%d号)",
                          v->plate, cur_level + 1, cur_pos + 1,
                          target_level + 1, target_pos + 1);
        }
    }
    return ERR_OK;
}
