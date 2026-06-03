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

    def record_access(self, plate: str, level: int, position: int, action: str):
        key = f"{plate}"
        self.access_counts[key] += 1
        hour = datetime.now().hour
        self.hourly_pattern[key][hour] += 1
        self.records.append({
            "plate": plate,
            "level": level,
            "position": position,
            "action": action,
            "timestamp": time.time(),
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


# ═══════════════════════════════════════════════════════════════════
# Q-learning 预摆放策略智能体
# ═══════════════════════════════════════════════════════════════════

class PreMovementQLearning:
    """
    使用Q-learning学习最优预摆放策略。

    状态(State): (当前小时, 车位占用率级别, 热门车辆数)
    动作(Action): 0=不预移动, 1=移动1辆热门车到出口层, 2=移动2辆, 3=移动3辆
    奖励(Reward): 基于用户等待时间减少量和移动成本的权衡
    """

    NUM_HOUR_BUCKETS = 6       # 0-3, 4-7, 8-11, 12-15, 16-19, 20-23
    NUM_OCCUPANCY_LEVELS = 4   # 0-25%, 25-50%, 50-75%, 75-100%
    NUM_HOT_LEVELS = 3         # 0, 1-2, 3+
    NUM_ACTIONS = 4            # 0, 1, 2, 3 辆车预移动

    def __init__(self, alpha: float = 0.1, gamma: float = 0.9, epsilon: float = 0.3):
        self.alpha = alpha
        self.gamma = gamma
        self.epsilon = epsilon
        self.epsilon_decay = 0.995
        self.epsilon_min = 0.05
        self.q_table: Dict[Tuple[int, int, int], List[float]] = {}
        self.total_episodes = 0
        self.total_reward = 0.0
        self.reward_history: List[float] = []

    def _get_state(self, hour: int, occupancy_pct: float, hot_count: int) -> Tuple[int, int, int]:
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
        return (hour_bucket, occ_level, hot_level)

    def _init_q(self, state: Tuple[int, int, int]):
        if state not in self.q_table:
            self.q_table[state] = [0.0] * self.NUM_ACTIONS

    def choose_action(self, hour: int, occupancy_pct: float, hot_count: int) -> int:
        state = self._get_state(hour, occupancy_pct, hot_count)
        self._init_q(state)
        if random.random() < self.epsilon:
            return random.randint(0, self.NUM_ACTIONS - 1)
        q_values = self.q_table[state]
        max_q = max(q_values)
        best_actions = [a for a, q in enumerate(q_values) if q == max_q]
        return random.choice(best_actions)

    def update(self, hour: int, occupancy_pct: float, hot_count: int,
               action: int, reward: float,
               next_hour: int, next_occupancy: float, next_hot: int):
        state = self._get_state(hour, occupancy_pct, hot_count)
        next_state = self._get_state(next_hour, next_occupancy, next_hot)
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
        for state, q_values in self.q_table.items():
            best_action = q_values.index(max(q_values))
            hour_range = f"{state[0]*4:02d}-{state[0]*4+3:02d}h"
            occ_labels = ["低(<25%)", "中(25-50%)", "高(50-75%)", "满(>75%)"]
            hot_labels = ["无热门", "少量热门", "大量热门"]
            key = f"{hour_range}|{occ_labels[state[1]]}|{hot_labels[state[2]]}"
            policy[key] = {
                "best_action": best_action,
                "q_values": [round(q, 3) for q in q_values],
            }
        return policy


# ═══════════════════════════════════════════════════════════════════
# 预移动执行器
# ═══════════════════════════════════════════════════════════════════

class PreMovementExecutor:
    """负责将热门车辆预移动到出口层(第0层)"""

    MOVE_TIME_PER_LEVEL = 8.0    # 每层移动耗时(秒)
    MOVE_TIME_LATERAL = 3.0      # 横移耗时(秒)

    def __init__(self):
        self.move_log: List[Dict[str, Any]] = []

    def calculate_move_cost(self, from_level: int, from_pos: int,
                            to_level: int, to_pos: int) -> float:
        vertical = abs(from_level - to_level) * self.MOVE_TIME_PER_LEVEL
        horizontal = abs(from_pos - to_pos) * self.MOVE_TIME_LATERAL
        return vertical + horizontal

    def calculate_retrieval_time(self, level: int, position: int) -> float:
        vertical = level * self.MOVE_TIME_PER_LEVEL
        horizontal = abs(position - LIFT_COLUMN) * self.MOVE_TIME_LATERAL
        return vertical + horizontal + 5.0  # 5秒固定装卸时间

    def execute_pre_move(self, vehicles_to_move: List[Dict],
                         garage_spots: List[List[Any]]) -> List[Dict]:
        results = []
        for v_info in vehicles_to_move:
            from_level = v_info["level"]
            from_pos = v_info["position"]
            plate = v_info["plate"]

            target = self._find_exit_layer_spot(garage_spots, from_pos)
            if target is None:
                results.append({"plate": plate, "moved": False, "reason": "出口层无空位"})
                continue

            to_level, to_pos = target
            cost = self.calculate_move_cost(from_level, from_pos, to_level, to_pos)

            move_record = {
                "plate": plate,
                "moved": True,
                "from": (from_level, from_pos),
                "to": (to_level, to_pos),
                "cost_seconds": round(cost, 1),
                "timestamp": time.time(),
            }
            results.append(move_record)
            self.move_log.append(move_record)

        return results

    def _find_exit_layer_spot(self, garage_spots, preferred_pos: int) -> Optional[Tuple[int, int]]:
        positions_by_distance = sorted(
            range(SPOTS_PER_LEVEL),
            key=lambda p: abs(p - preferred_pos)
        )
        for pos in positions_by_distance:
            if pos == LIFT_COLUMN:
                continue
            spot = garage_spots[0][pos]
            if not spot.get("occupied", False) and not spot.get("reserved", False):
                return (0, pos)
        return None


# ═══════════════════════════════════════════════════════════════════
# 用户满意度调查模拟
# ═══════════════════════════════════════════════════════════════════

class SatisfactionSurvey:
    """模拟用户满意度调查系统"""

    def __init__(self):
        self.surveys: List[Dict[str, Any]] = []
        self.strategy_scores: Dict[str, List[float]] = defaultdict(list)

    def simulate_survey(self, wait_time: float, strategy: str = "none") -> Dict[str, Any]:
        """
        根据等待时间模拟用户满意度评分(1-5分)
        等待时间越短，满意度越高，加入随机波动
        """
        if wait_time <= 10:
            base_score = 5.0
        elif wait_time <= 20:
            base_score = 4.5
        elif wait_time <= 30:
            base_score = 4.0
        elif wait_time <= 45:
            base_score = 3.5
        elif wait_time <= 60:
            base_score = 3.0
        elif wait_time <= 90:
            base_score = 2.5
        else:
            base_score = 2.0

        noise = random.gauss(0, 0.4)
        final_score = max(1.0, min(5.0, base_score + noise))
        final_score = round(final_score, 1)

        survey = {
            "timestamp": time.time(),
            "wait_time_seconds": round(wait_time, 1),
            "score": final_score,
            "strategy": strategy,
            "comment": self._generate_comment(final_score),
        }
        self.surveys.append(survey)
        self.strategy_scores[strategy].append(final_score)
        return survey

    def get_statistics(self) -> Dict[str, Any]:
        if not self.surveys:
            return {"total_surveys": 0}

        all_scores = [s["score"] for s in self.surveys]
        stats = {
            "total_surveys": len(self.surveys),
            "average_score": round(sum(all_scores) / len(all_scores), 2),
            "min_score": min(all_scores),
            "max_score": max(all_scores),
            "score_distribution": self._score_distribution(all_scores),
            "strategy_comparison": {},
        }

        for strategy, scores in self.strategy_scores.items():
            if scores:
                stats["strategy_comparison"][strategy] = {
                    "count": len(scores),
                    "average": round(sum(scores) / len(scores), 2),
                    "std_dev": round(self._std_dev(scores), 2),
                }
        return stats

    def get_optimization_suggestion(self) -> str:
        stats = self.get_statistics()
        if not stats.get("strategy_comparison"):
            return "数据不足，无法给出优化建议"

        pre_move = stats["strategy_comparison"].get("pre_move", {})
        no_move = stats["strategy_comparison"].get("none", {})

        if pre_move and no_move:
            diff = pre_move.get("average", 0) - no_move.get("average", 0)
            if diff > 0.3:
                return f"预移动策略显著提升满意度(+{diff:.2f}分)，建议持续使用"
            elif diff > 0:
                return f"预移动策略略微提升满意度(+{diff:.2f}分)，建议在高峰期使用"
            else:
                return "预移动策略未能提升满意度，建议调整Q-learning参数"
        return "需要更多数据对比两种策略的效果"

    def _generate_comment(self, score: float) -> str:
        if score >= 4.5:
            comments = ["非常快速！", "体验很好", "效率很高", "满意"]
        elif score >= 3.5:
            comments = ["还不错", "速度可以", "一般般", "等待时间可以接受"]
        elif score >= 2.5:
            comments = ["有点慢", "还需改进", "等了一会儿", "希望更快"]
        else:
            comments = ["太慢了", "等待太久", "需要改进", "不满意"]
        return random.choice(comments)

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
# 远程管理API（HTTP REST接口）
# ═══════════════════════════════════════════════════════════════════

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs


class GarageAPIState:
    """API共享状态"""
    def __init__(self):
        self.free_small = 0
        self.free_large = 0
        self.total_parked = 0
        self.faults: List[Dict[str, Any]] = []
        self.daily_revenue: Dict[str, float] = {}
        self.revenue_records: List[Dict[str, Any]] = []
        self.lock = threading.Lock()

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


def start_api_server(host: str = "0.0.0.0", port: int = 8080) -> HTTPServer:
    server = HTTPServer((host, port), ManagementAPIHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[API] 远程管理API启动于 http://{host}:{port}")
    print(f"[API] 接口: /api/spots, /api/faults, /api/revenue, /api/health")
    return server


# ═══════════════════════════════════════════════════════════════════
# 综合模拟引擎：对比有无预移动策略的存取时长
# ═══════════════════════════════════════════════════════════════════

class SimulationEngine:
    """模拟运行引擎，对比有无预移动策略"""

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
        plates = [f"京A{random.randint(10000, 99999)}" for _ in range(self.num_vehicles)]
        vehicles = []
        for plate in plates:
            freq = random.choices([1, 2, 3, 5, 8], weights=[30, 25, 20, 15, 10])[0]
            vehicles.append({"plate": plate, "frequency": freq})
        return vehicles

    def _simulate_garage_state(self) -> List[List[Dict]]:
        spots = []
        for level in range(NUM_LEVELS):
            row = []
            for pos in range(SPOTS_PER_LEVEL):
                occupied = random.random() < 0.4
                row.append({
                    "level": level,
                    "position": pos,
                    "occupied": occupied if not (level == 0 and pos == LIFT_COLUMN) else True,
                    "reserved": False,
                })
            spots.append(row)
        return spots

    def run_simulation(self) -> Dict[str, Any]:
        """运行完整模拟对比"""
        print("\n" + "=" * 60)
        print("  智能预摆放策略模拟对比实验")
        print("=" * 60)

        vehicles = self._generate_vehicle_pool()
        hot_vehicles = sorted(vehicles, key=lambda v: v["frequency"], reverse=True)[:8]

        print(f"\n[模拟参数] 车辆池: {self.num_vehicles}辆, 模拟时长: {self.sim_hours}小时")
        print(f"[热门车辆] Top 5 频次: {[v['frequency'] for v in hot_vehicles[:5]]}")

        # ─── 阶段1: 无预移动策略 ───
        print("\n─── 阶段1: 无预移动策略基线测试 ───")
        self.results_no_strategy = self._run_phase(vehicles, use_strategy=False)

        # ─── 阶段2: Q-learning训练 ───
        print("\n─── 阶段2: Q-learning训练阶段 ───")
        self._train_q_agent(vehicles, episodes=200)

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
            num_ops = random.randint(3, 8)
            garage_state = self._simulate_garage_state()

            if use_strategy:
                occupancy = sum(1 for row in garage_state for s in row if s["occupied"]) / (NUM_LEVELS * SPOTS_PER_LEVEL)
                hot_plates = [v["plate"] for v in vehicles if v["frequency"] >= 5]
                hot_count = len(hot_plates)
                action = self.q_agent.choose_action(hour % 24, occupancy, hot_count)

                if action > 0:
                    to_move = []
                    for v in vehicles:
                        if v["frequency"] >= 5 and len(to_move) < action:
                            assigned_level = random.randint(1, NUM_LEVELS - 1)
                            assigned_pos = random.choice([p for p in range(SPOTS_PER_LEVEL) if p != LIFT_COLUMN])
                            to_move.append({
                                "plate": v["plate"],
                                "level": assigned_level,
                                "position": assigned_pos,
                            })
                    self.executor.execute_pre_move(to_move, garage_state)

            for _ in range(num_ops):
                v = random.choice(vehicles)
                level = random.randint(0, NUM_LEVELS - 1)
                pos = random.choice([p for p in range(SPOTS_PER_LEVEL) if p != LIFT_COLUMN or level != 0])

                if use_strategy and v["frequency"] >= 5:
                    level = 0
                    available_ground = [p for p in range(SPOTS_PER_LEVEL)
                                        if p != LIFT_COLUMN and not garage_state[0][p]["occupied"]]
                    if available_ground:
                        pos = min(available_ground, key=lambda p: abs(p - LIFT_COLUMN))

                wait = self.executor.calculate_retrieval_time(level, pos)
                wait_times.append(wait)

                self.tracker.record_access(v["plate"], level, pos, "retrieve")
                self.survey.simulate_survey(wait, strategy=strategy_name)

        avg = sum(wait_times) / len(wait_times) if wait_times else 0
        print(f"  完成 {len(wait_times)} 次存取操作, 平均等待: {avg:.1f}秒")
        return wait_times

    def _train_q_agent(self, vehicles: List[Dict], episodes: int = 200):
        print(f"  训练 {episodes} 轮...")
        for ep in range(episodes):
            hour = random.randint(0, 23)
            occupancy = random.uniform(0.2, 0.8)
            hot_count = sum(1 for v in vehicles if v["frequency"] >= 5)

            action = self.q_agent.choose_action(hour, occupancy, hot_count)

            time_saved = action * random.uniform(5, 15)
            move_cost = action * random.uniform(2, 5)
            reward = time_saved - move_cost

            if occupancy > 0.75 and action > 2:
                reward -= 5.0

            next_hour = (hour + 1) % 24
            next_occ = min(1.0, occupancy + random.uniform(-0.1, 0.1))

            self.q_agent.update(hour, occupancy, hot_count,
                               action, reward,
                               next_hour, next_occ, hot_count)

        avg_reward = self.q_agent.total_reward / max(1, self.q_agent.total_episodes)
        print(f"  训练完成, 平均奖励: {avg_reward:.2f}, epsilon: {self.q_agent.epsilon:.3f}")

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
            },
            "improvement": {
                "avg_time_saved_seconds": round(improvement, 2),
                "improvement_percentage": round(improvement_pct, 1),
            },
            "satisfaction_survey": survey_stats,
            "optimization_suggestion": self.survey.get_optimization_suggestion(),
            "q_learning_policy": policy,
            "pre_movement_log": self.executor.move_log[-10:],
        }

    def _print_report(self, report: Dict):
        print("\n" + "=" * 60)
        print("  模拟对比报告")
        print("=" * 60)

        b = report["baseline_no_strategy"]
        w = report["with_pre_movement"]
        imp = report["improvement"]

        print(f"\n┌─────────────────────────────────────────────┐")
        print(f"│  策略对比结果                                │")
        print(f"├─────────────────────────────────────────────┤")
        print(f"│  无预移动策略:                               │")
        print(f"│    平均存取时长: {b['avg_wait_seconds']:>8.2f} 秒             │")
        print(f"│    最大等待时长: {b['max_wait_seconds']:>8.2f} 秒             │")
        print(f"│    操作总次数:   {b['total_operations']:>8d} 次             │")
        print(f"├─────────────────────────────────────────────┤")
        print(f"│  Q-learning预移动策略:                       │")
        print(f"│    平均存取时长: {w['avg_wait_seconds']:>8.2f} 秒             │")
        print(f"│    最大等待时长: {w['max_wait_seconds']:>8.2f} 秒             │")
        print(f"│    操作总次数:   {w['total_operations']:>8d} 次             │")
        print(f"├─────────────────────────────────────────────┤")
        print(f"│  效果提升:                                   │")
        print(f"│    平均节省时间: {imp['avg_time_saved_seconds']:>8.2f} 秒             │")
        print(f"│    提升百分比:   {imp['improvement_percentage']:>8.1f} %              │")
        print(f"└─────────────────────────────────────────────┘")

        survey = report["satisfaction_survey"]
        if survey.get("strategy_comparison"):
            print(f"\n┌─────────────────────────────────────────────┐")
            print(f"│  用户满意度对比                              │")
            print(f"├─────────────────────────────────────────────┤")
            for strategy, data in survey["strategy_comparison"].items():
                label = "预移动" if strategy == "pre_move" else "无策略"
                print(f"│  {label}: 均分 {data['average']:.2f} (σ={data['std_dev']:.2f}, n={data['count']})")
            print(f"├─────────────────────────────────────────────┤")
            print(f"│  建议: {report['optimization_suggestion']}")
            print(f"└─────────────────────────────────────────────┘")

        print(f"\n[Q-learning策略摘要]")
        for state_desc, info in list(report["q_learning_policy"].items())[:6]:
            print(f"  {state_desc} → 预移动{info['best_action']}辆 (Q={info['q_values']})")


# ═══════════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════════

def main():
    print("=" * 60)
    print("  智能立体车库 - 智能推荐与远程管理系统")
    print("=" * 60)

    # 启动远程管理API
    api_server = start_api_server(port=8080)

    # 模拟一些初始数据
    state = get_api_state()
    state.update_spots(free_small=8, free_large=5, total_parked=6)
    state.add_fault("sensor", "第2层3号位传感器偏移", level=1, position=2)
    state.record_revenue(15.0, "京A12345")
    state.record_revenue(25.5, "京B67890")
    state.record_revenue(8.0, "京C11111")

    print(f"\n[数据] 已注入模拟故障和收入数据")
    print(f"[API] 可通过浏览器访问:")
    print(f"  - 剩余车位: http://127.0.0.1:8080/api/spots")
    print(f"  - 故障状态: http://127.0.0.1:8080/api/faults")
    print(f"  - 日收入报表: http://127.0.0.1:8080/api/revenue")
    print(f"  - 系统健康: http://127.0.0.1:8080/api/health")

    # 运行对比模拟
    engine = SimulationEngine(num_vehicles=40, sim_hours=24)
    report = engine.run_simulation()

    # 导出JSON报告
    report_path = os.path.join(os.path.dirname(__file__), "simulation_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"\n[输出] 详细报告已保存: {report_path}")

    print("\n[API] 远程管理API持续运行中，按Ctrl+C退出...")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        api_server.shutdown()
        print("\n[关闭] 系统已关闭")


if __name__ == "__main__":
    main()
