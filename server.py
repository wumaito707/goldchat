"""
GoldChat backend — FastAPI + WebSockets + SQLite.
Real-time chat: accounts, presence, typing, read receipts, persistence.
"""
import sqlite3
import hashlib
import secrets
import json
import time
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
# Prefer the repaired project-local runtime when present.
runtime_vendor = Path(__file__).parent / "vendor-runtime"
if runtime_vendor.is_dir():
    sys.path.insert(0, str(runtime_vendor))
try:
    from PIL import Image
    import qrcode
except ImportError:
    sys.path.insert(0, str(Path(__file__).parent / "vendor"))
import features
import social
import account_security
import sms_config
import email_config
import cloud_database
import cloud_media
import push_notifications
import sponsorship_payments
import logging
import re

class RedactSessionTokens(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r'([?&](?:token|approval|poll_secret)=)[^\s"&]+', r'\1[redacted]', record.getMessage())
        record.args = ()
        return True

for logger_name in ('uvicorn.error', 'uvicorn.access'):
    logging.getLogger(logger_name).addFilter(RedactSessionTokens())
from datetime import datetime, timezone

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Query, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

BASE = Path(__file__).parent
DATA_DIR = Path(os.environ.get("GOLDCHAT_DATA_DIR", str(BASE)))
DATA_DIR.mkdir(parents=True, exist_ok=True)
sms_config.load_config(DATA_DIR)
email_config.load_config(DATA_DIR)
DB_PATH = DATA_DIR / "goldchat.db"
STATIC_DIR = BASE / "static"

def initialize_runtime():
    if os.environ.get('RENDER')=='true':
        required=('TURSO_DATABASE_URL','TURSO_AUTH_TOKEN','GOLDCHAT_STORAGE_URL','GOLDCHAT_STORAGE_KEY','GOLDCHAT_STORAGE_BUCKET','GOLDCHAT_VERIFICATION_SECRET','GOLDCHAT_EMAIL_API_KEY','GOLDCHAT_SMTP_FROM')
        if any(not os.environ.get(name) for name in required):
            raise RuntimeError('Cloud database, private storage, verification secret and email settings are required on Render')
    if os.environ.get('RENDER')=='true' and os.environ.get('GOLDCHAT_EMAIL_PROVIDER')!='brevo':
        raise RuntimeError('Render requires Brevo email API delivery')
    cloud_media.validate_private()
    init_db()

@asynccontextmanager
async def lifespan(app):
    initialize_runtime()
    yield

app = FastAPI(title="GoldChat", lifespan=lifespan)
_allowed_origins = {
    "https://goldchat-app.pages.dev",
    "https://goldchat.onrender.com",
    "https://goldchat-frankfurt.onrender.com",
}
_extra_origin = os.environ.get("GOLDCHAT_WEB_ORIGIN", "").strip()
if _extra_origin:
    _allowed_origins.add(_extra_origin.rstrip("/"))
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_allowed_origins),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    max_age=3600,
)
sponsorship_payments.install(app)

# Turso is a remote database. Running expiry cleanup for every API request
# delays user-facing requests with avoidable database work.
_cleanup_lock = threading.Lock()
_last_expired_cleanup = 0.0
_CLEANUP_INTERVAL_SECONDS = 300

# Startup makes several authenticated requests at once. Reuse a fresh session
# briefly so those requests do not each repeat the same remote Turso lookup.
_auth_cache_lock = threading.Lock()
_auth_cache = {}
_AUTH_CACHE_SECONDS = 8

@app.exception_handler(sqlite3.OperationalError)
async def database_error(request: Request, error: sqlite3.OperationalError):
    logging.getLogger('uvicorn.error').error('Database operation failed: %s', str(error))
    return JSONResponse(status_code=503, content={'detail':'GOLDCHAT could not reach its database. Please try again shortly.'})

# ---------- DB ----------
def get_db(*, cleanup=True):
    conn = cloud_database.connect(os.environ['TURSO_DATABASE_URL'],os.environ['TURSO_AUTH_TOKEN']) if os.environ.get('TURSO_DATABASE_URL') else sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    global _last_expired_cleanup
    if cleanup and time.monotonic() - _last_expired_cleanup >= _CLEANUP_INTERVAL_SECONDS:
        with _cleanup_lock:
            if time.monotonic() - _last_expired_cleanup >= _CLEANUP_INTERVAL_SECONDS:
                social.cleanup_expired(conn)
                _last_expired_cleanup = time.monotonic()
    return conn

