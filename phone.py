#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
שלוחת טלפון בטכנוליין: שואלים את Claude בקול, והתשובה מוקראת בטלפון.

שלוחת API בטכנוליין עם הכתובת:
    https://<השרת>/claude-phone/<PHONE_TOKEN>
(Caddy מעביר את /claude-phone/ לפורט PHONE_PORT.)

מהלך השיחה:
  1. בודקים שהמספר המתקשר נמצא ב-PHONE_ALLOWED.
  2. מקליטים את השאלה (מסיימים בסולמית).
  3. ברקע: מורידים את ההקלטה מטכנוליין, מתמללים בזיהוי הדיבור של ivrit.ai (ההגדרות של שמרטפון),
     ושולחים לשיחה של Claude. בינתיים המתקשר שומע צליל המתנה.
  4. כש-Claude מסיים, ה-Stop hook שומר את התשובה, והיא מוקראת.
  5. 1 = שאלה נוספת (באותה שיחה), 2 = שמיעה חוזרת, 0 = סיום.

כל שיחת טלפון היא שיחה נפרדת של Claude, בשם "📞 <תחילת השאלה>", ומופיעה גם באתר ובדף הניהול.
"""

import base64
import hmac
import json
import re
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import common
import sessions
from common import cfg, state

log = common.get_logger("phone")

PORT = int(cfg("PHONE_PORT", "8091"))
TOKEN = cfg("PHONE_TOKEN", "")
ALLOWED = {re.sub(r"\D", "", p) for p in (cfg("PHONE_ALLOWED", "") or "").split(",") if re.sub(r"\D", "", p)}
SHM_CONFIG = cfg("SHMARTPHONE_CONFIG", "/etc/shmartphone/app.json")
MAX_WAIT = int(cfg("PHONE_MAX_WAIT_SECONDS", "300"))
POLL = int(cfg("PHONE_POLL_SECONDS", "4"))

PHONE_MARK = "[שאלה בטלפון]"
PHONE_NOTE = ("(התשובה תוקרא בקול בטלפון: ענה בקצרה, בעברית מדוברת, במשפטים רגילים, "
              "בלי רשימות, בלי סימנים, בלי קישורים ובלי אימוג'י.)")

T = {
    "not_allowed": "המספר שלכם לא מורשה להשתמש בשירות הזה. להתראות.",
    "hidden": "לא ניתן להשתמש בשירות ממספר חסוי. להתראות.",
    "ask": "שלום. שאלו את Claude את השאלה שלכם אחרי הצליל, ובסיום הקישו סולמית.",
    "ask_more": "שאלו את השאלה הבאה אחרי הצליל, ובסיום הקישו סולמית.",
    "got": "קיבלתי. Claude חושב על התשובה, זה יכול לקחת כחצי דקה עד דקה.",
    "no_audio": "לא נשמעה שאלה. ננסה שוב.",
    "not_heard": "לא הצלחתי להבין את השאלה. ננסה שוב.",
    "error": "הייתה תקלה בהעברת השאלה. ננסה שוב.",
    "too_long": "התשובה מתעכבת. אפשר לראות אותה אחר כך באתר של Claude או בדף הניהול. להתראות.",
    "you_asked": "שאלתם: ",
    "after": "לשאלה נוספת הקישו 1. לשמיעה חוזרת הקישו 2. לסיום הקישו 0.",
    "bye": "להתראות.",
}

# מצב של כל שיחת טלפון, לפי מזהה השיחה בטכנוליין
calls = {}
calls_lock = threading.Lock()


def shm_cfg():
    with open(SHM_CONFIG, encoding="utf-8") as f:
        return json.load(f)


def norm_phone(p):
    d = re.sub(r"\D", "", p or "")
    if d.startswith("972"):
        d = "0" + d[3:]
    return d


# ---------- טכנוליין וזיהוי דיבור ----------
def fetch_recording(shm, file_id):
    url = shm.get("files_url", "https://api.tlivr.com/ivrFilesApi.php")
    data = urllib.parse.urlencode({"action": "fileDownload", "audio": file_id, "apiKey": shm["api_key"]}).encode()
    req = urllib.request.Request(url, data=data, headers={"User-Agent": "curl/8.5.0"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read(30 * 1024 * 1024)
        ctype = resp.headers.get("Content-Type", "")
    if "json" in ctype or body[:1] == b"{":
        raise RuntimeError("download failed: " + body[:200].decode("utf-8", "replace"))
    return body


def _runpod(t, method, path, body=None):
    req = urllib.request.Request(
        f"https://api.runpod.ai/v2/{t['endpoint_id']}/{path}",
        data=json.dumps(body).encode() if body is not None else None, method=method,
        headers={"Authorization": "Bearer " + t["api_key"], "Content-Type": "application/json",
                 "User-Agent": "curl/8.5.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read(5 * 1024 * 1024) or b"{}")


def _segments_text(output):
    parts = []

    def walk(x):
        if isinstance(x, list):
            for v in x:
                walk(v)
        elif isinstance(x, dict):
            if x.get("type") == "segments":
                parts.extend((s.get("text") or "").strip() for s in x.get("data") or [])
            else:
                for v in x.values():
                    walk(v)
    walk(output)
    return " ".join(p for p in parts if p)


def transcribe(shm, audio):
    t = shm.get("transcribe") or {}
    if not t.get("api_key") or not t.get("endpoint_id"):
        raise RuntimeError("זיהוי הדיבור לא מוגדר בשמרטפון (transcribe)")
    job = _runpod(t, "POST", "run", {"input": {
        "engine": "faster-whisper", "model": t.get("model") or "ivrit-ai/whisper-large-v3-turbo-ct2",
        "streaming": False,
        "transcribe_args": {"blob": base64.b64encode(audio).decode(), "language": "he"}}})
    deadline = time.time() + int(t.get("timeout", 180))
    while True:
        status = job.get("status")
        if status == "COMPLETED":
            return _segments_text(job.get("output"))
        if status in ("FAILED", "CANCELLED", "TIMED_OUT"):
            raise RuntimeError(f"transcribe {status}")
        if time.time() >= deadline:
            try:
                _runpod(t, "POST", "cancel/" + job["id"])
            except Exception:
                pass
            raise RuntimeError("transcribe: time limit")
        time.sleep(2)
        job = {**_runpod(t, "GET", "status/" + job["id"]), "id": job["id"]}


# ---------- עבודה ברקע: הקלטה -> טקסט -> Claude ----------
def process_question(call_id, file_id):
    c = calls[call_id]
    try:
        shm = shm_cfg()
        audio = fetch_recording(shm, file_id)
        text = transcribe(shm, audio).strip()
        if not text:
            c["status"] = "not_heard"
            return
        c["question"] = text
        if not c.get("key"):
            short = re.sub(r"\s+", " ", text)[:40].strip()
            c["key"] = f"📞 {time.strftime('%d/%m %H:%M')} {short}"
        key = c["key"]
        with state() as st:
            st["pending"].setdefault(key, []).append({"phone": call_id, "time": time.time()})
            st.setdefault("phone_answers", {}).pop(call_id, None)
        sessions.get_or_create_thread(key, title=key)
        sessions.send(key, f"{PHONE_MARK}\n{text}\n\n{PHONE_NOTE}")
        log.info("שאלה בטלפון נשלחה לשיחה '%s'", key)
        c["status"] = "thinking"
    except Exception:
        log.exception("תקלה בטיפול בשאלה בטלפון")
        c["status"] = "error"


def speakable(text, limit=1800):
    """מנקה סימני עיצוב, כדי שההקראה תישמע טבעית."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"[*_#`>|~]", " ", text)
    text = re.sub(r"^\s*[-•]\s*", "", text, flags=re.M)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + ". התשובה ארוכה, ואפשר לקרוא את ההמשך באתר."
    return text


def chunks(text, size=350):
    """מחלק טקסט ארוך לכמה קטעים להקראה, בסוף משפט כשאפשר."""
    out = []
    while len(text) > size:
        cut = max(text.rfind(". ", 0, size), text.rfind("? ", 0, size), text.rfind(", ", 0, size))
        cut = cut + 1 if cut > size // 3 else size
        out.append(text[:cut].strip())
        text = text[cut:].strip()
    if text:
        out.append(text)
    return out


# ---------- תגובות לטכנוליין ----------
def files(*texts):
    return [{"text": t} for t in texts if t]


def say(*texts):
    return {"type": "simpleMessage", "files": files(*texts)}


def hangup(*texts):
    return ([say(*texts)] if any(texts) else []) + [{"type": "hangup"}]


def record(call_id, prompt):
    c = calls[call_id]
    c["step"] = "record"
    c["n"] = c.get("n", 0) + 1
    name = "cq_" + re.sub(r"[^A-Za-z0-9_-]", "", call_id)[-30:] + f"_{c['n']}"
    return [{"type": "record", "name": "q", "max": 120, "min": 1, "confirm": "no",
             "fileName": name, "files": files(prompt)}]


def wait(call_id, text=None):
    c = calls[call_id]
    c["step"] = "wait"
    beep = None
    try:
        beep = {"fileLink": shm_cfg()["public_url"].rstrip("/") + "/beep.wav",
                "fileName": "shmartphone_beep_v1"}
    except Exception:
        pass
    f = files(text) if text else ([beep] if beep else files("רגע"))
    return [{"type": "simpleMenu", "name": "w", "enabledKeys": "0", "times": 1,
             "timeout": POLL, "errorReturn": "WAIT", "files": f}]


def answer_menu(call_id):
    c = calls[call_id]
    c["step"] = "menu"
    parts = []
    if not c.get("played"):
        parts.append(T["you_asked"] + c.get("question", ""))
    parts += chunks(speakable(c.get("answer", "")))
    c["played"] = True
    return [{"type": "simpleMenu", "name": "m", "enabledKeys": "0,1,2", "times": 1, "timeout": 10,
             "errorReturn": "NONE", "files": files(*parts, T["after"])}]


def handle(p):
    call_id = p.get("PBXcallId", "")
    if p.get("PBXcallStatus") == "HANGUP":
        with calls_lock:
            calls.pop(call_id, None)
        return []
    phone = norm_phone(p.get("PBXphone", ""))
    if not phone or len(phone) < 9:
        return hangup(T["hidden"])
    if phone not in ALLOWED:
        log.info("שיחה ממספר לא מורשה: %s", phone[:3] + "***" + phone[-3:])
        return hangup(T["not_allowed"])

    with calls_lock:
        c = calls.setdefault(call_id, {"step": None, "since": time.time()})
    step = c.get("step")

    if step == "record" and "q" in p:
        file_id = p.get("FILEID_q")
        if not file_id:
            return record(call_id, T["no_audio"] + " " + T["ask_more"])
        c.update(status="transcribing", since=time.time(), answer=None, played=False)
        threading.Thread(target=process_question, args=(call_id, file_id), daemon=True).start()
        return wait(call_id, T["got"])

    if step == "wait" and "w" in p:
        if p["w"] == "0":
            return hangup(T["bye"])
        status = c.get("status")
        if status in ("not_heard", "error"):
            return record(call_id, T[status] + " " + T["ask_more"])
        if status == "thinking":
            with state() as st:
                ans = st.setdefault("phone_answers", {}).pop(call_id, None)
            if ans:
                c.update(answer=ans, status="answered")
                return answer_menu(call_id)
        if time.time() - c.get("since", time.time()) > MAX_WAIT:
            return hangup(T["too_long"])
        return wait(call_id)

    if step == "menu" and "m" in p:
        key = p["m"]
        if key == "1":
            return record(call_id, T["ask_more"])
        if key == "2":
            c["played"] = False
            return answer_menu(call_id)
        return hangup(T["bye"])

    return record(call_id, T["ask"])


class Handler(BaseHTTPRequestHandler):
    server_version = "claude-phone"
    sys_version = ""

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        self.route()

    def do_POST(self):
        self.route()

    def route(self):
        try:
            url = urllib.parse.urlsplit(self.path)
            parts = [x for x in url.path.split("/") if x]
            if not TOKEN or len(parts) != 1 or not hmac.compare_digest(parts[0], TOKEN):
                return self.reply(404, b"not found", "text/plain")
            params = {k: v[-1] for k, v in urllib.parse.parse_qs(url.query, keep_blank_values=True).items()}
            if self.command == "POST":
                n = min(int(self.headers.get("Content-Length") or 0), 1024 * 1024)
                body = self.rfile.read(n).decode("utf-8", "replace")
                params.update({k: v[-1] for k, v in urllib.parse.parse_qs(body, keep_blank_values=True).items()})
            resp = handle(params)
            self.reply(200, json.dumps(resp, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")
        except Exception:
            log.exception("תקלה בשלוחת הטלפון")
            self.reply(200, json.dumps(hangup(T["error"].split(".")[0] + ". להתראות.")).encode(),
                       "application/json")

    def reply(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    if not TOKEN:
        raise SystemExit("חסרה הגדרה בקובץ .env: PHONE_TOKEN")
    log.info("שלוחת הטלפון עולה על פורט %s | מספרים מורשים: %d", PORT, len(ALLOWED))
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
