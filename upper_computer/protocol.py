"""智能立体车库上位机 - 通信协议"""

import json
import struct
import socket
from typing import Optional, Dict, Any

HEADER_SIZE = 4
HEADER_FORMAT = ">I"

CMD_STATUS = "status"
CMD_PARK = "park"
CMD_PARK_AT = "park_at"
CMD_RETRIEVE_BY_TICKET = "retrieve_by_ticket"
CMD_RETRIEVE_BY_PLATE = "retrieve_by_plate"
CMD_PAY = "pay"
CMD_QUERY_FEE = "query_fee"
CMD_HEARTBEAT = "heartbeat"

EVT_SPOT_UPDATE = "spot_update"


def send_message(sock: socket.socket, msg: Dict[str, Any]) -> bool:
    try:
        payload = json.dumps(msg, ensure_ascii=False).encode("utf-8")
        header = struct.pack(HEADER_FORMAT, len(payload))
        sock.sendall(header + payload)
        return True
    except (OSError, BrokenPipeError):
        return False


def recv_message(sock: socket.socket) -> Optional[Dict[str, Any]]:
    try:
        header_data = _recv_exact(sock, HEADER_SIZE)
        if header_data is None:
            return None
        length = struct.unpack(HEADER_FORMAT, header_data)[0]
        if length > 1024 * 1024:
            return None
        payload_data = _recv_exact(sock, length)
        if payload_data is None:
            return None
        return json.loads(payload_data.decode("utf-8"))
    except (OSError, json.JSONDecodeError, struct.error):
        return None


def _recv_exact(sock: socket.socket, n: int) -> Optional[bytes]:
    data = bytearray()
    while len(data) < n:
        chunk = sock.recv(n - len(data))
        if not chunk:
            return None
        data.extend(chunk)
    return bytes(data)


def make_request(cmd: str, seq: int, data: Dict[str, Any] = None) -> Dict[str, Any]:
    return {"cmd": cmd, "seq": seq, "data": data or {}}


def make_response(seq: int, ok: bool, data: Dict[str, Any] = None, error: str = None) -> Dict[str, Any]:
    return {"type": "response", "seq": seq, "ok": ok, "data": data or {}, "error": error}


def make_notify(event: str, data: Dict[str, Any] = None) -> Dict[str, Any]:
    return {"type": "notify", "event": event, "data": data or {}}
