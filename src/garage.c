#include "garage.h"
#include <stdio.h>
#include <string.h>

void garage_init(Garage *g) {
    memset(g, 0, sizeof(Garage));
    g->next_ticket_id = 1001;

    for (int level = 0; level < NUM_LEVELS; level++) {
        for (int pos = 0; pos < SPOTS_PER_LEVEL; pos++) {
            g->spots[level][pos].level = level;
            g->spots[level][pos].position = pos;
            g->spots[level][pos].occupied = false;
            g->spots[level][pos].reserved = false;
            g->spots[level][pos].vehicle_id = -1;

            if (pos == 0 || pos == 4) {
                g->spots[level][pos].capacity = SPOT_SMALL_ONLY;
            } else {
                g->spots[level][pos].capacity = SPOT_UNIVERSAL;
            }
        }
    }
}

int garage_count_free(const Garage *g, VehicleSize size) {
    int count = 0;
    for (int level = 0; level < NUM_LEVELS; level++) {
        for (int pos = 0; pos < SPOTS_PER_LEVEL; pos++) {
            if (level == 0 && pos == LIFT_COLUMN) continue;
            if (g->spots[level][pos].occupied) continue;
            if (g->spots[level][pos].reserved) continue;
            if (size == VEHICLE_LARGE && g->spots[level][pos].capacity == SPOT_SMALL_ONLY) continue;
            count++;
        }
    }
    return count;
}

bool garage_is_spot_available(const Garage *g, int level, int pos, VehicleSize size) {
    if (level < 0 || level >= NUM_LEVELS) return false;
    if (pos < 0 || pos >= SPOTS_PER_LEVEL) return false;
    if (level == 0 && pos == LIFT_COLUMN) return false;

    const ParkingSpot *spot = &g->spots[level][pos];
    if (spot->occupied) return false;
    if (spot->reserved) return false;
    if (size == VEHICLE_LARGE && spot->capacity == SPOT_SMALL_ONLY) return false;
    return true;
}

void garage_reserve_spot(Garage *g, int level, int pos) {
    if (level >= 0 && level < NUM_LEVELS && pos >= 0 && pos < SPOTS_PER_LEVEL) {
        g->spots[level][pos].reserved = true;
    }
}

void garage_unreserve_spot(Garage *g, int level, int pos) {
    if (level >= 0 && level < NUM_LEVELS && pos >= 0 && pos < SPOTS_PER_LEVEL) {
        g->spots[level][pos].reserved = false;
    }
}

Vehicle *garage_find_vehicle_by_ticket(Garage *g, int ticket_id) {
    for (int i = 0; i < g->vehicle_count; i++) {
        if (g->vehicles[i].id == ticket_id && g->vehicles[i].is_parked) {
            return &g->vehicles[i];
        }
    }
    return NULL;
}

Vehicle *garage_find_vehicle_at(Garage *g, int level, int position) {
    for (int i = 0; i < g->vehicle_count; i++) {
        if (g->vehicles[i].is_parked &&
            g->vehicles[i].level == level &&
            g->vehicles[i].position == position) {
            return &g->vehicles[i];
        }
    }
    return NULL;
}

int garage_add_vehicle(Garage *g, const char *plate, VehicleSize size, int level, int pos) {
    if (g->vehicle_count >= MAX_VEHICLES) return -1;

    if (level < 0 || level >= NUM_LEVELS) return -1;
    if (pos < 0 || pos >= SPOTS_PER_LEVEL) return -1;
    if (level == 0 && pos == LIFT_COLUMN) return -1;

    ParkingSpot *spot = &g->spots[level][pos];
    if (spot->occupied) return -1;
    if (size == VEHICLE_LARGE && spot->capacity == SPOT_SMALL_ONLY) return -1;

    Vehicle *v = &g->vehicles[g->vehicle_count];
    v->id = g->next_ticket_id++;
    v->size = size;
    strncpy(v->plate, plate, sizeof(v->plate) - 1);
    v->plate[sizeof(v->plate) - 1] = '\0';
    v->level = level;
    v->position = pos;
    v->entry_time = time(NULL);
    v->exit_time = 0;
    v->is_parked = true;
    v->is_temp_moved = false;
    v->original_level = level;
    v->original_position = pos;
    v->state = VSTATE_PARKED;

    spot->occupied = true;
    spot->reserved = false;
    spot->vehicle_id = v->id;
    g->vehicle_count++;

    return v->id;
}

ErrorCode garage_remove_vehicle(Garage *g, int ticket_id) {
    Vehicle *v = garage_find_vehicle_by_ticket(g, ticket_id);
    if (!v) return ERR_VEHICLE_NOT_FOUND;

    g->spots[v->level][v->position].occupied = false;
    g->spots[v->level][v->position].vehicle_id = -1;
    v->is_parked = false;
    v->state = VSTATE_RETRIEVED;
    v->exit_time = time(NULL);

    return ERR_OK;
}

