"""智能立体车库 - 智能推荐与Q-learning预摆放策略"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import random
import time
import math
import threading
from collections import defaultdict
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timedelta
from config import NUM_LEVELS, SPOTS_PER_LEVEL, LIFT_COLUMN


# ═══════════════════════════════════════════════════════════════════
# 存取频次历史记录器
# ═══════════════════════════════════════════════════════════════════

class AccessHistoryTracker:
    """追踪每个车位的历史存取频次"""

    def __init__(self):
        self.access_counts: Dict[str, int] = defaultdict(int)
        self.hourly_pattern: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.records: List[Dict[str, Any]] = []
        self.dwell_times: Dict[str, List[float]] = defaultdict(list)
        self.weekday_pattern: Dict[str, Dict[int, int]] = defaultdict(lambda: defaultdict(int))

    def record_access(self, plate: str, level: int, position: int, action: str,
                      dwell_minutes: float = 0.0):
        key = f"{plate}"
        self.access_counts[key] += 1
        now = datetime.now()
        hour = now.hour
        weekday = now.weekday()
        self.hourly_pattern[key][hour] += 1
        self.weekday_pattern[key][weekday] += 1
        if dwell_minutes > 0:
            self.dwell_times[key].append(dwell_minutes)
        self.records.append({
            "plate": plate,
            "level": level,
            "position": position,
            "action": action,
            "timestamp": time.time(),
            "hour": hour,
            "weekday": weekday,
        })

    def get_hot_vehicles(self, top_n: int = 5) -> List[Tuple[str, int]]:
        sorted_items = sorted(self.access_counts.items(), key=lambda x: x[1], reverse=True)
        return sorted_items[:top_n]

    def get_predicted_demand(self, hour: int) -> List[str]:
        predictions = []
        for plate, hourly in self.hourly_pattern.items():
            if hourly.get(hour, 0) >= 2:
                predictions.append(plate)
        return predictions

    def get_frequency(self, plate: str) -> int:
        return self.access_counts.get(plate, 0)

    def get_avg_dwell(self, plate: str) -> float:
        times = self.dwell_times.get(plate, [])
        return sum(times) / len(times) if times else 60.0

    def get_peak_hour_ratio(self, hour: int) -> float:
        total_this_hour = sum(
            hourly.get(hour, 0) for hourly in self.hourly_pattern.values()
        )
        total_all = sum(self.access_counts.values())
        return total_this_hour / max(1, total_all)

    def is_weekday_regular(self, plate: str, weekday: int) -> bool:
        return self.weekday_pattern[plate].get(weekday, 0) >= 2


# ═══════════════════════════════════════════════════════════════════
# Q-learning 预摆放策略智能体（扩展状态空间）
# ═══════════════════════════════════════════════════════════════════

class PreMovementQLearning:
    """
    使用Q-learning学习最优预摆放策略。

    扩展状态空间(State):
      - 时段桶(6档): 0-3h, 4-7h, 8-11h, 12-15h, 16-19h, 20-23h
      - 车位占用率(4档): <25%, 25-50%, 50-75%, >75%
      - 热门车辆数(3档): 0, 1-2, 3+
      - 出口层空位比(3档): 充裕(>=3), 紧张(1-2), 无空位(0)
      - 高峰时段标志(2档): 是否处于高峰期(7-9h, 17-19h)
      - 平均停留时长(3档): 短停(<30min), 中停(30-120min), 长停(>120min)

    动作(Action): 0=不预移动, 1=移动1辆, 2=移动2辆, 3=移动3辆
    奖励(Reward): 基于用户等待时间减少量、移动成本和用户满意度的综合权衡
    """

    NUM_ACTIONS = 4

    def __init__(self, alpha: float = 0.1, gamma: float = 0.9, epsilon: float = 0.3):
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_decay = 0.995
        self.epsilon_min = 0.05
        self.q_table: Dict[Tuple, List[float]] = {}
        self.total_episodes = 0
        self.total_reward = 0.0
        self.reward_history: List[float] = []

    def _get_state(self, hour: int, occupancy_pct: float, hot_count: int,
                   exit_free: int = 2, avg_dwell_min: float = 60.0) -> Tuple:
        hour_bucket = hour // 4

        if occupancy_pct < 0.25:
            occ_level = 0
        elif occupancy_pct < 0.50:
            occ_level = 1
        elif occupancy_pct < 0.75:
            occ_level = 2
        else:
            occ_level = 3

        hot_level = min(hot_count, 2)

        if exit_free >= 3:
            exit_level = 0
        elif exit_free >= 1:
            exit_level = 1
        else:
            exit_level = 2

        is_peak = 1 if hour in (7, 8, 9, 17, 18, 19) else 0

        if avg_dwell_min < 30:
            dwell_level = 0
        elif avg_dwell_min < 120:
            dwell_level = 1
        else:
            dwell_level = 2

        return (hour_bucket, occ_level, hot_level, exit_level, is_peak, dwell_level)

    def _init_q(self, state: Tuple):
        if state not in self.q_table:
            self.q_table[state] = [0.0] * self.NUM_ACTIONS

    def choose_action(self, hour: int, occupancy_pct: float, hot_count: int,
                      exit_free: int = 2, avg_dwell_min: float = 60.0) -> int:
        state = self._get_state(hour, occupancy_pct, hot_count, exit_free, avg_dwell_min)
        self._init_q(state)
        if random.random() < self.epsilon:
            return random.randint(0, self.NUM_ACTIONS - 1)
        q_values = self.q_table[state]
        max_q = max(q_values)
        best_actions = [a for a, q in enumerate(q_values) if q == max_q]
        return random.choice(best_actions)

    def update(self, hour: int, occupancy_pct: float, hot_count: int,
               action: int, reward: float,
               next_hour: int, next_occupancy: float, next_hot: int,
               exit_free: int = 2, avg_dwell_min: float = 60.0,
               next_exit_free: int = 2, next_dwell: float = 60.0):
        state = self._get_state(hour, occupancy_pct, hot_count, exit_free, avg_dwell_min)
        next_state = self._get_state(next_hour, next_occupancy, next_hot, next_exit_free, next_dwell)
        self._init_q(state)
        self._init_q(next_state)

        current_q = self.q_table[state][action]
        max_next_q = max(self.q_table[next_state])
        new_q = current_q + self.alpha * (reward + self.gamma * max_next_q - current_q)
        self.q_table[state][action] = new_q

        self.total_episodes += 1
        self.total_reward += reward
        self.reward_history.append(reward)

        self.epsilon = max(self.epsilon_min, self.epsilon * self.epsilon_decay)

    def get_policy_summary(self) -> Dict[str, Any]:
        policy = {}
        occ_labels = ["低(<25%)", "中(25-50%)", "高(50-75%)", "满(>75%)"]
        hot_labels = ["无热门", "少量热门", "大量热门"]
        exit_labels = ["充裕", "紧张", "无空位"]
        peak_labels = ["非高峰", "高峰"]
        dwell_labels = ["短停", "中停", "长停"]

        for state, q_values in self.q_table.items():
            best_action = q_values.index(max(q_values))
            hour_range = f"{state[0]*4:02d}-{state[0]*4+3:02d}h"
            key = (f"{hour_range}|{occ_labels[state[1]]}|{hot_labels[state[2]]}|"
                   f"出口{exit_labels[state[3]]}|{peak_labels[state[4]]}|{dwell_labels[state[5]]}")
            policy[key] = {
                "best_action": best_action,
                "q_values": [round(q, 3) for q in q_values],
            }
        return policy


# ═══════════════════════════════════════════════════════════════════
# 预移动执行器（增加多层备选位置搜索）
# ═══════════════════════════════════════════════════════════════════

class PreMovementExecutor:
    """负责将热门车辆预移动到出口层，出口层满时尝试备选层"""

    MOVE_TIME_PER_LEVEL = 8.0
    MOVE_TIME_LATERAL = 3.0

    def __init__(self):
        self.move_log: List[Dict[str, Any]] = []
        self.fallback_count = 0
        self.failed_count = 0

    def calculate_move_cost(self, from_level: int, from_pos: int,
                            to_level: int, to_pos: int) -> float:
        vertical = abs(from_level - to_level) * self.MOVE_TIME_PER_LEVEL
        horizontal = abs(from_pos - to_pos) * self.MOVE_TIME_LATERAL
        return vertical + horizontal

    def calculate_retrieval_time(self, level: int, position: int) -> float:
        vertical = level * self.MOVE_TIME_PER_LEVEL
        horizontal = abs(position - LIFT_COLUMN) * self.MOVE_TIME_LATERAL
        return vertical + horizontal + 5.0

    def execute_pre_move(self, vehicles_to_move: List[Dict],
                         garage_spots: List[List[Any]]) -> List[Dict]:
        results = []
        for v_info in vehicles_to_move:
            from_level = v_info["level"]
            from_pos = v_info["position"]
            plate = v_info["plate"]

            target = self._find_best_target(garage_spots, from_level, from_pos)
            if target is None:
                self.failed_count += 1
                results.append({"plate": plate, "moved": False, "reason": "所有备选位置均不可用"})
                continue

            to_level, to_pos, strategy = target
            cost = self.calculate_move_cost(from_level, from_pos, to_level, to_pos)

            if strategy != "exit_layer":
                self.fallback_count += 1

            move_record = {
                "plate": plate,
                "moved": True,
                "from": (from_level, from_pos),
                "to": (to_level, to_pos),
                "cost_seconds": round(cost, 1),
                "placement_strategy": strategy,
                "timestamp": time.time(),
            }
            results.append(move_record)
            self.move_log.append(move_record)

        return results

    def _find_best_target(self, garage_spots, from_level: int,
                          preferred_pos: int) -> Optional[Tuple[int, int, str]]:
        target = self._search_layer(garage_spots, 0, preferred_pos)
        if target:
            return (target[0], target[1], "exit_layer")

        target = self._search_layer_near_lift(garage_spots, 1)
        if target:
            return (target[0], target[1], "fallback_L2_near_lift")

        for level in range(1, NUM_LEVELS):
            target = self._search_layer(garage_spots, level, LIFT_COLUMN)
            if target:
                return (target[0], target[1], f"fallback_L{level+1}")

        return None

    def _search_layer(self, garage_spots, level: int,
                      preferred_pos: int) -> Optional[Tuple[int, int]]:
        positions_by_distance = sorted(
            range(SPOTS_PER_LEVEL),
            key=lambda p: abs(p - preferred_pos)
        )
        for pos in positions_by_distance:
            if level == 0 and pos == LIFT_COLUMN:
                continue
            spot = garage_spots[level][pos]
            if not spot.get("occupied", False) and not spot.get("reserved", False):
                return (level, pos)
        return None

    def _search_layer_near_lift(self, garage_spots, level: int) -> Optional[Tuple[int, int]]:
        candidates = sorted(
            range(SPOTS_PER_LEVEL),
            key=lambda p: abs(p - LIFT_COLUMN)
        )
        for pos in candidates:
            if level == 0 and pos == LIFT_COLUMN:
                continue
            spot = garage_spots[level][pos]
            if not spot.get("occupied", False) and not spot.get("reserved", False):
                return (level, pos)
        return None

    def get_stats(self) -> Dict[str, Any]:
        total_moves = len(self.move_log)
        exit_moves = sum(1 for m in self.move_log if m.get("placement_strategy") == "exit_layer")
        return {
            "total_moves": total_moves,
            "exit_layer_moves": exit_moves,
            "fallback_moves": self.fallback_count,
            "failed_moves": self.failed_count,
            "fallback_ratio": round(self.fallback_count / max(1, total_moves), 3),
        }


# ═══════════════════════════════════════════════════════════════════
# 用户满意度调查模拟（多维度评分）
# ═══════════════════════════════════════════════════════════════════

class SatisfactionSurvey:
    """模拟用户满意度调查系统 - 多维度评价"""

    DIMENSION_WEIGHTS = {
        "wait_time": 0.35,
        "smoothness": 0.20,
        "accuracy": 0.15,
        "safety": 0.15,
        "environment": 0.15,
    }

    def __init__(self):
        self.surveys: List[Dict[str, Any]] = []
        self.strategy_scores: Dict[str, List[float]] = defaultdict(list)
        self.dimension_history: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )

    def simulate_survey(self, wait_time: float, strategy: str = "none",
                        move_count: int = 0, fault_active: bool = False,
                        is_peak: bool = False) -> Dict[str, Any]:
        dimensions = self._score_all_dimensions(
            wait_time, strategy, move_count, fault_active, is_peak
        )

        weighted_score = sum(
            dimensions[dim] * weight
            for dim, weight in self.DIMENSION_WEIGHTS.items()
        )
        weighted_score = round(max(1.0, min(5.0, weighted_score)), 1)

        survey = {
            "timestamp": time.time(),
            "wait_time_seconds": round(wait_time, 1),
            "overall_score": weighted_score,
            "dimensions": {k: round(v, 2) for k, v in dimensions.items()},
            "strategy": strategy,
            "context": {
                "is_peak": is_peak,
                "fault_active": fault_active,
                "move_count": move_count,
            },
            "comment": self._generate_comment(weighted_score, dimensions),
        }
        self.surveys.append(survey)
        self.strategy_scores[strategy].append(weighted_score)
        for dim, score in dimensions.items():
            self.dimension_history[strategy][dim].append(score)
        return survey

    def _score_all_dimensions(self, wait_time: float, strategy: str,
                              move_count: int, fault_active: bool,
                              is_peak: bool) -> Dict[str, float]:
        wait_score = self._score_wait_time(wait_time)

        base_smooth = 4.5 if strategy == "pre_move" else 3.8
        if move_count > 2:
            base_smooth -= 0.3
        smoothness = base_smooth + random.gauss(0, 0.3)

        accuracy = 4.6 + random.gauss(0, 0.25)
        if fault_active:
            accuracy -= random.uniform(0.5, 1.5)

        safety = 4.7 + random.gauss(0, 0.2)
        if move_count > 3:
            safety -= 0.4

        env_base = 4.0
        if is_peak:
            env_base -= 0.5
        if fault_active:
            env_base -= 0.3
        environment = env_base + random.gauss(0, 0.3)

        return {
            "wait_time": max(1.0, min(5.0, wait_score)),
            "smoothness": max(1.0, min(5.0, smoothness)),
            "accuracy": max(1.0, min(5.0, accuracy)),
            "safety": max(1.0, min(5.0, safety)),
            "environment": max(1.0, min(5.0, environment)),
        }

    def _score_wait_time(self, wait_time: float) -> float:
        if wait_time <= 10:
            base = 5.0
        elif wait_time <= 20:
            base = 4.5
        elif wait_time <= 30:
            base = 4.0
        elif wait_time <= 45:
            base = 3.5
        elif wait_time <= 60:
            base = 3.0
        elif wait_time <= 90:
            base = 2.5
        else:
            base = 2.0
        return base + random.gauss(0, 0.3)

    def get_statistics(self) -> Dict[str, Any]:
        if not self.surveys:
            return {"total_surveys": 0}

        all_scores = [s["overall_score"] for s in self.surveys]
        stats = {
            "total_surveys": len(self.surveys),
            "average_score": round(sum(all_scores) / len(all_scores), 2),
            "min_score": min(all_scores),
            "max_score": max(all_scores),
            "score_distribution": self._score_distribution(all_scores),
            "strategy_comparison": {},
            "dimension_analysis": {},
        }

        for strategy, scores in self.strategy_scores.items():
            if scores:
                stats["strategy_comparison"][strategy] = {
                    "count": len(scores),
                    "average": round(sum(scores) / len(scores), 2),
                    "std_dev": round(self._std_dev(scores), 2),
                }

        for strategy, dims in self.dimension_history.items():
            dim_stats = {}
            for dim, scores in dims.items():
                if scores:
                    dim_stats[dim] = {
                        "average": round(sum(scores) / len(scores), 2),
                        "std_dev": round(self._std_dev(scores), 2),
                    }
            stats["dimension_analysis"][strategy] = dim_stats

        return stats

    def get_optimization_suggestion(self) -> str:
        stats = self.get_statistics()
        if not stats.get("strategy_comparison"):
            return "数据不足，无法给出优化建议"

        pre_move = stats["strategy_comparison"].get("pre_move", {})
        no_move = stats["strategy_comparison"].get("none", {})

        suggestions = []
        if pre_move and no_move:
            diff = pre_move.get("average", 0) - no_move.get("average", 0)
            if diff > 0.3:
                suggestions.append(f"预移动策略显著提升满意度(+{diff:.2f}分)，建议持续使用")
            elif diff > 0:
                suggestions.append(f"预移动策略略微提升满意度(+{diff:.2f}分)，建议在高峰期使用")
            else:
                suggestions.append("预移动策略未能提升满意度，建议调整Q-learning参数")

        dim_analysis = stats.get("dimension_analysis", {})
        for strategy, dims in dim_analysis.items():
            weakest_dim = None
            weakest_score = 5.0
            for dim, data in dims.items():
                if data["average"] < weakest_score:
                    weakest_score = data["average"]
                    weakest_dim = dim
            if weakest_dim and weakest_score < 3.5:
                dim_names = {
                    "wait_time": "等待时间",
                    "smoothness": "操作流畅度",
                    "accuracy": "定位精度",
                    "safety": "安全感知",
                    "environment": "环境舒适度",
                }
                label = "预移动" if strategy == "pre_move" else "无策略"
                suggestions.append(
                    f"[{label}]最弱维度: {dim_names.get(weakest_dim, weakest_dim)}"
                    f"(均分{weakest_score:.2f})，建议重点优化"
                )

        return "; ".join(suggestions) if suggestions else "需要更多数据对比两种策略的效果"

    def _generate_comment(self, score: float, dimensions: Dict[str, float]) -> str:
        worst_dim = min(dimensions, key=dimensions.get)
        dim_comments = {
            "wait_time": {True: "取车很快", False: "等待太久了"},
            "smoothness": {True: "操作很流畅", False: "中间停顿了好几次"},
            "accuracy": {True: "车辆定位准确", False: "感觉定位有些偏差"},
            "safety": {True: "感觉很安全", False: "有点担心车被刮蹭"},
            "environment": {True: "环境整洁", False: "车库里有些闷热嘈杂"},
        }

        if score >= 4.0:
            base = random.choice(["总体满意", "体验不错", "挺好的"])
            good_dim = max(dimensions, key=dimensions.get)
            extra = dim_comments.get(good_dim, {}).get(True, "")
            return f"{base}，{extra}" if extra else base
        elif score >= 3.0:
            base = random.choice(["一般般", "还行吧", "有提升空间"])
            bad = dim_comments.get(worst_dim, {}).get(False, "")
            return f"{base}，{bad}" if bad else base
        else:
            bad = dim_comments.get(worst_dim, {}).get(False, "需要改进")
            return f"不太满意，{bad}"

    def _score_distribution(self, scores: List[float]) -> Dict[str, int]:
        dist = {"1分": 0, "2分": 0, "3分": 0, "4分": 0, "5分": 0}
        for s in scores:
            bucket = min(5, max(1, int(round(s))))
            dist[f"{bucket}分"] += 1
        return dist

    @staticmethod
    def _std_dev(values: List[float]) -> float:
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return math.sqrt(variance)


# ═══════════════════════════════════════════════════════════════════
# 远程管理API（HTTP REST接口，含故障记录定期清理）
# ═══════════════════════════════════════════════════════════════════

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


class GarageAPIState:
    """API共享状态"""

    FAULT_RETENTION_HOURS = 72
    REVENUE_RETENTION_DAYS = 90
    CLEANUP_INTERVAL = 3600

    def __init__(self):
        self.free_small = 0
        self.free_large = 0
        self.total_parked = 0
        self.faults: List[Dict[str, Any]] = []
        self.daily_revenue: Dict[str, float] = {}
        self.revenue_records: List[Dict[str, Any]] = []
        self.lock = threading.Lock()
        self._cleanup_timer: Optional[threading.Timer] = None
        self._start_cleanup_scheduler()

    def _start_cleanup_scheduler(self):
        self._run_cleanup()
        self._schedule_next_cleanup()

    def _schedule_next_cleanup(self):
        self._cleanup_timer = threading.Timer(self.CLEANUP_INTERVAL, self._cleanup_tick)
        self._cleanup_timer.daemon = True
        self._cleanup_timer.start()

    def _cleanup_tick(self):
        self._run_cleanup()
        self._schedule_next_cleanup()

    def _run_cleanup(self):
        with self.lock:
            now = datetime.now()
            cutoff = now - timedelta(hours=self.FAULT_RETENTION_HOURS)
            cutoff_iso = cutoff.isoformat()

            before_count = len(self.faults)
            self.faults = [
                f for f in self.faults
                if not f["resolved"] or f.get("resolved_time", f["timestamp"]) > cutoff_iso
            ]
            removed_faults = before_count - len(self.faults)

            revenue_cutoff = (now - timedelta(days=self.REVENUE_RETENTION_DAYS)).strftime("%Y-%m-%d")
            before_rev = len(self.revenue_records)
            self.revenue_records = [
                r for r in self.revenue_records if r["date"] >= revenue_cutoff
            ]
            self.daily_revenue = {
                k: v for k, v in self.daily_revenue.items() if k >= revenue_cutoff
            }
            removed_revenue = before_rev - len(self.revenue_records)

            if removed_faults > 0 or removed_revenue > 0:
                print(f"[清理] 移除 {removed_faults} 条过期故障记录, "
                      f"{removed_revenue} 条过期收入记录")

    def stop_cleanup(self):
        if self._cleanup_timer:
            self._cleanup_timer.cancel()

    def update_spots(self, free_small: int, free_large: int, total_parked: int):
        with self.lock:
            self.free_small = free_small
            self.free_large = free_large
            self.total_parked = total_parked

    def add_fault(self, fault_type: str, description: str, level: int = -1, position: int = -1):
        with self.lock:
            self.faults.append({
                "id": len(self.faults) + 1,
                "type": fault_type,
                "description": description,
                "level": level,
                "position": position,
                "timestamp": datetime.now().isoformat(),
                "resolved": False,
            })

    def resolve_fault(self, fault_id: int):
        with self.lock:
            for f in self.faults:
                if f["id"] == fault_id:
                    f["resolved"] = True
                    f["resolved_time"] = datetime.now().isoformat()

    def record_revenue(self, amount: float, plate: str):
        with self.lock:
            today = datetime.now().strftime("%Y-%m-%d")
            self.daily_revenue[today] = self.daily_revenue.get(today, 0.0) + amount
            self.revenue_records.append({
                "date": today,
                "amount": round(amount, 2),
                "plate": plate,
                "time": datetime.now().isoformat(),
            })

    def get_revenue_report(self, date: str = None) -> Dict[str, Any]:
        with self.lock:
            if date is None:
                date = datetime.now().strftime("%Y-%m-%d")
            day_records = [r for r in self.revenue_records if r["date"] == date]
            total = self.daily_revenue.get(date, 0.0)
            return {
                "date": date,
                "total_revenue": round(total, 2),
                "transaction_count": len(day_records),
                "transactions": day_records[-20:],
            }

    def get_cleanup_info(self) -> Dict[str, Any]:
        with self.lock:
            return {
                "fault_retention_hours": self.FAULT_RETENTION_HOURS,
                "revenue_retention_days": self.REVENUE_RETENTION_DAYS,
                "cleanup_interval_seconds": self.CLEANUP_INTERVAL,
                "total_faults": len(self.faults),
                "total_revenue_records": len(self.revenue_records),
            }


_api_state = GarageAPIState()


def get_api_state() -> GarageAPIState:
    return _api_state


class ManagementAPIHandler(BaseHTTPRequestHandler):
    """远程管理REST API处理器"""

    def log_message(self, format, *args):
        pass

    def _send_json(self, data: Dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)

        routes = {
            "/api/spots": self._handle_spots,
            "/api/faults": self._handle_faults,
            "/api/revenue": self._handle_revenue,
            "/api/health": self._handle_health,
            "/api/cleanup": self._handle_cleanup,
        }

        handler = routes.get(path)
        if handler:
            handler(params)
        else:
            self._send_json({"error": "未知接口", "available": list(routes.keys())}, 404)

    def _handle_spots(self, params):
        state = get_api_state()
        with state.lock:
            self._send_json({
                "free_small": state.free_small,
                "free_large": state.free_large,
                "total_parked": state.total_parked,
                "total_capacity": NUM_LEVELS * SPOTS_PER_LEVEL - 1,
                "timestamp": datetime.now().isoformat(),
            })

    def _handle_faults(self, params):
        state = get_api_state()
        with state.lock:
            show_resolved = params.get("resolved", ["false"])[0].lower() == "true"
            faults = state.faults if show_resolved else [f for f in state.faults if not f["resolved"]]
            self._send_json({
                "faults": faults,
                "total_active": sum(1 for f in state.faults if not f["resolved"]),
                "total_resolved": sum(1 for f in state.faults if f["resolved"]),
                "retention_hours": state.FAULT_RETENTION_HOURS,
            })

    def _handle_revenue(self, params):
        state = get_api_state()
        date = params.get("date", [None])[0]
        report = state.get_revenue_report(date)
        self._send_json(report)

    def _handle_health(self, params):
        state = get_api_state()
        active_faults = sum(1 for f in state.faults if not f["resolved"])
        self._send_json({
            "status": "degraded" if active_faults > 0 else "healthy",
            "active_faults": active_faults,
            "uptime": "running",
            "timestamp": datetime.now().isoformat(),
        })

    def _handle_cleanup(self, params):
        state = get_api_state()
        self._send_json(state.get_cleanup_info())


def start_api_server(host: str = "0.0.0.0", port: int = 8080) -> HTTPServer:
    server = HTTPServer((host, port), ManagementAPIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[API] 远程管理API启动于 http://{host}:{port}")
    print(f"[API] 接口: /api/spots, /api/faults, /api/revenue, /api/health, /api/cleanup")
    return server


# ═══════════════════════════════════════════════════════════════════
# 综合模拟引擎：对比有无预移动策略的存取时长
# 车辆频率分布基于真实停车场数据统计规律
# ═══════════════════════════════════════════════════════════════════

class SimulationEngine:
    """模拟运行引擎，对比有无预移动策略"""

    # 基于真实停车场统计:
    # - 约40%为日常通勤车(工作日每天1-2次)
    # - 约25%为周边居民车(频繁进出，每天2-4次)
    # - 约20%为临时来访车(偶尔一次)
    # - 约10%为商务公务车(规律性强，固定时段)
    # - 约5%为高频短停车(快递/外卖/接送，每天5+次)
    VEHICLE_PROFILES = {
        "commuter": {"ratio": 0.40, "daily_freq": (1, 2), "dwell_min": (240, 600)},
        "resident": {"ratio": 0.25, "daily_freq": (2, 4), "dwell_min": (30, 180)},
        "visitor":  {"ratio": 0.20, "daily_freq": (0, 1), "dwell_min": (60, 240)},
        "business": {"ratio": 0.10, "daily_freq": (1, 3), "dwell_min": (60, 180)},
        "frequent": {"ratio": 0.05, "daily_freq": (5, 10), "dwell_min": (5, 30)},
    }

    # 基于真实数据的时段流量分布(24小时相对权重)
    HOURLY_TRAFFIC = [
        0.02, 0.01, 0.01, 0.01, 0.02, 0.03,  # 0-5h
        0.05, 0.10, 0.12, 0.08, 0.06, 0.05,  # 6-11h
        0.06, 0.05, 0.04, 0.05, 0.06, 0.10,  # 12-17h
        0.08, 0.05, 0.04, 0.03, 0.02, 0.02,  # 18-23h
    ]

    def __init__(self, num_vehicles: int = 50, sim_hours: int = 24):
        self.num_vehicles = num_vehicles
        self.sim_hours = sim_hours
        self.tracker = AccessHistoryTracker()
        self.q_agent = PreMovementQLearning(alpha=0.15, gamma=0.9, epsilon=0.5)
        self.executor = PreMovementExecutor()
        self.survey = SatisfactionSurvey()
        self.results_no_strategy: List[float] = []
        self.results_with_strategy: List[float] = []

    def _generate_vehicle_pool(self) -> List[Dict]:
        vehicles = []
        for profile_name, profile in self.VEHICLE_PROFILES.items():
            count = max(1, int(self.num_vehicles * profile["ratio"]))
            for _ in range(count):
                plate = f"京{random.choice('ABCDEFGH')}{random.randint(10000, 99999)}"
                freq_lo, freq_hi = profile["daily_freq"]
                dwell_lo, dwell_hi = profile["dwell_min"]
                daily_freq = random.randint(freq_lo, freq_hi)
                avg_dwell = random.uniform(dwell_lo, dwell_hi)

                preferred_hour = None
                if profile_name == "commuter":
                    preferred_hour = random.choice([7, 8, 9])
                elif profile_name == "business":
                    preferred_hour = random.choice([9, 10, 14, 15])

                vehicles.append({
                    "plate": plate,
                    "profile": profile_name,
                    "daily_frequency": daily_freq,
                    "avg_dwell_minutes": avg_dwell,
                    "preferred_hour": preferred_hour,
                })
        return vehicles

    def _simulate_garage_state(self, occupancy_target: float = 0.4) -> List[List[Dict]]:
        spots = []
        for level in range(NUM_LEVELS):
            row = []
            for pos in range(SPOTS_PER_LEVEL):
                is_lift = (level == 0 and pos == LIFT_COLUMN)
                occupied = is_lift or (random.random() < occupancy_target)
                row.append({
                    "level": level,
                    "position": pos,
                    "occupied": occupied,
                    "reserved": False,
                })
            spots.append(row)
        return spots

    def _get_hour_occupancy(self, hour: int) -> float:
        cumulative = sum(self.HOURLY_TRAFFIC[:hour+1])
        return min(0.9, 0.2 + cumulative * 2.0)

    def _count_exit_free(self, garage_state: List[List[Dict]]) -> int:
        count = 0
        for pos in range(SPOTS_PER_LEVEL):
            if pos == LIFT_COLUMN:
                continue
            if not garage_state[0][pos]["occupied"]:
                count += 1
        return count

    def run_simulation(self) -> Dict[str, Any]:
        """运行完整模拟对比"""
        print("\n" + "=" * 60)
        print("  智能预摆放策略模拟对比实验")
        print("=" * 60)

        vehicles = self._generate_vehicle_pool()
        hot_vehicles = sorted(vehicles, key=lambda v: v["daily_frequency"], reverse=True)[:8]

        print(f"\n[模拟参数] 车辆池: {len(vehicles)}辆, 模拟时长: {self.sim_hours}小时")
        print(f"[车辆构成]")
        profile_counts = defaultdict(int)
        for v in vehicles:
            profile_counts[v["profile"]] += 1
        profile_names = {
            "commuter": "通勤", "resident": "居民",
            "visitor": "访客", "business": "商务", "frequent": "高频短停"
        }
        for p, c in profile_counts.items():
            print(f"  {profile_names.get(p, p)}: {c}辆")
        print(f"[热门车辆] Top 5 日频次: {[v['daily_frequency'] for v in hot_vehicles[:5]]}")

        # ─── 阶段1: 无预移动策略 ───
        print("\n─── 阶段1: 无预移动策略基线测试 ───")
        self.results_no_strategy = self._run_phase(vehicles, use_strategy=False)

        # ─── 阶段2: Q-learning训练 ───
        print("\n─── 阶段2: Q-learning训练阶段 ───")
        self._train_q_agent(vehicles, episodes=300)

        # ─── 阶段3: 有预移动策略 ───
        print("\n─── 阶段3: 使用预移动策略测试 ───")
        self.results_with_strategy = self._run_phase(vehicles, use_strategy=True)

        # ─── 生成报告 ───
        report = self._generate_report()
        self._print_report(report)
        return report

    def _run_phase(self, vehicles: List[Dict], use_strategy: bool) -> List[float]:
        wait_times = []
        strategy_name = "pre_move" if use_strategy else "none"

        for hour in range(self.sim_hours):
            traffic_weight = self.HOURLY_TRAFFIC[hour % 24]
            num_ops = max(1, int(traffic_weight * 80 + random.randint(-2, 2)))
            occupancy_target = self._get_hour_occupancy(hour % 24)
            garage_state = self._simulate_garage_state(occupancy_target)
            is_peak = (hour % 24) in (7, 8, 9, 17, 18, 19)
            exit_free = self._count_exit_free(garage_state)

            fault_active = random.random() < 0.05

            if use_strategy:
                occupancy = sum(
                    1 for row in garage_state for s in row if s["occupied"]
                ) / (NUM_LEVELS * SPOTS_PER_LEVEL)
                hot_plates = [v for v in vehicles if v["daily_frequency"] >= 4]
                hot_count = len(hot_plates)

                avg_dwell = sum(v["avg_dwell_minutes"] for v in hot_plates) / max(1, len(hot_plates))

                action = self.q_agent.choose_action(
                    hour % 24, occupancy, hot_count, exit_free, avg_dwell
                )

                if action > 0:
                    to_move = []
                    candidates = sorted(hot_plates, key=lambda v: v["daily_frequency"], reverse=True)
                    for v in candidates:
                        if len(to_move) >= action:
                            break
                        if v.get("preferred_hour") and abs((hour % 24) - v["preferred_hour"]) <= 1:
                            assigned_level = random.randint(1, NUM_LEVELS - 1)
                            assigned_pos = random.choice(
                                [p for p in range(SPOTS_PER_LEVEL) if p != LIFT_COLUMN]
                            )
                            to_move.append({
                                "plate": v["plate"],
                                "level": assigned_level,
                                "position": assigned_pos,
                            })
                    if not to_move:
                        for v in candidates[:action]:
                            assigned_level = random.randint(1, NUM_LEVELS - 1)
                            assigned_pos = random.choice(
                                [p for p in range(SPOTS_PER_LEVEL) if p != LIFT_COLUMN]
                            )
                            to_move.append({
                                "plate": v["plate"],
                                "level": assigned_level,
                                "position": assigned_pos,
                            })
                    self.executor.execute_pre_move(to_move, garage_state)

            for _ in range(num_ops):
                hour_candidates = [
                    v for v in vehicles
                    if v.get("preferred_hour") is None or
                    abs((hour % 24) - v["preferred_hour"]) <= 2 or
                    random.random() < 0.3
                ]
                if not hour_candidates:
                    hour_candidates = vehicles
                v = random.choice(hour_candidates)

                level = random.randint(0, NUM_LEVELS - 1)
                pos = random.choice(
                    [p for p in range(SPOTS_PER_LEVEL) if p != LIFT_COLUMN or level != 0]
                )

                if use_strategy and v["daily_frequency"] >= 4:
                    available_ground = [
                        p for p in range(SPOTS_PER_LEVEL)
                        if p != LIFT_COLUMN and not garage_state[0][p]["occupied"]
                    ]
                    if available_ground:
                        level = 0
                        pos = min(available_ground, key=lambda p: abs(p - LIFT_COLUMN))

                wait = self.executor.calculate_retrieval_time(level, pos)
                wait_times.append(wait)

                self.tracker.record_access(
                    v["plate"], level, pos, "retrieve",
                    dwell_minutes=v["avg_dwell_minutes"]
                )
                self.survey.simulate_survey(
                    wait, strategy=strategy_name,
                    move_count=len(self.executor.move_log),
                    fault_active=fault_active,
                    is_peak=is_peak,
                )

        avg = sum(wait_times) / len(wait_times) if wait_times else 0
        print(f"  完成 {len(wait_times)} 次存取操作, 平均等待: {avg:.1f}秒")
        return wait_times

    def _train_q_agent(self, vehicles: List[Dict], episodes: int = 300):
        print(f"  训练 {episodes} 轮...")
        for ep in range(episodes):
            hour = random.randint(0, 23)
            occupancy = random.uniform(0.2, 0.85)
            hot_count = sum(1 for v in vehicles if v["daily_frequency"] >= 4)
            exit_free = random.randint(0, SPOTS_PER_LEVEL - 2)
            avg_dwell = random.uniform(10, 300)

            action = self.q_agent.choose_action(hour, occupancy, hot_count, exit_free, avg_dwell)

            time_saved = action * random.uniform(5, 15)
            move_cost = action * random.uniform(2, 5)
            reward = time_saved - move_cost

            if occupancy > 0.75 and action > 2:
                reward -= 5.0
            if exit_free == 0 and action > 0:
                reward -= 3.0 * action
            if hour in (7, 8, 9, 17, 18, 19):
                reward += action * 2.0
            if avg_dwell < 30 and action > 0:
                reward += 1.5

            next_hour = (hour + 1) % 24
            next_occ = min(1.0, max(0.0, occupancy + random.uniform(-0.1, 0.1)))
            next_exit_free = max(0, exit_free - action + random.randint(0, 1))

            self.q_agent.update(
                hour, occupancy, hot_count, action, reward,
                next_hour, next_occ, hot_count,
                exit_free=exit_free, avg_dwell_min=avg_dwell,
                next_exit_free=next_exit_free, next_dwell=avg_dwell,
            )

        avg_reward = self.q_agent.total_reward / max(1, self.q_agent.total_episodes)
        print(f"  训练完成, 平均奖励: {avg_reward:.2f}, epsilon: {self.q_agent.epsilon:.3f}")
        print(f"  Q表规模: {len(self.q_agent.q_table)} 个状态")

    def _generate_report(self) -> Dict[str, Any]:
        avg_no = sum(self.results_no_strategy) / len(self.results_no_strategy) if self.results_no_strategy else 0
        avg_with = sum(self.results_with_strategy) / len(self.results_with_strategy) if self.results_with_strategy else 0
        improvement = avg_no - avg_with
        improvement_pct = (improvement / avg_no * 100) if avg_no > 0 else 0

        survey_stats = self.survey.get_statistics()
        policy = self.q_agent.get_policy_summary()

        return {
            "simulation_params": {
                "num_vehicles": self.num_vehicles,
                "sim_hours": self.sim_hours,
                "q_learning_episodes": self.q_agent.total_episodes,
                "state_space_size": len(self.q_agent.q_table),
                "vehicle_profiles": {
                    k: {"ratio": v["ratio"], "daily_freq": v["daily_freq"]}
                    for k, v in self.VEHICLE_PROFILES.items()
                },
            },
            "baseline_no_strategy": {
                "total_operations": len(self.results_no_strategy),
                "avg_wait_seconds": round(avg_no, 2),
                "max_wait_seconds": round(max(self.results_no_strategy), 2) if self.results_no_strategy else 0,
                "min_wait_seconds": round(min(self.results_no_strategy), 2) if self.results_no_strategy else 0,
            },
            "with_pre_movement": {
                "total_operations": len(self.results_with_strategy),
                "avg_wait_seconds": round(avg_with, 2),
                "max_wait_seconds": round(max(self.results_with_strategy), 2) if self.results_with_strategy else 0,
                "min_wait_seconds": round(min(self.results_with_strategy), 2) if self.results_with_strategy else 0,
                "executor_stats": self.executor.get_stats(),
            },
            "improvement": {
                "avg_time_saved_seconds": round(improvement, 2),
                "improvement_percentage": round(improvement_pct, 1),
            },
            "satisfaction_survey": survey_stats,
            "optimization_suggestion": self.survey.get_optimization_suggestion(),
            "q_learning_policy_sample": dict(list(policy.items())[:10]),
            "pre_movement_log": self.executor.move_log[-10:],
        }

    def _print_report(self, report: Dict):
        print("\n" + "=" * 60)
        print("  模拟对比报告")
        print("=" * 60)

        b = report["baseline_no_strategy"]
        w = report["with_pre_movement"]
        imp = report["improvement"]

        print(f"\n┌─────────────────────────────────────────────────┐")
        print(f"│  策略对比结果                                    │")
        print(f"├─────────────────────────────────────────────────┤")
        print(f"│  无预移动策略:                                   │")
        print(f"│    平均存取时长: {b['avg_wait_seconds']:>8.2f} 秒              │")
        print(f"│    最大等待时长: {b['max_wait_seconds']:>8.2f} 秒              │")
        print(f"│    操作总次数:   {b['total_operations']:>8d} 次              │")
        print(f"├─────────────────────────────────────────────────┤")
        print(f"│  Q-learning预移动策略:                           │")
        print(f"│    平均存取时长: {w['avg_wait_seconds']:>8.2f} 秒              │")
        print(f"│    最大等待时长: {w['max_wait_seconds']:>8.2f} 秒              │")
        print(f"│    操作总次数:   {w['total_operations']:>8d} 次              │")
        print(f"├─────────────────────────────────────────────────┤")
        print(f"│  效果提升:                                       │")
        print(f"│    平均节省时间: {imp['avg_time_saved_seconds']:>8.2f} 秒              │")
        print(f"│    提升百分比:   {imp['improvement_percentage']:>8.1f} %               │")
        print(f"└─────────────────────────────────────────────────┘")

        ex_stats = w.get("executor_stats", {})
        if ex_stats:
            print(f"\n┌─────────────────────────────────────────────────┐")
            print(f"│  预移动执行统计                                  │")
            print(f"├─────────────────────────────────────────────────┤")
            print(f"│  总移动次数:     {ex_stats['total_moves']:>6d}                     │")
            print(f"│  出口层直接放置: {ex_stats['exit_layer_moves']:>6d}                     │")
            print(f"│  备选位置放置:   {ex_stats['fallback_moves']:>6d}                     │")
            print(f"│  放置失败次数:   {ex_stats['failed_moves']:>6d}                     │")
            print(f"│  备选比例:       {ex_stats['fallback_ratio']*100:>6.1f}%                    │")
            print(f"└─────────────────────────────────────────────────┘")

        survey = report["satisfaction_survey"]
        if survey.get("strategy_comparison"):
            print(f"\n┌─────────────────────────────────────────────────┐")
            print(f"│  用户满意度对比(多维度加权)                      │")
            print(f"├─────────────────────────────────────────────────┤")
            for strategy, data in survey["strategy_comparison"].items():
                label = "预移动" if strategy == "pre_move" else "无策略"
                print(f"│  {label}: 综合均分 {data['average']:.2f} "
                      f"(σ={data['std_dev']:.2f}, n={data['count']})")
            print(f"├─────────────────────────────────────────────────┤")

            dim_names = {"wait_time": "等待时间", "smoothness": "流畅度",
                         "accuracy": "精度", "safety": "安全", "environment": "环境"}
            dim_analysis = survey.get("dimension_analysis", {})
            for strategy, dims in dim_analysis.items():
                label = "预移动" if strategy == "pre_move" else "无策略"
                dim_strs = [f"{dim_names.get(d,d)}:{s['average']:.1f}"
                            for d, s in dims.items()]
                print(f"│  [{label}] {', '.join(dim_strs)}")

            print(f"├─────────────────────────────────────────────────┤")
            print(f"│  建议: {report['optimization_suggestion'][:42]}")
            if len(report['optimization_suggestion']) > 42:
                print(f"│        {report['optimization_suggestion'][42:]}")
            print(f"└─────────────────────────────────────────────────┘")

        print(f"\n[Q-learning] 状态空间: {report['simulation_params']['state_space_size']} 个状态")
        print(f"[Q-learning策略样本]")
        for state_desc, info in list(report["q_learning_policy_sample"].items())[:6]:
            print(f"  {state_desc}")
            print(f"    → 预移动{info['best_action']}辆 (Q={info['q_values']})")


# ═══════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  智能立体车库 - 智能推荐与远程管理系统 v2.0")
    print("=" * 60)

    api_server = start_api_server(port=8080)

    state = get_api_state()
    state.update_spots(free_small=8, free_large=5, total_parked=6)
    state.add_fault("sensor", "第2层3号位传感器偏移", level=1, position=2)
    state.record_revenue(15.0, "京A12345")
    state.record_revenue(25.5, "京B67890")
    state.record_revenue(8.0, "京C11111")

    print(f"\n[数据] 已注入模拟故障和收入数据")
    print(f"[清理] 故障记录保留 {state.FAULT_RETENTION_HOURS}h, "
          f"收入记录保留 {state.REVENUE_RETENTION_DAYS}天, "
          f"每 {state.CLEANUP_INTERVAL}s 自动清理")
    print(f"[API] 可通过浏览器访问:")
    print(f"  - 剩余车位: http://127.0.0.1:8080/api/spots")
    print(f"  - 故障状态: http://127.0.0.1:8080/api/faults")
    print(f"  - 日收入报表: http://127.0.0.1:8080/api/revenue")
    print(f"  - 系统健康: http://127.0.0.1:8080/api/health")
    print(f"  - 清理状态: http://127.0.0.1:8080/api/cleanup")

    engine = SimulationEngine(num_vehicles=50, sim_hours=24)
    report = engine.run_simulation()

    report_path = os.path.join(os.path.dirname(__file__), "simulation_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n[输出] 详细报告已保存: {report_path}")

    print("\n[API] 远程管理API持续运行中，按Ctrl+C退出...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        state.stop_cleanup()
        api_server.shutdown()
        print("\n[关闭] 系统已关闭")


if __name__ == "__main__":
    main()
