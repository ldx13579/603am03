"""智能立体车库上位机 - 费用计算"""

from datetime import datetime
from typing import Dict, Any
from config import (
    RATE_SMALL_PER_MINUTE, RATE_LARGE_PER_MINUTE,
    FREE_MINUTES, MAX_DAILY_FEE_SMALL, MAX_DAILY_FEE_LARGE,
)
from models import Vehicle, VehicleSize


def calculate_fee(size: VehicleSize, entry_time: float, exit_time: float) -> float:
    duration_seconds = exit_time - entry_time
    duration_minutes = int(duration_seconds / 60)
    billable = duration_minutes - FREE_MINUTES
    if billable <= 0:
        return 0.0
    if size == VehicleSize.SMALL:
        rate = RATE_SMALL_PER_MINUTE
        cap = MAX_DAILY_FEE_SMALL
    else:
        rate = RATE_LARGE_PER_MINUTE
        cap = MAX_DAILY_FEE_LARGE
    fee = billable * rate
    return min(fee, cap)


def get_duration_minutes(entry_time: float, exit_time: float) -> int:
    return max(0, int((exit_time - entry_time) / 60))


def generate_bill(vehicle: Vehicle, exit_time: float = None) -> Dict[str, Any]:
    if exit_time is None:
        exit_time = datetime.now().timestamp()
    duration = get_duration_minutes(vehicle.entry_time, exit_time)
    fee = calculate_fee(vehicle.size, vehicle.entry_time, exit_time)
    return {
        "ticket_id": vehicle.id,
        "plate": vehicle.plate,
        "size": "small" if vehicle.size == VehicleSize.SMALL else "large",
        "entry_time": vehicle.entry_time,
        "exit_time": exit_time,
        "duration_minutes": duration,
        "fee": round(fee, 2),
    }