def get_verification_db():
    # Verification never reads messages or statuses; avoid remote chat cleanup.
    return get_db(cleanup=False)

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        salt TEXT NOT NULL,
        avatar_initial TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        type TEXT NOT NULL,  -- 'direct' | 'group'
        title TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS chat_members (
        chat_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        joined_at TEXT NOT NULL,
        PRIMARY KEY (chat_id, user_id),
        FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER NOT NULL,
        sender_id INTEGER NOT NULL,
        text TEXT NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (chat_id) REFERENCES chats(id) ON DELETE CASCADE,
        FOREIGN KEY (sender_id) REFERENCES users(id) ON DELETE CASCADE
    );
    CREATE TABLE IF NOT EXISTS read_state (
        chat_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        last_read_msg_id INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY (chat_id, user_id)
    );
    """)
    features.init_schema(conn)
    social.init_schema(conn)
    account_security.init_schema(conn)
    push_notifications.init_schema(conn)
    conn.commit()
    conn.close()

def hash_pw(password, salt=None):
    if salt is None:
        salt = secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 200000)
    return h.hex(), salt

# ---------- Presence and socket subscriptions (in-memory) ----------
ONLINE = {}            # user_id -> set of websocket ids
CONNECTIONS = {}      # ws_id -> (user_id, websocket)
SUBSCRIBED = {}        # chat_id -> set of ws_ids

class ConnectionManager:
    def __init__(self):
        self.active = {}  # ws_id -> {user_id, ws, chat_ids:set}

    async def connect(self, ws_id, user_id, ws):
        self.active[ws_id] = {"user_id": user_id, "ws": ws, "chat_ids": set()}
        ONLINE.setdefault(user_id, set()).add(ws_id)
        delivered_chats = advance_delivery(user_id)
        if delivered_chats:
            conn = get_db(cleanup=False)
            try:
                peers = conn.execute("""SELECT cm2.chat_id,cm2.user_id FROM chat_members cm1
                    JOIN chat_members cm2 ON cm1.chat_id=cm2.chat_id
                    WHERE cm1.user_id=? AND cm2.user_id!=?""", (user_id,user_id)).fetchall()
            finally:
                conn.close()
            recipients = {}
            for row in peers:
                if row['chat_id'] in delivered_chats:
                    recipients.setdefault(row['user_id'], []).append(row['chat_id'])
            for peer_id, chat_ids in recipients.items():
                await self.send_to_user(peer_id, {"type":"delivery", "chat_ids":chat_ids})
        await self.broadcast_presence(user_id, True)

    def disconnect(self, ws_id):
        info = self.active.pop(ws_id, None)
        if not info:
            return
        uid = info["user_id"]
        # unsubscribe from chats
        for cid in info["chat_ids"]:
            SUBSCRIBED.get(cid, set()).discard(ws_id)
        ONLINE.get(uid, set()).discard(ws_id)
        if not ONLINE.get(uid):
            ONLINE.pop(uid, None)
            last_seen = now_iso()
            conn = get_db(cleanup=False)
            try:
                conn.execute('UPDATE users SET last_seen_at=? WHERE id=?', (last_seen, uid))
                conn.commit()
            finally:
                conn.close()
            import asyncio
            asyncio.create_task(self.broadcast_presence(uid, False, last_seen))

    async def subscribe(self, ws_id, chat_id):
        self.active[ws_id]["chat_ids"].add(chat_id)
        SUBSCRIBED.setdefault(chat_id, set()).add(ws_id)

    async def send_to_user(self, user_id, data):
        sent = False
        for ws_id in list(ONLINE.get(user_id, set())):
            info = self.active.get(ws_id)
            if info:
                try:
                    await info["ws"].send_text(json.dumps(data))
                    sent = True
                except Exception:
                    self.disconnect(ws_id)
        return sent

    async def broadcast_chat(self, chat_id, data, exclude_ws=None):
        for ws_id in list(SUBSCRIBED.get(chat_id, set())):
            if ws_id == exclude_ws:
                continue
            info = self.active.get(ws_id)
            if info:
                try:
                    await info["ws"].send_text(json.dumps(data))
                except Exception:
                    self.disconnect(ws_id)

    async def broadcast_presence(self, user_id, online, last_seen=None, include_hidden=False):
        # notify all users sharing a chat with this user
        conn = get_db()
        shared = conn.execute("""
            SELECT DISTINCT cm2.user_id FROM chat_members cm1
            JOIN chat_members cm2 ON cm1.chat_id = cm2.chat_id
            WHERE cm1.user_id = ? AND cm2.user_id != ?
        """, (user_id, user_id)).fetchall()
        conn.close()
        for row in shared:
            visible = presence_visible(user_id, row["user_id"])
            if not visible and not include_hidden:
                continue
            await self.send_to_user(row["user_id"], {
                "type": "presence", "user_id": user_id, "online": online and visible,
                "last_seen": None if online or not visible else last_seen
            })

mgr = ConnectionManager()

# ---------- Helpers ----------
def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def fmt_time(iso):
    try:
        dt = datetime.fromisoformat(iso.replace("Z",""))
        return dt.strftime("%H:%M")
    except Exception:
        return ""

def presence_visible(subject_id, observer_id):
    if subject_id == observer_id:
        return True
    with get_db() as conn:
        subject=conn.execute("SELECT privacy FROM users WHERE id=?",(subject_id,)).fetchone()
        blocked=conn.execute("SELECT 1 FROM blocks WHERE (user_id=? AND blocked_id=?) OR (user_id=? AND blocked_id=?)",(subject_id,observer_id,observer_id,subject_id)).fetchone()
        contact=conn.execute("SELECT 1 FROM contacts WHERE user_id=? AND contact_id=?",(subject_id,observer_id)).fetchone()
    conn.close()
    return bool(subject and not blocked and (subject['privacy']=='everyone' or (subject['privacy']=='contacts' and contact)))

def read_receipts_visible(subject_id, observer_id, conn):
    """Whether an observer may learn that this user read a message."""
    if subject_id == observer_id:
        return True
    row = conn.execute("""SELECT u.privacy,u.read_receipts,
        EXISTS(SELECT 1 FROM contacts WHERE user_id=? AND contact_id=?) AS contact,
        EXISTS(SELECT 1 FROM blocks WHERE (user_id=? AND blocked_id=?) OR (user_id=? AND blocked_id=?)) AS blocked
        FROM users u WHERE u.id=?""",
        (subject_id,observer_id,subject_id,observer_id,observer_id,subject_id,subject_id)).fetchone()
    return bool(row and row['read_receipts'] and not row['blocked']
                and (row['privacy']=='everyone' or (row['privacy']=='contacts' and row['contact'])))

def advance_delivery(user_id, chat_id=None, message_id=None):
    """Persist delivery once a user's socket can receive messages; never regress it."""
    conn = get_db(cleanup=False)
    try:
        rows = conn.execute("""SELECT cm.chat_id,
            (SELECT MAX(id) FROM messages WHERE chat_id=cm.chat_id) AS newest,
            COALESCE(rs.last_delivered_msg_id,0) AS delivered
            FROM chat_members cm LEFT JOIN read_state rs
            ON rs.chat_id=cm.chat_id AND rs.user_id=cm.user_id
            WHERE cm.user_id=? AND (? IS NULL OR cm.chat_id=?)""",
            (user_id,chat_id,chat_id)).fetchall()
        changed = set()
        for row in rows:
            newest = message_id if message_id is not None else row['newest']
            if newest and newest > row['delivered']:
                conn.execute("""INSERT INTO read_state(chat_id,user_id,last_delivered_msg_id)
                    VALUES(?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET
                    last_delivered_msg_id=MAX(read_state.last_delivered_msg_id,excluded.last_delivered_msg_id)""",
                    (row['chat_id'],user_id,newest))
                changed.add(row['chat_id'])
        conn.commit()
        return changed
    finally:
        conn.close()

