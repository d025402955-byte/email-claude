# -*- coding: utf-8 -*-
"""הגדרות ופונקציות משותפות לבוט ול-hook."""

import contextlib
import email.utils
import fcntl
import json
import logging
import os
import smtplib
import ssl
import sys
from email.mime.text import MIMEText

HERE = os.path.dirname(os.path.abspath(__file__))
WORK_DIR = os.path.join(HERE, "work")
STATE_FILE = os.path.join(HERE, "state.json")
LOCK_FILE = os.path.join(HERE, "state.lock")


def load_env(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


load_env(os.path.join(HERE, ".env"))


def cfg(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and not val:
        sys.exit(f"חסרה הגדרה בקובץ .env: {name}")
    return val


EMAIL_ADDRESS = cfg("EMAIL_ADDRESS", required=True)
EMAIL_PASSWORD = cfg("EMAIL_APP_PASSWORD", required=True)
IMAP_HOST = cfg("IMAP_HOST", "imap.gmail.com")
SMTP_HOST = cfg("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(cfg("SMTP_PORT", "465"))
ALLOWED_SENDERS = [
    s.strip().lower()
    for s in (cfg("ALLOWED_SENDERS", "") or EMAIL_ADDRESS).split(",")
    if s.strip()
]
SUBJECT_TAG = (cfg("SUBJECT_TAG", "שאלה") or "").strip()
CHECK_EVERY_SECONDS = int(cfg("CHECK_EVERY_SECONDS", "60"))
CLAUDE_BIN = cfg("CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))


def get_logger(name):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(os.path.join(HERE, "bot.log"), encoding="utf-8"),
        ],
    )
    return logging.getLogger(name)


# ---------- מצב: איזה נושא שייך לאיזו שיחה, ואילו תשובות ממתינות ----------
@contextlib.contextmanager
def state():
    """פותח את קובץ המצב עם נעילה, ושומר אותו בסוף."""
    with open(LOCK_FILE, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = {"threads": {}, "pending": {}}
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, encoding="utf-8") as f:
                data = json.load(f)
        data.setdefault("threads", {})
        data.setdefault("pending", {})
        yield data
        tmp = STATE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, STATE_FILE)


# ---------- שליחת מייל ----------
def send_email(to_addr, subject, body, in_reply_to=None, references=None):
    if not subject.lower().startswith(("re:", "השב:")):
        subject = "Re: " + subject
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid()
    msg["X-Email-Claude-Bot"] = "1"  # כדי שהבוט לא יענה לעצמו
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = ((references or "") + " " + in_reply_to).strip()
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=60) as s:
        s.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        s.send_message(msg)