/* ─── Two-phase commit: Park ─── */

int garage_prepare_park(Garage *g, const char *plate, VehicleSize size, int level, int pos) {
    if (g->vehicle_count >= MAX_VEHICLES) return -1;
    if (level < 0 || level >= NUM_LEVELS) return -1;
    if (pos < 0 || pos >= SPOTS_PER_LEVEL) return -1;
    if (level == 0 && pos == LIFT_COLUMN) return -1;

    ParkingSpot *spot = &g->spots[level][pos];
    if (spot->occupied) return -1;
    if (size == VEHICLE_LARGE && spot->capacity == SPOT_SMALL_ONLY) return -1;

    Vehicle *v = &g->vehicles[g->vehicle_count];
    v->id = g->next_ticket_id++;
    v->size = size;
    strncpy(v->plate, plate, sizeof(v->plate) - 1);
    v->plate[sizeof(v->plate) - 1] = '\0';
    v->level = level;
    v->position = pos;
    v->entry_time = time(NULL);
    v->exit_time = 0;
    v->is_parked = true;
    v->is_temp_moved = false;
    v->original_level = level;
    v->original_position = pos;
    v->state = VSTATE_PARKING_PREPARE;

    spot->occupied = true;
    spot->reserved = false;
    spot->vehicle_id = v->id;
    g->vehicle_count++;

    return v->id;
}

void garage_commit_park(Garage *g, int ticket_id) {
    for (int i = 0; i < g->vehicle_count; i++) {
        if (g->vehicles[i].id == ticket_id) {
            g->vehicles[i].state = VSTATE_PARKED;
            return;
        }
    }
}

void garage_abort_park(Garage *g, int ticket_id) {
    for (int i = 0; i < g->vehicle_count; i++) {
        if (g->vehicles[i].id == ticket_id && g->vehicles[i].state == VSTATE_PARKING_PREPARE) {
            Vehicle *v = &g->vehicles[i];
            g->spots[v->level][v->position].occupied = false;
            g->spots[v->level][v->position].vehicle_id = -1;
            v->is_parked = false;
            v->state = VSTATE_NONE;
            return;
        }
    }
}

/* ─── Two-phase commit: Retrieve ─── */

void garage_prepare_retrieve(Garage *g, int ticket_id) {
    for (int i = 0; i < g->vehicle_count; i++) {
        if (g->vehicles[i].id == ticket_id && g->vehicles[i].is_parked) {
            g->vehicles[i].state = VSTATE_RETRIEVING_PREPARE;
            return;
        }
    }
}

void garage_commit_retrieve(Garage *g, int ticket_id) {
    for (int i = 0; i < g->vehicle_count; i++) {
        if (g->vehicles[i].id == ticket_id && g->vehicles[i].state == VSTATE_RETRIEVING_PREPARE) {
            Vehicle *v = &g->vehicles[i];
            g->spots[v->level][v->position].occupied = false;
            g->spots[v->level][v->position].vehicle_id = -1;
            v->is_parked = false;
            v->state = VSTATE_RETRIEVED;
            v->exit_time = time(NULL);
            return;
        }
    }
}

void garage_abort_retrieve(Garage *g, int ticket_id) {
    for (int i = 0; i < g->vehicle_count; i++) {
        if (g->vehicles[i].id == ticket_id && g->vehicles[i].state == VSTATE_RETRIEVING_PREPARE) {
            g->vehicles[i].state = VSTATE_PARKED;
            return;
        }
    }
}

void garage_display_status(const Garage *g) {
    printf("\n");
    printf("============== 立体车库状态 ==============\n");
    for (int level = NUM_LEVELS - 1; level >= 0; level--) {
        printf("  第%d层: ", level + 1);
        for (int pos = 0; pos < SPOTS_PER_LEVEL; pos++) {
            if (level == 0 && pos == LIFT_COLUMN) {
                printf("[升降口] ");
                continue;
            }
            const ParkingSpot *s = &g->spots[level][pos];
            if (s->occupied) {
                Vehicle *v = NULL;
                for (int i = 0; i < g->vehicle_count; i++) {
                    if (g->vehicles[i].id == s->vehicle_id && g->vehicles[i].is_parked) {
                        v = &g->vehicles[i];
                        break;
                    }
                }
                if (v) {
                    printf("[%s%s] ", v->size == VEHICLE_SMALL ? "小" : "大", v->plate);
                } else {
                    printf("[占用] ");
                }
            } else {
                printf("[%s空] ", s->capacity == SPOT_SMALL_ONLY ? "小型" : "通用");
            }
        }
        printf("\n");
    }
    printf("==========================================\n");
    printf("  可用车位: 小型车 %d 个, 大型车 %d 个\n",
           garage_count_free(g, VEHICLE_SMALL),
           garage_count_free(g, VEHICLE_LARGE));
    printf("==========================================\n\n");
}
