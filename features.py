import base64
import binascii
import hashlib
import json
import secrets
import time
import social
import cloud_media
from contextlib import contextmanager
from pathlib import Path
from fastapi import HTTPException, Query, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

MAX_FILE_BYTES = 10 * 1024 * 1024


def init_schema(conn):
    for table, column, definition in [
        ('users', 'bio', "TEXT NOT NULL DEFAULT ''"),
        ('users', 'privacy', "TEXT NOT NULL DEFAULT 'contacts'"),
        ('chats', 'owner_id', 'INTEGER'),
        ('messages', 'edited_at', 'TEXT'),
        ('messages', 'deleted', 'INTEGER NOT NULL DEFAULT 0'),
        ('messages', 'reply_to', 'INTEGER'),
        ('messages', 'attachment_id', 'INTEGER'),
        ('messages', 'forwarded', 'INTEGER NOT NULL DEFAULT 0'),
    ]:
        columns = {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}
        if column not in columns:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS contacts (user_id INTEGER NOT NULL REFERENCES users(id), contact_id INTEGER NOT NULL REFERENCES users(id), PRIMARY KEY(user_id,contact_id));
    CREATE TABLE IF NOT EXISTS blocks (user_id INTEGER NOT NULL REFERENCES users(id), blocked_id INTEGER NOT NULL REFERENCES users(id), PRIMARY KEY(user_id,blocked_id));
    CREATE TABLE IF NOT EXISTS attachments (id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES chats(id), user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL, path TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS reactions (message_id INTEGER NOT NULL REFERENCES messages(id), user_id INTEGER NOT NULL REFERENCES users(id), emoji TEXT NOT NULL, PRIMARY KEY(message_id,user_id));
    CREATE TABLE IF NOT EXISTS stars (message_id INTEGER NOT NULL REFERENCES messages(id), user_id INTEGER NOT NULL REFERENCES users(id), PRIMARY KEY(message_id,user_id));
    CREATE TABLE IF NOT EXISTS chat_preferences (chat_id INTEGER NOT NULL REFERENCES chats(id), user_id INTEGER NOT NULL REFERENCES users(id), pinned INTEGER NOT NULL DEFAULT 0, archived INTEGER NOT NULL DEFAULT 0, muted INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(chat_id,user_id));
    CREATE TABLE IF NOT EXISTS statuses (id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), text TEXT NOT NULL, created_at TEXT NOT NULL, expires_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES chats(id), user_id INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL, starts_at TEXT NOT NULL, description TEXT NOT NULL DEFAULT '');
    CREATE TABLE IF NOT EXISTS polls (id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES chats(id), user_id INTEGER NOT NULL REFERENCES users(id), question TEXT NOT NULL, options TEXT NOT NULL, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS poll_votes (poll_id INTEGER NOT NULL REFERENCES polls(id), user_id INTEGER NOT NULL REFERENCES users(id), option_index INTEGER NOT NULL, PRIMARY KEY(poll_id,user_id));
    CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, chat_id INTEGER NOT NULL REFERENCES chats(id), user_id INTEGER NOT NULL REFERENCES users(id), title TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS message_pins (message_id INTEGER PRIMARY KEY REFERENCES messages(id), chat_id INTEGER NOT NULL REFERENCES chats(id), user_id INTEGER NOT NULL REFERENCES users(id));
    CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id,id);
    CREATE INDEX IF NOT EXISTS idx_members_user ON chat_members(user_id,chat_id);
    ''')


class GroupIn(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    member_ids: list[int] = Field(default_factory=list, max_length=100)
    kind: str = 'group'

class GroupUpdate(BaseModel):
    title: str = Field(min_length=1,max_length=80)

class OwnerUpdate(BaseModel):
    user_id: int

class ForwardIn(BaseModel):
    chat_id: int

class ProfileIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=80)
    bio: str = Field(default='', max_length=280)
    privacy: str = 'contacts'

class MessageIn(BaseModel):
    text: str = Field(default='', max_length=10000)
    reply_to: int | None = None
    attachment_id: int | None = None

class PhoneContactsIn(BaseModel):
    emails:list[str]=Field(default_factory=list,max_length=100)
    phones:list[str]=Field(default_factory=list,max_length=100)

class UploadIn(BaseModel):
    mime: str = ""
    name: str = Field(min_length=1, max_length=255)
    data: str = Field(max_length=14000000)

class ReactionIn(BaseModel):
    emoji: str = Field(min_length=1, max_length=16)

class PreferencesIn(BaseModel):
    pinned: bool = False
    archived: bool = False
    muted: bool = False

class StatusIn(BaseModel):
    text: str = Field(min_length=1, max_length=700)

class PollIn(BaseModel):
    question: str = Field(min_length=1,max_length=200)
    options: list[str] = Field(min_length=2,max_length=10)

class VoteIn(BaseModel):
    option_index: int

class TaskIn(BaseModel):
    title: str = Field(min_length=1,max_length=200)

class TaskUpdate(BaseModel):
    completed: bool

class ImportIn(BaseModel):
    messages: list[dict] = Field(max_length=500)

class EventIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    starts_at: str
    description: str = Field(default='', max_length=2000)


def install(app, b):
    db = b['get_db']
    auth = b['auth_user']
    member = b['require_member']
    public = b['user_public']
    now = b['now_iso']
    manager = b['mgr']
    uploads = b.get('DATA_DIR',b['BASE']) / 'uploads'

    @contextmanager
    def connection():
        conn=db()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def user(token):
        return auth(token)['id']

    def profile(row):
        return {**public(row), 'bio': row['bio'], 'privacy': row['privacy']}

    def message_row(mid, uid):
        with connection() as conn:
            row = conn.execute('SELECT * FROM messages WHERE id=?', (mid,)).fetchone()
            if not row:
                raise HTTPException(404, 'Message not found')
        conn.close()
        member(row['chat_id'], uid)
        return row

    def allowed_send(cid, uid):
        member(cid, uid)
        with connection() as conn:
            chat = conn.execute('SELECT * FROM chats WHERE id=?', (cid,)).fetchone()
            if chat['type'] == 'channel' and chat['owner_id'] != uid:
                raise HTTPException(403, 'Only the channel owner can post')
            blocked = conn.execute('''SELECT 1 FROM blocks b JOIN chat_members cm ON cm.user_id=b.blocked_id
                WHERE cm.chat_id=? AND b.user_id=? UNION SELECT 1 FROM blocks b JOIN chat_members cm ON cm.user_id=b.user_id
                WHERE cm.chat_id=? AND b.blocked_id=?''', (cid,uid,cid,uid)).fetchone()
            if blocked and chat['type'] == 'direct':
                raise HTTPException(403, 'Messaging is blocked for this contact')
        conn.close()

    def detail(row, uid, conn, cached=None):
        if cached is None:
            sender = conn.execute('SELECT * FROM users WHERE id=?', (row['sender_id'],)).fetchone()
            reacts = conn.execute('SELECT emoji,COUNT(*) AS count FROM reactions WHERE message_id=? GROUP BY emoji', (row['id'],)).fetchall()
            starred = bool(conn.execute('SELECT 1 FROM stars WHERE message_id=? AND user_id=?', (row['id'],uid)).fetchone())
            attachment = conn.execute('SELECT id,name,mime,size FROM attachments WHERE id=?', (row['attachment_id'],)).fetchone() if row['attachment_id'] and not row['deleted'] else None
            reply = conn.execute('SELECT id,text,deleted FROM messages WHERE id=?', (row['reply_to'],)).fetchone() if row['reply_to'] else None
            read = conn.execute('SELECT MIN(COALESCE(rs.last_read_msg_id,0)) AS n FROM chat_members cm LEFT JOIN read_state rs ON rs.chat_id=cm.chat_id AND rs.user_id=cm.user_id WHERE cm.chat_id=? AND cm.user_id!=?', (row['chat_id'],uid)).fetchone()['n']
        else:
            sender=cached['senders'][row['sender_id']]
            reacts=cached['reactions'].get(row['id'],[])
            starred=row['id'] in cached['stars']
            attachment=cached['attachments'].get(row['attachment_id']) if not row['deleted'] else None
            reply=cached['replies'].get(row['reply_to'])
            read=cached['read']
        return {'id':row['id'], 'chat_id':row['chat_id'], 'sender':public(sender), 'text':'Message deleted' if row['deleted'] else row['text'],
            'time':b['fmt_time'](row['created_at']), 'iso':row['created_at'], 'mine':row['sender_id']==uid, 'read':bool(read and read>=row['id']),
            'expires_at':row['expires_at'], 'forwarded':bool(row['forwarded']), 'edited':bool(row['edited_at']), 'deleted':bool(row['deleted']), 'attachment':dict(attachment) if attachment else None,
            'reply':{'id':reply['id'],'text':'Message deleted' if reply['deleted'] else reply['text']} if reply else None,
            'reactions':[dict(r) for r in reacts], 'starred':starred}

    async def changed(cid):
        with connection() as conn:
            ids=[r['user_id'] for r in conn.execute('SELECT user_id FROM chat_members WHERE chat_id=?',(cid,))]
        conn.close()
        for uid in ids:
            await manager.send_to_user(uid, {'type':'chat_changed','chat_id':cid})

    @app.get('/api/v2/chats')
    def chats(token: str = Depends(b["session_token"])):
        uid=user(token)
        results=b['chat_list_for'](uid)
        with connection() as conn:
            preferences={r['id']:r for r in conn.execute('SELECT c.id,c.owner_id,c.disappearing_seconds,p.pinned,p.archived,p.muted FROM chats c JOIN chat_members cm ON cm.chat_id=c.id LEFT JOIN chat_preferences p ON p.chat_id=c.id AND p.user_id=cm.user_id WHERE cm.user_id=?',(uid,))}
            for chat in results:
                pref=preferences[chat['id']]
                chat.update({k:pref[k] or 0 for k in ['pinned','archived','muted']})
                chat['owner_id']=pref['owner_id']
                chat['disappearing_seconds']=pref['disappearing_seconds']
                if chat['type']!='direct':
                    chat['peer']=None
                    chat['peer_online']=False
        conn.close()
        return sorted(results,key=lambda c:not c['pinned'])

    @app.get('/api/v2/chats/{cid}/messages')
    def messages(cid: int, token: str = Depends(b["session_token"]), q: str = '', before: int | None = None):
        uid=user(token); member(cid,uid)
        with connection() as conn:
            rows=conn.execute('SELECT * FROM messages WHERE chat_id=? AND NOT EXISTS(SELECT 1 FROM message_hidden h WHERE h.message_id=messages.id AND h.user_id=?) AND (? IS NULL OR id<?) AND (?=? OR (deleted=0 AND text LIKE ?)) ORDER BY id DESC LIMIT 50', (cid,uid,before,before,q,'','%'+q+'%')).fetchall()
            def related(table,column,ids,select='*',extra='',args=()):
                ids=list(set(v for v in ids if v is not None))
                if not ids:return []
                marks=','.join('?' for _ in ids)
                return conn.execute(f'SELECT {select} FROM {table} WHERE {column} IN ({marks}) {extra}',tuple(ids)+tuple(args)).fetchall()
            reactions={}
            for r in related('reactions','message_id',[r['id'] for r in rows],'message_id,emoji,COUNT(*) AS count','GROUP BY message_id,emoji'):
                reactions.setdefault(r['message_id'],[]).append({'emoji':r['emoji'],'count':r['count']})
            cached={
                'senders':{r['id']:r for r in related('users','id',[r['sender_id'] for r in rows])},
                'attachments':{r['id']:r for r in related('attachments','id',[r['attachment_id'] for r in rows if not r['deleted']],'id,name,mime,size')},
                'replies':{r['id']:r for r in related('messages','id',[r['reply_to'] for r in rows],'id,text,deleted')},
                'stars':{r['message_id'] for r in related('stars','message_id',[r['id'] for r in rows],'message_id','AND user_id=?',(uid,))},
                'reactions':reactions,
                'read':conn.execute('SELECT MIN(COALESCE(rs.last_read_msg_id,0)) AS n FROM chat_members cm LEFT JOIN read_state rs ON rs.chat_id=cm.chat_id AND rs.user_id=cm.user_id WHERE cm.chat_id=? AND cm.user_id!=?',(cid,uid)).fetchone()['n']}
            result=[detail(r,uid,conn,cached) for r in reversed(rows)]
        conn.close()
        return result

    @app.post('/api/groups')
    async def group(body: GroupIn, token: str = Depends(b["session_token"])):
        uid=user(token)
        ids=set(body.member_ids+[uid])
        if body.kind not in {'group','channel'} or not body.title.strip():
            raise HTTPException(400,'Choose a group or channel and a title')
        with connection() as conn:
            for mid in ids:
                if not conn.execute('SELECT 1 FROM users WHERE id=?',(mid,)).fetchone():
                    raise HTTPException(404,'Member not found')
            cid=conn.execute('INSERT INTO chats(type,title,created_at,owner_id) VALUES(?,?,?,?)',(body.kind,body.title.strip(),now(),uid)).lastrowid
            conn.executemany('INSERT INTO chat_members(chat_id,user_id,joined_at) VALUES(?,?,?)',[(cid,mid,now()) for mid in ids])
        conn.close()
        await changed(cid)
        return {'chat_id':cid}

    @app.post('/api/groups/{cid}/members/{mid}')
    async def add_member(cid:int, mid:int, token:str=Depends(b["session_token"])):
        uid=user(token); member(cid,uid)
        with connection() as conn:
            chat=conn.execute('SELECT * FROM chats WHERE id=?',(cid,)).fetchone()
            if chat['type']=='direct' or chat['owner_id']!=uid:
                raise HTTPException(403,'Only the owner can add members')
            if not conn.execute('SELECT 1 FROM users WHERE id=?',(mid,)).fetchone():
                raise HTTPException(404,'User not found')
            conn.execute('INSERT OR IGNORE INTO chat_members VALUES(?,?,?)',(cid,mid,now()))
        conn.close(); await changed(cid)
        return {'ok':True}

    def owner_chat(cid,uid):
        member(cid,uid)
        with connection() as conn:chat=conn.execute('SELECT * FROM chats WHERE id=?',(cid,)).fetchone()
        if chat['type']=='direct' or chat['owner_id']!=uid:
            raise HTTPException(403,'Only the group or channel owner can do this')
        return chat

    async def remove_membership(cid,uid):
        for wsid in list(b['ONLINE'].get(uid,set())):
            info=manager.active.get(wsid)
            if info:
                info['chat_ids'].discard(cid)
                b['SUBSCRIBED'].get(cid,set()).discard(wsid)
        await manager.send_to_user(uid,{'type':'membership_removed','chat_id':cid})

    @app.patch('/api/groups/{cid}')
    async def rename_group(cid:int,body:GroupUpdate,token:str=Depends(b["session_token"])):
        uid=user(token);owner_chat(cid,uid)
        if not body.title.strip():raise HTTPException(400,'Choose a name')
        with connection() as conn:conn.execute('UPDATE chats SET title=? WHERE id=?',(body.title.strip(),cid))
        await changed(cid);return {'ok':True}

    @app.delete('/api/groups/{cid}/members/{mid}')
    async def remove_member(cid:int,mid:int,token:str=Depends(b["session_token"])):
        uid=user(token);owner_chat(cid,uid)
        if mid==uid:raise HTTPException(400,'Transfer ownership before leaving')
        member(cid,mid)
        with connection() as conn:
            conn.execute('DELETE FROM chat_members WHERE chat_id=? AND user_id=?',(cid,mid))
        await remove_membership(cid,mid);await changed(cid);return {'ok':True}

    @app.post('/api/groups/{cid}/owner')
    async def transfer_owner(cid:int,body:OwnerUpdate,token:str=Depends(b["session_token"])):
        uid=user(token);owner_chat(cid,uid);member(cid,body.user_id)
        with connection() as conn:conn.execute('UPDATE chats SET owner_id=? WHERE id=?',(body.user_id,cid))
        await changed(cid);return {'ok':True}

    @app.post('/api/groups/{cid}/leave')
    async def leave(cid:int, token:str=Depends(b["session_token"])):
        uid=user(token); member(cid,uid)
        with connection() as conn:
            chat=conn.execute('SELECT * FROM chats WHERE id=?',(cid,)).fetchone()
            if chat['type']=='direct' or chat['owner_id']==uid:
                raise HTTPException(400,'The owner must keep managing this group')
            conn.execute('DELETE FROM chat_members WHERE chat_id=? AND user_id=?',(cid,uid))
        conn.close()
        for wsid in list(b['ONLINE'].get(uid,set())):
            info=manager.active.get(wsid)
            if info:
                info['chat_ids'].discard(cid)
                b['SUBSCRIBED'].get(cid,set()).discard(wsid)
        await changed(cid)
        return {'ok':True}

    @app.get('/api/profile')
    def get_profile(token:str=Depends(b["session_token"])):
        return profile(auth(token))

    @app.patch('/api/profile')
    async def save_profile(body:ProfileIn, token:str=Depends(b["session_token"])):
        uid=user(token)
        if not body.display_name.strip() or body.privacy not in {'everyone','contacts','nobody'}:
            raise HTTPException(400,'Invalid profile settings')
        with connection() as conn:
            conn.execute('UPDATE users SET display_name=?,avatar_initial=?,bio=?,privacy=? WHERE id=?',(body.display_name.strip(),body.display_name.strip()[0].upper(),body.bio,body.privacy,uid))
            row=conn.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
        conn.close()
        with connection() as conn:
            cids=[r['chat_id'] for r in conn.execute('SELECT chat_id FROM chat_members WHERE user_id=?',(uid,))]
        for cid in cids: await changed(cid)
        await manager.send_to_user(uid,{'type':'profile_changed'})
        return profile(row)

    @app.post('/api/contacts/match-phone')
    def match_phone_contacts(body:PhoneContactsIn,token:str=Depends(b["session_token"])):
        uid=user(token)
        emails=list({address.strip().lower() for address in body.emails if len(address)<255})
        phones=list({number.strip() for number in body.phones if len(number)<32})
        clauses=[];args=[]
        for column,values in [('verified_email',emails),('verified_phone',phones)]:
            if values:clauses.append('LOWER('+column+') IN ('+','.join('?' for _ in values)+')');args.extend(values)
        if not clauses:return []
        with connection() as conn:
            rows=conn.execute('SELECT u.* FROM users u WHERE u.id!=? AND ('+' OR '.join(clauses)+') AND NOT EXISTS(SELECT 1 FROM blocks WHERE (user_id=? AND blocked_id=u.id) OR (user_id=u.id AND blocked_id=?))',[uid,*args,uid,uid]).fetchall()
            result=[public(row) for row in rows]
        conn.close();return result

    @app.get('/api/contacts')
    def contacts(token:str=Depends(b["session_token"])):
        uid=user(token)
        with connection() as conn:
            rows=conn.execute('SELECT u.* FROM contacts c JOIN users u ON c.contact_id=u.id WHERE c.user_id=? ORDER BY display_name',(uid,)).fetchall()
            result=[public(r) for r in rows]
        conn.close(); return result

    @app.post('/api/contacts/{mid}')
    def add_contact(mid:int, token:str=Depends(b["session_token"])):
        uid=user(token)
        with connection() as conn:
            if mid==uid or not conn.execute('SELECT 1 FROM users WHERE id=?',(mid,)).fetchone():
                raise HTTPException(400,'Choose another existing user')
            conn.execute('INSERT OR IGNORE INTO contacts VALUES(?,?)',(uid,mid))
        conn.close(); return {'ok':True}

    @app.delete('/api/contacts/{mid}')
    def delete_contact(mid:int, token:str=Depends(b["session_token"])):
        uid=user(token)
        with connection() as conn: conn.execute('DELETE FROM contacts WHERE user_id=? AND contact_id=?',(uid,mid))
        conn.close(); return {'ok':True}

    @app.get('/api/blocks')
    def blocks(token:str=Depends(b["session_token"])):
        uid=user(token)
        with connection() as conn:
            rows=conn.execute('SELECT u.* FROM blocks b JOIN users u ON u.id=b.blocked_id WHERE b.user_id=?',(uid,)).fetchall()
            result=[public(r) for r in rows]
        conn.close(); return result

    @app.post('/api/blocks/{mid}')
    def block(mid:int, token:str=Depends(b["session_token"])):
        uid=user(token)
        with connection() as conn:
            if mid==uid or not conn.execute('SELECT 1 FROM users WHERE id=?',(mid,)).fetchone():
                raise HTTPException(400,'Choose another existing user')
            conn.execute('INSERT OR IGNORE INTO blocks VALUES(?,?)',(uid,mid))
        conn.close(); return {'ok':True}

    @app.delete('/api/blocks/{mid}')
    def unblock(mid:int, token:str=Depends(b["session_token"])):
        uid=user(token)
        with connection() as conn: conn.execute('DELETE FROM blocks WHERE user_id=? AND blocked_id=?',(uid,mid))
        conn.close(); return {'ok':True}

    @app.post('/api/chats/{cid}/preferences')
    def preferences(cid:int, body:PreferencesIn, token:str=Depends(b["session_token"])):
        uid=user(token); member(cid,uid)
        with connection() as conn:
            conn.execute('INSERT INTO chat_preferences VALUES(?,?,?,?,?) ON CONFLICT(chat_id,user_id) DO UPDATE SET pinned=excluded.pinned, archived=excluded.archived, muted=excluded.muted',(cid,uid,body.pinned,body.archived,body.muted))
        conn.close(); return {'ok':True}

    @app.post('/api/chats/{cid}/uploads')
    def upload(cid:int, body:UploadIn, token:str=Depends(b["session_token"])):
        uid=user(token); allowed_send(cid,uid)
        try: raw=base64.b64decode(body.data,validate=True)
        except (ValueError,binascii.Error): raise HTTPException(400,'Invalid file data')
        if not raw or len(raw)>MAX_FILE_BYTES: raise HTTPException(400,'Files must be between 1 byte and 10 MB')
        name=Path(body.name.replace('\\','/')).name
        safe_mimes={'.png':'image/png','.jpg':'image/jpeg','.jpeg':'image/jpeg','.gif':'image/gif','.webp':'image/webp','.mp4':'video/mp4','.webm':'video/webm','.m4a':'audio/mp4','.mp3':'audio/mpeg','.wav':'audio/wav','.ogg':'audio/ogg','.pdf':'application/pdf','.txt':'text/plain'}
        mime=safe_mimes.get(Path(name).suffix.lower(),'application/octet-stream')
        if Path(name).suffix.lower()=='.webm' and body.mime.split(';')[0]=='audio/webm': mime='audio/webm'
        # Serve downloads as attachments and never permit HTML/SVG execution.
        uploads.mkdir(exist_ok=True)
        key=secrets.token_hex(24)
        dest=uploads/key
        cloud_media.put(uploads,key,raw,mime)
        try:
            with connection() as conn:
                aid=conn.execute('INSERT INTO attachments(chat_id,user_id,name,path,mime,size) VALUES(?,?,?,?,?,?)',(cid,uid,name,key,mime,len(raw))).lastrowid
            conn.close()
        except Exception:
            dest.unlink(missing_ok=True); raise
        return {'id':aid,'name':name,'mime':mime,'size':len(raw)}

    @app.get('/api/attachments/{aid}')
    def download(aid:int, token:str=Depends(b["session_token"]), inline:bool=False):
        uid=user(token)
        with connection() as conn: row=conn.execute('SELECT * FROM attachments WHERE id=?',(aid,)).fetchone()
        conn.close()
        if not row: raise HTTPException(404,'File not found')
        if row['expires_at'] and row['expires_at']<=time.time():raise HTTPException(404,'Attachment expired')
        member(row['chat_id'],uid)
        if not cloud_media.exists(uploads,row['path']): raise HTTPException(404,'File unavailable')
        headers={'X-Content-Type-Options':'nosniff','Cache-Control':'private, no-store','Referrer-Policy':'no-referrer'}
        if inline:
            if row['mime'] not in {'image/png','image/jpeg','image/gif','image/webp','video/mp4','video/webm','audio/webm','audio/mp4','audio/mpeg','audio/wav','audio/ogg'}:
                raise HTTPException(400,'This file type cannot be previewed')
            headers['Content-Disposition']='inline'
            return cloud_media.response(uploads,row['path'],row['mime'],headers)
        return cloud_media.response(uploads,row['path'],row['mime'],headers,filename=row['name'])

    @app.post('/api/chats/{cid}/messages')
    async def send(cid:int, body:MessageIn, token:str=Depends(b["session_token"])):
        uid=user(token); allowed_send(cid,uid)
        text=body.text.strip()
        if not text and not body.attachment_id: raise HTTPException(400,'Write a message or attach a file')
        with connection() as conn:
            if body.reply_to and not conn.execute('SELECT 1 FROM messages WHERE id=? AND chat_id=? AND deleted=0',(body.reply_to,cid)).fetchone():
                raise HTTPException(400,'Reply must reference a message in this chat')
            if body.attachment_id and not conn.execute('SELECT 1 FROM attachments WHERE id=? AND chat_id=? AND user_id=?',(body.attachment_id,cid,uid)).fetchone():
                raise HTTPException(400,'Attachment must belong to you and this chat')
            mid=conn.execute('INSERT INTO messages(chat_id,sender_id,text,created_at,reply_to,attachment_id,expires_at) VALUES(?,?,?,?,?,?,?)',(cid,uid,text,now(),body.reply_to,body.attachment_id,social.expiry_for(conn,cid))).lastrowid
            row=conn.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
            if body.attachment_id and row['expires_at']:
                conn.execute('UPDATE attachments SET expires_at=CASE WHEN expires_at IS NULL THEN ? ELSE MIN(expires_at,?) END WHERE id=?',(row['expires_at'],row['expires_at'],body.attachment_id))
            result=detail(row,uid,conn)
        conn.close(); b["SOCIAL_HOOKS"]["notify_message"](mid); await changed(cid)
        return result

    @app.post('/api/messages/{mid}/forward')
    async def forward(mid:int,body:ForwardIn,token:str=Depends(b["session_token"])):
        uid=user(token);source=message_row(mid,uid);allowed_send(body.chat_id,uid)
        if source['deleted']:raise HTTPException(400,'Deleted messages cannot be forwarded')
        with connection() as conn:
            aid=None
            if source['attachment_id']:
                file=conn.execute('SELECT * FROM attachments WHERE id=?',(source['attachment_id'],)).fetchone()
                if not file or not cloud_media.exists(uploads,file['path']):raise HTTPException(404,'Attachment unavailable')
                aid=conn.execute('INSERT INTO attachments(chat_id,user_id,name,path,mime,size) VALUES(?,?,?,?,?,?)',(body.chat_id,uid,file['name'],file['path'],file['mime'],file['size'])).lastrowid
            new_id=conn.execute('INSERT INTO messages(chat_id,sender_id,text,created_at,attachment_id,forwarded,expires_at) VALUES(?,?,?,?,?,1,?)',(body.chat_id,uid,source['text'],now(),aid,social.expiry_for(conn,body.chat_id))).lastrowid
            row=conn.execute('SELECT * FROM messages WHERE id=?',(new_id,)).fetchone()
            if aid:conn.execute('UPDATE attachments SET expires_at=? WHERE id=?',(row['expires_at'],aid))
            result=detail(row,uid,conn)
        b["SOCIAL_HOOKS"]["notify_message"](new_id)
        await changed(body.chat_id);return result

    @app.patch('/api/messages/{mid}')
    async def edit(mid:int, body:MessageIn, token:str=Depends(b["session_token"])):
        uid=user(token); row=message_row(mid,uid)
        if row['sender_id']!=uid or row['deleted']: raise HTTPException(403,'Only your own active messages can be edited')
        if not body.text.strip(): raise HTTPException(400,'Message cannot be empty')
        with connection() as conn:
            conn.execute('UPDATE messages SET text=?,edited_at=? WHERE id=?',(body.text.strip(),now(),mid))
            conn.execute('UPDATE notifications SET body=? WHERE message_id=?',(body.text.strip()[:180],mid))
        conn.close(); await changed(row['chat_id']); return {'ok':True}

    @app.delete('/api/messages/{mid}')
    async def delete(mid:int, token:str=Depends(b["session_token"])):
        uid=user(token); row=message_row(mid,uid)
        if row['sender_id']!=uid: raise HTTPException(403,'Only your own messages can be deleted')
        with connection() as conn:
            conn.execute('UPDATE messages SET text=?,deleted=1 WHERE id=?',('',mid))
            conn.execute('DELETE FROM reactions WHERE message_id=?',(mid,))
            conn.execute('DELETE FROM notifications WHERE message_id=?',(mid,))
        conn.close(); await changed(row['chat_id']); return {'ok':True}

    @app.post('/api/messages/{mid}/reaction')
    async def react(mid:int, body:ReactionIn, token:str=Depends(b["session_token"])):
        uid=user(token); row=message_row(mid,uid)
        if row['deleted']: raise HTTPException(400,'Message was deleted')
        if body.emoji not in {'👍','❤️','😂','😮','😢','🙏'}: raise HTTPException(400,'Unsupported reaction')
        with connection() as conn:
            existing=conn.execute('SELECT emoji FROM reactions WHERE message_id=? AND user_id=?',(mid,uid)).fetchone()
            if existing and existing['emoji']==body.emoji:
                conn.execute('DELETE FROM reactions WHERE message_id=? AND user_id=?',(mid,uid))
            else:
                conn.execute('INSERT INTO reactions VALUES(?,?,?) ON CONFLICT(message_id,user_id) DO UPDATE SET emoji=excluded.emoji',(mid,uid,body.emoji))
        conn.close(); await changed(row['chat_id']); return {'ok':True}

    @app.post('/api/messages/{mid}/star')
    def star(mid:int, token:str=Depends(b["session_token"])):
        uid=user(token); message_row(mid,uid)
        with connection() as conn:
            exists=conn.execute('SELECT 1 FROM stars WHERE message_id=? AND user_id=?',(mid,uid)).fetchone()
            if exists: conn.execute('DELETE FROM stars WHERE message_id=? AND user_id=?',(mid,uid))
            else: conn.execute('INSERT INTO stars VALUES(?,?)',(mid,uid))
        conn.close(); return {'starred':not bool(exists)}

    @app.get('/api/stars')
    def stars(token:str=Depends(b["session_token"])):
        uid=user(token)
        with connection() as conn:
            rows=conn.execute('SELECT m.* FROM stars s JOIN messages m ON m.id=s.message_id JOIN chat_members cm ON cm.chat_id=m.chat_id AND cm.user_id=s.user_id WHERE s.user_id=? ORDER BY m.id DESC',(uid,)).fetchall()
            result=[detail(r,uid,conn) for r in rows]
        conn.close(); return result

    @app.get('/api/statuses')
    def statuses(token:str=Depends(b["session_token"])):
        uid=user(token)
        with connection() as conn:
            rows=conn.execute('''SELECT s.*,u.username,u.display_name,u.avatar_initial FROM statuses s JOIN users u ON u.id=s.user_id
            WHERE s.expires_at>? AND (s.user_id=? OR EXISTS(SELECT 1 FROM contacts c WHERE c.user_id=? AND c.contact_id=s.user_id))
            AND NOT EXISTS(SELECT 1 FROM blocks b WHERE (b.user_id=? AND b.blocked_id=s.user_id) OR (b.user_id=s.user_id AND b.blocked_id=?))
            AND (s.user_id=? OR u.privacy='everyone' OR (u.privacy='contacts' AND EXISTS(SELECT 1 FROM contacts c WHERE c.user_id=s.user_id AND c.contact_id=?)))
            ORDER BY s.id DESC''',(time.time(),uid,uid,uid,uid,uid,uid)).fetchall()
            result=[dict(r) for r in rows]
        conn.close(); return result

    @app.post('/api/statuses')
    def post_status(body:StatusIn, token:str=Depends(b["session_token"])):
        uid=user(token)
        if not body.text.strip(): raise HTTPException(400,'Write a status')
        with connection() as conn:
            sid=conn.execute('INSERT INTO statuses(user_id,text,created_at,expires_at) VALUES(?,?,?,?)',(uid,body.text.strip(),now(),time.time()+86400)).lastrowid
        conn.close(); return {'id':sid}

    @app.delete('/api/statuses/{sid}')
    def delete_status(sid:int, token:str=Depends(b["session_token"])):
        uid=user(token)
        with connection() as conn: conn.execute('DELETE FROM statuses WHERE id=? AND user_id=?',(sid,uid))
        conn.close(); return {'ok':True}

    @app.get('/api/chats/{cid}/events')
    def events(cid:int, token:str=Depends(b["session_token"])):
        uid=user(token); member(cid,uid)
        with connection() as conn: result=[dict(r) for r in conn.execute('SELECT * FROM events WHERE chat_id=? ORDER BY starts_at',(cid,))]
        conn.close(); return result

    @app.post('/api/chats/{cid}/events')
    async def add_event(cid:int, body:EventIn, token:str=Depends(b["session_token"])):
        from datetime import datetime
        uid=user(token); allowed_send(cid,uid)
        try:
            dt=datetime.fromisoformat(body.starts_at.replace('Z','+00:00'))
            if dt.tzinfo is None: raise ValueError()
        except ValueError: raise HTTPException(400,'Choose a valid date and time with a time zone')
        if not body.title.strip(): raise HTTPException(400,'Event needs a title')
        with connection() as conn:
            eid=conn.execute('INSERT INTO events(chat_id,user_id,title,starts_at,description) VALUES(?,?,?,?,?)',(cid,uid,body.title.strip(),dt.isoformat(),body.description)).lastrowid
        conn.close(); await changed(cid); return {'id':eid}

    @app.get('/api/export')
    def export(token:str=Depends(b["session_token"])):
        uid=user(token)
        with connection() as conn:
            cs=[dict(r) for r in conn.execute('SELECT c.* FROM chats c JOIN chat_members cm ON cm.chat_id=c.id WHERE cm.user_id=?',(uid,))]
            for c in cs:
                c['messages']=[detail(r,uid,conn) for r in conn.execute('SELECT * FROM messages WHERE chat_id=? AND NOT EXISTS(SELECT 1 FROM message_hidden h WHERE h.message_id=messages.id AND h.user_id=?) ORDER BY id',(c['id'],uid))]
            contacts=[public(r) for r in conn.execute('SELECT u.* FROM contacts c JOIN users u ON u.id=c.contact_id WHERE c.user_id=?',(uid,))]
        conn.close(); return {'format':'goldchat-export-v1','exported_at':now(),'profile':profile(auth(token)),'contacts':contacts,'chats':cs}

    @app.get('/api/chats/{cid}/polls')
    def polls(cid:int,token:str=Depends(b["session_token"])):
        uid=user(token);member(cid,uid)
        with connection() as conn:
            result=[]
            for row in conn.execute('SELECT * FROM polls WHERE chat_id=? ORDER BY id DESC',(cid,)):
                poll=dict(row);poll['options']=json.loads(poll['options'])
                counts={r['option_index']:r['n'] for r in conn.execute('SELECT option_index,COUNT(*) AS n FROM poll_votes WHERE poll_id=? GROUP BY option_index',(poll['id'],))}
                own=conn.execute('SELECT option_index FROM poll_votes WHERE poll_id=? AND user_id=?',(poll['id'],uid)).fetchone()
                poll['counts']=[counts.get(i,0) for i in range(len(poll['options']))];poll['my_vote']=own['option_index'] if own else None
                result.append(poll)
        return result

    @app.post('/api/chats/{cid}/polls')
    async def create_poll(cid:int,body:PollIn,token:str=Depends(b["session_token"])):
        uid=user(token);allowed_send(cid,uid)
        options=[x.strip() for x in body.options]
        if not body.question.strip() or any(not x or len(x)>100 for x in options) or len(set(options))!=len(options):
            raise HTTPException(400,'Use a question and 2-10 different options under 100 characters')
        with connection() as conn:
            pid=conn.execute('INSERT INTO polls(chat_id,user_id,question,options,created_at) VALUES(?,?,?,?,?)',(cid,uid,body.question.strip(),json.dumps(options),now())).lastrowid
        await changed(cid);return {'id':pid}

    @app.post('/api/polls/{pid}/vote')
    async def vote(pid:int,body:VoteIn,token:str=Depends(b["session_token"])):
        uid=user(token)
        with connection() as conn: row=conn.execute('SELECT * FROM polls WHERE id=?',(pid,)).fetchone()
        if not row:raise HTTPException(404,'Poll not found')
        member(row['chat_id'],uid)
        if not 0<=body.option_index<len(json.loads(row['options'])):raise HTTPException(400,'Invalid option')
        with connection() as conn:
            conn.execute('INSERT INTO poll_votes VALUES(?,?,?) ON CONFLICT(poll_id,user_id) DO UPDATE SET option_index=excluded.option_index',(pid,uid,body.option_index))
        await changed(row['chat_id']);return {'ok':True}

    @app.get('/api/chats/{cid}/tasks')
    def tasks(cid:int,token:str=Depends(b["session_token"])):
        uid=user(token);member(cid,uid)
        with connection() as conn:return [dict(r) for r in conn.execute('SELECT * FROM tasks WHERE chat_id=? ORDER BY completed,id DESC',(cid,))]

    @app.post('/api/chats/{cid}/tasks')
    async def create_task(cid:int,body:TaskIn,token:str=Depends(b["session_token"])):
        uid=user(token);allowed_send(cid,uid)
        if not body.title.strip():raise HTTPException(400,'Give the task a title')
        with connection() as conn:tid=conn.execute('INSERT INTO tasks(chat_id,user_id,title,created_at) VALUES(?,?,?,?)',(cid,uid,body.title.strip(),now())).lastrowid
        await changed(cid);return {'id':tid}

    @app.patch('/api/tasks/{tid}')
    async def update_task(tid:int,body:TaskUpdate,token:str=Depends(b["session_token"])):
        uid=user(token)
        with connection() as conn: row=conn.execute('SELECT * FROM tasks WHERE id=?',(tid,)).fetchone()
        if not row:raise HTTPException(404,'Task not found')
        allowed_send(row['chat_id'],uid)
        with connection() as conn:conn.execute('UPDATE tasks SET completed=? WHERE id=?',(body.completed,tid))
        await changed(row['chat_id']);return {'ok':True}

    @app.post('/api/messages/{mid}/pin')
    async def pin_message(mid:int,token:str=Depends(b["session_token"])):
        uid=user(token);row=message_row(mid,uid);allowed_send(row['chat_id'],uid)
        if row['deleted']:raise HTTPException(400,'Message was deleted')
        with connection() as conn:
            existing=conn.execute('SELECT 1 FROM message_pins WHERE message_id=?',(mid,)).fetchone()
            if existing:conn.execute('DELETE FROM message_pins WHERE message_id=?',(mid,))
            else:conn.execute('INSERT INTO message_pins VALUES(?,?,?)',(mid,row['chat_id'],uid))
        await changed(row['chat_id']);return {'pinned':not bool(existing)}

    @app.get('/api/chats/{cid}/pins')
    def pins(cid:int,token:str=Depends(b["session_token"])):
        uid=user(token);member(cid,uid)
        with connection() as conn:
            return [detail(r,uid,conn) for r in conn.execute('SELECT m.* FROM message_pins p JOIN messages m ON m.id=p.message_id WHERE p.chat_id=? AND m.deleted=0 ORDER BY m.id DESC',(cid,))]

    @app.post('/api/chats/{cid}/import')
    async def import_messages(cid:int,body:ImportIn,token:str=Depends(b["session_token"])):
        uid=user(token);allowed_send(cid,uid)
        texts=[]
        for item in body.messages:
            text=item.get('text','')
            if item.get('deleted') or not isinstance(text,str) or not text.strip():continue
            sender=item.get('sender') or {}
            name=sender.get('display_name','Unknown') if isinstance(sender,dict) else 'Unknown'
            if not isinstance(name,str):name='Unknown'
            text='[Imported from '+name[:80]+'] '+text
            if len(text)>10000:raise HTTPException(400,'Imported messages must be under 10000 characters')
            texts.append(text)
        with connection() as conn:
            conn.executemany('INSERT INTO messages(chat_id,sender_id,text,created_at,expires_at) VALUES(?,?,?,?,?)',[(cid,uid,text,now(),social.expiry_for(conn,cid)) for text in texts])
        await changed(cid);return {'imported':len(texts)}

    @app.get('/api/devices')
    def devices(token:str=Depends(b["session_token"])):
        uid=user(token)
        current=hashlib.sha256(token.encode()).hexdigest()
        with connection() as conn:
            rows=conn.execute('SELECT token_hash,expires_at,label,created_at FROM sessions WHERE user_id=? AND expires_at>? ORDER BY expires_at DESC',(uid,time.time())).fetchall()
        return [{'id':r['token_hash'],'expires_at':r['expires_at'],'current':r['token_hash']==current,'label':r['label'],'created_at':r['created_at']} for r in rows]

    @app.delete('/api/devices/{sid}')
    async def revoke_device(sid:str, token:str=Depends(b["session_token"])):
        uid=user(token)
        with connection() as conn:
            conn.execute('DELETE FROM sessions WHERE token_hash=? AND user_id=?',(sid,uid))
        for wsid,info in list(manager.active.items()):
            if info['user_id']==uid and hashlib.sha256(info.get('token','').encode()).hexdigest()==sid:
                await info['ws'].close(code=4401)
                manager.disconnect(wsid)
        return {'ok':True}

    @app.post('/api/contact-backup/import')
    def import_contacts(body:list[dict],token:str=Depends(b["session_token"])):
        uid=user(token)
        if len(body)>1000: raise HTTPException(400,'Import at most 1000 contacts at once')
        imported=0
        with connection() as conn:
            for entry in body:
                username=entry.get('username')
                if not isinstance(username,str): continue
                peer=conn.execute('SELECT id FROM users WHERE username=?',(username,)).fetchone()
                if peer and peer['id']!=uid:
                    cur=conn.execute('INSERT OR IGNORE INTO contacts VALUES(?,?)',(uid,peer['id']))
                    imported+=cur.rowcount
        return {'imported':imported}

    return {'allowed_send':allowed_send,'changed':changed}
