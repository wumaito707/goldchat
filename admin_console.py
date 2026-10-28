"""Owner-only account management and audited review of retained content."""
import hashlib
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

import cloud_media

# Provision only a specifically confirmed existing record, never the first
# signup or a matching display name. The owner confirmed this existing account.
OWNER_ACCOUNT = {'id':8,'username':'Jos','created_at':'2026-10-18T22:04:49.180156Z'}
ANNOUNCEMENT_LIFETIME_SECONDS = 2 * 60 * 60


def init_schema(conn):
    columns={row[1] for row in conn.execute('PRAGMA table_info(users)')}
    for name in ('suspended_at','deleted_at'):
        if name not in columns:
            conn.execute(f'ALTER TABLE users ADD COLUMN {name} REAL')
    conn.executescript('''
        CREATE TABLE IF NOT EXISTS admin_roles (
            user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
            role TEXT NOT NULL CHECK(role='owner'), created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS admin_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL,
            target_type TEXT NOT NULL, target_id INTEGER, reason TEXT NOT NULL,
            created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_admin_audit_created ON admin_audit(id);
        CREATE TABLE IF NOT EXISTS update_announcements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            author_id INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL,
            body TEXT NOT NULL, created_at REAL NOT NULL, expires_at REAL NOT NULL,
            withdrawn_at REAL);
        CREATE INDEX IF NOT EXISTS idx_update_announcements_expiry ON update_announcements(expires_at);
    ''')
    if OWNER_ACCOUNT:
        changed=conn.execute('''INSERT OR IGNORE INTO admin_roles(user_id,role,created_at)
            SELECT id,'owner',? FROM users WHERE id=? AND username=? AND created_at=?''',
            (datetime.now(timezone.utc).isoformat(), OWNER_ACCOUNT['id'], OWNER_ACCOUNT['username'], OWNER_ACCOUNT['created_at']))
        if changed.rowcount:
            conn.execute('INSERT INTO admin_audit(actor_id,action,target_type,target_id,reason,created_at) VALUES(?,?,?,?,?,?)',
                (OWNER_ACCOUNT['id'],'owner_provisioned','user',OWNER_ACCOUNT['id'],'Owner access configured by the project owner',datetime.now(timezone.utc).isoformat()))


class ReviewIn(BaseModel):
    reason: str = Field(min_length=10, max_length=500)
    before: int | None = Field(default=None, ge=1)

    @field_validator('reason')
    @classmethod
    def meaningful_reason(cls, value):
        value=value.strip()
        if len(value)<10:
            raise ValueError('Enter a support or moderation reason with at least 10 characters')
        return value


class SuspensionIn(ReviewIn):
    suspended: bool


class DeletionIn(ReviewIn):
    deleted: bool
    username_confirmation: str = Field(min_length=3,max_length=32)


class AnnouncementIn(BaseModel):
    title: str = Field(min_length=3,max_length=100)
    body: str = Field(min_length=1,max_length=700)

    @field_validator('title','body')
    @classmethod
    def trim_text(cls,value,info):
        value=value.strip()
        if len(value)<(3 if info.field_name=='title' else 1):
            raise ValueError('Enter announcement text')
        return value