def chat_receipt_state(conn, chat_id, observer_id):
    """Read all peer receipt watermarks and privacy in one database request."""
    peers = conn.execute("""SELECT cm.user_id,COALESCE(rs.last_read_msg_id,0) AS read_id,
        MAX(COALESCE(rs.last_delivered_msg_id,0),COALESCE(rs.last_read_msg_id,0)) AS delivered_id,
        u.privacy,u.read_receipts,
        EXISTS(SELECT 1 FROM contacts c WHERE c.user_id=u.id AND c.contact_id=?) AS receipt_contact,
        EXISTS(SELECT 1 FROM blocks b WHERE (b.user_id=u.id AND b.blocked_id=?) OR (b.user_id=? AND b.blocked_id=u.id)) AS receipt_blocked
        FROM chat_members cm JOIN users u ON u.id=cm.user_id
        LEFT JOIN read_state rs ON rs.chat_id=cm.chat_id AND rs.user_id=cm.user_id
        WHERE cm.chat_id=? AND cm.user_id!=?""",
        (observer_id,observer_id,observer_id,chat_id,observer_id)).fetchall()
    return {
        'read': min((peer['read_id'] for peer in peers), default=0),
        'delivered': min((peer['delivered_id'] for peer in peers), default=0),
        'readable': bool(peers and all(peer['read_receipts'] and not peer['receipt_blocked'] and
            (peer['privacy']=='everyone' or (peer['privacy']=='contacts' and peer['receipt_contact']))
            for peer in peers)),
    }


def user_public(row):
    return {
        "id": row["id"], "username": row["username"],
        "display_name": row["display_name"],
        "avatar_initial": row["avatar_initial"],
        "avatar_media_id": row["avatar_media_id"] if "avatar_media_id" in row.keys() else None,
        "verified": bool(row["verified_email"]) if "verified_email" in row.keys() else False,
    }

