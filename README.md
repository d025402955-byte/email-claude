# בוט מייל ל-Claude, דרך המנוי

שולחים מייל עם המילה **שאלה** בנושא. Claude עונה במייל, והשיחה מופיעה גם באתר (claude.ai/code) ובאפליקציה, בשם 📧 ואחריו נושא המייל.
מייל נוסף עם אותו נושא ממשיך את אותה שיחה. אפשר להמשיך לכתוב גם מהאתר או מהאפליקציה.

## התקנה על השרת (בחלון ה-SSH)
1. מורידים את הקוד:
```
cd /opt
git clone https://github.com/d025402955-byte/email-claude.git
cd email-claude
bash install.sh
```
2. ממלאים את הפרטים בקובץ ההגדרות: `nano /opt/email-claude/.env`
   שומרים עם Ctrl+O ואז Enter, ויוצאים עם Ctrl+X. מריצים שוב `bash install.sh`.
3. מתחברים ל-Claude עם המנוי (פעם אחת):
```
cd /opt/email-claude/work
/root/.local/bin/claude
```
   - בוחרים התחברות עם חשבון Claude (המנוי), פותחים את הקישור בדפדפן ומדביקים חזרה את הקוד.
   - כשהוא שואל אם לסמוך על התיקייה, עונים כן.
   - כותבים `/remote-control` ומאשרים.
   - כותבים `/exit`.
4. מריצים בפעם האחרונה:
```
cd /opt/email-claude && bash install.sh
```

## פקודות שימושיות
- לראות מה הבוט עושה: `tail -f /opt/email-claude/bot.log`
- לעצור את הבוט: `systemctl stop email-claude`
- לעדכן לגרסה חדשה: `cd /opt/email-claude && git pull && systemctl restart email-claude`
- לראות את השיחות הפתוחות על השרת: `tmux ls`