def install(app, b):
    @contextmanager
    def db():
        conn=b['get_db'](cleanup=False)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def actor(token: str = Depends(b['session_token'])):
        # Recheck the session and role in the database on every admin request.
        # Normal chat-session caching never grants administrative privileges.
        with db() as conn:
            row=conn.execute('''SELECT u.id,u.username,u.suspended_at,u.deleted_at,r.role FROM sessions s
                JOIN users u ON u.id=s.user_id LEFT JOIN admin_roles r ON r.user_id=u.id
                WHERE s.token_hash=? AND s.expires_at>?''', (hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
        if row is None:
            raise HTTPException(401,'Sign in to GOLDCHAT to continue')
        if row['suspended_at'] is not None or row['deleted_at'] is not None or row['role']!='owner':
            raise HTTPException(403,'Owner access is required')
        return row

    def audit(conn, owner, action, kind, target, reason):
        conn.execute('INSERT INTO admin_audit(actor_id,action,target_type,target_id,reason,created_at) VALUES(?,?,?,?,?,?)',
            (owner['id'],action,kind,target,reason,b['now_iso']()))

    def batches(conn, statements):
        return conn.query_batch(statements) if hasattr(conn,'query_batch') else [conn.execute(sql,args).fetchall() for sql,args in statements]

    def search_term(value):
        return '%'+value.strip().replace('!','!!').replace('%','!%').replace('_','!_')+'%'

    async def disconnect(uid):
        for wsid,info in list(b['mgr'].active.items()):
            if info['user_id']==uid:
                try:
                    await info['ws'].close(code=4401)
                except Exception:
                    pass
                b['mgr'].disconnect(wsid)

    @app.middleware('http')
    async def private_admin_responses(request, call_next):
        response=await call_next(request)
        if request.url.path.startswith('/api/admin/') or request.url.path=='/api/announcements':
            response.headers['Cache-Control']='no-store'
            response.headers['Pragma']='no-cache'
            response.headers['X-Content-Type-Options']='nosniff'
        return response

    @app.get('/api/admin/access')
    def access(token: str = Depends(b['session_token'])):
        try:
            owner=actor(token)
        except HTTPException as error:
            if error.status_code==403:
                return {'allowed':False}
            raise
        return {'allowed':True,'username':owner['username'],'role':'owner'}

    async def announce_changed():
        for uid in {info['user_id'] for info in list(b['mgr'].active.values())}:
            try:
                await b['mgr'].send_to_user(uid,{'type':'announcements_changed'})
            except Exception:
                # Periodic refresh also picks up updates after a disconnected socket.
                pass

    @app.get('/api/announcements')
    def active_announcement(token: str = Depends(b['session_token'])):
        b['auth_user'](token)
        now=time.time()
        with db() as conn:
            row=conn.execute('''SELECT id,title,body,created_at,expires_at FROM update_announcements
                WHERE withdrawn_at IS NULL AND expires_at>? ORDER BY id DESC LIMIT 1''',(now,)).fetchone()
        return {'announcement':dict(row) if row else None,'server_time':time.time()}

    @app.get('/api/admin/announcements')
    def announcements(owner=Depends(actor)):
        with db() as conn:
            rows=conn.execute('''SELECT id,title,body,created_at,expires_at,withdrawn_at
                FROM update_announcements ORDER BY id DESC LIMIT 20''').fetchall()
        return {'items':[dict(row) for row in rows],'server_time':time.time(),
                'lifetime_seconds':ANNOUNCEMENT_LIFETIME_SECONDS}

    @app.post('/api/admin/announcements')
    async def publish_announcement(body: AnnouncementIn, owner=Depends(actor)):
        now=time.time();expires=now+ANNOUNCEMENT_LIFETIME_SECONDS
        with db() as conn:
            conn.execute('UPDATE update_announcements SET withdrawn_at=? WHERE withdrawn_at IS NULL AND expires_at>?',(now,now))
            aid=conn.execute('INSERT INTO update_announcements(author_id,title,body,created_at,expires_at) VALUES(?,?,?,?,?)',
                (owner['id'],body.title,body.body,now,expires)).lastrowid
            audit(conn,owner,'update_announcement_published','announcement',aid,body.title)
        await announce_changed()
        return {'id':aid,'created_at':now,'expires_at':expires}

    @app.post('/api/admin/announcements/{aid}/withdraw')
    async def withdraw_announcement(aid: int, body: ReviewIn, owner=Depends(actor)):
        with db() as conn:
            if not conn.execute('SELECT 1 FROM update_announcements WHERE id=?',(aid,)).fetchone():
                raise HTTPException(404,'Announcement not found')
            conn.execute('UPDATE update_announcements SET withdrawn_at=COALESCE(withdrawn_at,?) WHERE id=?',(time.time(),aid))
            audit(conn,owner,'update_announcement_withdrawn','announcement',aid,body.reason)
        await announce_changed()
        return {'ok':True}

    @app.get('/api/admin/overview')
    def overview(owner=Depends(actor)):
        day=datetime.fromtimestamp(time.time()-86400,timezone.utc).isoformat().replace('+00:00','Z')
        with db() as conn:
            counts=conn.execute('''SELECT
                (SELECT COUNT(*) FROM users) AS users,
                (SELECT COUNT(*) FROM users WHERE created_at>=?) AS signups_24h,
                (SELECT COUNT(*) FROM users WHERE suspended_at IS NOT NULL) AS suspended,
                (SELECT COUNT(*) FROM users WHERE deleted_at IS NOT NULL) AS deleted_accounts,
                (SELECT COUNT(*) FROM chats) AS conversations,
                (SELECT COUNT(*) FROM messages WHERE deleted=0 AND (expires_at IS NULL OR expires_at>?)) AS messages,
                (SELECT COUNT(*) FROM statuses WHERE expires_at>?) AS statuses,
                (SELECT COUNT(DISTINCT user_id) FROM sessions WHERE expires_at>?) AS signed_in_accounts,
                (SELECT COUNT(*) FROM call_history WHERE created_at>?) AS calls_24h''',
                (day,time.time(),time.time(),time.time(),time.time()-86400)).fetchone()
            recent=conn.execute('SELECT id,username,display_name,created_at FROM users ORDER BY id DESC LIMIT 8').fetchall()
        return {'counts':dict(counts),'recent_users':[dict(row) for row in recent],
            'service':{'email_configured':b['account_security'].delivery_ready('email'),
                       'google_configured':bool(b['google_client_id']()),
                       'push_configured':b['push_notifications'].configured(),
                       'cloud_storage':cloud_media.configured()},'checked_at':b['now_iso']()}

    @app.get('/api/admin/users')
    def users(q: str = Query('',max_length=80), state: str = Query('all',pattern='^(all|active|banned|deleted)$'), offset: int = Query(0,ge=0), owner=Depends(actor)):
        term=search_term(q)
        where="(u.username LIKE ? ESCAPE '!' OR u.display_name LIKE ? ESCAPE '!' OR u.verified_email LIKE ? ESCAPE '!')"
        where += {'all':'','active':' AND u.suspended_at IS NULL AND u.deleted_at IS NULL','banned':' AND u.suspended_at IS NOT NULL AND u.deleted_at IS NULL','deleted':' AND u.deleted_at IS NOT NULL'}[state]
        with db() as conn:
            results=batches(conn,[(f'SELECT COUNT(*) AS total FROM users u WHERE {where}',(term,term,term)),
                (f'''SELECT u.id,u.username,u.display_name,u.verified_email,u.created_at,u.suspended_at,u.deleted_at,
                    u.last_seen_at,(u.google_sub IS NOT NULL) AS google_linked,
                    (SELECT COUNT(*) FROM messages m WHERE m.sender_id=u.id AND m.deleted=0 AND (m.expires_at IS NULL OR m.expires_at>?)) AS message_count,
                    (SELECT COUNT(*) FROM chat_members cm WHERE cm.user_id=u.id) AS chat_count,
                    EXISTS(SELECT 1 FROM admin_roles r WHERE r.user_id=u.id) AS is_owner
                    FROM users u WHERE {where} ORDER BY u.id DESC LIMIT 25 OFFSET ?''',
                 (time.time(),term,term,term,offset))])
        return {'total':results[0][0]['total'],'items':[dict(row) for row in results[1]],'offset':offset,'limit':25}

    @app.get('/api/admin/chats')
    def chats(user_id: int | None = Query(None,ge=1), q: str = Query('',max_length=80), offset: int = Query(0,ge=0), owner=Depends(actor)):
        term=search_term(q)
        where="""(? IS NULL OR EXISTS(SELECT 1 FROM chat_members f WHERE f.chat_id=c.id AND f.user_id=?))
            AND (COALESCE(c.title,'') LIKE ? ESCAPE '!' OR EXISTS(SELECT 1 FROM chat_members f JOIN users u ON u.id=f.user_id WHERE f.chat_id=c.id AND (u.username LIKE ? ESCAPE '!' OR u.display_name LIKE ? ESCAPE '!')))"""
        args=(user_id,user_id,term,term,term)
        with db() as conn:
            results=batches(conn,[(f'SELECT COUNT(*) AS total FROM chats c WHERE {where}',args),
                (f'''SELECT c.id,c.type,c.title,c.created_at,
                    (SELECT GROUP_CONCAT(u.username,', ') FROM chat_members cm JOIN users u ON u.id=cm.user_id WHERE cm.chat_id=c.id) AS participants,
                    (SELECT COUNT(*) FROM messages m WHERE m.chat_id=c.id AND m.deleted=0 AND (m.expires_at IS NULL OR m.expires_at>?)) AS message_count
                    FROM chats c WHERE {where} ORDER BY c.id DESC LIMIT 25 OFFSET ?''', (time.time(),*args,offset))])
        return {'total':results[0][0]['total'],'items':[dict(row) for row in results[1]],'offset':offset,'limit':25}

    @app.post('/api/admin/chats/{cid}/messages')
    def messages(cid: int, body: ReviewIn, owner=Depends(actor)):
        with db() as conn:
            chat=conn.execute('SELECT id,type,title FROM chats WHERE id=?',(cid,)).fetchone()
            if not chat:
                raise HTTPException(404,'Conversation not found')
            rows=conn.execute('''SELECT m.id,m.sender_id,u.username,u.display_name,
                CASE WHEN m.deleted=1 THEN '' ELSE m.text END AS text,m.created_at,m.deleted,m.edited_at,
                CASE WHEN m.deleted=0 THEN a.id END AS attachment_id,
                CASE WHEN m.deleted=0 THEN a.name END AS attachment_name,
                CASE WHEN m.deleted=0 THEN a.mime END AS attachment_mime
                FROM messages m JOIN users u ON u.id=m.sender_id LEFT JOIN attachments a ON a.id=m.attachment_id
                WHERE m.chat_id=? AND (m.expires_at IS NULL OR m.expires_at>?) AND (? IS NULL OR m.id<?)
                ORDER BY m.id DESC LIMIT 51''',(cid,time.time(),body.before,body.before)).fetchall()
            audit(conn,owner,'messages_reviewed','chat',cid,body.reason)
            items=[dict(row) for row in reversed(rows[:50])]
        return {'chat':dict(chat),'items':items,'has_more':len(rows)>50,'before':items[0]['id'] if items else None}

    @app.post('/api/admin/statuses/review')
    def statuses(body: ReviewIn, owner=Depends(actor)):
        with db() as conn:
            rows=conn.execute('''SELECT s.id,s.user_id,u.username,u.display_name,s.text,s.audience,s.created_at,s.expires_at,
                sm.id AS media_id,sm.name AS media_name,sm.mime AS media_mime FROM statuses s
                JOIN users u ON u.id=s.user_id LEFT JOIN social_media sm ON sm.id=s.media_id
                WHERE s.expires_at>? AND (? IS NULL OR s.id<?) ORDER BY s.id DESC LIMIT 51''',
                (time.time(),body.before,body.before)).fetchall()
            audit(conn,owner,'statuses_reviewed','status',None,body.reason)
        return {'items':[dict(row) for row in rows[:50]],'has_more':len(rows)>50,'before':rows[min(49,len(rows)-1)]['id'] if rows else None}

    @app.post('/api/admin/media/{kind}/{mid}/review')
    def media(kind: str, mid: int, body: ReviewIn, owner=Depends(actor)):
        with db() as conn:
            if kind=='attachment':
                row=conn.execute('''SELECT a.path,a.mime,a.name FROM attachments a WHERE a.id=?
                    AND (a.expires_at IS NULL OR a.expires_at>?) AND EXISTS(SELECT 1 FROM messages m
                    WHERE m.attachment_id=a.id AND m.deleted=0 AND (m.expires_at IS NULL OR m.expires_at>?))''', (mid,time.time(),time.time())).fetchone()
                root=b['DATA_DIR']/'uploads'
            elif kind=='status':
                row=conn.execute('''SELECT sm.path,sm.mime,sm.name FROM social_media sm WHERE sm.id=?
                    AND EXISTS(SELECT 1 FROM statuses s WHERE s.media_id=sm.id AND s.expires_at>?)''', (mid,time.time())).fetchone()
                root=b['DATA_DIR']/'social-media'
            else:
                raise HTTPException(404,'Media not found')
            if not row or row['path'] in ('.','..') or '/' in row['path'] or '\\' in row['path'] or Path(row['path']).name!=row['path']:
                raise HTTPException(404,'Media unavailable')
            audit(conn,owner,'media_reviewed',kind,mid,body.reason)
        # Commit the audit before retrieving or returning the private object.
        headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'}
        return cloud_media.response(root,row['path'],row['mime'],headers,filename=row['name'])

    @app.get('/api/admin/calls')
    def calls(offset: int = Query(0,ge=0), owner=Depends(actor)):
        with db() as conn:
            results=batches(conn,[('SELECT COUNT(*) AS total FROM call_history',()),('''SELECT h.id,h.chat_id,h.video,h.status,h.created_at,h.connected_at,h.ended_at,
                u.username AS caller,v.username AS callee FROM call_history h JOIN users u ON u.id=h.caller_id
                JOIN users v ON v.id=h.callee_id ORDER BY h.created_at DESC LIMIT 50 OFFSET ?''',(offset,))])
            audit(conn,owner,'call_history_viewed','calls',None,'Owner reviewed call history metadata')
        return {'items':[dict(row) for row in results[1]],'total':results[0][0]['total'],'offset':offset,'limit':50}

    @app.get('/api/admin/audit')
    def audit_log(before: int | None = Query(None,ge=1), owner=Depends(actor)):
        with db() as conn:
            rows=conn.execute('''SELECT a.id,a.action,a.target_type,a.target_id,a.reason,a.created_at,u.username AS actor
                FROM admin_audit a JOIN users u ON u.id=a.actor_id WHERE (? IS NULL OR a.id<?)
                ORDER BY a.id DESC LIMIT 51''',(before,before)).fetchall()
        return {'items':[dict(row) for row in rows[:50]],'has_more':len(rows)>50,'before':rows[min(49,len(rows)-1)]['id'] if rows else None}

    @app.post('/api/admin/users/{uid}/suspension')
    async def suspension(uid: int, body: SuspensionIn, owner=Depends(actor)):
        with db() as conn:
            if not conn.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():
                raise HTTPException(404,'Account not found')
            if conn.execute('SELECT 1 FROM admin_roles WHERE user_id=?',(uid,)).fetchone():
                raise HTTPException(400,'Owner accounts cannot be suspended here')
            conn.execute('UPDATE users SET suspended_at=? WHERE id=?',(time.time() if body.suspended else None,uid))
            if body.suspended:
                conn.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
            audit(conn,owner,'account_suspended' if body.suspended else 'account_restored','user',uid,body.reason)
        if body.suspended:
            await disconnect(uid)
        return {'ok':True,'suspended':body.suspended}

    @app.post('/api/admin/users/{uid}/sign-out')
    async def sign_out(uid: int, body: ReviewIn, owner=Depends(actor)):
        with db() as conn:
            if not conn.execute('SELECT 1 FROM users WHERE id=?',(uid,)).fetchone():
                raise HTTPException(404,'Account not found')
            if conn.execute('SELECT 1 FROM admin_roles WHERE user_id=?',(uid,)).fetchone():
                raise HTTPException(400,'Manage owner sessions from Linked devices')
            conn.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
            audit(conn,owner,'account_signed_out','user',uid,body.reason)
        await disconnect(uid)
        return {'ok':True}

    @app.post('/api/admin/users/{uid}/deletion')
    async def deletion(uid: int, body: DeletionIn, owner=Depends(actor)):
        with db() as conn:
            target=conn.execute('SELECT username FROM users WHERE id=?',(uid,)).fetchone()
            if not target:
                raise HTTPException(404,'Account not found')
            if conn.execute('SELECT 1 FROM admin_roles WHERE user_id=?',(uid,)).fetchone():
                raise HTTPException(400,'Owner accounts cannot be deleted here')
            if body.username_confirmation!=target['username']:
                raise HTTPException(400,'Type the exact account username to confirm')
            conn.execute('UPDATE users SET deleted_at=? WHERE id=?',(time.time() if body.deleted else None,uid))
            if body.deleted:
                conn.execute('DELETE FROM sessions WHERE user_id=?',(uid,))
            audit(conn,owner,'account_deleted' if body.deleted else 'deleted_account_restored','user',uid,body.reason)
        if body.deleted:
            await disconnect(uid)
        return {'ok':True,'deleted':body.deleted}

    return {'actor':actor}
