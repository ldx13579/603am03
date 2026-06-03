"""智能立体车库上位机 - 车位分配与路径规划"""

from typing import Optional, Tuple, List
from config import NUM_LEVELS, SPOTS_PER_LEVEL, LIFT_COLUMN
from models import Garage, VehicleSize

GROUND_PRIORITY = [1, 3, 0, 4]
UPPER_PRIORITY = [2, 1, 3, 0, 4]


def assign_spot(garage: Garage, size: VehicleSize) -> Optional[Tuple[int, int]]:
    for pos in GROUND_PRIORITY:
        if garage.is_spot_available(0, pos, size):
            return (0, pos)
    for level in range(1, NUM_LEVELS):
        for pos in UPPER_PRIORITY:
            if garage.is_spot_available(level, pos, size):
                return (level, pos)
    return None


def plan_park_steps(level: int, position: int) -> List[str]:
    steps = []
    if level == 0:
        if position < LIFT_COLUMN:
            steps.append(f"横移至第{position + 1}号位")
        elif position > LIFT_COLUMN:
            steps.append(f"横移至第{position + 1}号位")
        steps.append("装载车辆")
    else:
        steps.append("车辆驶入升降口")
        steps.append("装载车辆")
        if level > 0:
            steps.append(f"升降机上升至第{level + 1}层")
        if position != LIFT_COLUMN:
            direction = "左移" if position < LIFT_COLUMN else "右移"
            steps.append(f"横移载车板{direction}至第{position + 1}号位")
        steps.append("卸载车辆至车位")
        steps.append("升降机返回地面")
    return steps


def plan_retrieve_steps(level: int, position: int) -> List[str]:
    steps = []
    if level == 0:
        steps.append(f"从第{position + 1}号位取出车辆")
        steps.append("车辆驶出")
    else:
        steps.append(f"升降机上升至第{level + 1}层")
        if position != LIFT_COLUMN:
            direction = "左移" if position < LIFT_COLUMN else "右移"
            steps.append(f"横移载车板{direction}至第{position + 1}号位")
        steps.append("装载车辆")
        steps.append(f"横移载车板回到升降口")
        steps.append("升降机下降至地面")
        steps.append("卸载车辆")
        steps.append("车辆驶出")
    return steps
