#ifndef COMMON_H
#define COMMON_H

#include <stdint.h>
#include <stdbool.h>
#include <time.h>

#define NUM_LEVELS        3
#define SPOTS_PER_LEVEL   5
#define TOTAL_SPOTS       (NUM_LEVELS * SPOTS_PER_LEVEL)
#define MAX_VEHICLES      TOTAL_SPOTS
#define MAX_LOG_ENTRIES   256
#define LIFT_COLUMN       2
#define MOVEMENT_STEP_MS  200

typedef enum {
    VEHICLE_SMALL = 0,
    VEHICLE_LARGE = 1
} VehicleSize;

typedef enum {
    SPOT_SMALL_ONLY = 0,
    SPOT_UNIVERSAL  = 1
} SpotCapacity;

typedef enum {
    STATE_IDLE = 0,
    STATE_PARKING,
    STATE_RETRIEVING,
    STATE_ERROR
} SystemState;

typedef enum {
    ACTION_LIFT_UP,
    ACTION_LIFT_DOWN,
    ACTION_MOVE_LEFT,
    ACTION_MOVE_RIGHT,
    ACTION_LOAD_VEHICLE,
    ACTION_UNLOAD_VEHICLE,
    ACTION_TEMP_MOVE_OUT,
    ACTION_TEMP_MOVE_BACK
} ActionType;

typedef struct {
    ActionType action;
    int        param;
    char       description[128];
} MovementStep;

typedef struct {
    int level;
    int position;
} SpotLocation;

#define MAX_STEPS 32

typedef struct {
    MovementStep steps[MAX_STEPS];
    int          count;
} MovementSequence;

typedef struct {
    int         id;
    VehicleSize size;
    char        plate[16];
    int         level;
    int         position;
    time_t      entry_time;
    time_t      exit_time;
    bool        is_parked;
    bool        is_temp_moved;
    int         original_level;
    int         original_position;
} Vehicle;

typedef struct {
    int          level;
    int          position;
    SpotCapacity capacity;
    bool         occupied;
    int          vehicle_id;
} ParkingSpot;

typedef enum {
    LOG_PARK,
    LOG_RETRIEVE,
    LOG_MOVE,
    LOG_BLOCKAGE,
    LOG_BILLING,
    LOG_ERROR,
    LOG_FAULT
} LogType;

typedef struct {
    LogType  type;
    time_t   timestamp;
    int      vehicle_id;
    char     message[256];
} LogEntry;

typedef enum {
    ERR_OK = 0,
    ERR_GARAGE_FULL,
    ERR_NO_SUITABLE_SPOT,
    ERR_VEHICLE_NOT_FOUND,
    ERR_INVALID_INPUT,
    ERR_STATE_CONFLICT,
    ERR_PATH_BLOCKED,
    ERR_MECHANICAL_FAULT
} ErrorCode;

#endif
