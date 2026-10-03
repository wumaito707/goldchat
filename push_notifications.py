"""Device subscriptions and private Web Push delivery."""
import base64, hashlib, json, logging, os, time
from concurrent.futures import ThreadPoolExecutor
from threading import BoundedSemaphore
from urllib.parse import urlsplit
from fastapi import Depends, HTTPException
from pydantic import BaseModel

POOL=ThreadPoolExecutor(max_workers=2,thread_name_prefix='goldchat-push')
SLOTS=BoundedSemaphore(20)

def configured():
    return bool(os.environ.get('GOLDCHAT_VAPID_PRIVATE_KEY') and os.environ.get('GOLDCHAT_VAPID_PUBLIC_KEY'))

def init_schema(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS push_subscriptions(endpoint TEXT PRIMARY KEY,user_id INTEGER NOT NULL REFERENCES users(id),session_hash TEXT NOT NULL REFERENCES sessions(token_hash) ON DELETE CASCADE,subscription TEXT NOT NULL)")

class SubscriptionIn(BaseModel):
    endpoint:str
    keys:dict[str,str]

class EndpointIn(BaseModel):
    endpoint:str

def validate_subscription(body):
    url=urlsplit(body.endpoint)
    allowed={'fcm.googleapis.com','updates.push.services.mozilla.com','web.push.apple.com','webpush.push.apple.com'}
    host=url.hostname or ''
    if url.scheme!='https' or url.username or url.password or url.port not in (None,443) or not (host in allowed or host.endswith('.notify.windows.com')) or len(body.endpoint)>2048:
        raise HTTPException(400,'Unsupported push notification service')
    try:
        values=[base64.urlsafe_b64decode(body.keys[k]+'='*(-len(body.keys[k])%4)) for k in ('p256dh','auth')]
        if len(values[0])!=65 or values[0][0]!=4 or len(values[1])!=16:raise ValueError()
    except (KeyError,ValueError):raise HTTPException(400,'Invalid notification subscription') from None

def install(app,b):
    @app.get('/api/push/config')
    def config():return {'enabled':configured(),'public_key':os.environ.get('GOLDCHAT_VAPID_PUBLIC_KEY','')}

    @app.post('/api/push/subscribe')
    def subscribe(body:SubscriptionIn,token:str=Depends(b['session_token'])):
        uid=b['auth_user'](token)['id']
        if not configured():raise HTTPException(503,'Phone notifications are not configured yet')
        validate_subscription(body)
        conn=b['get_db']()
        try:
            with conn:
                conn.execute('INSERT INTO push_subscriptions(endpoint,user_id,session_hash,subscription) VALUES(?,?,?,?) ON CONFLICT(endpoint) DO UPDATE SET user_id=excluded.user_id,session_hash=excluded.session_hash,subscription=excluded.subscription',(body.endpoint,uid,hashlib.sha256(token.encode()).hexdigest(),json.dumps(body.model_dump())))
        finally:conn.close()
        return {'ok':True}

    @app.post('/api/push/unsubscribe')
    def unsubscribe(body:EndpointIn,token:str=Depends(b['session_token'])):
        uid=b['auth_user'](token)['id'];conn=b['get_db']()
        try:
            with conn:conn.execute('DELETE FROM push_subscriptions WHERE user_id=? AND endpoint=?',(uid,body.endpoint))
        finally:conn.close()
        return {'ok':True}

    def deliver(user,cid):
        try:
            from pywebpush import webpush, WebPushException
            conn=b['get_db']()
            try:
                rows=conn.execute('SELECT p.* FROM push_subscriptions p JOIN sessions s ON s.token_hash=p.session_hash WHERE p.user_id=? AND s.expires_at>? AND NOT EXISTS(SELECT 1 FROM chat_preferences cp WHERE cp.chat_id=? AND cp.user_id=p.user_id AND cp.muted=1) AND EXISTS(SELECT 1 FROM chat_members WHERE chat_id=? AND user_id=p.user_id)',(user,time.time(),cid,cid)).fetchall()
            finally:conn.close()
            for row in rows:
                try:
                    # Message content stays inside GOLDCHAT, off the lock screen.
                    webpush(subscription_info=json.loads(row['subscription']),data=json.dumps({'title':'GOLDCHAT','body':'You have a new message.','chat_id':cid}),vapid_private_key=os.environ['GOLDCHAT_VAPID_PRIVATE_KEY'],vapid_claims={'sub':'mailto:'+os.environ.get('GOLDCHAT_SMTP_FROM','adewoleadewumi61@gmail.com')},ttl=300,timeout=10)
                except WebPushException as error:
                    if getattr(error,'status_code',None) in (404,410) or (error.response is not None and error.response.status_code in (404,410)):
                        conn=b['get_db']()
                        try:
                            with conn:conn.execute('DELETE FROM push_subscriptions WHERE endpoint=? AND session_hash=?',(row['endpoint'],row['session_hash']))
                        finally:conn.close()
                    else:logging.getLogger('uvicorn.error').warning('Push notification delivery failed')
        except Exception:logging.getLogger('uvicorn.error').warning('Push notification unavailable')
        finally:SLOTS.release()

    def enqueue(user,cid):
        if configured() and SLOTS.acquire(blocking=False):POOL.submit(deliver,user,cid)
    return enqueue
