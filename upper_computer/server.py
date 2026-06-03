"""智能立体车库上位机 - TCP服务端"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import socket
import threading
import time
import uuid
import random as _rand
from datetime import datetime
from typing import List, Dict, Any, Tuple
from collections import OrderedDict

from config import SERVER_HOST, SERVER_PORT
from models import Garage, VehicleSize, VehicleState
from billing import calculate_fee, generate_bill
from path_planner import assign_spot, plan_park_steps, plan_retrieve_steps
from protocol import (
    send_message, recv_message, make_response, make_notify,
    CMD_STATUS, CMD_PARK, CMD_PARK_AT, CMD_RETRIEVE_BY_TICKET,
    CMD_RETRIEVE_BY_PLATE, CMD_PAY, CMD_QUERY_FEE, CMD_HEARTBEAT,
    EVT_SPOT_UPDATE,
)


class ClientHandler:
    def __init__(self, sock: socket.socket, addr, server: "ParkingServer"):
        self.sock = sock
        self.addr = addr
        self.server = server
        self.alive = True

    def run(self):
        print(f"[连接] 客户端 {self.addr} 已连接")
        try:
            while self.alive:
                msg = recv_message(self.sock)
                if msg is None:
                    break
                self._handle_message(msg)
        except Exception as e:
            print(f"[错误] 客户端 {self.addr}: {e}")
        finally:
            self.alive = False
            self.server.remove_client(self)
            try:
                self.sock.close()
            except OSError:
                pass
            print(f"[断开] 客户端 {self.addr} 已断开")

    def send(self, msg):
        if self.alive:
            send_message(self.sock, msg)

    def _handle_message(self, msg):
        cmd = msg.get("cmd", "")
        seq = msg.get("seq", 0)
        data = msg.get("data", {})
        idempotency_key = data.get("idempotency_key")

        if idempotency_key:
            cached = self.server.get_cached_response(idempotency_key)
            if cached is not None:
                cached_resp = cached.copy()
                cached_resp["seq"] = seq
                self.send(cached_resp)
                return

        handler_map = {
            CMD_STATUS: self._cmd_status,
            CMD_PARK: self._cmd_park,
            CMD_PARK_AT: self._cmd_park_at,
            CMD_RETRIEVE_BY_TICKET: self._cmd_retrieve_by_ticket,
            CMD_RETRIEVE_BY_PLATE: self._cmd_retrieve_by_plate,
            CMD_PAY: self._cmd_pay,
            CMD_QUERY_FEE: self._cmd_query_fee,
            CMD_HEARTBEAT: self._cmd_heartbeat,
        }

        handler = handler_map.get(cmd)
        if handler:
            handler(seq, data)
        else:
            self.send(make_response(seq, False, error=f"未知命令: {cmd}"))

    def _cmd_status(self, seq, data):
        with self.server.lock:
            status = self.server.garage.get_status()
        self.send(make_response(seq, True, data=status))

    def _cmd_park(self, seq, data):
        plate = data.get("plate", "").strip()
        size_str = data.get("size", "small").lower()
        if not plate:
            self.send(make_response(seq, False, error="车牌不能为空"))
            return

        size = VehicleSize.SMALL if size_str == "small" else VehicleSize.LARGE

        with self.server.lock:
            existing = self.server.garage.find_vehicle_by_plate(plate)
            if existing:
                self.send(make_response(seq, False, error=f"车牌 {plate} 已在库中"))
                return

            spot = assign_spot(self.server.garage, size)
            if spot is None:
                self.send(make_response(seq, False, error="车库已满或无适配车位"))
                return

            level, pos = spot
            ticket_id = self.server.garage.add_vehicle(plate, size, level, pos)
            if ticket_id < 0:
                self.send(make_response(seq, False, error="入库失败"))
                return

            steps = plan_park_steps(level, pos)

        self.send(make_response(seq, True, data={
            "ticket_id": ticket_id,
            "level": level,
            "position": pos,
            "steps": steps,
        }))
        self.server.broadcast_status()

    def _cmd_park_at(self, seq, data):
        plate = data.get("plate", "").strip()
        size_str = data.get("size", "small").lower()
        level = data.get("level", -1)
        pos = data.get("position", -1)

        if not plate:
            self.send(make_response(seq, False, error="车牌不能为空"))
            return

        size = VehicleSize.SMALL if size_str == "small" else VehicleSize.LARGE

        with self.server.lock:
            existing = self.server.garage.find_vehicle_by_plate(plate)
            if existing:
                self.send(make_response(seq, False, error=f"车牌 {plate} 已在库中"))
                return

            if not self.server.garage.is_spot_available(level, pos, size):
                self.send(make_response(seq, False, error="该车位不可用"))
                return

            ticket_id = self.server.garage.add_vehicle(plate, size, level, pos)
            if ticket_id < 0:
                self.send(make_response(seq, False, error="入库失败"))
                return

            steps = plan_park_steps(level, pos)

        self.send(make_response(seq, True, data={
            "ticket_id": ticket_id,
            "level": level,
            "position": pos,
            "steps": steps,
        }))
        self.server.broadcast_status()

    def _cmd_retrieve_by_ticket(self, seq, data):
        ticket_id = data.get("ticket_id", -1)
        with self.server.lock:
            v = self.server.garage.find_vehicle_by_ticket(ticket_id)
            if v is None:
                self.send(make_response(seq, False, error="未找到该票号对应的车辆"))
                return
            bill = generate_bill(v)
            steps = plan_retrieve_steps(v.level, v.position)

        self.send(make_response(seq, True, data={
            "bill": bill,
            "steps": steps,
            "level": v.level,
            "position": v.position,
        }))

    def _cmd_retrieve_by_plate(self, seq, data):
        plate = data.get("plate", "").strip()
        if not plate:
            self.send(make_response(seq, False, error="车牌不能为空"))
            return

        with self.server.lock:
            v = self.server.garage.find_vehicle_by_plate(plate)
            if v is None:
                self.send(make_response(seq, False, error=f"未找到车牌 {plate} 对应的车辆"))
                return
            bill = generate_bill(v)
            steps = plan_retrieve_steps(v.level, v.position)

        self.send(make_response(seq, True, data={
            "bill": bill,
            "steps": steps,
            "ticket_id": v.id,
            "level": v.level,
            "position": v.position,
        }))

    def _cmd_pay(self, seq, data):
        ticket_id = data.get("ticket_id", -1)
        method = data.get("method", "cash")
        idempotency_key = data.get("idempotency_key")

        with self.server.lock:
            v = self.server.garage.find_vehicle_by_ticket(ticket_id)
            if v is None:
                self.send(make_response(seq, False, error="未找到该车辆"))
                return
            now = datetime.now().timestamp()
            fee = calculate_fee(v.size, v.entry_time, now)
            plate = v.plate

        time.sleep(0.5)
        payment_success = _rand.random() > 0.02

        if not payment_success:
            self.send(make_response(seq, False, error="支付失败，请重试"))
            return

        receipt = {
            "ticket_id": ticket_id,
            "plate": plate,
            "fee": round(fee, 2),
            "method": method,
            "payment_time": datetime.now().isoformat(),
            "transaction_id": str(uuid.uuid4())[:8].upper(),
        }
        resp = make_response(seq, True, data={"receipt": receipt})
        self.send(resp)

        if idempotency_key:
            self.server.cache_response(idempotency_key, resp)

        with self.server.lock:
            self.server.garage.remove_vehicle(ticket_id)
        self.server.broadcast_status()

    def _cmd_query_fee(self, seq, data):
        ticket_id = data.get("ticket_id", -1)
        with self.server.lock:
            v = self.server.garage.find_vehicle_by_ticket(ticket_id)
            if v is None:
                self.send(make_response(seq, False, error="未找到该车辆"))
                return
            now = datetime.now().timestamp()
            fee = calculate_fee(v.size, v.entry_time, now)
            duration = int((now - v.entry_time) / 60)

        self.send(make_response(seq, True, data={
            "ticket_id": ticket_id,
            "plate": v.plate,
            "fee": round(fee, 2),
            "duration_minutes": duration,
        }))

    def _cmd_heartbeat(self, seq, data):
        self.send(make_response(seq, True, data={
            "time": datetime.now().isoformat(),
            "state": "idle",
        }))


class ParkingServer:
    DEDUP_CACHE_MAX = 256

    def __init__(self, host: str = SERVER_HOST, port: int = SERVER_PORT):
        self.host = host
        self.port = port
        self.garage = Garage()
        self.lock = threading.Lock()
        self.clients: List[ClientHandler] = []
        self.clients_lock = threading.Lock()
        self.running = False
        self._dedup_cache: OrderedDict = OrderedDict()
        self._dedup_lock = threading.Lock()

    def cache_response(self, idempotency_key: str, response: Dict[str, Any]):
        with self._dedup_lock:
            self._dedup_cache[idempotency_key] = response
            while len(self._dedup_cache) > self.DEDUP_CACHE_MAX:
                self._dedup_cache.popitem(last=False)

    def get_cached_response(self, idempotency_key: str) -> Any:
        with self._dedup_lock:
            return self._dedup_cache.get(idempotency_key)

    def run(self):
        self.running = True
        server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server_sock.bind((self.host, self.port))
        server_sock.listen(5)
        server_sock.settimeout(1.0)

        print(f"[启动] 智能立体车库服务端启动于 {self.host}:{self.port}")
        print(f"[信息] 3层 x 5车位，升降横移式，等待客户端连接...")

        try:
            while self.running:
                try:
                    client_sock, addr = server_sock.accept()
                    handler = ClientHandler(client_sock, addr, self)
                    with self.clients_lock:
                        self.clients.append(handler)
                    t = threading.Thread(target=handler.run, daemon=True)
                    t.start()
                except socket.timeout:
                    continue
        except KeyboardInterrupt:
            print("\n[关闭] 服务端关闭中...")
        finally:
            self.running = False
            server_sock.close()
            with self.clients_lock:
                for c in self.clients:
                    c.alive = False
                    try:
                        c.sock.close()
                    except OSError:
                        pass

    def remove_client(self, handler: ClientHandler):
        with self.clients_lock:
            if handler in self.clients:
                self.clients.remove(handler)

    def broadcast_status(self):
        with self.lock:
            status = self.garage.get_status()
        notify = make_notify(EVT_SPOT_UPDATE, status)
        dead_clients = []
        with self.clients_lock:
            for c in self.clients:
                if not c.alive:
                    dead_clients.append(c)
                    continue
                try:
                    c.send(notify)
                except Exception:
                    c.alive = False
                    dead_clients.append(c)
            for c in dead_clients:
                if c in self.clients:
                    self.clients.remove(c)


if __name__ == "__main__":
    server = ParkingServer()
    server.run()
