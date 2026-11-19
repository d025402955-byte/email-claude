import io
def edit(path, pairs):
    s = io.open(path, encoding="utf-8", newline="").read()
    for a, b in pairs:
        assert s.count(a) == 1, (path, a)
        s = s.replace(a, b)
    io.open(path, "w", encoding="utf-8", newline="").write(s)

edit("sessions.py", [
 ('def get_or_create_thread(key):\n', 'def get_or_create_thread(key, title=None):\n'),
 ('"title": f"📧 {key}"', '"title": title or f"📧 {key}"'),
 ('WEB_MARK = "[הודעה מדף הניהול]"', 'WEB_MARK = "[הודעה מדף הניהול]"\nPHONE_MARK = "[שאלה בטלפון]"'),
 ('                    source, text = "admin", text[len(WEB_MARK):].strip()\n',
  '                    source, text = "admin", text[len(WEB_MARK):].strip()\n'
  '                elif text.startswith(PHONE_MARK):\n                    source = "phone"\n'
  '                    text = text[len(PHONE_MARK):].split("\n\n(התשובה תוקרא")[0].strip()\n'),
])
edit("stop_hook.py", [
 ('    answer = last_assistant_text(data) or "Claude סיים בלי טקסט תשובה. אפשר לראות את השיחה באתר."\n',
  '    answer = last_assistant_text(data) or "Claude סיים בלי טקסט תשובה. אפשר לראות את השיחה באתר."\n'
  '    if item.get("phone"):  # שאלה מהטלפון: phone.py מקריא את התשובה\n'
  '        with state() as st:\n'
  '            st.setdefault("phone_answers", {})[item["phone"]] = answer\n'
  '        log.info("תשובה לשאלה בטלפון מוכנה (%s)", key)\n'
  '        return\n'),
])
edit("admin.py", [
 ("site:'🌐 מהאתר / האפליקציה'}", "site:'🌐 מהאתר / האפליקציה',phone:'📞 מהטלפון'}"),
 ("textContent='📧 '+k;", "textContent=(k.startsWith('📞')?'':'📧 ')+k;"),
])
edit("work/CLAUDE.md", [
 ('- הודעות שמתחילות ב-"[הודעה מדף הניהול]"',
  '- הודעות שמתחילות ב-"[שאלה בטלפון]" נאמרו בקול בטלפון ותומללו, ולכן ייתכנו בהן שגיאות זיהוי. התשובה שלך תוקרא בקול:\n'
  '  ענה בקצרה (עד כמה משפטים), בעברית מדוברת, בלי רשימות, סימנים, קישורים או אימוג\'י.\n'
  '- הודעות שמתחילות ב-"[הודעה מדף הניהול]"'),
])
edit(".env.example", [
 ("ADMIN_PORT=8090", "ADMIN_PORT=8090\n\n# ===== שלוחת טלפון בטכנוליין (phone.py) =====\n"
  "# מספרי טלפון שמותר להם לשאול בטלפון, מופרדים בפסיק. ריק = אף אחד\nPHONE_ALLOWED=\n"
  "# מחרוזת סודית שבכתובת השלוחה (install.sh יוצר אחת אם חסר)\nPHONE_TOKEN=\nPHONE_PORT=8091\n"
  "# מאיפה לקחת את מפתח טכנוליין ואת הגדרות זיהוי הדיבור\nSHMARTPHONE_CONFIG=/etc/shmartphone/app.json"),
])
print("EDITED")