def get_or_create_direct_chat(user_a, user_b):
    conn = get_db()
    match = """SELECT c.id FROM chats c WHERE c.type='direct'
        AND EXISTS(SELECT 1 FROM chat_members WHERE chat_id=c.id AND user_id=?)
        AND EXISTS(SELECT 1 FROM chat_members WHERE chat_id=c.id AND user_id=?)
        AND (SELECT COUNT(*) FROM chat_members WHERE chat_id=c.id)=2"""
    # Both writes run under one lock, including the existence check. Only a
    # newly inserted chat receives members; existing histories stay intact.
    statements = [
        ("INSERT INTO chats(type,created_at) SELECT 'direct',? WHERE NOT EXISTS("+match+")", (now_iso(),user_a,user_b)),
        ("WITH new_chat AS MATERIALIZED (SELECT last_insert_rowid() AS id WHERE changes()>0) INSERT INTO chat_members(chat_id,user_id,joined_at) SELECT new_chat.id,user_id,? FROM new_chat CROSS JOIN (SELECT ? AS user_id UNION ALL SELECT ?)",(now_iso(),user_a,user_b)),
    ]
    try:
        if hasattr(conn,'execute_batch'):
            conn.execute_batch(statements)
        else:
            conn.execute('BEGIN IMMEDIATE')
            for sql,args in statements:conn.execute(sql,args)
            conn.commit()
        row=conn.execute(match+" ORDER BY c.id LIMIT 1",(user_a,user_b)).fetchone()
        return row['id']
    finally:
        conn.close()

def chat_list_for(user_id):
    conn = get_db()
    queries=[
        ('\n        SELECT c.*, (SELECT COUNT(*) FROM messages m WHERE m.chat_id=c.id) AS msg_count\n        FROM chats c\n        JOIN chat_members cm ON cm.chat_id=c.id\n        WHERE cm.user_id=?\n        ORDER BY (SELECT MAX(created_at) FROM messages m WHERE m.chat_id=c.id) DESC\n    ',(user_id,)),
        ('''SELECT cm.chat_id,u.*,
            EXISTS(SELECT 1 FROM contacts c WHERE c.user_id=u.id AND c.contact_id=?) AS receipt_contact,
            EXISTS(SELECT 1 FROM blocks b WHERE (b.user_id=u.id AND b.blocked_id=?) OR (b.user_id=? AND b.blocked_id=u.id)) AS receipt_blocked
            FROM chat_members cm JOIN users u ON u.id=cm.user_id
            WHERE cm.user_id!=? AND cm.chat_id IN (SELECT chat_id FROM chat_members WHERE user_id=?)''',
            (user_id,user_id,user_id,user_id,user_id)),
        ('SELECT m.* FROM messages m WHERE m.id=(SELECT MAX(m2.id) FROM messages m2 WHERE m2.chat_id=m.chat_id AND NOT EXISTS(SELECT 1 FROM message_hidden h WHERE h.message_id=m2.id AND h.user_id=?)) AND m.chat_id IN (SELECT chat_id FROM chat_members WHERE user_id=?)',(user_id, user_id)),
        ('SELECT m.chat_id,COUNT(*) AS n FROM messages m JOIN chat_members cm ON cm.chat_id=m.chat_id AND cm.user_id=? LEFT JOIN read_state rs ON rs.chat_id=m.chat_id AND rs.user_id=? WHERE m.sender_id!=? AND m.id>COALESCE(rs.last_read_msg_id,0) GROUP BY m.chat_id',(user_id, user_id, user_id)),
        ('SELECT cm.chat_id,MIN(COALESCE(rs.last_read_msg_id,0)) AS read_id,MIN(MAX(COALESCE(rs.last_delivered_msg_id,0),COALESCE(rs.last_read_msg_id,0))) AS delivered_id FROM chat_members cm LEFT JOIN read_state rs ON rs.chat_id=cm.chat_id AND rs.user_id=cm.user_id WHERE cm.user_id!=? AND cm.chat_id IN (SELECT chat_id FROM chat_members WHERE user_id=?) GROUP BY cm.chat_id',(user_id, user_id))
    ]
    data=conn.query_batch(queries) if hasattr(conn,"query_batch") else [conn.execute(sql,args).fetchall() for sql,args in queries]
    rows=data[0]
    memberships={}
    for m in data[1]:memberships.setdefault(m["chat_id"],[]).append(m)
    last_messages={r["chat_id"]:r for r in data[2]}
    unread_counts={r["chat_id"]:r["n"] for r in data[3]}
    peer_reads={r["chat_id"]:r for r in data[4]}
    out = []
    for r in rows:
        members=memberships.get(r['id'],[])
        last=last_messages.get(r['id'])
        unread=unread_counts.get(r['id'],0)
        peer=members[0] if members else None
        receipt=peer_reads.get(r['id'])
        receipt_visible=bool(last and last['sender_id']==user_id and members and all(
            m['read_receipts'] and not m['receipt_blocked'] and
            (m['privacy']=='everyone' or (m['privacy']=='contacts' and m['receipt_contact']))
            for m in members))
        out.append({
            "id": r["id"], "type": r["type"], "title": r["title"],
            "peer": user_public(peer) if peer else None,
            "members": [user_public(m) for m in members],
            "last_message": {
                "id": last["id"] if last else None,
                "read": bool(receipt_visible and receipt and receipt['read_id']>=last['id']),
                "delivered": bool(last and last['sender_id']==user_id and receipt and (receipt['delivered_id'] or 0)>=last['id']),
                "text": last["text"] if last else "",
                "sender_id": last["sender_id"] if last else None,
                "time": fmt_time(last["created_at"]) if last else "",
                "iso": last["created_at"] if last else None,
            } if last else None,
            "unread": unread,
            "peer_online": (peer["id"] in ONLINE and presence_visible(peer["id"], user_id)) if peer else False,
            "peer_last_seen": (peer["last_seen_at"] if peer["id"] not in ONLINE else None) if peer and presence_visible(peer["id"], user_id) else None,
        })
    conn.close()
    return out

