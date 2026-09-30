"""Telegram listener: watches for /start, triggers the produce workflow."""
import json, os, subprocess, urllib.request

API = f"https://api.telegram.org/bot{os.environ['TELEGRAM_BOT_TOKEN']}"
CHAT_ID = str(os.environ["TELEGRAM_CHAT_ID"])
OFFSET_FILE = "memory/tg_offset.txt"

def tg(method, **params):
    req = urllib.request.Request(f"{API}/{method}",
        data=json.dumps(params).encode(), headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=60).read())

def main():
    offset = 0
    try:
        offset = int(open(OFFSET_FILE).read().strip())
    except Exception:
        pass
    try:
        res = tg("getUpdates", offset=offset, timeout=0, allowed_updates=["message"])
    except Exception as e:
        print(f"[listen] getUpdates error (ignoring this round): {e}")
        return
    updates = res.get("result", [])
    if not updates:
        print("[listen] nothing new")
        return
    trigger = False
    new_offset = offset
    for u in updates:
        new_offset = max(new_offset, u["update_id"] + 1)
        msg = u.get("message") or {}
        if str(msg.get("chat", {}).get("id")) == CHAT_ID:
            text = (msg.get("text") or "").strip()
            if text.startswith("/start"):
                trigger = True
    os.makedirs("memory", exist_ok=True)
    open(OFFSET_FILE, "w").write(str(new_offset))
    if trigger:
        print("[listen] /start received — dispatching produce workflow")
        subprocess.run(["gh", "workflow", "run", "produce.yml", "--ref", "main"],
                       check=True, env=os.environ)
        print("[listen] dispatched")
    else:
        print("[listen] updates seen, no /start")

main()
