"""Minimal OsEngine MCP v2 HTTP client for one-off calls."""
import json
import sys
import urllib.request

URL = "http://localhost:6500/api/v2/mcp"
KEY = "osengine-mcp-default-key"
BASE = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "X-Api-Key": KEY,
    "MCP-Protocol-Version": "2024-11-05",
}


class Client:
    def __init__(self):
        self.sid = None
        self.i = 0
        self.call("initialize", {"protocolVersion": "2024-11-05",
                                 "capabilities": {},
                                 "clientInfo": {"name": "algo-sandbox", "version": "1.0"}},
                  notify=False)

    def call(self, method, params=None, notify=False):
        self.i += 1
        body = {"jsonrpc": "2.0", "method": method}
        if not notify:
            body["id"] = self.i
        if params is not None:
            body["params"] = params
        h = dict(BASE)
        if self.sid:
            h["Mcp-Session-Id"] = self.sid
        req = urllib.request.Request(URL, data=json.dumps(body).encode(), headers=h)
        with urllib.request.urlopen(req, timeout=180) as r:
            if not self.sid:
                self.sid = r.headers.get("Mcp-Session-Id")
            raw = r.read().decode()
        if notify or not raw.strip():
            return None
        return json.loads(raw)

    def tool(self, name, args=None):
        r = self.call("tools/call", {"name": name, "arguments": args or {}})
        if "error" in r:
            raise RuntimeError(f"{name}: {r['error']}")
        content = r.get("result", {}).get("content", [])
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        joined = "\n".join(texts)
        try:
            return json.loads(joined)
        except Exception:
            return joined


if __name__ == "__main__":
    name = sys.argv[1]
    args = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    c = Client()
    print(json.dumps(c.tool(name, args), ensure_ascii=False, indent=1))
