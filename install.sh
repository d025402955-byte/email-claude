#!/bin/bash
# התקנת הבוט כשירות שרץ תמיד ועולה לבד אחרי הפעלה מחדש של השרת
set -e
cd /opt/email-claude
if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  echo "נוצר קובץ .env - מלא אותו עם: nano /opt/email-claude/.env ואז הרץ שוב: bash install.sh"
  exit 0
fi
chmod 600 .env
cp email-claude.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable email-claude
systemctl restart email-claude
sleep 3
systemctl --no-pager status email-claude | head -n 15
echo ""
echo "הבוט הותקן ורץ. לצפייה ביומן: tail -f /opt/email-claude/bot.log"
