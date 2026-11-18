#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בוט מייל ל-Claude דרך המנוי (Claude Code + Remote Control)
----------------------------------------------------------
- בודק את המייל כל דקה.
- לכל נושא מייל יש שיחה משלו, עם אותו שם, באתר claude.ai/code ובאפליקציה.
- מייל חדש עם אותו נושא ממשיך את אותה שיחה.
- התשובה נשלחת חזרה במייל על ידי stop_hook.py כש-Claude מסיים לענות.
"""

import email
import email.utils
import hashlib
import imaplib
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from email.header import decode_header, make_header

import common
from common import cfg, state

log = common.get_logger("bot")


# ---------- עזרי מייל ----------
def decode_str(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


def html_to_text(html):
    html = re.sub(r"(?is)<(script|style).*?</\1>", "", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>", "\n", html)
    html = re.sub(r"<[^>]+>", "", html)
    return re.sub(r"\n{3,}", "\n\n", html).strip()


def get_body(msg):
    plain, html = None, None
    for part in (msg.walk() if msg.is_multipart() else [msg]):
        if part.get_content_disposition() == "attachment":
            continue
        ctype = part.get_content_type()
        if ctype not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            text = payload.decode(charset, errors="replace")
        except LookupError:
            text = payload.decode("utf-8", errors="replace")
        if ctype == "text/plain" and plain is None:
            plain = text
        elif ctype == "text/html" and html is None:
            html = text
    return (plain or (html_to_text(html) if html else "")).strip()


QUOTE_MARKERS = [
    r"^On .+wrote:\s*$",
    r"^ב.+כתב/?ה?:\s*$",
    r"^בתאריך .+",
    r"^-+\s*Original Message\s*-+",
    r"^-+\s*הודעה מקורית\s*-+",
    r"^From: ",
    r"^מאת: ",
]


def only_new_text(body):
    """משאיר רק את מה שנכתב עכשיו, בלי ההתכתבות המצוטטת (היא כבר בשיחה)."""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith(">") or any(re.match(m, s) for m in QUOTE_MARKERS):
            return "\n".join(lines[:i]).strip()
    return body.strip()


def thread_key(subject):
    """נושא בלי Re:/Fwd:/השב: - כך שכל השרשור מקבל אותו מפתח."""
    s = subject.strip()
    while True:
        new = re.sub(r"^\s*(re|fw|fwd|השב|העבר)\s*:\s*", "", s, flags=re.I)
        if new == s:
            break
        s = new
    return s.strip() or "(ללא נושא)"


# ---------- tmux + Claude ----------
def tmux(*args, check=True):
    return subprocess.run(["tmux", *args], capture_output=True, text=True, check=check)


def tmux_alive(name):
    return tmux("has-session", "-t", name, check=False).returncode == 0


def start_session(key, thread):
    """פותח (או מחזיר לחיים) שיחה עם Remote Control, בשם של נושא המייל."""
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


def send_to_claude(name, text):
    """מדביק את השאלה בחלון של Claude ולוחץ Enter."""
    with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as f:
        f.write(text)
        path = f.name
    try:
        tmux("load-buffer", "-b", "emailq", path)
        tmux("paste-buffer", "-p", "-d", "-b", "emailq", "-t", name)
        time.sleep(1.5)
        tmux("send-keys", "-t", name, "Enter")
    finally:
        os.unlink(path)


# ---------- בדיקת התיבה ----------
def handle_message(msg):
    sender = email.utils.parseaddr(msg.get("From", ""))[1].lower()
    subject = decode_str(msg.get("Subject", ""))
    key = thread_key(subject)
    question = only_new_text(get_body(msg)) or subject
    log.info("שאלה חדשה מ-%s, נושא: %s", sender, subject)

    with state() as st:
        thread = st["threads"].get(key)
        if not thread:
            h = hashlib.md5(key.encode("utf-8")).hexdigest()[:8]
            thread = {"tmux": f"mail-{h}", "title": f"📧 {key}", "session_id": None}
            st["threads"][key] = thread
        st["pending"].setdefault(key, []).append({
            "to": sender,
            "subject": subject,
            "message_id": msg.get("Message-ID"),
            "references": msg.get("References", ""),
            "time": time.time(),
        })

    if not tmux_alive(thread["tmux"]):
        start_session(key, thread)
    send_to_claude(thread["tmux"], f"[שאלה שהגיעה במייל]\n{question}")
    log.info("השאלה נשלחה לשיחה '%s'", thread["title"])


def check_inbox():
    imap = imaplib.IMAP4_SSL(common.IMAP_HOST)
    try:
        imap.login(common.EMAIL_ADDRESS, common.EMAIL_PASSWORD)
        imap.select("INBOX")
        typ, data = imap.uid("search", None, "UNSEEN")
        if typ != "OK":
            return
        for uid in data[0].split():
            # PEEK = בלי לסמן כנקרא, כדי לא לגעת במיילים שלא שייכים לבוט
            typ, msg_data = imap.uid("fetch", uid, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            if msg.get("X-Email-Claude-Bot"):
                continue
            sender = email.utils.parseaddr(msg.get("From", ""))[1].lower()
            if sender not in common.ALLOWED_SENDERS:
                continue
            if common.SUBJECT_TAG and common.SUBJECT_TAG not in decode_str(msg.get("Subject", "")):
                continue
            imap.uid("store", uid, "+FLAGS", "(\\Seen)")
            try:
                handle_message(msg)
            except Exception as e:
                log.exception("תקלה בטיפול במייל")
                try:
                    common.send_email(sender, decode_str(msg.get("Subject", "")),
                                      f"הייתה תקלה בהעברת השאלה ל-Claude: {e}",
                                      msg.get("Message-ID"), msg.get("References", ""))
                except Exception:
                    log.exception("גם שליחת הודעת התקלה נכשלה")
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def main():
    log.info("הבוט התחיל. תיבה: %s | מורשים: %s | מילה בנושא: %s",
             common.EMAIL_ADDRESS, ", ".join(common.ALLOWED_SENDERS),
             common.SUBJECT_TAG or "(כל מייל)")
    once = "--once" in sys.argv
    while True:
        try:
            check_inbox()
        except Exception:
            log.exception("שגיאה בבדיקת המייל")
        if once:
            break
        time.sleep(common.CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