def messages_for(chat_id, user_id, limit=200):
    conn = get_db()
    msgs = conn.execute("SELECT * FROM messages WHERE chat_id=? AND NOT EXISTS(SELECT 1 FROM message_hidden h WHERE h.message_id=messages.id AND h.user_id=?) ORDER BY id DESC LIMIT ?", (chat_id,user_id, limit)).fetchall()
    msgs = list(reversed(msgs))
    receipt = chat_receipt_state(conn,chat_id,user_id)
    out = []
    for m in msgs:
        sender = conn.execute("SELECT id, username, display_name, avatar_initial, avatar_media_id FROM users WHERE id=?", (m["sender_id"],)).fetchone()
        out.append({
            "id": m["id"], "chat_id": chat_id,
            "sender": user_public(sender),
            "text": m["text"],
            "time": fmt_time(m["created_at"]),
            "iso": m["created_at"],
            "mine": m["sender_id"] == user_id,
            "read": bool(m['sender_id']==user_id and receipt['readable'] and receipt['read']>=m['id']),
            "delivered": bool(m['sender_id']==user_id and receipt['delivered']>=m['id']),
        })
    conn.close()
    return out

# ---------- Models ----------
class RegisterIn(BaseModel):
    username: str
    password: str
    display_name: str = ""
    verification_proof: str = ""

class LoginIn(BaseModel):
    username: str
    password: str

class GoogleLoginIn(BaseModel):
    credential: str
    link: bool = False

def session_token(request: Request, token: str = Query("")):
    authorization=request.headers.get("authorization", "")
    if authorization.startswith("Bearer "):
        return authorization[7:]
    return request.cookies.get("gc_session", "") or token

# ---------- REST ----------
@app.post("/api/register")
def register(body: RegisterIn):
    import re
    if not re.fullmatch(r"[A-Za-z0-9_]{3,32}", body.username.strip()):
        raise HTTPException(400, "Username must be 3-32 letters, numbers or underscores")
    if not 8 <= len(body.password) <= 128:
        raise HTTPException(400, "Password must be 8-128 characters")
    if len(body.display_name.strip()) > 80:
        raise HTTPException(400, "Display name must be under 80 characters")
    display = body.display_name.strip() or body.username.strip()
    initial = display[0].upper() if display else "U"
    pw_hash, salt = hash_pw(body.password)
    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        contact = consume_registration(conn, body.verification_proof)
        conn.execute("INSERT INTO users (username, display_name, password_hash, salt, avatar_initial, created_at, verified_email, verified_phone, verified_at) VALUES (?,?,?,?,?,?,?,?,?)",
                     (body.username.strip(), display, pw_hash, salt, initial, now_iso(), contact['address'] if contact['channel']=='email' else None, contact['address'] if contact['channel']=='phone' else None, time.time()))
        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        raise HTTPException(400, "Username or verified contact already in use")
    except HTTPException:
        conn.rollback(); conn.close(); raise
    row = conn.execute("SELECT * FROM users WHERE username=?", (body.username.strip(),)).fetchone()
    conn.close()
    token = create_session(row["id"])
    return {"user": user_public(row), "token": token}

@app.post("/api/login")
def login(body: LoginIn):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE username=? OR verified_email=?", (body.username.strip(),body.username.strip().lower())).fetchone()
    conn.close()
    if not row:
        raise HTTPException(400, "Invalid username or password")
    pw_hash, _ = hash_pw(body.password, row["salt"])
    if not secrets.compare_digest(pw_hash, row["password_hash"]):
        raise HTTPException(400, "Invalid username or password")
    token = create_session(row["id"])
    return {"user": user_public(row), "token": token}

@app.get("/api/auth/google/config")
def google_login_config():
    return {"client_id": os.environ.get("GOLDCHAT_GOOGLE_CLIENT_ID", "").strip()}

