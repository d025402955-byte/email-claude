#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
בוט מייל ל-Claude
------------------
בודק את תיבת המייל כל דקה. כשמגיע מייל חדש מכתובת מורשית
(ואם הוגדר - עם מילת מפתח בנושא), שולח את השאלה ל-Claude
ועונה באותו שרשור מייל.

משתמש רק בספריות שמגיעות עם פייתון - אין צורך להתקין כלום.
ההגדרות נקראות מהקובץ .env שליד הסקריפט.
"""

import email
import email.utils
import imaplib
import json
import logging
import os
import re
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.request
from email.header import decode_header, make_header
from email.mime.text import MIMEText

HERE = os.path.dirname(os.path.abspath(__file__))


# ---------- קריאת הגדרות ----------
def load_env(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            val = val.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), val)


load_env(os.path.join(HERE, ".env"))


def cfg(name, default=None, required=False):
    val = os.environ.get(name, default)
    if required and not val:
        sys.exit(f"חסרה הגדרה בקובץ .env: {name}")
    return val


EMAIL_ADDRESS = cfg("EMAIL_ADDRESS", required=True)
EMAIL_PASSWORD = cfg("EMAIL_APP_PASSWORD", required=True)
ANTHROPIC_API_KEY = cfg("ANTHROPIC_API_KEY", required=True)
IMAP_HOST = cfg("IMAP_HOST", "imap.gmail.com")
SMTP_HOST = cfg("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(cfg("SMTP_PORT", "465"))
# כתובות שמותר להן לשאול (מופרדות בפסיק). ברירת מחדל: הכתובת שלך בלבד
ALLOWED_SENDERS = [
    s.strip().lower()
    for s in cfg("ALLOWED_SENDERS", EMAIL_ADDRESS).split(",")
    if s.strip()
]
# מילה שחייבת להופיע בנושא המייל (ריק = כל מייל מכתובת מורשית)
SUBJECT_TAG = cfg("SUBJECT_TAG", "שאלה").strip()
MODEL = cfg("MODEL", "claude-sonnet-5-5")
MAX_TOKENS = int(cfg("MAX_TOKENS", "2000"))
CHECK_EVERY_SECONDS = int(cfg("CHECK_EVERY_SECONDS", "60"))
SYSTEM_PROMPT = cfg(
    "SYSTEM_PROMPT",
    "אתה עוזר שעונה על שאלות שמגיעות במייל. ענה תמיד בעברית, "
    "בצורה ברורה ומסודרת, בטקסט רגיל בלי סימני עיצוב מיוחדים.",
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(HERE, "bot.log"), encoding="utf-8"),
    ],
)
log = logging.getLogger("email-bot")


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
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
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
    if plain:
        return plain.strip()
    if html:
        return html_to_text(html)
    return ""


def split_new_and_quoted(body):
    """מפריד בין מה שכתבת עכשיו לבין ההיסטוריה המצוטטת של השרשור."""
    markers = [
        r"^On .+wrote:\s*$",
        r"^ב.+כתב/?ה?:\s*$",
        r"^בתאריך .+",
        r"^-+\s*Original Message\s*-+",
        r"^-+\s*הודעה מקורית\s*-+",
        r"^From: ",
        r"^מאת: ",
    ]
    lines = body.splitlines()
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith(">") or any(re.match(m, s) for m in markers):
            new = "\n".join(lines[:i]).strip()
            old = "\n".join(lines[i:]).strip()
            return new, old
    return body.strip(), ""


# ---------- פנייה ל-Claude ----------
def ask_claude(question, history=""):
    content = question
    if history:
        content = (
            "זו המשך שיחה במייל. ההתכתבות הקודמת (לצורך הקשר):\n"
            f"{history[:15000]}\n\n"
            f"ההודעה החדשה שלי:\n{question}"
        )
    data = json.dumps(
        {
            "model": MODEL,
            "max_tokens": MAX_TOKENS,
            "system": SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": content}],
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=data,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        result = json.loads(r.read().decode("utf-8"))
    return "".join(
        b.get("text", "") for b in result.get("content", []) if b.get("type") == "text"
    ).strip()


# ---------- שליחת תשובה ----------
def send_reply(original, to_addr, answer):
    subject = decode_str(original.get("Subject", ""))
    if not subject.lower().startswith(("re:", "השב:")):
        subject = "Re: " + subject
    msg = MIMEText(answer, "plain", "utf-8")
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Date"] = email.utils.formatdate(localtime=True)
    msg["Message-ID"] = email.utils.make_msgid()
    msg["X-Email-Claude-Bot"] = "1"  # סימון כדי שהבוט לא יענה לעצמו
    orig_id = original.get("Message-ID")
    if orig_id:
        msg["In-Reply-To"] = orig_id
        refs = original.get("References", "")
        msg["References"] = (refs + " " + orig_id).strip()
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx, timeout=60) as s:
        s.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        s.send_message(msg)


# ---------- בדיקת התיבה ----------
def check_inbox():
    imap = imaplib.IMAP4_SSL(IMAP_HOST)
    try:
        imap.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        imap.select("INBOX")
        typ, data = imap.uid("search", None, "UNSEEN")
        if typ != "OK":
            return
        uids = data[0].split()
        for uid in uids:
            # PEEK = קורא בלי לסמן כנקרא, כדי לא לגעת במיילים שלא שייכים לבוט
            typ, msg_data = imap.uid("fetch", uid, "(BODY.PEEK[])")
            if typ != "OK" or not msg_data or not msg_data[0]:
                continue
            msg = email.message_from_bytes(msg_data[0][1])

            if msg.get("X-Email-Claude-Bot"):
                continue
            sender = email.utils.parseaddr(msg.get("From", ""))[1].lower()
            if sender not in ALLOWED_SENDERS:
                continue
            subject = decode_str(msg.get("Subject", ""))
            if SUBJECT_TAG and SUBJECT_TAG not in subject:
                continue

            body = get_body(msg)
            question, history = split_new_and_quoted(body)
            if not question:
                question = subject

            log.info("שאלה חדשה מ-%s, נושא: %s", sender, subject)
            # מסמן כנקרא מיד, כדי שלא תישלח תשובה כפולה אם יש תקלה באמצע
            imap.uid("store", uid, "+FLAGS", "(\\Seen)")
            try:
                answer = ask_claude(question, history)
                if not answer:
                    answer = "לא התקבלה תשובה מ-Claude. נסה לשלוח שוב."
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", errors="replace")[:500]
                log.error("שגיאה מ-Claude: %s %s", e.code, detail)
                answer = f"הייתה תקלה בפנייה ל-Claude (קוד {e.code}). נסה שוב מאוחר יותר."
            except Exception as e:
                log.exception("שגיאה בפנייה ל-Claude")
                answer = f"הייתה תקלה בפנייה ל-Claude: {e}"
            send_reply(msg, sender, answer)
            log.info("נשלחה תשובה ל-%s", sender)
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def main():
    log.info(
        "הבוט התחיל. תיבה: %s | כתובות מורשות: %s | מילה בנושא: %s",
        EMAIL_ADDRESS,
        ", ".join(ALLOWED_SENDERS),
        SUBJECT_TAG or "(כל מייל)",
    )
    once = "--once" in sys.argv
    while True:
        try:
            check_inbox()
        except Exception:
            log.exception("שגיאה בבדיקת המייל")
        if once:
            break
        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    main()
