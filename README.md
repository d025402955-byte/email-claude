# בוט מייל ל-Claude

שולחים מייל עם שאלה, ותוך דקה בערך מגיעה תשובה מ-Claude באותו שרשור.

## איך זה עובד
- הבוט רץ על השרת בקמטרה ובודק את המייל כל דקה.
- הוא עונה רק למיילים שמגיעים מכתובות מורשות (ברירת מחדל: הכתובת שלך בלבד).
- הוא עונה רק כשבנושא המייל מופיעה המילה **שאלה** (אפשר לשנות או לבטל בקובץ ‎.env).
- אפשר להמשיך לשאול באותו שרשור, ו-Claude יקבל גם את ההתכתבות הקודמת.

## מה צריך להכין לפני ההתקנה
1. **סיסמת אפליקציה של ג'ימייל**: נכנסים ל-myaccount.google.com/apppasswords (צריך שאימות דו-שלבי יהיה מופעל), יוצרים סיסמה בשם "email bot" ומעתיקים את 16 האותיות.
2. **מפתח API של Claude**: נכנסים ל-console.anthropic.com, טוענים קרדיט (בתשלום, נפרד מהמנוי ל-Claude), ויוצרים מפתח ב-API Keys.

## התקנה על השרת (בחלון ה-SSH)
```
cd /opt
git clone https://github.com/d025402955-byte/email-claude.git
cd email-claude
bash install.sh
nano .env
bash install.sh
```
בפעם הראשונה install.sh יוצר את הקובץ ‎.env. ממלאים בו את הפרטים, שומרים (Ctrl+O, Enter, Ctrl+X) ומריצים שוב.

## פקודות שימושיות
- לראות מה הבוט עושה: `tail -f /opt/email-claude/bot.log`
- לעצור: `systemctl stop email-claude`
- להפעיל מחדש: `systemctl restart email-claude`
- לעדכן לגרסה חדשה: `cd /opt/email-claude && git pull && systemctl restart email-claude`
