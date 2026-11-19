#!/bin/bash
# ממלא את קובץ ההגדרות .env בשאלות פשוטות, בלי לערוך קובץ
cd /opt/email-claude
[ -f .env ] || cp .env.example .env
chmod 600 .env

set_value() {
  local key="$1" val="$2"
  val="${val//[$'\r\n']/}"
  grep -v "^${key}=" .env > .env.tmp
  echo "${key}=${val}" >> .env.tmp
  mv .env.tmp .env
  chmod 600 .env
}

echo ""
echo "=== הגדרת בוט המייל ==="
echo "(טיפ: אפשר להדביק תשובה עם לחיצה ימנית בעכבר)"
echo ""

read -r -p "1) מה כתובת המייל שהבוט ישתמש בה? " EMAIL
EMAIL="$(echo "$EMAIL" | tr -d ' ')"
set_value EMAIL_ADDRESS "$EMAIL"

echo ""
echo "2) הדבק את סיסמת האפליקציה של המייל (16 אותיות)."
echo "   בזמן ההדבקה לא יופיע כלום על המסך - זה תקין. אחר כך לחץ Enter."
read -r -s -p "   סיסמת אפליקציה: " APPPW
echo ""
APPPW="$(echo "$APPPW" | tr -d ' ')"
set_value EMAIL_APP_PASSWORD "$APPPW"

echo ""
echo "3) בחר סיסמה לדף הניהול (גם כאן לא יופיע כלום על המסך)."
read -r -s -p "   סיסמה לדף הניהול: " ADMINPW
echo ""
set_value ADMIN_PASSWORD "$ADMINPW"

echo ""
echo "=== נשמר! ==="
echo "כתובת מייל: $EMAIL"
echo "אורך סיסמת האפליקציה: ${#APPPW} תווים (צריך להיות 16)"
echo ""
echo ">>> עכשיו הרץ: bash install.sh"
