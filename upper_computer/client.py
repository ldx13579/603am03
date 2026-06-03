"""智能立体车库上位机 - Tkinter GUI客户端"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
import socket
import threading
import queue
import time
import random
from datetime import datetime

from config import (
    SERVER_HOST, SERVER_PORT, NUM_LEVELS, SPOTS_PER_LEVEL, LIFT_COLUMN,
    SPOT_WIDTH, SPOT_HEIGHT, SPOT_PADDING, CANVAS_PADDING,
    RECONNECT_MAX_BACKOFF, RECONNECT_BASE,
)
from protocol import (
    send_message, recv_message, make_request,
    CMD_STATUS, CMD_PARK, CMD_PARK_AT, CMD_RETRIEVE_BY_TICKET,
    CMD_RETRIEVE_BY_PLATE, CMD_PAY, CMD_QUERY_FEE, CMD_HEARTBEAT,
    EVT_SPOT_UPDATE,
)


class NetworkManager:
    def __init__(self, host, port, msg_queue: queue.Queue, status_queue: queue.Queue):
        self.host = host
        self.port = port
        self.msg_queue = msg_queue
        self.status_queue = status_queue
        self._sock = None
        self._connected = False
        self._reconnect_attempt = 0
        self._stop = threading.Event()
        self._send_queue = queue.Queue()
        self._seq = 0
        self._lock = threading.Lock()

    @property
    def connected(self):
        return self._connected

    def start(self):
        threading.Thread(target=self._connect_loop, daemon=True).start()
        threading.Thread(target=self._send_loop, daemon=True).start()

    def stop(self):
        self._stop.set()
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass

    def send_command(self, cmd: str, data: dict = None) -> int:
        with self._lock:
            self._seq += 1
            seq = self._seq
        msg = make_request(cmd, seq, data)
        self._send_queue.put(msg)
        return seq

    def _connect_loop(self):
        while not self._stop.is_set():
            try:
                self._sock = socket.create_connection(
                    (self.host, self.port), timeout=5
                )
                self._sock.settimeout(2.0)
                self._connected = True
                self._reconnect_attempt = 0
                self.status_queue.put(("connected", None))
                self._read_loop()
            except (ConnectionError, OSError, socket.timeout):
                pass
            finally:
                self._connected = False
                if self._sock:
                    try:
                        self._sock.close()
                    except OSError:
                        pass
                    self._sock = None

            if self._stop.is_set():
                break

            backoff = min(
                RECONNECT_BASE * (2 ** self._reconnect_attempt),
                RECONNECT_MAX_BACKOFF,
            )
            jitter = random.uniform(0, backoff * 0.3)
            total_wait = backoff + jitter
            self._reconnect_attempt += 1
            self.status_queue.put(("disconnected", total_wait))
            self._stop.wait(total_wait)

    def _read_loop(self):
        while not self._stop.is_set() and self._connected:
            try:
                msg = recv_message(self._sock)
                if msg is None:
                    break
                self.msg_queue.put(msg)
            except socket.timeout:
                continue
            except (OSError, ConnectionError):
                break

    def _send_loop(self):
        while not self._stop.is_set():
            try:
                msg = self._send_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if self._connected and self._sock:
                if not send_message(self._sock, msg):
                    self._connected = False


class ParkDialog(tk.Toplevel):
    def __init__(self, parent, level, position, capacity_label):
        super().__init__(parent)
        self.title("存车")
        self.result = None
        self.resizable(False, False)
        self.grab_set()

        frame = ttk.Frame(self, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=f"目标车位: 第{level+1}层 第{position+1}号 ({capacity_label})").pack(anchor=tk.W)
        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=8)

        ttk.Label(frame, text="车牌号:").pack(anchor=tk.W)
        self.plate_var = tk.StringVar()
        plate_entry = ttk.Entry(frame, textvariable=self.plate_var, width=20)
        plate_entry.pack(fill=tk.X, pady=(0, 8))
        plate_entry.focus_set()

        ttk.Label(frame, text="车辆类型:").pack(anchor=tk.W)
        self.size_var = tk.StringVar(value="small")
        size_frame = ttk.Frame(frame)
        size_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Radiobutton(size_frame, text="小型车", variable=self.size_var, value="small").pack(side=tk.LEFT)
        ttk.Radiobutton(size_frame, text="大型车", variable=self.size_var, value="large").pack(side=tk.LEFT, padx=10)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_frame, text="确认存车", command=self._confirm).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side=tk.RIGHT)

        self.bind("<Return>", lambda e: self._confirm())
        self.geometry("+%d+%d" % (parent.winfo_x() + 100, parent.winfo_y() + 100))

    def _confirm(self):
        plate = self.plate_var.get().strip()
        if not plate:
            messagebox.showwarning("提示", "请输入车牌号", parent=self)
            return
        self.result = {"plate": plate, "size": self.size_var.get()}
        self.destroy()


class RetrieveDialog(tk.Toplevel):
    def __init__(self, parent, vehicle_info, bill_info, steps):
        super().__init__(parent)
        self.title("取车 & 支付")
        self.result = None
        self.resizable(False, False)
        self.grab_set()

        frame = ttk.Frame(self, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        info_frame = ttk.LabelFrame(frame, text="车辆信息", padding=8)
        info_frame.pack(fill=tk.X, pady=(0, 8))

        plate = vehicle_info.get("plate", "")
        ticket_id = bill_info.get("ticket_id", 0)
        size_text = "小型车" if bill_info.get("size") == "small" else "大型车"
        duration = bill_info.get("duration_minutes", 0)
        fee = bill_info.get("fee", 0)
        entry_dt = datetime.fromtimestamp(bill_info.get("entry_time", 0))

        ttk.Label(info_frame, text=f"车牌: {plate}").pack(anchor=tk.W)
        ttk.Label(info_frame, text=f"票号: {ticket_id}").pack(anchor=tk.W)
        ttk.Label(info_frame, text=f"类型: {size_text}").pack(anchor=tk.W)
        ttk.Label(info_frame, text=f"入库: {entry_dt.strftime('%Y-%m-%d %H:%M:%S')}").pack(anchor=tk.W)
        ttk.Label(info_frame, text=f"时长: {duration} 分钟").pack(anchor=tk.W)

        fee_label = ttk.Label(info_frame, text=f"费用: ¥{fee:.2f}", font=("", 12, "bold"))
        fee_label.pack(anchor=tk.W, pady=(4, 0))

        if steps:
            step_frame = ttk.LabelFrame(frame, text="取车动作序列", padding=8)
            step_frame.pack(fill=tk.X, pady=(0, 8))
            for i, step in enumerate(steps, 1):
                ttk.Label(step_frame, text=f"  {i}. {step}").pack(anchor=tk.W)

        pay_frame = ttk.LabelFrame(frame, text="支付方式", padding=8)
        pay_frame.pack(fill=tk.X, pady=(0, 8))
        self.method_var = tk.StringVar(value="wechat")
        ttk.Radiobutton(pay_frame, text="微信支付", variable=self.method_var, value="wechat").pack(anchor=tk.W)
        ttk.Radiobutton(pay_frame, text="支付宝", variable=self.method_var, value="alipay").pack(anchor=tk.W)
        ttk.Radiobutton(pay_frame, text="现金", variable=self.method_var, value="cash").pack(anchor=tk.W)

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(btn_frame, text="确认支付并取车", command=self._confirm).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side=tk.RIGHT)

        self.geometry("+%d+%d" % (parent.winfo_x() + 100, parent.winfo_y() + 100))

    def _confirm(self):
        self.result = {"method": self.method_var.get()}
        self.destroy()


class PlateSearchDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("车牌搜索取车")
        self.result = None
        self.resizable(False, False)
        self.grab_set()

        frame = ttk.Frame(self, padding=15)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text="输入车牌号查询在库车辆:").pack(anchor=tk.W)
        self.plate_var = tk.StringVar()
        entry = ttk.Entry(frame, textvariable=self.plate_var, width=20)
        entry.pack(fill=tk.X, pady=8)
        entry.focus_set()

        btn_frame = ttk.Frame(frame)
        btn_frame.pack(fill=tk.X)
        ttk.Button(btn_frame, text="搜索", command=self._search).pack(side=tk.LEFT)
        ttk.Button(btn_frame, text="取消", command=self.destroy).pack(side=tk.RIGHT)

        self.bind("<Return>", lambda e: self._search())
        self.geometry("+%d+%d" % (parent.winfo_x() + 100, parent.winfo_y() + 100))

    def _search(self):
        plate = self.plate_var.get().strip()
        if not plate:
            messagebox.showwarning("提示", "请输入车牌号", parent=self)
            return
        self.result = plate
        self.destroy()


class ParkingClient(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("智能立体车库 - 上位机监控系统")
        self.geometry("750x650")
        self.resizable(False, False)

        self.msg_queue = queue.Queue()
        self.status_queue = queue.Queue()
        self.spots_data = []
        self.pending_callbacks = {}

        self._build_menu()
        self._build_ui()

        self.net = NetworkManager(SERVER_HOST, SERVER_PORT, self.msg_queue, self.status_queue)
        self.net.start()

        self.after(50, self._poll_messages)
        self.after(100, self._poll_status)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_menu(self):
        menubar = tk.Menu(self)
        self.config(menu=menubar)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="刷新状态", command=self._request_status)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self._on_close)
        menubar.add_cascade(label="操作", menu=file_menu)

        search_menu = tk.Menu(menubar, tearoff=0)
        search_menu.add_command(label="按车牌取车", command=self._show_plate_search)
        menubar.add_cascade(label="搜索", menu=search_menu)

    def _build_ui(self):
        main_frame = ttk.Frame(self, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)

        title_label = ttk.Label(main_frame, text="智能立体车库 停车引导与计费系统",
                                font=("Microsoft YaHei", 14, "bold"))
        title_label.pack(pady=(0, 10))

        canvas_width = SPOTS_PER_LEVEL * (SPOT_WIDTH + SPOT_PADDING) + CANVAS_PADDING * 2
        canvas_height = NUM_LEVELS * (SPOT_HEIGHT + SPOT_PADDING) + CANVAS_PADDING * 2 + 30
        self.canvas = tk.Canvas(main_frame, width=canvas_width, height=canvas_height,
                                bg="#f0f0f0", relief=tk.SUNKEN, bd=2)
        self.canvas.pack(pady=(0, 10))
        self.canvas.bind("<Button-1>", self._on_canvas_click)

        info_frame = ttk.LabelFrame(main_frame, text="系统信息", padding=8)
        info_frame.pack(fill=tk.X, pady=(0, 8))

        info_row = ttk.Frame(info_frame)
        info_row.pack(fill=tk.X)
        self.free_small_label = ttk.Label(info_row, text="小型车空位: --")
        self.free_small_label.pack(side=tk.LEFT, padx=(0, 20))
        self.free_large_label = ttk.Label(info_row, text="大型车空位: --")
        self.free_large_label.pack(side=tk.LEFT, padx=(0, 20))
        self.parked_label = ttk.Label(info_row, text="在库车辆: --")
        self.parked_label.pack(side=tk.LEFT)

        log_frame = ttk.LabelFrame(main_frame, text="操作日志", padding=5)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_list = tk.Listbox(log_frame, height=8, font=("Consolas", 9))
        log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self.log_list.yview)
        self.log_list.config(yscrollcommand=log_scroll.set)
        self.log_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.status_bar = ttk.Label(self, text="正在连接服务器...", relief=tk.SUNKEN,
                                    anchor=tk.W, padding=(5, 2))
        self.status_bar.pack(side=tk.BOTTOM, fill=tk.X)

        self._draw_empty_grid()

    def _draw_empty_grid(self):
        self.canvas.delete("all")
        for level in range(NUM_LEVELS):
            display_row = NUM_LEVELS - 1 - level
            y = CANVAS_PADDING + display_row * (SPOT_HEIGHT + SPOT_PADDING) + 20
            label_y = y + SPOT_HEIGHT / 2
            self.canvas.create_text(CANVAS_PADDING - 5, label_y,
                                    text=f"L{level+1}", anchor=tk.E,
                                    font=("Microsoft YaHei", 9, "bold"))
            for pos in range(SPOTS_PER_LEVEL):
                x = CANVAS_PADDING + 15 + pos * (SPOT_WIDTH + SPOT_PADDING)
                color = "#cccccc"
                text = "..."
                self.canvas.create_rectangle(x, y, x + SPOT_WIDTH, y + SPOT_HEIGHT,
                                             fill=color, outline="#999999", width=1)
                self.canvas.create_text(x + SPOT_WIDTH / 2, y + SPOT_HEIGHT / 2,
                                        text=text, font=("Microsoft YaHei", 9))

    def _draw_grid(self):
        self.canvas.delete("all")

        for pos in range(SPOTS_PER_LEVEL):
            x = CANVAS_PADDING + 15 + pos * (SPOT_WIDTH + SPOT_PADDING)
            self.canvas.create_text(x + SPOT_WIDTH / 2, CANVAS_PADDING + 5,
                                    text=f"P{pos+1}", font=("Microsoft YaHei", 8))

        for level in range(NUM_LEVELS):
            display_row = NUM_LEVELS - 1 - level
            y = CANVAS_PADDING + display_row * (SPOT_HEIGHT + SPOT_PADDING) + 20
            self.canvas.create_text(CANVAS_PADDING - 5, y + SPOT_HEIGHT / 2,
                                    text=f"L{level+1}", anchor=tk.E,
                                    font=("Microsoft YaHei", 9, "bold"))

            for pos in range(SPOTS_PER_LEVEL):
                x = CANVAS_PADDING + 15 + pos * (SPOT_WIDTH + SPOT_PADDING)
                spot_info = self._get_spot_info(level, pos)

                if level == 0 and pos == LIFT_COLUMN:
                    color = "#888888"
                    text = "升降口"
                    text_color = "white"
                elif spot_info and spot_info.get("occupied"):
                    color = "#e74c3c"
                    vehicle = spot_info.get("vehicle")
                    if vehicle:
                        plate = vehicle.get("plate", "?")
                        size_ch = "小" if vehicle.get("size", 0) == 0 else "大"
                        text = f"{plate}\n({size_ch})"
                    else:
                        text = "占用"
                    text_color = "white"
                elif spot_info and spot_info.get("reserved"):
                    color = "#f39c12"
                    text = "预留"
                    text_color = "black"
                else:
                    cap = spot_info.get("capacity", 1) if spot_info else 1
                    if cap == 0:
                        color = "#a8e6cf"
                        text = "小型空"
                    else:
                        color = "#55efc4"
                        text = "通用空"
                    text_color = "#2d3436"

                self.canvas.create_rectangle(
                    x, y, x + SPOT_WIDTH, y + SPOT_HEIGHT,
                    fill=color, outline="#2d3436", width=2,
                    tags=f"spot_{level}_{pos}"
                )
                self.canvas.create_text(
                    x + SPOT_WIDTH / 2, y + SPOT_HEIGHT / 2,
                    text=text, fill=text_color,
                    font=("Microsoft YaHei", 8), tags=f"text_{level}_{pos}"
                )

    def _get_spot_info(self, level, pos):
        for s in self.spots_data:
            if s.get("level") == level and s.get("position") == pos:
                return s
        return None

    def _on_canvas_click(self, event):
        if not self.net.connected:
            messagebox.showwarning("提示", "未连接服务器")
            return

        for level in range(NUM_LEVELS):
            display_row = NUM_LEVELS - 1 - level
            y = CANVAS_PADDING + display_row * (SPOT_HEIGHT + SPOT_PADDING) + 20
            for pos in range(SPOTS_PER_LEVEL):
                x = CANVAS_PADDING + 15 + pos * (SPOT_WIDTH + SPOT_PADDING)
                if x <= event.x <= x + SPOT_WIDTH and y <= event.y <= y + SPOT_HEIGHT:
                    self._handle_spot_click(level, pos)
                    return

    def _handle_spot_click(self, level, pos):
        if level == 0 and pos == LIFT_COLUMN:
            return

        spot_info = self._get_spot_info(level, pos)
        if spot_info and spot_info.get("occupied"):
            vehicle = spot_info.get("vehicle")
            if vehicle:
                ticket_id = vehicle.get("id")
                self._initiate_retrieve(ticket_id)
        else:
            self._initiate_park(level, pos, spot_info)

    def _initiate_park(self, level, pos, spot_info):
        cap = spot_info.get("capacity", 1) if spot_info else 1
        cap_text = "小型车位" if cap == 0 else "通用车位"

        dlg = ParkDialog(self, level, pos, cap_text)
        self.wait_window(dlg)

        if dlg.result:
            plate = dlg.result["plate"]
            size = dlg.result["size"]
            seq = self.net.send_command(CMD_PARK_AT, {
                "plate": plate,
                "size": size,
                "level": level,
                "position": pos,
            })
            self.pending_callbacks[seq] = ("park", plate)
            self._log(f"正在存车: {plate} -> L{level+1}P{pos+1}")

    def _initiate_retrieve(self, ticket_id):
        seq = self.net.send_command(CMD_RETRIEVE_BY_TICKET, {"ticket_id": ticket_id})
        self.pending_callbacks[seq] = ("retrieve_info", ticket_id)
        self._log(f"正在查询取车信息: 票号 {ticket_id}")

    def _show_plate_search(self):
        dlg = PlateSearchDialog(self)
        self.wait_window(dlg)

        if dlg.result:
            seq = self.net.send_command(CMD_RETRIEVE_BY_PLATE, {"plate": dlg.result})
            self.pending_callbacks[seq] = ("retrieve_info_plate", dlg.result)
            self._log(f"正在按车牌搜索: {dlg.result}")

    def _request_status(self):
        self.net.send_command(CMD_STATUS)

    def _poll_messages(self):
        while not self.msg_queue.empty():
            try:
                msg = self.msg_queue.get_nowait()
                self._handle_server_msg(msg)
            except queue.Empty:
                break
        self.after(50, self._poll_messages)

    def _poll_status(self):
        while not self.status_queue.empty():
            try:
                status, data = self.status_queue.get_nowait()
                if status == "connected":
                    self.status_bar.config(text=f"已连接 | 服务器: {SERVER_HOST}:{SERVER_PORT}",
                                           foreground="green")
                    self._log("已连接到服务器")
                    self._request_status()
                elif status == "disconnected":
                    wait = f"{data:.1f}" if data else "?"
                    self.status_bar.config(
                        text=f"连接断开 | {wait}秒后重连...",
                        foreground="red"
                    )
                    self._log(f"与服务器断开连接，{wait}秒后重连")
            except queue.Empty:
                break
        self.after(200, self._poll_status)

    def _handle_server_msg(self, msg):
        msg_type = msg.get("type", "")

        if msg_type == "response":
            seq = msg.get("seq", 0)
            ok = msg.get("ok", False)
            data = msg.get("data", {})
            error = msg.get("error")

            callback_info = self.pending_callbacks.pop(seq, None)

            if not ok:
                self._log(f"[错误] {error}")
                messagebox.showerror("操作失败", error or "未知错误")
                return

            if callback_info:
                cb_type = callback_info[0]
                if cb_type == "park":
                    plate = callback_info[1]
                    ticket = data.get("ticket_id")
                    level = data.get("level", 0)
                    pos = data.get("position", 0)
                    steps = data.get("steps", [])
                    self._log(f"[存车成功] {plate} -> L{level+1}P{pos+1} 票号:{ticket}")
                    step_text = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps))
                    messagebox.showinfo("存车成功",
                                        f"车牌: {plate}\n车位: 第{level+1}层 第{pos+1}号\n"
                                        f"票号: {ticket}\n\n动作序列:\n{step_text}")

                elif cb_type in ("retrieve_info", "retrieve_info_plate"):
                    bill = data.get("bill", {})
                    steps = data.get("steps", [])
                    ticket_id = bill.get("ticket_id") or data.get("ticket_id")
                    vehicle_info = {"plate": bill.get("plate", "")}
                    dlg = RetrieveDialog(self, vehicle_info, bill, steps)
                    self.wait_window(dlg)
                    if dlg.result:
                        pay_seq = self.net.send_command(CMD_PAY, {
                            "ticket_id": ticket_id,
                            "method": dlg.result["method"],
                        })
                        self.pending_callbacks[pay_seq] = ("pay", bill.get("plate", ""))

                elif cb_type == "pay":
                    plate = callback_info[1]
                    receipt = data.get("receipt", {})
                    fee = receipt.get("fee", 0)
                    method_names = {"wechat": "微信支付", "alipay": "支付宝", "cash": "现金"}
                    method_text = method_names.get(receipt.get("method", ""), "未知")
                    txn_id = receipt.get("transaction_id", "")
                    self._log(f"[取车完成] {plate} 费用:¥{fee:.2f} {method_text}")
                    messagebox.showinfo("支付成功",
                                        f"车牌: {plate}\n费用: ¥{fee:.2f}\n"
                                        f"方式: {method_text}\n流水号: {txn_id}")
            else:
                if "spots" in data:
                    self._update_display(data)

        elif msg_type == "notify":
            event = msg.get("event", "")
            data = msg.get("data", {})
            if event == EVT_SPOT_UPDATE:
                self._update_display(data)

    def _update_display(self, status_data):
        self.spots_data = status_data.get("spots", [])
        free_small = status_data.get("free_small", 0)
        free_large = status_data.get("free_large", 0)
        total_parked = status_data.get("total_parked", 0)

        self.free_small_label.config(text=f"小型车空位: {free_small}")
        self.free_large_label.config(text=f"大型车空位: {free_large}")
        self.parked_label.config(text=f"在库车辆: {total_parked}")
        self._draw_grid()

    def _log(self, text):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_list.insert(tk.END, f"[{timestamp}] {text}")
        self.log_list.see(tk.END)
        if self.log_list.size() > 200:
            self.log_list.delete(0, 0)

    def _on_close(self):
        self.net.stop()
        self.destroy()


if __name__ == "__main__":
    app = ParkingClient()
    app.mainloop()
