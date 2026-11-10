#!/usr/bin/env python3
"""펜션 영업 행사지도 로컬 서버 (파이썬 표준 라이브러리만 사용)

실행:  python3 serve.py          (포트 바꾸려면: python3 serve.py 9000)
노트북:  http://localhost:8080
휴대폰:  노트북과 같은 와이파이에서 실행 시 출력되는 http://<노트북IP>:8080

메모는 이 폴더의 memos.json 하나에 저장되고, 노트북·휴대폰이 같은 파일을 함께 씁니다.
같은 와이파이에 있는 누구나 접속할 수 있으니 카페 같은 공용 와이파이에서는 켜 두지 마세요.
"""
import http.server
import json
import os
import socket
import sys
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
MEMO_FILE = os.path.join(ROOT, "memos.json")
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
MAX_BODY = 5 * 1024 * 1024
LOCK = threading.Lock()


def empty():
    return {"items": {}, "note": {"t": "", "u": 0}}


def load():
    try:
        with open(MEMO_FILE, encoding="utf-8") as f:
            data = json.load(f)
        data.setdefault("items", {})
        data.setdefault("note", {"t": "", "u": 0})
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return empty()


def merge(base, incoming):
    """항목별로 더 나중에 수정된(u가 큰) 쪽을 남긴다."""
    for key, val in (incoming.get("items") or {}).items():
        if not isinstance(val, dict):
            continue
        if val.get("u", 0) > base["items"].get(key, {}).get("u", 0):
            base["items"][key] = val
    note = incoming.get("note") or {}
    if isinstance(note, dict) and note.get("u", 0) > base["note"].get("u", 0):
        base["note"] = note
    return base


def save(data):
    tmp = MEMO_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, MEMO_FILE)


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.split("?")[0] == "/api/memos":
            with LOCK:
                return self.send_json(load())
        return super().do_GET()

    def do_PUT(self):
        if self.path.split("?")[0] != "/api/memos":
            return self.send_json({"error": "not found"}, 404)
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self.send_json({"error": "bad size"}, 400)
        try:
            incoming = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return self.send_json({"error": "bad json"}, 400)
        with LOCK:
            data = merge(load(), incoming)
            save(data)
        return self.send_json(data)

    def log_message(self, fmt, *args):
        if args and "/api/" in str(args[0]):
            return
        if args and "favicon" in str(args[0]):
            return
        super().log_message(fmt, *args)


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))  # 실제로 패킷을 보내지 않음
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


if __name__ == "__main__":
    server = http.server.ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print("펜션 영업 행사지도 실행 중")
    print(f"  노트북: http://localhost:{PORT}")
    print(f"  휴대폰: http://{lan_ip()}:{PORT}  (같은 와이파이)")
    print(f"  메모 파일: {MEMO_FILE}")
    print("  종료: Ctrl+C")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료했습니다.")
