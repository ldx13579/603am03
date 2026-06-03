"""智能立体车库上位机 - 数据模型"""

from enum import IntEnum
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from config import NUM_LEVELS, SPOTS_PER_LEVEL, LIFT_COLUMN


class VehicleSize(IntEnum):
    SMALL = 0
    LARGE = 1


class SpotCapacity(IntEnum):
    SMALL_ONLY = 0
    UNIVERSAL = 1


class VehicleState(IntEnum):
    NONE = 0
    PARKING_PREPARE = 1
    PARKED = 2
    RETRIEVING_PREPARE = 3
    RETRIEVED = 4


class SystemState(IntEnum):
    IDLE = 0
    PARKING = 1
    RETRIEVING = 2
    ERROR = 3


@dataclass
class Vehicle:
    id: int
    size: VehicleSize
    plate: str
    level: int
    position: int
    entry_time: float
    exit_time: float = 0.0
    is_parked: bool = True
    is_temp_moved: bool = False
    original_level: int = 0
    original_position: int = 0
    state: VehicleState = VehicleState.PARKED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "size": int(self.size),
            "plate": self.plate,
            "level": self.level,
            "position": self.position,
            "entry_time": self.entry_time,
            "exit_time": self.exit_time,
            "is_parked": self.is_parked,
            "state": int(self.state),
        }


@dataclass
class ParkingSpot:
    level: int
    position: int
    capacity: SpotCapacity
    occupied: bool = False
    reserved: bool = False
    vehicle_id: int = -1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "position": self.position,
            "capacity": int(self.capacity),
            "occupied": self.occupied,
            "reserved": self.reserved,
            "vehicle_id": self.vehicle_id,
        }


class Garage:
    def __init__(self):
        self.spots: List[List[ParkingSpot]] = []
        self.vehicles: List[Vehicle] = []
        self.next_ticket_id: int = 1001
        self._init_spots()

    def _init_spots(self):
        self.spots = []
        for level in range(NUM_LEVELS):
            row = []
            for pos in range(SPOTS_PER_LEVEL):
                if pos == 0 or pos == 4:
                    cap = SpotCapacity.SMALL_ONLY
                else:
                    cap = SpotCapacity.UNIVERSAL
                row.append(ParkingSpot(level=level, position=pos, capacity=cap))
            self.spots.append(row)

    def count_free(self, size: VehicleSize) -> int:
        count = 0
        for level in range(NUM_LEVELS):
            for pos in range(SPOTS_PER_LEVEL):
                if level == 0 and pos == LIFT_COLUMN:
                    continue
                spot = self.spots[level][pos]
                if spot.occupied or spot.reserved:
                    continue
                if size == VehicleSize.LARGE and spot.capacity == SpotCapacity.SMALL_ONLY:
                    continue
                count += 1
        return count

    def is_spot_available(self, level: int, pos: int, size: VehicleSize) -> bool:
        if level < 0 or level >= NUM_LEVELS:
            return False
        if pos < 0 or pos >= SPOTS_PER_LEVEL:
            return False
        if level == 0 and pos == LIFT_COLUMN:
            return False
        spot = self.spots[level][pos]
        if spot.occupied or spot.reserved:
            return False
        if size == VehicleSize.LARGE and spot.capacity == SpotCapacity.SMALL_ONLY:
            return False
        return True

    def add_vehicle(self, plate: str, size: VehicleSize, level: int, pos: int) -> int:
        if not self.is_spot_available(level, pos, size):
            return -1
        vehicle = Vehicle(
            id=self.next_ticket_id,
            size=size,
            plate=plate,
            level=level,
            position=pos,
            entry_time=datetime.now().timestamp(),
            original_level=level,
            original_position=pos,
            state=VehicleState.PARKED,
        )
        self.next_ticket_id += 1
        self.vehicles.append(vehicle)
        spot = self.spots[level][pos]
        spot.occupied = True
        spot.reserved = False
        spot.vehicle_id = vehicle.id
        return vehicle.id

    def remove_vehicle(self, ticket_id: int) -> bool:
        v = self.find_vehicle_by_ticket(ticket_id)
        if v is None:
            return False
        spot = self.spots[v.level][v.position]
        spot.occupied = False
        spot.vehicle_id = -1
        v.is_parked = False
        v.state = VehicleState.RETRIEVED
        v.exit_time = datetime.now().timestamp()
        return True

    def find_vehicle_by_ticket(self, ticket_id: int) -> Optional[Vehicle]:
        for v in self.vehicles:
            if v.id == ticket_id and v.is_parked:
                return v
        return None

    def find_vehicle_by_plate(self, plate: str) -> Optional[Vehicle]:
        plate_lower = plate.lower()
        for v in self.vehicles:
            if v.is_parked and v.plate.lower() == plate_lower:
                return v
        return None

    def get_status(self) -> Dict[str, Any]:
        spots_data = []
        for level in range(NUM_LEVELS):
            for pos in range(SPOTS_PER_LEVEL):
                spot = self.spots[level][pos]
                spot_info = spot.to_dict()
                if spot.occupied and spot.vehicle_id >= 0:
                    v = self.find_vehicle_by_ticket(spot.vehicle_id)
                    if v:
                        spot_info["vehicle"] = v.to_dict()
                spots_data.append(spot_info)
        return {
            "spots": spots_data,
            "free_small": self.count_free(VehicleSize.SMALL),
            "free_large": self.count_free(VehicleSize.LARGE),
            "total_parked": sum(1 for v in self.vehicles if v.is_parked),
            "system_state": int(SystemState.IDLE),
        }
