#ifndef GARAGE_H
#define GARAGE_H

#include "common.h"

typedef struct {
    ParkingSpot spots[NUM_LEVELS][SPOTS_PER_LEVEL];
    Vehicle     vehicles[MAX_VEHICLES];
    int         vehicle_count;
    int         next_ticket_id;
} Garage;

void      garage_init(Garage *g);
int       garage_count_free(const Garage *g, VehicleSize size);
bool      garage_is_spot_available(const Garage *g, int level, int pos, VehicleSize size);
Vehicle  *garage_find_vehicle_by_ticket(Garage *g, int ticket_id);
Vehicle  *garage_find_vehicle_at(Garage *g, int level, int position);
int       garage_add_vehicle(Garage *g, const char *plate, VehicleSize size, int level, int pos);
ErrorCode garage_remove_vehicle(Garage *g, int ticket_id);
void      garage_display_status(const Garage *g);

#endif
