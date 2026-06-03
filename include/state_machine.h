#ifndef STATE_MACHINE_H
#define STATE_MACHINE_H

#include "common.h"

typedef enum {
    EVENT_PARK_REQUEST,
    EVENT_RETRIEVE_REQUEST,
    EVENT_MOVE_COMPLETE,
    EVENT_ERROR_OCCURRED,
    EVENT_RESET
} Event;

typedef struct {
    SystemState current_state;
    int         active_vehicle_id;
} StateMachine;

void        sm_init(StateMachine *sm);
ErrorCode   sm_handle_event(StateMachine *sm, Event event, int vehicle_id);
SystemState sm_get_state(const StateMachine *sm);
const char *sm_state_name(SystemState state);

#endif
