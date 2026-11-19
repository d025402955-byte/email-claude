# -*- coding: utf-8 -*-
"""ניהול השיחות של Claude (ב-tmux) - משותף לבוט המייל ולדף הניהול."""

import glob
import hashlib
import json
import os
import shlex
import subprocess
import tempfile
import threading
import time

import common
from common import cfg, state

log = common.get_logger("sessions")
_lock = threading.Lock()

EMAIL_MARK = "[שאלה שהגיעה במייל]"
WEB_MARK = "[הודעה מדף הניהול]"
PHONE_MARK = "[שאלה בטלפון]"


def tmux(*args, check=True):
    return subprocess.run(["tmux", *args], capture_output=True, text=True, check=check)


def tmux_alive(name):
    return tmux("has-session", "-t", name, check=False).returncode == 0


def get_or_create_thread(key, title=None):
    """מחזיר את פרטי השיחה של נושא מסוים, ויוצר רשומה אם אין."""
    with state() as st:
        thread = st["threads"].get(key)
        if not thread:
            h = hashlib.md5(key.encode("utf-8")).hexdigest()[:8]
            thread = {"tmux": f"mail-{h}", "title": title or f"📧 {key}", "session_id": None,
                      "created": time.time()}
            st["threads"][key] = thread
        return dict(thread)


def start_session(key, thread):
    """פותח (או מחזיר לחיים) שיחה עם Remote Control, בשם של הנושא."""
    name = thread["tmux"]
    cmd = [common.CLAUDE_BIN]
    if thread.get("session_id"):
        cmd += ["--resume", thread["session_id"]]
    cmd += ["--remote-control", thread["title"]]
    log.info("פותח שיחה '%s' (tmux: %s)", thread["title"], name)
    tmux(
        "new-session", "-d", "-s", name, "-x", "200", "-y", "50",
        "-e", f"EMAIL_THREAD={key}",
        "-c", common.WORK_DIR,
        " ".join(shlex.quote(c) for c in cmd),
    )
    time.sleep(int(cfg("STARTUP_WAIT_SECONDS", "15")))
    if not tmux_alive(name):
        raise RuntimeError("Claude Code לא עלה. הרץ ידנית: claude בתיקייה work ובדוק שאתה מחובר")


def _paste(name, text):
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
        f.write(text)
        path = f.name
    try:
        buf = "q" + str(os.getpid())
        tmux("load-buffer", "-b", buf, path)
        tmux("paste-buffer", "-p", "-d", "-b", buf, "-t", name)
        time.sleep(1.5)
        tmux("send-keys", "-t", name, "Enter")
    finally:
        os.unlink(path)


def send(key, text):
    """שולח הודעה לשיחה (פותח אותה אם היא סגורה)."""
    with _lock:
        thread = get_or_create_thread(key)
        if not tmux_alive(thread["tmux"]):
            start_session(key, thread)
        _paste(thread["tmux"], text)
    with state() as st:
        st["threads"][key]["updated"] = time.time()


def close(key):
    with state() as st:
        thread = st["threads"].get(key)
    if thread and tmux_alive(thread["tmux"]):
        tmux("kill-session", "-t", thread["tmux"], check=False)


# ---------- קריאת השיחה מהקובץ ש-Claude Code שומר ----------
def transcript_path(session_id):
    if not session_id:
        return None
    home = os.path.expanduser("~/.claude/projects")
    found = glob.glob(os.path.join(home, "*", f"{session_id}.jsonl"))
    return found[0] if found else None


def _text_of(content):
    if isinstance(content, str):
        return content
    parts = []
    for c in content or []:
        if isinstance(c, dict) and c.get("type") == "text":
            parts.append(c.get("text", ""))
    return "\n".join(parts)


def read_messages(session_id, limit=200):
    """מחזיר רשימת הודעות: [{role, text, source}]"""
    path = transcript_path(session_id)
    if not path:
        return []
    msgs = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            kind = item.get("type")
            if kind not in ("user", "assistant") or item.get("isSidechain"):
                continue
            message = item.get("message") or {}
            text = _text_of(message.get("content")).strip()
            if not text or text.startswith("<"):  # פקודות פנימיות
                continue
            source = "site"
            if kind == "user":
                if text.startswith(EMAIL_MARK):
                    source, text = "email", text[len(EMAIL_MARK):].strip()
                elif text.startswith(WEB_MARK):
                    source, text = "admin", text[len(WEB_MARK):].strip()
                elif text.startswith(PHONE_MARK):
                    source = "phone"
                    text = text[len(PHONE_MARK):].split(chr(10) * 2 + "(התשובה תוקרא")[0].strip()
            # תשובה אחת של Claude יכולה להתפצל לכמה שורות - מאחדים
            if kind == "assistant" and msgs and msgs[-1]["role"] == "assistant":
                msgs[-1]["text"] += "\n\n" + text
                continue
            msgs.append({"role": kind, "text": text, "source": source,
                         "time": item.get("timestamp", "")})
    return msgs[-limit:]
