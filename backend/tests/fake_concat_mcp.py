"""Servidor MCP falso que imita o `concat --mcp headless` (usado quando o Concat não está instalado).

Registra cada chamada em $FAKE_CONCAT_LOG e cria a pasta do projeto como o Concat faria.
"""
import json
import os
import sys
from pathlib import Path

log_path = os.environ.get("FAKE_CONCAT_LOG")
projects: dict[str, dict] = {}


def reply(rid, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": rid, "result": result}) + "\n")
    sys.stdout.flush()


def tool_result(data, error=False):
    return {"content": [{"type": "text", "text": json.dumps(data)}], "isError": error, "structuredContent": data}


for line in sys.stdin:
    msg = json.loads(line)
    if "id" not in msg:
        continue
    method, params = msg["method"], msg.get("params", {})
    if method == "initialize":
        reply(msg["id"], {"protocolVersion": params["protocolVersion"], "capabilities": {"tools": {}},
                          "serverInfo": {"name": "fake-concat", "version": "0"}})
        continue
    if method != "tools/call":
        reply(msg["id"], {})
        continue
    name, args = params["name"], params["arguments"]
    if log_path:
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"tool": name, "args": args}) + "\n")
    if name == "concat_version":
        reply(msg["id"], tool_result({"version": "fake", "mcp": {"mode": "headless"}}))
    elif name == "project_create":
        d = Path(args["location"]) / args["name"]
        if d.exists():
            reply(msg["id"], tool_result({"message": "folder holds a project"}, error=True))
            continue
        d.mkdir(parents=True)
        (d / "project.concat").write_text("{}")
        projects[str(d)] = {"media": [], "captions": []}
        reply(msg["id"], tool_result({"path": str(d)}))
    elif name == "media_import":
        if not Path(args["file"]).is_file():
            reply(msg["id"], tool_result({"message": "no such file"}, error=True))
            continue
        projects[args["path"]]["media"].append(args["file"])
        reply(msg["id"], tool_result({"createdId": "m1"}))
    elif name == "captions_add":
        bad = [c for c in args["captions"] if c["end"] <= c["start"]]
        reply(msg["id"], tool_result({"message": "end before start"} if bad else {"createdId": "c9"}, error=bool(bad)))
    else:
        reply(msg["id"], tool_result({"ok": True}))
