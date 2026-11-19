#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
דף ניהול לבוט המייל
-------------------
- רשימת כל השיחות (מהמייל ומהדף).
- קריאת כל שיחה, כולל מה שנכתב מהמייל, מהאתר ומהאפליקציה.
- שליחת הודעה לשיחה קיימת, או פתיחת שיחה חדשה.
נכנסים עם הסיסמה שב-ADMIN_PASSWORD שבקובץ .env.
"""

import hashlib
import hmac
import json
import threading
import time
import urllib.parse
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import common
import sessions
from common import cfg, state

log = common.get_logger("admin")
PASSWORD = cfg("ADMIN_PASSWORD", required=True)
PORT = int(cfg("ADMIN_PORT", "8090"))
TOKEN = hmac.new(PASSWORD.encode(), b"email-claude-admin", hashlib.sha256).hexdigest()

# שגיאות אחרונות בשליחה, כדי להציג אותן בדף
errors = {}


def send_in_background(key, text):
    def run():
        try:
            sessions.send(key, f"{sessions.WEB_MARK}\n{text}")
            errors.pop(key, None)
        except Exception as e:
            log.exception("שליחה מדף הניהול נכשלה")
            errors[key] = str(e)
    threading.Thread(target=run, daemon=True).start()


def list_threads():
    with state() as st:
        threads = st["threads"]
        pending = st["pending"]
    out = []
    for key, t in threads.items():
        out.append({
            "key": key,
            "title": t.get("title", key),
            "alive": sessions.tmux_alive(t["tmux"]),
            "updated": t.get("updated") or t.get("created") or 0,
            "waiting_email": len(pending.get(key, [])),
        })
    out.sort(key=lambda x: x["updated"], reverse=True)
    return out


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    # ---------- עזרים ----------
    def logged_in(self):
        c = SimpleCookie(self.headers.get("Cookie", ""))
        return "auth" in c and hmac.compare_digest(c["auth"].value, TOKEN)

    def reply(self, code, body, ctype="application/json; charset=utf-8", headers=None):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def json(self, obj, code=200):
        self.reply(code, json.dumps(obj, ensure_ascii=False))

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n).decode("utf-8") if n else ""
        if "json" in (self.headers.get("Content-Type") or ""):
            return json.loads(raw or "{}")
        return {k: v[0] for k, v in urllib.parse.parse_qs(raw).items()}

    # ---------- GET ----------
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        if url.path == "/login":
            return self.reply(200, LOGIN_HTML, "text/html; charset=utf-8")
        if not self.logged_in():
            if url.path.startswith("/api/"):
                return self.json({"error": "צריך להתחבר"}, 401)
            return self.reply(302, "", headers={"Location": "login"})
        if url.path == "/":
            return self.reply(200, APP_HTML, "text/html; charset=utf-8")
        if url.path == "/api/threads":
            return self.json(list_threads())
        if url.path == "/api/messages":
            key = q.get("key", "")
            with state() as st:
                t = st["threads"].get(key) or {}
                waiting = len(st["pending"].get(key, []))
            msgs = sessions.read_messages(t.get("session_id"))
            return self.json({
                "messages": msgs,
                "alive": bool(t) and sessions.tmux_alive(t["tmux"]),
                "waiting_email": waiting,
                "error": errors.get(key),
            })
        self.json({"error": "לא נמצא"}, 404)

    # ---------- POST ----------
    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        if url.path == "/login":
            data = self.body()
            if hmac.compare_digest(data.get("password", ""), PASSWORD):
                return self.reply(302, "", headers={
                    "Location": "./",
                    "Set-Cookie": f"auth={TOKEN}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000",
                })
            time.sleep(2)  # האטה מול ניחוש סיסמאות
            return self.reply(302, "", headers={"Location": "login?bad=1"})
        if not self.logged_in():
            return self.json({"error": "צריך להתחבר"}, 401)
        data = self.body()
        if url.path == "/api/send":
            key, text = (data.get("key") or "").strip(), (data.get("text") or "").strip()
            if not key or not text:
                return self.json({"error": "חסר נושא או טקסט"}, 400)
            send_in_background(key, text)
            return self.json({"ok": True})
        if url.path == "/api/new":
            title, text = (data.get("title") or "").strip(), (data.get("text") or "").strip()
            if not title or not text:
                return self.json({"error": "צריך לכתוב נושא והודעה"}, 400)
            sessions.get_or_create_thread(title)
            send_in_background(title, text)
            return self.json({"ok": True, "key": title})
        if url.path == "/api/close":
            sessions.close(data.get("key", ""))
            return self.json({"ok": True})
        self.json({"error": "לא נמצא"}, 404)


LOGIN_HTML = """<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>כניסה - Claude במייל</title>
<style>body{font-family:Arial,sans-serif;background:#f4f1ea;display:flex;align-items:center;justify-content:center;height:100vh;margin:0}
form{background:#fff;padding:32px;border-radius:12px;box-shadow:0 2px 12px #0001;width:280px}
h1{font-size:20px;margin:0 0 16px}input{width:100%;box-sizing:border-box;padding:10px;font-size:16px;margin-bottom:12px;border:1px solid #ccc;border-radius:8px}
button{width:100%;padding:10px;font-size:16px;background:#c96442;color:#fff;border:0;border-radius:8px;cursor:pointer}
.bad{color:#b00;font-size:14px;margin-bottom:8px}</style></head><body>
<form method="post" action="login"><h1>📧 Claude במייל - ניהול</h1>
<div class="bad" id="bad" hidden>סיסמה שגויה</div>
<input type="password" name="password" placeholder="סיסמה" autofocus>
<button>כניסה</button></form>
<script>if(location.search.includes('bad'))document.getElementById('bad').hidden=false</script></body></html>"""

APP_HTML = r"""<!doctype html><html lang="he" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Claude במייל - ניהול</title>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Arial,sans-serif;background:#f4f1ea;color:#222;height:100vh;display:flex}
#side{width:300px;background:#fff;border-left:1px solid #ddd;display:flex;flex-direction:column}
#side h1{font-size:18px;margin:0;padding:16px;border-bottom:1px solid #eee}
#newbtn{margin:12px;padding:10px;background:#c96442;color:#fff;border:0;border-radius:8px;font-size:15px;cursor:pointer}
#list{overflow-y:auto;flex:1}
.th{padding:12px 16px;border-bottom:1px solid #f0f0f0;cursor:pointer}
.th:hover{background:#faf7f2}.th.sel{background:#f3e7df}
.th .t{font-weight:bold;font-size:15px}.th .s{font-size:12px;color:#777;margin-top:4px}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-left:6px;background:#bbb}.dot.on{background:#2a9d4b}
#main{flex:1;display:flex;flex-direction:column;min-width:0}
#head{padding:14px 20px;background:#fff;border-bottom:1px solid #ddd;display:flex;align-items:center;gap:12px}
#head .t{font-size:17px;font-weight:bold;flex:1}
#head button{padding:6px 12px;border:1px solid #ccc;background:#fff;border-radius:6px;cursor:pointer}
#msgs{flex:1;overflow-y:auto;padding:20px}
.m{max-width:760px;margin:0 0 14px;padding:12px 14px;border-radius:12px;white-space:pre-wrap;line-height:1.5}
.m.user{background:#c96442;color:#fff;margin-right:0;margin-left:auto}
.m.assistant{background:#fff;border:1px solid #e5e0d8}
.m .src{font-size:11px;opacity:.8;margin-bottom:4px}
#status{padding:0 20px 6px;font-size:13px;color:#777;min-height:20px}
#form{display:flex;gap:8px;padding:12px 20px;background:#fff;border-top:1px solid #ddd}
#form textarea{flex:1;height:70px;padding:10px;font-size:15px;border:1px solid #ccc;border-radius:8px;resize:vertical;font-family:inherit}
#form button{padding:0 22px;background:#c96442;color:#fff;border:0;border-radius:8px;font-size:15px;cursor:pointer}
#empty{margin:auto;color:#888;font-size:16px;text-align:center}
#title{display:none;flex:1;padding:8px;font-size:15px;border:1px solid #ccc;border-radius:6px}
@media(max-width:700px){body{flex-direction:column}#side{width:100%;max-height:35vh}}
</style></head><body>
<div id="side"><h1>📧 Claude במייל</h1>
<button id="newbtn" onclick="newThread()">+ שיחה חדשה</button><div id="list"></div></div>
<div id="main">
 <div id="head"><span class="t" id="htitle">בחר שיחה</span><input id="title" placeholder="נושא השיחה החדשה">
  <button id="closebtn" onclick="closeThread()" hidden title="סוגר את השיחה בשרת כדי לפנות זיכרון. מייל או הודעה חדשים יפתחו אותה מחדש">סגור בשרת</button></div>
 <div id="msgs"><div id="empty">בחר שיחה מהרשימה, או פתח שיחה חדשה</div></div>
 <div id="status"></div>
 <form id="form" onsubmit="send(event)"><textarea id="text" placeholder="כתוב הודעה ל-Claude..."></textarea><button>שלח</button></form>
</div>
<script>
let cur=null, isNew=false, lastCount=-1;
const SRC={email:'📧 מהמייל',admin:'🖥️ מדף הניהול',site:'🌐 מהאתר / האפליקציה'};
function esc(s){return s.replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
function ago(t){if(!t)return'';const d=(Date.now()/1000-t);if(d<60)return'עכשיו';if(d<3600)return'לפני '+Math.round(d/60)+' דק׳';if(d<86400)return'לפני '+Math.round(d/3600)+' שעות';return new Date(t*1000).toLocaleDateString('he-IL')}
async function api(p,b){const r=await fetch(p,b?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b)}:{});if(r.status==401){location='login';throw 0}return r.json()}
async function loadList(){
 const th=await api('api/threads');
 document.getElementById('list').innerHTML=th.map(t=>`<div class="th ${t.key===cur?'sel':''}" onclick='openThread(${JSON.stringify(t.key)})'>
  <div class="t"><span class="dot ${t.alive?'on':''}"></span>${esc(t.title)}</div>
  <div class="s">${t.alive?'פתוחה בשרת':'סגורה בשרת'} · ${ago(t.updated)}${t.waiting_email?' · ממתין לתשובה במייל':''}</div></div>`).join('')||'<div class="th"><div class="s">אין עדיין שיחות</div></div>';
}
function openThread(k){cur=k;isNew=false;lastCount=-1;
 document.getElementById('htitle').style.display='';document.getElementById('title').style.display='none';
 document.getElementById('htitle').textContent='📧 '+k;document.getElementById('closebtn').hidden=false;loadMsgs();loadList()}
function newThread(){cur=null;isNew=true;
 document.getElementById('htitle').style.display='none';const t=document.getElementById('title');t.style.display='block';t.value='';t.focus();
 document.getElementById('closebtn').hidden=true;document.getElementById('msgs').innerHTML='<div id="empty">כתוב נושא למעלה והודעה למטה. השיחה תופיע גם באתר ובאפליקציה, ואפשר יהיה להמשיך אותה גם במייל עם אותו נושא.</div>';document.getElementById('status').textContent=''}
async function loadMsgs(){
 if(!cur)return;const d=await api('api/messages?key='+encodeURIComponent(cur));
 const box=document.getElementById('msgs');
 if(d.messages.length!==lastCount){
  box.innerHTML=d.messages.map(m=>`<div class="m ${m.role}">${m.role=='user'?`<div class="src">${SRC[m.source]}</div>`:''}${esc(m.text)}</div>`).join('')||'<div id="empty">עדיין אין הודעות. השיחה נפתחת בשרת, זה לוקח כמה שניות...</div>';
  box.scrollTop=box.scrollHeight;lastCount=d.messages.length}
 const last=d.messages[d.messages.length-1];
 document.getElementById('status').textContent=d.error?('⚠️ '+d.error):(last&&last.role=='user'?'Claude כותב תשובה...':(d.alive?'':'השיחה סגורה בשרת. הודעה חדשה תפתח אותה מחדש.'));
}
async function send(e){e.preventDefault();const ta=document.getElementById('text');const text=ta.value.trim();if(!text)return;
 if(isNew){const title=document.getElementById('title').value.trim();if(!title){alert('צריך לכתוב נושא');return}
  const r=await api('api/new',{title,text});if(r.error){alert(r.error);return}ta.value='';openThread(r.key)}
 else if(cur){const r=await api('api/send',{key:cur,text});if(r.error){alert(r.error);return}ta.value='';}
 document.getElementById('status').textContent='שולח ל-Claude...';}
async function closeThread(){if(cur&&confirm('לסגור את השיחה בשרת? היא לא תימחק, ותיפתח שוב בהודעה הבאה.')){await api('api/close',{key:cur});loadList();loadMsgs()}}
document.getElementById('text').addEventListener('keydown',e=>{if(e.key=='Enter'&&(e.ctrlKey||e.metaKey))send(e)});
loadList();setInterval(loadList,10000);setInterval(loadMsgs,3000);
</script></body></html>"""


def main():
    log.info("דף הניהול עולה על פורט %s", PORT)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
