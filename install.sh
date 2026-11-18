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

cp email-claude.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable email-claude >/dev/null 2>&1
systemctl restart email-claude
sleep 3
systemctl --no-pager status email-claude | head -n 8
echo ""
echo "== הבוט רץ! לצפייה ביומן: tail -f /opt/email-claude/bot.log =="
