#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
רץ אוטומטית כל פעם ש-Claude מסיים לענות (Stop hook).
אם השיחה נפתחה ממייל ויש שאלה שממתינה לתשובה - שולח את התשובה במייל.
"""

import json
import os
import sys

import common
from common import state

log = common.get_logger("hook")


def last_assistant_text(data):
    text = data.get("last_assistant_message")
    if isinstance(text, str) and text.strip():
        return text.strip()
    # גיבוי: קריאה מקובץ השיחה
    path = data.get("transcript_path")
    if not path or not os.path.exists(path):
        return ""
    last = ""
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                item = json.loads(line)
            except ValueError:
                continue
            if item.get("type") != "assistant":
                continue
            content = (item.get("message") or {}).get("content") or []
            parts = [c.get("text", "") for c in content
                     if isinstance(c, dict) and c.get("type") == "text"]
            if any(p.strip() for p in parts):
                last = "\n".join(parts).strip()
    return last


def main():
    key = os.environ.get("EMAIL_THREAD")
    if not key:
        return  # שיחה רגילה, לא מהמייל
    try:
        data = json.load(sys.stdin)
    except ValueError:
        data = {}

    with state() as st:
        thread = st["threads"].get(key)
        if thread and data.get("session_id"):
            thread["session_id"] = data["session_id"]
        queue = st["pending"].get(key) or []
        item = queue.pop(0) if queue else None
        if not queue:
            st["pending"].pop(key, None)

    if not item:
        return  # המשכת את השיחה מהאתר - אין מה לשלוח במייל

    answer = last_assistant_text(data) or "Claude סיים בלי טקסט תשובה. אפשר לראות את השיחה באתר."
    if item.get("phone"):  # שאלה מהטלפון: phone.py מקריא את התשובה
        with state() as st:
            st.setdefault("phone_answers", {})[item["phone"]] = answer
        log.info("תשובה לשאלה בטלפון מוכנה (%s)", key)
        return
    try:
        common.send_email(item["to"], item["subject"], answer,
                          item.get("message_id"), item.get("references"))
        log.info("נשלחה תשובה במייל ל-%s (%s)", item["to"], key)
    except Exception:
        log.exception("שליחת התשובה במייל נכשלה")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("תקלה ב-hook")
    sys.exit(0)
