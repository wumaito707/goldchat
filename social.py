import cloud_media
"""Media statuses, profile pictures, notifications, QR linking and chat expiry."""
import base64,binascii,hashlib,io,json,secrets,time
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urlencode
from fastapi import HTTPException,Query,Request,Depends
from fastapi.responses import FileResponse,Response
from pydantic import BaseModel,Field

TIMERS={0,86400,604800,7776000}

def init_schema(conn):
    additions=[('users','avatar_media_id','INTEGER'),('messages','expires_at','REAL'),('attachments','expires_at','REAL'),('chats','disappearing_seconds','INTEGER NOT NULL DEFAULT 0'),('statuses','media_id','INTEGER'),('sessions','label',"TEXT NOT NULL DEFAULT 'Browser'"),('sessions','created_at','REAL NOT NULL DEFAULT 0')]
    for table,column,definition in additions:
        if column not in {r[1] for r in conn.execute(f'PRAGMA table_info({table})')}:
            conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS social_media(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),purpose TEXT NOT NULL,name TEXT NOT NULL,path TEXT NOT NULL,mime TEXT NOT NULL,size INTEGER NOT NULL,expires_at REAL);
    CREATE TABLE IF NOT EXISTS notifications(id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),kind TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,chat_id INTEGER,message_id INTEGER,created_at TEXT NOT NULL,read_at TEXT);
    CREATE TABLE IF NOT EXISTS device_links(id TEXT PRIMARY KEY,approval_hash TEXT NOT NULL,poll_hash TEXT NOT NULL,label TEXT NOT NULL,expires_at REAL NOT NULL,approved_uid INTEGER,consumed INTEGER NOT NULL DEFAULT 0);
    CREATE TABLE IF NOT EXISTS call_history(id TEXT PRIMARY KEY,chat_id INTEGER NOT NULL REFERENCES chats(id),caller_id INTEGER NOT NULL REFERENCES users(id),callee_id INTEGER NOT NULL REFERENCES users(id),video INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL,created_at REAL NOT NULL,connected_at REAL,ended_at REAL);
    CREATE TABLE IF NOT EXISTS message_hidden(message_id INTEGER NOT NULL REFERENCES messages(id),user_id INTEGER NOT NULL REFERENCES users(id),PRIMARY KEY(message_id,user_id));
    CREATE INDEX IF NOT EXISTS idx_message_expiry ON messages(expires_at);
    CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id,id);
    ''')

def cleanup_expired(conn):
    # Called before queries so expired content is not leaked by legacy endpoints.
    if 'expires_at' not in {r[1] for r in conn.execute('PRAGMA table_info(messages)')}:
        return
    now=time.time()
    expired=[r[0] for r in conn.execute('SELECT id FROM messages WHERE expires_at IS NOT NULL AND expires_at<=?',(now,))]
    if expired:
        marks=','.join('?' for _ in expired)
        for table,col in [('reactions','message_id'),('stars','message_id'),('message_pins','message_id'),('notifications','message_id'),('message_hidden','message_id')]:
            conn.execute(f'DELETE FROM {table} WHERE {col} IN ({marks})',expired)
        conn.execute(f'UPDATE messages SET reply_to=NULL WHERE reply_to IN ({marks})',expired)
        conn.execute(f'DELETE FROM messages WHERE id IN ({marks})',expired)
    conn.execute('DELETE FROM statuses WHERE expires_at<=?',(now,))
    conn.execute('DELETE FROM device_links WHERE expires_at<=?',(now,))
    for row in conn.execute("SELECT h.*,u.display_name FROM call_history h JOIN users u ON u.id=h.caller_id WHERE h.status='ringing' AND h.created_at<?",(now-90,)).fetchall():
        conn.execute("UPDATE call_history SET status='missed',ended_at=? WHERE id=?",(now,row['id']))
        conn.execute("INSERT INTO notifications(user_id,kind,title,body,chat_id,created_at) VALUES(?,?,?,?,?,?)",(row['callee_id'],'call','Missed call',row['display_name']+' called',row['chat_id'],datetime.fromtimestamp(now,timezone.utc).isoformat()))
    conn.commit()

def expiry_for(conn,cid):
    timer=conn.execute('SELECT disappearing_seconds FROM chats WHERE id=?',(cid,)).fetchone()
    return time.time()+timer[0] if timer and timer[0] else None

class MediaIn(BaseModel):
    purpose:str
    name:str=Field(min_length=1,max_length=255)
    data:str=Field(max_length=14000000)
    mime:str=''
class StatusIn(BaseModel):
    text:str=Field(default='',max_length=700)
    media_id:int|None=None
class TimerIn(BaseModel):
    seconds:int
class CookieIn(BaseModel):
    token:str

class LinkCreate(BaseModel):
    label:str=Field(default='Linked browser',min_length=1,max_length=80)
class LinkApproval(BaseModel):
    id:str
    challenge:str
class LinkPoll(BaseModel):
    poll_secret:str
class CallCreate(BaseModel):
    chat_id:int
    video:bool=False
class CallAction(BaseModel):
    action:str


def install(app,b,hooks):
    root=b['DATA_DIR']/'social-media'
    @contextmanager
    def db():
        conn=b['get_db']()
        try:
            with conn:yield conn
        finally:conn.close()
    def uid(token):return b['auth_user'](token)['id']
    def media_public(row):return {k:row[k] for k in ('id','name','mime','size')}
    def can_status(viewer,author,conn):
        if viewer==author:return True
        if conn.execute('SELECT 1 FROM blocks WHERE (user_id=? AND blocked_id=?) OR (user_id=? AND blocked_id=?)',(viewer,author,author,viewer)).fetchone():return False
        p=conn.execute('SELECT privacy FROM users WHERE id=?',(author,)).fetchone()
        follows=conn.execute('SELECT 1 FROM contacts WHERE user_id=? AND contact_id=?',(viewer,author)).fetchone()
        known=conn.execute('SELECT 1 FROM contacts WHERE user_id=? AND contact_id=?',(author,viewer)).fetchone()
        return bool(p and follows and (p[0]=='everyone' or (p[0]=='contacts' and known)))
    def qr(text):
        import qrcode
        from qrcode.image.svg import SvgPathImage
        image=qrcode.make(text,image_factory=SvgPathImage,box_size=8,border=4)
        out=io.BytesIO();image.save(out)
        return Response(out.getvalue(),media_type='image/svg+xml',headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff'})
    def alert(conn,user,kind,title,body,cid=None,mid=None):
        conn.execute('INSERT INTO notifications(user_id,kind,title,body,chat_id,message_id,created_at) VALUES(?,?,?,?,?,?,?)',(user,kind,title,body,cid,mid,b['now_iso']()))
    def notify_message(mid):
        with db() as conn:
            m=conn.execute('SELECT m.*,u.display_name FROM messages m JOIN users u ON u.id=m.sender_id WHERE m.id=?',(mid,)).fetchone()
            if not m:return
            for member in conn.execute('SELECT user_id FROM chat_members WHERE chat_id=? AND user_id!=?',(m['chat_id'],m['sender_id'])):
                alert(conn,member[0],'message',m['display_name'],m['text'][:180] or 'New attachment',m['chat_id'],mid)
    def call_row(call_id,user):
        with db() as conn:row=conn.execute('SELECT * FROM call_history WHERE id=?',(call_id,)).fetchone()
        if not row or user not in (row['caller_id'],row['callee_id']):raise HTTPException(404,'Call not found')
        return row
    def update_call(call_id,user,action):
        row=call_row(call_id,user)
        if row['ended_at']:return
        with db() as conn:
            if action=='connected':conn.execute("UPDATE call_history SET status='connected',connected_at=COALESCE(connected_at,?) WHERE id=?",(time.time(),call_id))
            elif action=='answer':
                if user!=row['callee_id']:raise HTTPException(403,'Only the recipient can answer')
                conn.execute("UPDATE call_history SET status='answered' WHERE id=?",(call_id,))
            else:
                status={'busy':'busy','unavailable':'unavailable','failed':'failed','missed':'missed'}.get(action)
                if status is None:status='completed' if row['connected_at'] else ('cancelled' if user==row['caller_id'] else 'declined')
                conn.execute('UPDATE call_history SET status=?,ended_at=? WHERE id=?',(status,time.time(),call_id))
                if not row['connected_at'] and status in {'missed','unavailable','cancelled'}:
                    alert(conn,row['callee_id'],'call','Missed call','Video call' if row['video'] else 'Voice call',row['chat_id'])
    def create_call(cid,user,video):
        hooks['allowed_send'](cid,user)
        with db() as conn:
            c=conn.execute('SELECT type FROM chats WHERE id=?',(cid,)).fetchone()
            peer=conn.execute('SELECT user_id FROM chat_members WHERE chat_id=? AND user_id!=?',(cid,user)).fetchone()
            if c[0]!='direct' or not peer:raise HTTPException(400,'Calls require a direct chat')
            cid_call=secrets.token_hex(16)
            conn.execute('INSERT INTO call_history(id,chat_id,caller_id,callee_id,video,status,created_at) VALUES(?,?,?,?,?,?,?)',(cid_call,cid,user,peer[0],video,'ringing',time.time()))
        return cid_call
    def record_signal(cid,user,signal):
        kind=signal['kind'];call_id=signal.get('call_id')
        if kind=='offer' and not call_id:call_id=create_call(cid,user,bool(signal.get('video')));signal['call_id']=call_id
        if not call_id:
            with db() as conn:
                row=conn.execute("SELECT id FROM call_history WHERE chat_id=? AND (caller_id=? OR callee_id=?) AND ended_at IS NULL ORDER BY created_at DESC LIMIT 1",(cid,user,user)).fetchone()
            if row:call_id=row[0];signal['call_id']=call_id
        if call_id:
            row=call_row(call_id,user)
            if row['chat_id']!=cid:raise HTTPException(403,'Call belongs to another chat')
            if kind=='offer' and row['caller_id']!=user:raise HTTPException(403,'Only the caller can send the offer')
            if kind in {'answer','hangup','busy','unavailable'}:update_call(call_id,user,kind)
        return call_id

    @app.post('/api/social/session-cookie')
    def session_cookie(body:CookieIn,request:Request):
        uid(body.token)
        response=Response(status_code=204)
        response.set_cookie('gc_session',body.token,httponly=True,secure=request.url.scheme=='https',samesite='strict',max_age=30*86400,path='/')
        return response

    @app.post('/api/social/media')
    async def upload_media(body:MediaIn,token:str=Depends(b["session_token"])):
        user=uid(token)
        if body.purpose not in {'avatar','status'}:raise HTTPException(400,'Invalid upload purpose')
        try:data=base64.b64decode(body.data,validate=True)
        except (ValueError,binascii.Error):raise HTTPException(400,'Invalid file data')
        if not 0<len(data)<=10*1024*1024:raise HTTPException(400,'Files must be between 1 byte and 10 MB')
        name=Path(body.name.replace('\\','/')).name
        mime=body.mime.split(';')[0]
        supported={'image/png','image/jpeg','image/gif','image/webp','audio/webm','audio/mp4','audio/mpeg','audio/wav','audio/ogg','video/mp4','video/webm'}
        if mime not in supported:raise HTTPException(400,'Choose a photo, video or audio file')
        if mime.startswith('image/'):
            from PIL import Image,ImageOps,UnidentifiedImageError
            try:
                im=Image.open(io.BytesIO(data))
                if im.width*im.height>25000000:raise ValueError('Image too large')
                im.verify()
                if body.purpose=='avatar':
                    im=Image.open(io.BytesIO(data));im=ImageOps.exif_transpose(im);im=ImageOps.fit(im.convert('RGB'),(512,512));out=io.BytesIO();im.save(out,format='PNG');data=out.getvalue();mime='image/png';name='avatar.png'
            except (UnidentifiedImageError,OSError,ValueError,Image.DecompressionBombError):raise HTTPException(400,'Invalid or oversized image')
        elif body.purpose=='avatar':raise HTTPException(400,'Profile pictures must be images')
        key=secrets.token_hex(24);cloud_media.put(root,key,data,mime)
        with db() as conn:
            mid=conn.execute('INSERT INTO social_media(user_id,purpose,name,path,mime,size,expires_at) VALUES(?,?,?,?,?,?,?)',(user,body.purpose,name,key,mime,len(data),None if body.purpose=='avatar' else time.time()+86400)).lastrowid
            if body.purpose=='avatar':conn.execute('UPDATE users SET avatar_media_id=? WHERE id=?',(mid,user))
            result=media_public(conn.execute('SELECT * FROM social_media WHERE id=?',(mid,)).fetchone())
            cids=[r[0] for r in conn.execute('SELECT chat_id FROM chat_members WHERE user_id=?',(user,))] if body.purpose=='avatar' else []
        for cid in cids:await hooks['changed'](cid)
        if body.purpose=='avatar':await b['mgr'].send_to_user(user,{'type':'profile_changed'})
        return result

    @app.delete('/api/social/avatar')
    async def remove_avatar(token:str=Depends(b["session_token"])):
        user=uid(token)
        with db() as conn:
            conn.execute('UPDATE users SET avatar_media_id=NULL WHERE id=?',(user,))
            cids=[r[0] for r in conn.execute('SELECT chat_id FROM chat_members WHERE user_id=?',(user,))]
        for cid in cids:await hooks['changed'](cid)
        await b['mgr'].send_to_user(user,{'type':'profile_changed'})
        return {'ok':True}

    @app.get('/api/social/media/{mid}')
    def get_media(mid:int,request:Request,token:str=Depends(b["session_token"])):
        user=uid(token or request.cookies.get('gc_session',''))
        with db() as conn:
            media=conn.execute('SELECT * FROM social_media WHERE id=?',(mid,)).fetchone()
            if not media:raise HTTPException(404,'Media unavailable')
            if media['expires_at'] and media['expires_at']<=time.time():raise HTTPException(404,'Status expired')
            if media['purpose']=='status' and user!=media['user_id']:
                active=conn.execute('SELECT 1 FROM statuses WHERE media_id=? AND expires_at>?',(mid,time.time())).fetchone()
                if not active or not can_status(user,media['user_id'],conn):raise HTTPException(403,'Status unavailable')
            elif media['purpose']=='avatar':
                if not conn.execute('SELECT 1 FROM users WHERE avatar_media_id=?',(mid,)).fetchone():raise HTTPException(404,'Profile picture removed')
        if not cloud_media.exists(root,media['path']):raise HTTPException(404,'Media unavailable')
        return cloud_media.response(root,media['path'],media['mime'],headers={'Content-Disposition':'inline','X-Content-Type-Options':'nosniff','Cache-Control':'private, no-store','Referrer-Policy':'no-referrer'})

    @app.get('/api/social/statuses')
    def statuses(token:str=Depends(b["session_token"])):
        user=uid(token)
        with db() as conn:
            result=[]
            for row in conn.execute('SELECT s.*,u.username,u.display_name,u.avatar_initial,u.avatar_media_id FROM statuses s JOIN users u ON u.id=s.user_id WHERE s.expires_at>? ORDER BY s.id DESC',(time.time(),)):
                if not can_status(user,row['user_id'],conn):continue
                status=dict(row);media=conn.execute('SELECT * FROM social_media WHERE id=?',(row['media_id'],)).fetchone() if row['media_id'] else None
                status['media']=media_public(media) if media else None;result.append(status)
        return result

    @app.post('/api/social/statuses')
    async def post_status(body:StatusIn,token:str=Depends(b["session_token"])):
        user=uid(token)
        if not body.text.strip() and not body.media_id:raise HTTPException(400,'Write text or choose a photo, video or audio file')
        deadline=time.time()+86400
        name=b['auth_user'](token)['display_name']
        with db() as conn:
            if body.media_id:
                media=conn.execute("SELECT * FROM social_media WHERE id=? AND user_id=? AND purpose='status'",(body.media_id,user)).fetchone()
                if not media or media['expires_at']<=time.time():raise HTTPException(400,'Upload your own status media first')
                if conn.execute('SELECT 1 FROM statuses WHERE media_id=?',(body.media_id,)).fetchone():raise HTTPException(400,'This media has already been posted')
                conn.execute('UPDATE social_media SET expires_at=? WHERE id=?',(deadline,body.media_id))
            sid=conn.execute('INSERT INTO statuses(user_id,text,media_id,created_at,expires_at) VALUES(?,?,?,?,?)',(user,body.text.strip(),body.media_id,b['now_iso'](),deadline)).lastrowid
            viewers=[r[0] for r in conn.execute('SELECT user_id FROM contacts WHERE contact_id=?',(user,))]
            for viewer in viewers:
                if can_status(viewer,user,conn):alert(conn,viewer,'status',name,'New status update')
        for viewer in viewers:await b['mgr'].send_to_user(viewer,{'type':'notifications_changed'})
        return {'id':sid,'expires_at':deadline}

    @app.delete('/api/social/statuses/{sid}')
    def delete_status(sid:int,token:str=Depends(b["session_token"])):
        user=uid(token)
        with db() as conn:
            row=conn.execute('SELECT * FROM statuses WHERE id=? AND user_id=?',(sid,user)).fetchone()
            if not row:raise HTTPException(404,'Status not found')
            conn.execute('DELETE FROM statuses WHERE id=?',(sid,))
            if row['media_id']:conn.execute('UPDATE social_media SET expires_at=? WHERE id=?',(time.time(),row['media_id']))
        return {'ok':True}

    @app.get('/api/social/notifications')
    def notifications(token:str=Depends(b["session_token"])):
        user=uid(token)
        with db() as conn:
            result=[dict(r) for r in conn.execute('SELECT n.* FROM notifications n WHERE user_id=? AND (chat_id IS NULL OR EXISTS(SELECT 1 FROM chat_members cm WHERE cm.chat_id=n.chat_id AND cm.user_id=?)) ORDER BY id DESC LIMIT 100',(user,user))]
            unread=conn.execute('SELECT COUNT(*) FROM notifications WHERE user_id=? AND read_at IS NULL AND (chat_id IS NULL OR EXISTS(SELECT 1 FROM chat_members WHERE chat_id=notifications.chat_id AND user_id=?))',(user,user)).fetchone()[0]
        return {'items':result,'unread':unread}

    @app.post('/api/social/notifications/read')
    def read_all_notifications(token:str=Depends(b["session_token"])):
        user=uid(token)
        with db() as conn:conn.execute('UPDATE notifications SET read_at=? WHERE user_id=? AND read_at IS NULL',(b['now_iso'](),user))
        return {'ok':True}

    @app.post('/api/social/notifications/{nid}/read')
    def read_notification(nid:int,token:str=Depends(b["session_token"])):
        user=uid(token)
        with db() as conn:conn.execute('UPDATE notifications SET read_at=? WHERE user_id=? AND id=?',(b['now_iso'](),user,nid))
        return {'ok':True}

    @app.get('/api/social/chats/{cid}/disappearing')
    def get_timer(cid:int,token:str=Depends(b["session_token"])):
        user=uid(token);b['require_member'](cid,user)
        with db() as conn:timer=conn.execute('SELECT disappearing_seconds FROM chats WHERE id=?',(cid,)).fetchone()[0]
        return {'seconds':timer,'options':sorted(TIMERS)}

    @app.post('/api/social/chats/{cid}/disappearing')
    async def set_timer(cid:int,body:TimerIn,token:str=Depends(b["session_token"])):
        user=uid(token);b['require_member'](cid,user)
        if body.seconds not in TIMERS:raise HTTPException(400,'Choose off, 24 hours, 7 days or 90 days')
        with db() as conn:
            chat=conn.execute('SELECT * FROM chats WHERE id=?',(cid,)).fetchone()
            if chat['type']!='direct' and chat['owner_id']!=user:raise HTTPException(403,'Only the owner can set the group timer')
            conn.execute('UPDATE chats SET disappearing_seconds=? WHERE id=?',(body.seconds,cid))
        await hooks['changed'](cid);return {'seconds':body.seconds}

    @app.post('/api/social/messages/{mid}/hide')
    async def hide_message(mid:int,token:str=Depends(b["session_token"])):
        user=uid(token)
        with db() as conn:row=conn.execute('SELECT * FROM messages WHERE id=?',(mid,)).fetchone()
        if not row:raise HTTPException(404,'Message not found')
        b['require_member'](row['chat_id'],user)
        with db() as conn:
            conn.execute('INSERT OR IGNORE INTO message_hidden VALUES(?,?)',(mid,user))
            conn.execute('DELETE FROM stars WHERE message_id=? AND user_id=?',(mid,user))
            conn.execute('DELETE FROM notifications WHERE message_id=? AND user_id=?',(mid,user))
        await b['mgr'].send_to_user(user,{'type':'chat_changed','chat_id':row['chat_id']})
        return {'ok':True}

    @app.get('/api/social/contact-qr')
    def contact_qr(request:Request,token:str=Depends(b["session_token"])):
        account=b['auth_user'](token or request.cookies.get('gc_session',''));url=str(request.base_url).rstrip('/')+'/?'+urlencode({'contact':account['username']})
        return qr(url)

    @app.get('/api/social/contact/{username}')
    def contact_lookup(username:str,token:str=Depends(b["session_token"])):
        uid(token)
        with db() as conn:row=conn.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
        if not row:raise HTTPException(404,'Contact not found')
        return b['user_public'](row)

    link_attempts={}
    @app.post('/api/social/device-links')
    def create_link(body:LinkCreate,request:Request):
        now=time.time();ip=request.client.host if request.client else 'local'
        recent=[t for t in link_attempts.get(ip,[]) if now-t<60]
        if len(recent)>=10:raise HTTPException(429,'Wait a minute before creating another link code')
        link_attempts[ip]=recent+[now]
        link_id=secrets.token_hex(12);challenge=secrets.token_hex(24);poll=secrets.token_hex(24)
        with db() as conn:conn.execute('INSERT INTO device_links(id,approval_hash,poll_hash,label,expires_at) VALUES(?,?,?,?,?)',(link_id,hashlib.sha256(challenge.encode()).hexdigest(),hashlib.sha256(poll.encode()).hexdigest(),body.label,now+300))
        return {'id':link_id,'challenge':challenge,'poll_secret':poll,'expires_at':now+300,'url':str(request.base_url).rstrip('/')+'/?'+urlencode({'device_link':link_id,'approval':challenge})}

    def link_valid(link_id,secret,column):
        with db() as conn:row=conn.execute('SELECT * FROM device_links WHERE id=?',(link_id,)).fetchone()
        if not row or row['expires_at']<=time.time() or row['consumed']:raise HTTPException(410,'Link code expired or already used')
        if not secrets.compare_digest(hashlib.sha256(secret.encode()).hexdigest(),row[column]):raise HTTPException(403,'Invalid link code')
        return row

    @app.get('/api/social/device-links/{link_id}/qr')
    def link_qr(link_id:str,approval:str,request:Request):
        link_valid(link_id,approval,'approval_hash')
        return qr(str(request.base_url).rstrip('/')+'/?'+urlencode({'device_link':link_id,'approval':approval}))

    @app.post('/api/social/device-links/preview')
    def preview_link(body:LinkApproval,token:str=Depends(b["session_token"])):
        uid(token);row=link_valid(body.id,body.challenge,'approval_hash')
        return {'label':row['label'],'expires_at':row['expires_at'],'approved':bool(row['approved_uid'])}

    @app.post('/api/social/device-links/approve')
    async def approve_link(body:LinkApproval,token:str=Depends(b["session_token"])):
        user=uid(token);link_valid(body.id,body.challenge,'approval_hash')
        with db() as conn:
            changed=conn.execute('UPDATE device_links SET approved_uid=? WHERE id=? AND approved_uid IS NULL AND consumed=0 AND expires_at>?',(user,body.id,time.time())).rowcount
            if not changed:raise HTTPException(409,'Link was already approved or expired')
            label=conn.execute('SELECT label FROM device_links WHERE id=?',(body.id,)).fetchone()[0]
            alert(conn,user,'device','Device linked',label)
        await b['mgr'].send_to_user(user,{'type':'notifications_changed'})
        return {'ok':True}

    @app.post('/api/social/device-links/{link_id}/claim')
    def claim_link(link_id:str,body:LinkPoll):
        row=link_valid(link_id,body.poll_secret,'poll_hash')
        if not row['approved_uid']:return {'pending':True}
        # Consume atomically. A QR can create only one session.
        with db() as conn:
            if not conn.execute('UPDATE device_links SET consumed=1 WHERE id=? AND consumed=0',(link_id,)).rowcount:raise HTTPException(410,'Link already used')
            account=conn.execute('SELECT * FROM users WHERE id=?',(row['approved_uid'],)).fetchone()
        return {'pending':False,'token':b['create_session'](row['approved_uid'],row['label']),'user':b['user_public'](account)}

    @app.post('/api/social/device-links/{link_id}/cancel')
    def cancel_link(link_id:str,body:LinkPoll):
        link_valid(link_id,body.poll_secret,'poll_hash')
        with db() as conn:conn.execute('DELETE FROM device_links WHERE id=?',(link_id,))
        return {'ok':True}

    @app.post('/api/social/calls')
    def new_call(body:CallCreate,token:str=Depends(b["session_token"])):
        return {'id':create_call(body.chat_id,uid(token),body.video)}

    @app.post('/api/social/calls/{call_id}')
    async def call_action(call_id:str,body:CallAction,token:str=Depends(b["session_token"])):
        user=uid(token)
        if body.action not in {'connected','answer','hangup','busy','unavailable','failed','missed'}:raise HTTPException(400,'Invalid call action')
        update_call(call_id,user,body.action)
        row=call_row(call_id,user)
        for peer in (row['caller_id'],row['callee_id']):await b['mgr'].send_to_user(peer,{'type':'notifications_changed'})
        return {'ok':True}

    @app.get('/api/social/calls')
    def call_history(token:str=Depends(b["session_token"])):
        user=uid(token)
        with db() as conn:
            results=[]
            for row in conn.execute('SELECT * FROM call_history WHERE caller_id=? OR callee_id=? ORDER BY created_at DESC LIMIT 100',(user,user)):
                result=dict(row);peer=conn.execute('SELECT * FROM users WHERE id=?',(row['callee_id'] if row['caller_id']==user else row['caller_id'],)).fetchone()
                result['peer']=b['user_public'](peer);result['direction']='outgoing' if row['caller_id']==user else 'incoming';result['duration']=max(0,int((row['ended_at'] or time.time())-row['connected_at'])) if row['connected_at'] else 0
                results.append(result)
        return results

    return {'notify_message':notify_message,'record_signal':record_signal,'update_call':update_call}