@app.post("/api/auth/google")
def google_login(body: GoogleLoginIn, token: str = Depends(session_token)):
    client_id = os.environ.get("GOLDCHAT_GOOGLE_CLIENT_ID", "").strip()
    if not client_id:
        raise HTTPException(503, "Google sign-in is not configured yet")
    if len(body.credential) > 10000:
        raise HTTPException(400, "Invalid Google sign-in")
    linking_user = auth_user(token) if body.link else None
    try:
        from functools import partial
        from google.oauth2 import id_token
        from google.auth.transport import requests as google_requests
        claims = id_token.verify_oauth2_token(body.credential, partial(google_requests.Request(), timeout=10), client_id)
    except Exception as exc:
        logging.getLogger('uvicorn.error').info('Google ID token rejected: %s', type(exc).__name__)
        raise HTTPException(401, "Google sign-in could not be verified") from None
    sub = str(claims.get('sub') or '')
    email = str(claims.get('email') or '').strip().lower()
    if not sub or not email or claims.get('email_verified') not in (True, 'true'):
        raise HTTPException(401, "Google account email must be verified")
    conn = get_db(cleanup=False)
    try:
        existing = conn.execute('SELECT * FROM users WHERE google_sub=?', (sub,)).fetchone()
        if body.link:
            # Linking never creates or switches accounts. The verified email
            # and authenticated GOLDCHAT account must belong to this user.
            current = conn.execute('SELECT * FROM users WHERE id=?', (linking_user['id'],)).fetchone()
            if not current or (current['verified_email'] or '').lower() != email:
                raise HTTPException(409, 'Choose the Google account that matches your verified GOLDCHAT email')
            if existing and existing['id'] != current['id']:
                raise HTTPException(409, 'This Google account is already connected to another GOLDCHAT account')
            changed = conn.execute('UPDATE users SET google_sub=? WHERE id=? AND (google_sub IS NULL OR google_sub=?)', (sub, current['id'], sub))
            if changed.rowcount != 1:
                raise HTTPException(409, 'A different Google account is already connected')
            conn.commit()
            row = conn.execute('SELECT * FROM users WHERE id=?', (current['id'],)).fetchone()
        elif existing:
            row = existing
        else:
            email_owner = conn.execute('SELECT * FROM users WHERE verified_email=?', (email,)).fetchone()
            if email_owner:
                # A matching email alone cannot silently attach a new login method.
                raise HTTPException(409, 'This email already has a GOLDCHAT account. Sign in with your password, then connect Google in Settings → Account recovery.')
            else:
                if not (email.endswith('@gmail.com') or claims.get('hd')):
                    raise HTTPException(400, 'Use email verification for non-Gmail accounts, then connect Google in Account settings')
                display = str(claims.get('name') or email.split('@')[0]).strip()[:80] or 'Google user'
                username = re.sub(r'[^A-Za-z0-9_]', '', email.split('@')[0])[:20] or 'user'
                username = username if len(username) >= 3 else 'user'
                username += '_' + secrets.token_hex(3)
                password_hash, salt = hash_pw(secrets.token_urlsafe(48))
                conn.execute('INSERT INTO users (username, display_name, password_hash, salt, avatar_initial, created_at, verified_email, verified_at, google_sub) VALUES (?,?,?,?,?,?,?,?,?)',
                    (username, display, password_hash, salt, display[0].upper(), now_iso(), email, time.time(), sub))
                conn.commit()
                row = conn.execute('SELECT * FROM users WHERE google_sub=?', (sub,)).fetchone()
    except sqlite3.IntegrityError:
        conn.rollback()
        raise HTTPException(409, 'This Google account is already linked. Please try again.')
    finally:
        conn.close()
    session = token if body.link else create_session(row['id'])
    return {"user": user_public(row), "token": session}

def create_session(uid, label="Browser"):
    token = secrets.token_hex(24)
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE expires_at<=?", (time.time(),))
        conn.execute("INSERT INTO sessions(token_hash,user_id,expires_at,label,created_at) VALUES(?,?,?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), uid, time.time()+30*86400,label[:80],time.time()))
    conn.close()
    return token


def require_member(chat_id: int, user_id: int):
    with get_db() as conn:
        member = conn.execute(
            "SELECT 1 FROM chat_members WHERE chat_id=? AND user_id=?",
            (chat_id, user_id),
        ).fetchone()
    conn.close()
    if not member:
        raise HTTPException(403, "You are not a member of this chat")


def auth_user(token: str):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    now = time.monotonic()
    with _auth_cache_lock:
        cached = _auth_cache.get(token_hash)
        if cached and cached[0] > now:
            return cached[1]
    with get_db() as conn:
        row = conn.execute("SELECT u.* FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>?", (token_hash,time.time())).fetchone()
    conn.close()
    if row is None:
        raise HTTPException(401, "Invalid or expired session")
    with _auth_cache_lock:
        _auth_cache[token_hash] = (now + _AUTH_CACHE_SECONDS, row)
    return row


@app.post("/api/logout")
async def logout(token: str = Depends(session_token)):
    uid = auth_user(token)["id"]
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (hashlib.sha256(token.encode()).hexdigest(),))
    conn.close()
    with _auth_cache_lock:
        _auth_cache.pop(hashlib.sha256(token.encode()).hexdigest(), None)
    # This token's sockets are closed; other signed-in devices stay online.
    for wsid, info in list(mgr.active.items()):
        if info.get("token") == token:
            await info["ws"].close(code=4401)
            mgr.disconnect(wsid)
    return {"ok": True}


