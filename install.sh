#!/bin/bash
# התקנת בוט המייל. מריצים כמה פעמים - כל פעם הוא אומר מה הצעד הבא.
set -e
cd /opt/email-claude

echo "== מתקין tmux =="
command -v tmux >/dev/null || (apt-get update -qq && apt-get install -y -qq tmux)

if [ ! -x /root/.local/bin/claude ]; then
  echo "== מתקין Claude Code =="
  curl -fsSL https://claude.ai/install.sh | bash
fi

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
if ! grep -q "^ADMIN_PASSWORD=." .env; then
  echo ""
  echo ">>> חסרה סיסמה לדף הניהול. פתח את הקובץ ומלא את ADMIN_PASSWORD:"
  echo "    nano /opt/email-claude/.env"
  echo ">>> ואחר כך הרץ שוב: bash install.sh"
  exit 0
fi
  echo ""
  echo ">>> הצעד הבא: מלא את הפרטים בקובץ ההגדרות:"
  echo "    nano /opt/email-claude/.env"
  echo ">>> ואחר כך הרץ שוב: bash install.sh"
  exit 0
fi
chmod 600 .env

if [ ! -f /root/.claude/.credentials.json ]; then
  echo ""
  echo ">>> הצעד הבא: להתחבר ל-Claude עם המנוי שלך (פעם אחת בלבד):"
  echo "    cd /opt/email-claude/work && /root/.local/bin/claude"
  echo ">>> אחרי ההתחברות: אשר את התיקייה, כתוב /remote-control ואשר, ואז /exit"
  echo ">>> ואחר כך הרץ שוב: cd /opt/email-claude && bash install.sh"
  exit 0
fi

cp email-claude.service email-claude-admin.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable email-claude email-claude-admin >/dev/null 2>&1
systemctl restart email-claude email-claude-admin
PORT=$(grep "^ADMIN_PORT=" .env | cut -d= -f2); PORT=${PORT:-8090}
command -v ufw >/dev/null && ufw status | grep -q active && ufw allow "$PORT"/tcp >/dev/null
sleep 3
echo ""
systemctl is-active --quiet email-claude && echo "✔ בוט המייל רץ" || echo "✘ בוט המייל לא רץ - בדוק: tail /opt/email-claude/bot.log"
systemctl is-active --quiet email-claude-admin && echo "✔ דף הניהול רץ: http://$(hostname -I | awk '{print $1}'):$PORT" || echo "✘ דף הניהול לא רץ - בדוק: tail /opt/email-claude/bot.log"