@app.get("/api/me")
def me(token: str = Depends(session_token)):
    return user_public(auth_user(token))

@app.get("/api/chats")
def list_chats(token: str = Depends(session_token)):
    u = auth_user(token)
    return chat_list_for(u["id"])

@app.get("/api/chats/{chat_id}/messages")
def get_messages(chat_id: int, token: str = Depends(session_token)):
    u = auth_user(token)
    require_member(chat_id, u["id"])
    return messages_for(chat_id, u["id"])

@app.get("/api/users/search")
def search_users(q: str = Query(...), token: str = Depends(session_token)):
    u = auth_user(token)
    conn = get_db()
    rows = conn.execute("""
        SELECT * FROM users
        WHERE (username LIKE ? OR display_name LIKE ?) AND id != ?
        LIMIT 20
    """, (f"%{q}%", f"%{q}%", u["id"])).fetchall()
    conn.close()
    # include online status
    result = []
    for r in rows:
        pub = user_public(r); pub["online"] = r["id"] in ONLINE and presence_visible(r["id"], u["id"])
        result.append(pub)
    return result

@app.post("/api/chats/direct/{user_id}")
def start_direct(user_id: int, token: str = Depends(session_token)):
    u = auth_user(token)
    if user_id == u["id"]:
        raise HTTPException(400, "Choose another user to start a chat")
    conn = get_db()
    peer = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not peer:
        conn.close(); raise HTTPException(404, "User not found")
    cid = get_or_create_direct_chat(u["id"], user_id)
    conn.close()
    return {"chat_id": cid}

@app.post("/api/chats/{chat_id}/read")
async def mark_read(chat_id: int, token: str = Depends(session_token)):
    u = auth_user(token)
    require_member(chat_id, u["id"])
    conn = get_db()
    last = conn.execute("SELECT MAX(id) AS m FROM messages WHERE chat_id=?", (chat_id,)).fetchone()
    last_id = last["m"] or 0
    previous=conn.execute("SELECT last_read_msg_id,last_delivered_msg_id FROM read_state WHERE chat_id=? AND user_id=?",(chat_id,u['id'])).fetchone()
    previous_read=previous['last_read_msg_id'] if previous else 0
    previous_delivery=previous['last_delivered_msg_id'] if previous else 0
    conn.execute("""
        INSERT INTO read_state (chat_id, user_id, last_read_msg_id,last_delivered_msg_id) VALUES (?,?,?,?)
        ON CONFLICT(chat_id, user_id) DO UPDATE SET
        last_read_msg_id=MAX(read_state.last_read_msg_id,excluded.last_read_msg_id),
        last_delivered_msg_id=MAX(read_state.last_delivered_msg_id,excluded.last_delivered_msg_id)
    """, (chat_id, u["id"], last_id,last_id))
    conn.execute("UPDATE notifications SET read_at=? WHERE chat_id=? AND user_id=? AND kind='message' AND read_at IS NULL",(now_iso(),chat_id,u["id"]))
    recipients=[r['user_id'] for r in conn.execute("SELECT user_id FROM chat_members WHERE chat_id=?",(chat_id,))]
    readable={recipient:read_receipts_visible(u['id'],recipient,conn) for recipient in recipients if recipient!=u['id']}
    conn.commit(); conn.close()
    if last_id>previous_read:
        await mgr.send_to_user(u['id'], {"type":"read","chat_id":chat_id,"user_id":u['id'],"last_read_msg_id":last_id})
    for recipient in recipients:
        if recipient==u['id']:
            continue
        if last_id>previous_read and readable[recipient]:
            await mgr.send_to_user(recipient, {"type":"read","chat_id":chat_id,"user_id":u['id'],"last_read_msg_id":last_id})
        elif last_id>previous_delivery:
            await mgr.send_to_user(recipient, {"type":"delivery","chat_ids":[chat_id]})
    return {"ok": True}

# ---------- WebSocket ----------
@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket, token: str = Query("")):
    token = token or websocket.cookies.get("gc_session", "")
    try:
        uid = auth_user(token)["id"]
    except HTTPException:
        await websocket.close(code=4401)
        return
    await websocket.accept()
    ws_id = secrets.token_hex(8)
    await mgr.connect(ws_id, uid, websocket)
    mgr.active[ws_id]["token"] = token
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                auth_user(token)
            except HTTPException:
                await websocket.close(code=4401)
                break
            if len(raw) > 20000:
                await websocket.send_text(json.dumps({"type":"error","message":"Request too large"}))
                continue
            try:
                data = json.loads(raw)
                if not isinstance(data, dict):
                    raise ValueError("Expected an object")
                t = data.get("type")
                if t in {"subscribe", "message", "typing"}:
                    chat_id = int(data["chat_id"])
                    require_member(chat_id, uid)
                    if t in {"message", "typing"}:
                        FEATURE_HOOKS["allowed_send"](chat_id, uid)
            except (ValueError, TypeError, KeyError, HTTPException):
                await websocket.send_text(json.dumps({"type": "error", "message": "Invalid request or chat access denied"}))
                continue
            if t == "call_signal":
                try:
                    cid=int(data["chat_id"])
                    FEATURE_HOOKS["allowed_send"](cid,uid)
                    with get_db() as conn:
                        chat=conn.execute("SELECT type FROM chats WHERE id=?",(cid,)).fetchone()
                        peers=conn.execute("SELECT user_id FROM chat_members WHERE chat_id=? AND user_id!=?",(cid,uid)).fetchall()
                    conn.close()
                    signal=data.get("signal")
                    if chat["type"]!="direct" or not isinstance(signal,dict) or signal.get("kind") not in {"offer","answer","ice","hangup","busy"}:
                        raise ValueError()
                    call_id=SOCIAL_HOOKS["record_signal"](cid,uid,signal)
                    if not peers or not ONLINE.get(peers[0]["user_id"]):
                        if call_id: SOCIAL_HOOKS["update_call"](call_id,uid,"unavailable")
                        await websocket.send_text(json.dumps({"type":"call_signal","chat_id":cid,"signal":{"kind":"unavailable"}}))
                        continue
                    for peer in peers:
                        await mgr.send_to_user(peer["user_id"],{"type":"call_signal","chat_id":cid,"from_user":uid,"signal":signal})
                except (ValueError,TypeError,KeyError,HTTPException):
                    await websocket.send_text(json.dumps({"type":"error","message":"Call not permitted"}))
            elif t == "subscribe":
                chat_id = int(data["chat_id"])
                await mgr.subscribe(ws_id, chat_id)
            elif t == "message":
                chat_id = int(data["chat_id"])
                text = data.get("text", "")
                if not isinstance(text, str) or len(text) > 10000:
                    await websocket.send_text(json.dumps({"type": "error", "message": "Messages must be text under 10000 characters"}))
                    continue
                text = text.strip()
                if not text:
                    continue
                conn = get_db()
                # verify membership
                member = conn.execute("SELECT 1 FROM chat_members WHERE chat_id=? AND user_id=?", (chat_id, uid)).fetchone()
                if not member:
                    conn.close(); continue
                cur = conn.execute("INSERT INTO messages (chat_id, sender_id, text, created_at,expires_at) VALUES (?,?,?,?,?)",
                                   (chat_id, uid, text, now_iso(),social.expiry_for(conn,chat_id)))
                msg_id = cur.lastrowid
                sender = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
                conn.commit(); conn.close()
                payload = {
                    "type": "message",
                    "id": msg_id, "chat_id": chat_id,
                    "sender": user_public(sender),
                    "text": text,
                    "time": fmt_time(now_iso()),
                    "iso": now_iso(),
                    "mine": False,
                }
                SOCIAL_HOOKS["notify_message"](msg_id)
                # Send the complete message to every linked device immediately.
                # This avoids a follow-up REST fetch for ordinary new messages.
                await FEATURE_HOOKS["changed"](chat_id, payload)
            elif t == "typing":
                chat_id = int(data["chat_id"])
                is_typing = bool(data.get("typing", True))
                await mgr.broadcast_chat(chat_id, {"type":"typing","chat_id":chat_id,"user_id":uid,"typing":is_typing}, exclude_ws=ws_id)
            elif t == "ping":
                await websocket.send_text(json.dumps({"type":"pong"}))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        mgr.disconnect(ws_id)

FEATURE_HOOKS = features.install(app, globals())
PUSH_MESSAGE = push_notifications.install(app, globals())
SOCIAL_HOOKS = social.install(app, globals(),FEATURE_HOOKS)
consume_registration = account_security.install(app, globals())

# ---------- Static serving ----------
# SPA fallback: serve index.html for non-API routes
@app.get("/")
def root():
    return FileResponse(STATIC_DIR / "index.html")

@app.get("/service-worker.js")
def service_worker():
    return FileResponse(STATIC_DIR / "service-worker.js", media_type="application/javascript", headers={"Cache-Control":"no-cache","Service-Worker-Allowed":"/"})

@app.get("/.well-known/assetlinks.json")
def android_assetlinks():
    return FileResponse(STATIC_DIR / "assetlinks.json", media_type="application/json")

@app.get("/healthz")
def health():
    return {"ok": True}

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=os.environ.get("GOLDCHAT_HOST", "127.0.0.1"), port=int(os.environ.get("PORT", os.environ.get("GOLDCHAT_PORT", "8001"))), access_log=False)
