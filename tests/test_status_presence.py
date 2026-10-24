"""Regression checks for chat privacy, identity and owner administration."""
import os
import gc
import json
import sqlite3
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient


class OwnerProvisioningTest(unittest.TestCase):
    def test_owner_bootstrap_requires_the_exact_confirmed_database_record(self):
        import admin_console
        conn=sqlite3.connect(':memory:')
        try:
            conn.execute('CREATE TABLE users(id INTEGER PRIMARY KEY,username TEXT,created_at TEXT)')
            conn.execute("INSERT INTO users VALUES(8,'Jos','different-account-time')")
            admin_console.init_schema(conn)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM admin_roles').fetchone()[0],0)
            conn.execute('UPDATE users SET created_at=? WHERE id=8',(admin_console.OWNER_ACCOUNT['created_at'],))
            admin_console.init_schema(conn)
            admin_console.init_schema(conn)
            self.assertEqual(conn.execute('SELECT user_id,role FROM admin_roles').fetchall(),[(8,'owner')])
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM admin_audit').fetchone()[0],1)
        finally:
            conn.close()


class StatusPresenceTest(unittest.TestCase):
    @classmethod
    @contextmanager
    def db(cls):
        conn = cls.server.get_db()
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ['GOLDCHAT_DATA_DIR'] = cls.temp.name
        cls.static = Path(__file__).resolve().parents[1] / 'static'
        cls.created_static = not cls.static.exists()
        cls.static.mkdir(exist_ok=True)
        import server
        cls.server = server
        server.init_db()
        with cls.db() as conn:
            for name in ('author', 'viewer', 'other', 'sender', 'recipient'):
                conn.execute('INSERT INTO users(username,display_name,password_hash,salt,avatar_initial,created_at) VALUES(?,?,?,?,?,?)',
                             (name, name.title(), 'unused', 'unused', name[0].upper(), server.now_iso()))
            conn.execute('INSERT INTO contacts(user_id,contact_id) VALUES(2,1)')
            conn.execute('INSERT INTO contacts(user_id,contact_id) VALUES(3,1)')
            conn.execute('INSERT INTO contacts(user_id,contact_id) VALUES(1,2)')
        cls.tokens = {uid: server.create_session(uid) for uid in (1, 2, 3, 4, 5)}
        cls.client = TestClient(server.app)

    @classmethod
    def tearDownClass(cls):
        cls.client.close()
        gc.collect()
        cls.temp.cleanup()
        if cls.created_static:
            cls.static.rmdir()

    def call(self, uid, method, path, **kwargs):
        response = self.client.request(method, path, headers={'Authorization': 'Bearer ' + self.tokens[uid]}, **kwargs)
        self.assertLess(response.status_code, 400, response.text)
        return response.json()

    @contextmanager
    def owner(self):
        with self.db() as conn:
            conn.execute("INSERT INTO admin_roles(user_id,role,created_at) VALUES(1,'owner',?)",(self.server.now_iso(),))
        try:
            yield {'Authorization':'Bearer '+self.tokens[1]}
        finally:
            with self.db() as conn:
                conn.execute('DELETE FROM admin_roles WHERE user_id=1')

    def test_admin_routes_enforce_fresh_owner_permissions(self):
        paths=[('GET','overview',None),('GET','users',None),('GET','chats',None),
               ('GET','calls',None),('GET','audit',None),
               ('GET','announcements',None),
               ('POST','announcements',{'title':'GOLDCHAT update','body':'New app improvements'}),
               ('POST','announcements/1/withdraw',{'reason':'Withdraw an update announcement'}),
               ('POST','chats/1/messages',{'reason':'Investigate a user report'}),
               ('POST','statuses/review',{'reason':'Investigate a user report'}),
               ('POST','media/attachment/1/review',{'reason':'Investigate a user report'}),
               ('POST','users/2/suspension',{'reason':'Investigate a user report','suspended':True}),
               ('POST','users/2/deletion',{'reason':'Investigate a user report','deleted':True,'username_confirmation':'viewer'}),
               ('POST','users/2/sign-out',{'reason':'Investigate a user report'})]
        for method,path,body in paths:
            url='/api/admin/'+path
            self.assertEqual(self.client.request(method,url,json=body).status_code,401,url)

            denied=self.client.request(method,url,json=body,headers={'Authorization':'Bearer '+self.tokens[2]})
            self.assertEqual(denied.status_code,403,denied.text)
            self.assertEqual(denied.headers['cache-control'],'no-store')
        self.assertEqual(self.call(2,'GET','/api/admin/access'),{'allowed':False})
        self.call(2,'PATCH','/api/profile',json={'display_name':'Viewer','bio':'','privacy':'everyone','role':'owner','is_owner':True})
        self.assertFalse(self.call(2,'GET','/api/admin/access')['allowed'])
        with self.owner() as headers:
            self.assertTrue(self.client.get('/api/admin/access',headers=headers).json()['allowed'])
            overview=self.client.get('/api/admin/overview',headers=headers)
            self.assertEqual(overview.status_code,200,overview.text)
            self.assertGreaterEqual(overview.json()['counts']['users'],5)
            users=self.client.get('/api/admin/users',headers=headers).json()
            self.assertGreaterEqual(users['total'],5)
            for user in users['items']:
                self.assertTrue({'id','username','display_name','verified_email','created_at','is_owner'}<=user.keys())
                self.assertFalse({'password_hash','salt','google_sub','token_hash'} & user.keys())
            # Permission removal takes effect even when normal auth is cached.
            self.call(1,'GET','/api/me')
            with self.db() as conn:
                conn.execute('DELETE FROM admin_roles WHERE user_id=1')
            self.assertEqual(self.client.get('/api/admin/overview',headers=headers).status_code,403)
        self.assertFalse(self.call(1,'GET','/api/admin/access')['allowed'])

    def test_bulk_chat_clear_is_personal_and_does_not_mark_messages_read(self):
        chat=self.call(4,'POST','/api/groups',json={'title':'Personal clear regression','member_ids':[5]})
        cid=chat.get('chat_id',chat.get('id'))
        message=self.call(5,'POST',f'/api/chats/{cid}/messages',json={'text':'Keep this for the other member'})
        self.call(4,'POST',f'/api/messages/{message["id"]}/star')
        self.call(5,'POST',f'/api/messages/{message["id"]}/pin')
        with patch.object(self.server.mgr,'send_to_user',new_callable=AsyncMock) as events:
            self.call(4,'POST','/api/chats/bulk',json={'chat_ids':[cid],'action':'clear'})
            events.assert_awaited_once_with(4,{'type':'personal_chats_changed','chat_ids':[cid],'action':'clear'})
        self.assertEqual(self.call(4,'GET',f'/api/v2/chats/{cid}/messages'),[])
        self.assertTrue(any(x['id']==message['id'] for x in self.call(5,'GET',f'/api/v2/chats/{cid}/messages')))
        self.assertFalse(any(x['id']==message['id'] for x in self.call(4,'GET','/api/stars')))
        self.assertEqual(self.call(4,'GET',f'/api/chats/{cid}/pins'),[])
        mine=next(x for x in self.call(4,'GET','/api/v2/chats') if x['id']==cid)
        self.assertEqual(mine['unread'],0)
        with self.db() as conn:
            state=conn.execute('SELECT last_read_msg_id FROM read_state WHERE chat_id=? AND user_id=4',(cid,)).fetchone()
            self.assertTrue(state is None or state[0]<message['id'])

    def test_bulk_delete_returns_on_new_messages_and_validates_all_memberships(self):
        chat=self.call(4,'POST','/api/groups',json={'title':'Personal delete regression','member_ids':[5]})
        cid=chat.get('chat_id',chat.get('id'))
        self.call(5,'POST',f'/api/chats/{cid}/messages',json={'text':'Earlier message'})
        bad=self.client.post('/api/chats/bulk',headers={'Authorization':'Bearer '+self.tokens[4]},json={'chat_ids':[cid,999999],'action':'delete'})
        self.assertEqual(bad.status_code,403)
        self.assertTrue(self.call(4,'GET',f'/api/v2/chats/{cid}/messages'))
        self.call(4,'POST','/api/chats/bulk',json={'chat_ids':[cid],'action':'delete'})
        self.assertNotIn(cid,[c['id'] for c in self.call(4,'GET','/api/v2/chats')])
        self.assertIn(cid,[c['id'] for c in self.call(5,'GET','/api/v2/chats')])
        message=self.call(5,'POST',f'/api/chats/{cid}/messages',json={'text':'A new message brings the chat back'})
        self.assertIn(cid,[c['id'] for c in self.call(4,'GET','/api/v2/chats')])
        self.assertEqual([m['id'] for m in self.call(4,'GET',f'/api/v2/chats/{cid}/messages')],[message['id']])
        self.call(4,'POST',f'/api/chats/{cid}/read')
        self.call(4,'POST','/api/chats/bulk',json={'chat_ids':[cid],'action':'mark_unread'})
        self.assertEqual(next(c for c in self.call(4,'GET','/api/v2/chats') if c['id']==cid)['unread'],1)
        self.call(4,'POST','/api/chats/bulk',json={'chat_ids':[cid],'action':'mark_read'})
        self.assertEqual(next(c for c in self.call(4,'GET','/api/v2/chats') if c['id']==cid)['unread'],0)
        self.call(4,'POST',f'/api/chats/{cid}/preferences',json={'muted':True,'archived':True,'pinned':True})

    def test_status_likes_respect_audience_expiry_and_are_idempotent(self):
        status=self.call(1,'POST','/api/social/statuses',json={'text':'Fresh blue status','background':'#528ff5','audience':'contacts'})
        sid=status['id']
        self.call(2,'PUT',f'/api/social/statuses/{sid}/like?liked=true')
        self.call(2,'PUT',f'/api/social/statuses/{sid}/like?liked=true')
        self.assertTrue(next(s for s in self.call(2,'GET','/api/social/statuses') if s['id']==sid)['liked'])
        views=self.call(1,'GET',f'/api/social/statuses/{sid}/views')
        self.assertEqual(views['count'],1)
        self.assertTrue(views['viewers'][0]['liked'])
        forbidden=self.client.put(f'/api/social/statuses/{sid}/like',headers={'Authorization':'Bearer '+self.tokens[3]})
        self.assertEqual(forbidden.status_code,404)
        self.call(2,'PUT',f'/api/social/statuses/{sid}/like?liked=false')
        self.assertFalse(next(s for s in self.call(2,'GET','/api/social/statuses') if s['id']==sid)['liked'])
        with self.db() as conn:
            conn.execute('UPDATE statuses SET expires_at=? WHERE id=?',(time.time()-1,sid))
        expired=self.client.put(f'/api/social/statuses/{sid}/like',headers={'Authorization':'Bearer '+self.tokens[2]})
        self.assertEqual(expired.status_code,404)

    def test_startup_migrates_an_old_database_before_expiry_cleanup(self):
        legacy_path=Path(self.temp.name)/'legacy-upgrade.db'
        source=self.server.get_db(cleanup=False)
        legacy=sqlite3.connect(legacy_path)
        try:
            source.backup(legacy)
            legacy.execute('DROP TABLE status_likes')
            legacy.execute('INSERT INTO statuses(user_id,text,created_at,expires_at) VALUES(?,?,?,?)',(1,'Expired before this upgrade',self.server.now_iso(),time.time()-10))
            legacy.commit()
        finally:
            source.close()
            legacy.close()
        with patch.object(self.server,'DB_PATH',legacy_path),patch.object(self.server,'_last_expired_cleanup',0):
            self.server.init_db()
        migrated=sqlite3.connect(legacy_path)
        try:
            self.assertIsNotNone(migrated.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='status_likes'").fetchone())
        finally:
            migrated.close()

    def test_update_announcements_expire_after_two_hours_without_expiring_notifications(self):
        import admin_console
        from datetime import datetime,timezone
        now=time.time()
        with self.db() as conn:
            nid=conn.execute('INSERT INTO notifications(user_id,kind,title,body,created_at) VALUES(?,?,?,?,?)',
                (2,'message','Normal notification','This alert keeps its current behavior',datetime.fromtimestamp(now-10800,timezone.utc).isoformat())).lastrowid
        self.assertEqual(self.client.get('/api/announcements').status_code,401)
        with self.owner() as headers, patch.object(admin_console.time,'time',return_value=now):
            invalid=self.client.post('/api/admin/announcements',headers=headers,json={'title':'   ','body':'   '})
            self.assertEqual(invalid.status_code,422)
            posted=self.client.post('/api/admin/announcements',headers=headers,
                json={'title':' GOLDCHAT update ','body':' New chat improvements ','expires_at':now+86400})
            self.assertEqual(posted.status_code,200,posted.text)
            self.assertEqual(posted.json()['expires_at']-posted.json()['created_at'],7200)
            aid=posted.json()['id']
        with patch.object(admin_console.time,'time',return_value=now+7199):
            visible=self.call(2,'GET','/api/announcements')['announcement']
            self.assertEqual(visible['id'],aid)
            self.assertEqual(visible['title'],'GOLDCHAT update')
        with patch.object(admin_console.time,'time',return_value=now+7200):
            response=self.client.get('/api/announcements',headers={'Authorization':'Bearer '+self.tokens[2]})
            self.assertEqual(response.status_code,200,response.text)
            self.assertIsNone(response.json()['announcement'])
            self.assertEqual(response.headers['cache-control'],'no-store')
            self.assertIn(nid,{n['id'] for n in self.call(2,'GET','/api/social/notifications')['items']})

    def test_owner_can_replace_or_withdraw_update_announcements_and_actions_are_audited(self):
        with self.owner() as headers:
            first=self.client.post('/api/admin/announcements',headers=headers,json={'title':'First update','body':'First change'}).json()['id']
            second=self.client.post('/api/admin/announcements',headers=headers,json={'title':'Second update','body':'Second change'}).json()['id']
            self.assertEqual(self.call(3,'GET','/api/announcements')['announcement']['id'],second)
            history=self.client.get('/api/admin/announcements',headers=headers).json()['items']
            self.assertIsNotNone(next(item for item in history if item['id']==first)['withdrawn_at'])
            withdrawn=self.client.post(f'/api/admin/announcements/{second}/withdraw',headers=headers,json={'reason':'Owner withdrew this update announcement'})
            self.assertEqual(withdrawn.status_code,200,withdrawn.text)
            self.assertIsNone(self.call(3,'GET','/api/announcements')['announcement'])
            with self.db() as conn:
                actions={r['action'] for r in conn.execute('SELECT action FROM admin_audit WHERE target_type=? AND target_id=?',('announcement',second))}
                self.assertEqual(actions,{'update_announcement_published','update_announcement_withdrawn'})

    def test_admin_message_review_is_audited_paginated_and_does_not_mark_read(self):
        server=self.server
        cid=server.get_or_create_direct_chat(4,5)
        with self.db() as conn:
            conn.execute('INSERT OR IGNORE INTO read_state(chat_id,user_id,last_read_msg_id) VALUES(?,?,0)',(cid,5))
            before=[tuple(row) for row in conn.execute('SELECT * FROM read_state WHERE chat_id=?',(cid,))]
            ids=[]
            for i in range(53):
                ids.append(conn.execute('INSERT INTO messages(chat_id,sender_id,text,created_at) VALUES(?,?,?,?)',
                    (cid,4,'Retained moderation fixture '+str(i),server.now_iso())).lastrowid)
            deleted=conn.execute('INSERT INTO messages(chat_id,sender_id,text,created_at,deleted) VALUES(?,?,?,?,1)',
                (cid,4,'Deleted content must stay hidden',server.now_iso())).lastrowid
            expired=conn.execute('INSERT INTO messages(chat_id,sender_id,text,created_at,expires_at) VALUES(?,?,?,?,?)',
                (cid,4,'Expired content must stay hidden',server.now_iso(),time.time()-10)).lastrowid
        self.assertEqual(self.client.get(f'/api/v2/chats/{cid}/messages',headers={'Authorization':'Bearer '+self.tokens[1]}).status_code,403)
        with self.owner() as headers:
            self.assertEqual(self.client.post(f'/api/admin/chats/{cid}/messages',headers=headers,json={'reason':'          '}).status_code,422)
            reviewed=self.client.post(f'/api/admin/chats/{cid}/messages',headers=headers,json={'reason':'Investigating reported chat abuse'})
            self.assertEqual(reviewed.status_code,200,reviewed.text)
            data=reviewed.json()
            self.assertEqual(len(data['items']),50)
            self.assertTrue(data['has_more'])
            self.assertNotIn(expired,{item['id'] for item in data['items']})
            tombstone=next(item for item in data['items'] if item['id']==deleted)
            self.assertEqual(tombstone['text'],'')
            self.assertIsNone(tombstone['attachment_id'])
            earlier=self.client.post(f'/api/admin/chats/{cid}/messages',headers=headers,
                json={'reason':'Investigating reported chat abuse','before':data['before']}).json()
            self.assertTrue(ids[0] in {item['id'] for item in earlier['items']})
            self.assertFalse({item['id'] for item in earlier['items']} & {item['id'] for item in data['items']})
            with self.db() as conn:
                self.assertEqual([tuple(row) for row in conn.execute('SELECT * FROM read_state WHERE chat_id=?',(cid,))],before)
                log=conn.execute("SELECT actor_id,reason FROM admin_audit WHERE action='messages_reviewed' AND target_id=? ORDER BY id DESC",(cid,)).fetchall()
                self.assertEqual(len(log),2)
                self.assertEqual(log[0]['actor_id'],1)
                self.assertEqual(log[0]['reason'],'Investigating reported chat abuse')

    def test_admin_media_and_status_review_excludes_expired_and_deleted_content(self):
        from fastapi.responses import Response
        import cloud_media
        server=self.server;cid=server.get_or_create_direct_chat(4,5)
        with self.db() as conn:
            aid=conn.execute('INSERT INTO attachments(chat_id,user_id,name,path,mime,size) VALUES(?,?,?,?,?,?)',
                (cid,4,'fixture.png','private-test-object.png','image/png',4)).lastrowid
            mid=conn.execute('INSERT INTO messages(chat_id,sender_id,text,created_at,attachment_id) VALUES(?,?,?,?,?)',
                (cid,4,'Media fixture',server.now_iso(),aid)).lastrowid
            active=conn.execute('INSERT INTO statuses(user_id,text,created_at,expires_at,audience) VALUES(?,?,?,?,?)',
                (4,'Private active status',server.now_iso(),time.time()+600,'nobody')).lastrowid
            expired=conn.execute('INSERT INTO statuses(user_id,text,created_at,expires_at,audience) VALUES(?,?,?,?,?)',
                (4,'Expired status',server.now_iso(),time.time()-10,'everyone')).lastrowid
        self.assertEqual(self.client.get(f'/api/attachments/{aid}',headers={'Authorization':'Bearer '+self.tokens[1]}).status_code,403)
        with self.owner() as headers:
            statuses=self.client.post('/api/admin/statuses/review',headers=headers,json={'reason':'Investigating a status report'}).json()['items']
            self.assertIn(active,{item['id'] for item in statuses})
            self.assertNotIn(expired,{item['id'] for item in statuses})
            self.assertTrue(all('path' not in item for item in statuses))
            def audited_response(root,key,mime,headers,filename):
                # An independent connection sees the committed audit BEFORE data retrieval.
                with self.db() as conn:
                    row=conn.execute("SELECT reason FROM admin_audit WHERE action='media_reviewed' AND target_id=? ORDER BY id DESC LIMIT 1",(aid,)).fetchone()
                    self.assertEqual(row['reason'],'Investigating a shared file report')
                self.assertEqual(key,'private-test-object.png')
                return Response(b'test',media_type=mime,headers=headers)
            with patch.object(cloud_media,'response',side_effect=audited_response) as retrieve:
                response=self.client.post(f'/api/admin/media/attachment/{aid}/review',headers=headers,json={'reason':'Investigating a shared file report'})
                self.assertEqual(response.status_code,200,response.text)
                self.assertEqual(response.headers['cache-control'],'no-store')
                with self.db() as conn:
                    conn.execute('UPDATE messages SET deleted=1 WHERE id=?',(mid,))
                self.assertEqual(self.client.post(f'/api/admin/media/attachment/{aid}/review',headers=headers,json={'reason':'Investigating a shared file report'}).status_code,404)
                with self.db() as conn:
                    conn.execute('UPDATE messages SET deleted=0,expires_at=? WHERE id=?',(time.time()-10,mid))
                self.assertEqual(self.client.post(f'/api/admin/media/attachment/{aid}/review',headers=headers,json={'reason':'Investigating a shared file report'}).status_code,404)
                self.assertEqual(retrieve.call_count,1)

    def test_admin_review_fails_closed_when_the_audit_cannot_be_saved(self):
        import cloud_media
        server=self.server;cid=server.get_or_create_direct_chat(4,5)
        original_db=server.get_db
        class DeniedAuditConnection:
            def __init__(self,conn):self.conn=conn
            def __enter__(self):self.conn.__enter__();return self
            def __exit__(self,*args):return self.conn.__exit__(*args)
            def close(self):self.conn.close()
            def execute(self,sql,args=()):
                if sql.startswith('INSERT INTO admin_audit'):
                    raise sqlite3.OperationalError('Audit storage unavailable in synthetic test')
                return self.conn.execute(sql,args)
        with self.owner() as headers, patch.object(server,'get_db',side_effect=lambda **kw:DeniedAuditConnection(original_db(**kw))), patch.object(cloud_media,'response') as retrieve:
            response=self.client.post(f'/api/admin/chats/{cid}/messages',headers=headers,json={'reason':'Investigating a user report'})
            self.assertEqual(response.status_code,503,response.text)
            self.assertNotIn('Retained moderation fixture',response.text)
            retrieve.assert_not_called()

    def test_admin_account_actions_revoke_sessions_and_protect_the_owner(self):
        server=self.server;password='Only a synthetic test password'
        hashed,salt=server.hash_pw(password)
        with self.db() as conn:
            uid=conn.execute('INSERT INTO users(username,display_name,password_hash,salt,avatar_initial,created_at,verified_email,google_sub) VALUES(?,?,?,?,?,?,?,?)',
                ('moderation_target','Moderation target',hashed,salt,'M',server.now_iso(),'moderation@gmail.com','moderation-google-sub')).lastrowid
            conn.execute('INSERT INTO contacts(user_id,contact_id) VALUES(1,?)',(uid,))
            sid=conn.execute('INSERT INTO statuses(user_id,text,created_at,expires_at,audience) VALUES(?,?,?,?,?)',
                (uid,'Moderation target status',server.now_iso(),time.time()+600,'everyone')).lastrowid
        token=server.create_session(uid);target_headers={'Authorization':'Bearer '+token}
        cid=server.get_or_create_direct_chat(1,uid)
        self.assertEqual(self.client.get('/api/me',headers=target_headers).status_code,200)
        class FakeSocket:
            closed=False
            async def close(self,code):self.closed=code
        socket=FakeSocket();wsid='owner-ban-test'
        server.mgr.active[wsid]={'user_id':uid,'ws':socket,'chat_ids':set(),'token':token}
        server.ONLINE.setdefault(uid,set()).add(wsid)
        reason='Confirmed abuse report in test fixture'
        with self.owner() as headers:
            def action(path,body):return self.client.post(f'/api/admin/users/{uid}/'+path,headers=headers,json={'reason':reason,**body})
            self.assertEqual(self.client.post('/api/admin/users/1/suspension',headers=headers,json={'reason':reason,'suspended':True}).status_code,400)
            self.assertEqual(self.client.post('/api/admin/users/1/deletion',headers=headers,json={'reason':reason,'deleted':True,'username_confirmation':'author'}).status_code,400)
            self.assertEqual(action('suspension',{'suspended':True}).status_code,200)
            self.assertEqual(socket.closed,4401)
            self.assertNotIn(wsid,server.mgr.active)
            self.assertNotIn(uid,server.ONLINE)
            self.assertEqual(self.client.get('/api/me',headers=target_headers).status_code,401)
            self.assertEqual(self.client.post('/api/login',json={'username':'moderation_target','password':password}).status_code,403)
            from google.oauth2 import id_token
            with patch.object(id_token,'verify_oauth2_token',return_value={'sub':'moderation-google-sub','email':'moderation@gmail.com','email_verified':True}):
                self.assertEqual(self.client.post('/api/auth/google',json={'credential':'test-google-token'}).status_code,403)
            self.assertEqual(self.client.post(f'/api/chats/{cid}/messages',headers=headers,json={'text':'Should be unavailable'}).status_code,403)
            self.assertEqual(self.client.post('/api/social/calls',headers=headers,json={'chat_id':cid}).status_code,403)
            self.assertEqual(self.client.post(f'/api/chats/direct/{uid}',headers=headers).status_code,404)
            self.assertEqual(self.client.get('/api/social/contact/moderation_target',headers=headers).status_code,404)
            self.assertNotIn(uid,{u['id'] for u in self.client.get('/api/users/search?q=moderation_target',headers=headers).json()})
            self.assertNotIn(sid,{s['id'] for s in self.call(1,'GET','/api/social/statuses')})
            banned=self.client.get('/api/admin/users?state=banned',headers=headers).json()
            self.assertIn(uid,{u['id'] for u in banned['items']})
            self.assertEqual(action('suspension',{'suspended':False}).status_code,200)
            login=self.client.post('/api/login',json={'username':'moderation_target','password':password})
            self.assertEqual(login.status_code,200,login.text)
            restored_token=login.json()['token']
            self.assertEqual(action('deletion',{'deleted':True,'username_confirmation':'wrong_name'}).status_code,400)
            self.assertEqual(action('deletion',{'deleted':True,'username_confirmation':'moderation_target'}).status_code,200)
            self.assertEqual(self.client.get('/api/me',headers={'Authorization':'Bearer '+restored_token}).status_code,401)
            self.assertEqual(self.client.post('/api/login',json={'username':'moderation_target','password':password}).status_code,403)
            self.assertIn(uid,{u['id'] for u in self.client.get('/api/admin/users?state=deleted',headers=headers).json()['items']})
            self.assertEqual(action('deletion',{'deleted':False,'username_confirmation':'moderation_target'}).status_code,200)
            login=self.client.post('/api/login',json={'username':'moderation_target','password':password})
            self.assertEqual(login.status_code,200,login.text)
            restored_token=login.json()['token']
            self.assertEqual(action('sign-out',{}).status_code,200)
            self.assertEqual(self.client.get('/api/me',headers={'Authorization':'Bearer '+restored_token}).status_code,401)
            audits=self.client.get('/api/admin/audit',headers=headers).json()['items']
            self.assertTrue({'account_suspended','account_restored','account_deleted','deleted_account_restored','account_signed_out'}<={a['action'] for a in audits if a['target_id']==uid})

    def test_google_configuration_uses_the_deployed_public_id_and_environment_override(self):
        with patch.dict(os.environ, {'GOLDCHAT_GOOGLE_CLIENT_ID': ''}):
            response=self.client.get('/api/auth/google/config')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['client_id'],self.server.GOOGLE_WEB_CLIENT_ID)
        with patch.dict(os.environ, {'GOLDCHAT_GOOGLE_CLIENT_ID': 'overridden-client.apps.googleusercontent.com'}):
            self.assertEqual(self.client.get('/api/auth/google/config').json()['client_id'],'overridden-client.apps.googleusercontent.com')

    def test_google_signup_and_existing_email_protection(self):
        from google.oauth2 import id_token
        with patch.dict(os.environ, {'GOLDCHAT_GOOGLE_CLIENT_ID': 'test-web-client'}), patch.object(id_token, 'verify_oauth2_token') as verify:
            verify.return_value={'sub':'google-test-123','email':'new-google-user@gmail.com','email_verified':True,'name':'Google User'}
            created=self.client.post('/api/auth/google',json={'credential':'signed-test-token'})
            self.assertEqual(verify.call_args.args[2],'test-web-client')
            self.assertEqual(created.status_code,200,created.text)
            self.assertEqual(created.json()['user']['display_name'],'Google User')
            self.assertEqual(self.client.post('/api/auth/google',json={'credential':'signed-test-token'}).json()['user']['id'],created.json()['user']['id'])
            with self.db() as conn:
                conn.execute('UPDATE users SET verified_email=? WHERE id=1',('existing@gmail.com',))
            verify.return_value={'sub':'google-test-456','email':'existing@gmail.com','email_verified':True}
            conflict=self.client.post('/api/auth/google',json={'credential':'another-signed-token'})
            self.assertEqual(conflict.status_code,409)
            linked=self.client.post('/api/auth/google',json={'credential':'another-signed-token','link':True},headers={'Authorization':'Bearer '+self.tokens[1]})
            self.assertEqual(linked.status_code,200,linked.text)
            self.assertEqual(linked.json()['user']['id'],1)
            self.assertEqual(linked.json()['token'],self.tokens[1])
            with self.db() as conn:
                before=conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
            verify.return_value={'sub':'google-different','email':'different@gmail.com','email_verified':True}
            mismatch=self.client.post('/api/auth/google',json={'credential':'different-email','link':True},headers={'Authorization':'Bearer '+self.tokens[1]})
            self.assertEqual(mismatch.status_code,409)
            with self.db() as conn:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM users').fetchone()[0],before)
            self.assertEqual(self.client.post('/api/auth/google',json={'credential':'different-email','link':True}).status_code,401)
            verify.return_value={'sub':'google-unverified','email':'unverified@gmail.com','email_verified':False}
            self.assertEqual(self.client.post('/api/auth/google',json={'credential':'unverified'}).status_code,401)
            verify.side_effect=ValueError('invalid signature')
            self.assertEqual(self.client.post('/api/auth/google',json={'credential':'invalid'}).status_code,401)

    def test_status_audience_is_per_post_and_survives_profile_change(self):
        own = self.call(1, 'POST', '/api/social/statuses', json={'text': 'only me', 'audience': 'nobody'})['id']
        mutual = self.call(1, 'POST', '/api/social/statuses', json={'text': 'mutual', 'audience': 'contacts'})['id']
        followers = self.call(1, 'POST', '/api/social/statuses', json={'text': 'followers', 'audience': 'everyone'})['id']
        self.assertEqual({s['id'] for s in self.call(2, 'GET', '/api/social/statuses')}, {mutual, followers})
        self.assertEqual({s['id'] for s in self.call(3, 'GET', '/api/social/statuses')}, {followers})
        self.assertEqual({s['id'] for s in self.call(2, 'GET', '/api/statuses')}, {mutual, followers})
        self.assertEqual(self.client.post('/api/social/statuses/' + str(own) + '/view',
                                          headers={'Authorization': 'Bearer ' + self.tokens[2]}).status_code, 404)
        self.call(1, 'PATCH', '/api/profile', json={'display_name': 'Author', 'bio': '', 'privacy': 'nobody'})
        self.assertEqual({s['id'] for s in self.call(2, 'GET', '/api/social/statuses')}, {mutual, followers})
        self.assertEqual({s['id'] for s in self.call(3, 'GET', '/api/statuses')}, {followers})
        with self.db() as conn:
            media_id = conn.execute('INSERT INTO social_media(user_id,purpose,name,path,mime,size,expires_at) VALUES(?,?,?,?,?,?,?)',
                                    (1, 'status', 'private.png', 'missing-media', 'image/png', 10, time.time() + 86400)).lastrowid
        self.call(1, 'POST', '/api/social/statuses', json={'media_id': media_id, 'audience': 'nobody'})
        self.assertEqual(self.client.get('/api/social/media/' + str(media_id),
                                         headers={'Authorization': 'Bearer ' + self.tokens[2]}).status_code, 403)

    def test_last_seen_is_hidden_with_presence(self):
        server = self.server
        cid = server.get_or_create_direct_chat(1, 2)
        with self.db() as conn:
            conn.execute('UPDATE users SET privacy=?,last_seen_at=? WHERE id=1', ('everyone', server.now_iso()))
        visible = next(c for c in server.chat_list_for(2) if c['id'] == cid)
        self.assertIsNotNone(visible['peer_last_seen'])
        with self.db() as conn:
            conn.execute('UPDATE users SET privacy=? WHERE id=1', ('nobody',))
        hidden = next(c for c in server.chat_list_for(2) if c['id'] == cid)
        self.assertFalse(hidden['peer_online'])
        self.assertIsNone(hidden['peer_last_seen'])

    def test_bootstrap_combines_profile_and_chats(self):
        self.server.get_or_create_direct_chat(1, 2)
        response = self.call(1, 'GET', '/api/v2/bootstrap')
        self.assertEqual(response['user'], self.call(1, 'GET', '/api/me'))
        self.assertEqual(response['chats'], self.call(1, 'GET', '/api/v2/chats'))
        self.assertEqual(self.client.get('/api/v2/bootstrap').status_code, 401)

    def test_message_receipts_follow_delivery_read_and_privacy(self):
        server = self.server
        cid = server.get_or_create_direct_chat(4, 5)
        with self.db() as conn:
            conn.execute("UPDATE users SET privacy='everyone',read_receipts=1 WHERE id=5")
        sent = self.call(4, 'POST', f'/api/chats/{cid}/messages', json={'text': 'Receipt test'})
        mid = sent['id']

        def own_message(path):
            return next(m for m in self.call(4, 'GET', path) if m['id'] == mid)

        def home_message():
            return next(c for c in self.call(4, 'GET', '/api/v2/chats') if c['id'] == cid)['last_message']

        for row in (own_message(f'/api/v2/chats/{cid}/messages'), own_message(f'/api/chats/{cid}/messages'), home_message()):
            self.assertFalse(row['delivered'])
            self.assertFalse(row['read'])

        self.assertEqual(server.advance_delivery(5, cid), {cid})
        for row in (own_message(f'/api/v2/chats/{cid}/messages'), home_message()):
            self.assertTrue(row['delivered'])
            self.assertFalse(row['read'])
        self.assertEqual(server.advance_delivery(5, cid), set())

        self.call(5, 'POST', f'/api/chats/{cid}/read')
        for row in (own_message(f'/api/v2/chats/{cid}/messages'), own_message(f'/api/chats/{cid}/messages'), home_message()):
            self.assertTrue(row['delivered'])
            self.assertTrue(row['read'])

        self.call(5, 'PATCH', '/api/profile', json={'display_name': 'Recipient', 'bio': '', 'privacy': 'everyone', 'read_receipts': False})
        self.assertFalse(own_message(f'/api/v2/chats/{cid}/messages')['read'])
        self.assertFalse(home_message()['read'])
        self.call(5, 'PATCH', '/api/profile', json={'display_name': 'Recipient', 'bio': '', 'privacy': 'nobody', 'read_receipts': True})
        self.assertFalse(own_message(f'/api/chats/{cid}/messages')['read'])
        self.assertFalse(home_message()['read'])

    def test_online_recipient_gets_persisted_delivery(self):
        server = self.server
        cid = server.get_or_create_direct_chat(4, 5)

        class FakeSocket:
            def __init__(self):
                self.events = []

            async def send_text(self, data):
                self.events.append(json.loads(data))

        socket = FakeSocket()
        ws_id = 'receipt-test-recipient'
        server.ONLINE.setdefault(5, set()).add(ws_id)
        server.mgr.active[ws_id] = {'user_id': 5, 'ws': socket, 'chat_ids': set()}
        try:
            mid = self.call(4, 'POST', f'/api/chats/{cid}/messages', json={'text': 'Online delivery'})['id']
            message = next(m for m in self.call(4, 'GET', f'/api/v2/chats/{cid}/messages') if m['id'] == mid)
            self.assertTrue(message['delivered'])
            self.assertFalse(message['read'])
            received=next(event for event in socket.events if event['type']=='message')
            self.assertEqual(received['id'],mid)
            self.assertEqual(received['text'],'Online delivery')
            self.assertEqual(received['chat_id'],cid)
            self.assertEqual(received['sender']['id'],4)
        finally:
            server.mgr.active.pop(ws_id, None)
            server.ONLINE.get(5, set()).discard(ws_id)
            if not server.ONLINE.get(5):
                server.ONLINE.pop(5, None)

    def test_message_retry_is_idempotent_and_broadcasts_content_before_notifications(self):
        cid=self.call(4,'POST','/api/groups',json={'title':'Safe retry regression','member_ids':[5]})['chat_id']
        body={'text':'Send this exactly once','client_id':'retry-regression-message'}
        order=[]
        async def deliver(uid,event):
            order.append(('socket',uid,event))
            return False
        def notify(mid):order.append(('notification',mid))
        with patch.object(self.server.mgr,'send_to_user',side_effect=deliver),patch.dict(self.server.SOCIAL_HOOKS,{'notify_message':notify}):
            sent=self.call(4,'POST',f'/api/chats/{cid}/messages',json=body)
            retry=self.call(4,'POST',f'/api/chats/{cid}/messages',json=body)
        self.assertEqual(sent['id'],retry['id'])
        self.assertEqual(sent['client_id'],body['client_id'])
        self.assertEqual([event[0] for event in order],['socket','socket','socket','socket','notification'])
        messages=[event for event in order[:-1] if event[2]['type']=='message']
        self.assertEqual(len(messages),2)
        for event in messages:
            self.assertEqual(event[2]['type'],'message')
            self.assertEqual(event[2]['text'],body['text'])
            self.assertEqual(event[2]['client_id'],body['client_id'])
            self.assertFalse(event[2]['starred'])
        self.assertEqual(len([event for event in order[:-1] if event[2].get('message_id')==sent['id']]),2)
        with self.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM messages WHERE sender_id=4 AND client_id=?',(body['client_id'],)).fetchone()[0],1)
        mismatch=self.client.post(f'/api/chats/{cid}/messages',headers={'Authorization':'Bearer '+self.tokens[4]},json={**body,'text':'Different text'})
        self.assertEqual(mismatch.status_code,409)
        own=next(m for m in self.call(4,'GET',f'/api/v2/chats/{cid}/messages') if m['id']==sent['id'])
        peer=next(m for m in self.call(5,'GET',f'/api/v2/chats/{cid}/messages') if m['id']==sent['id'])
        self.assertEqual(own['client_id'],body['client_id'])
        self.assertIsNone(peer['client_id'])
        # The send reference belongs to its authenticated sender.
        theirs=self.call(5,'POST',f'/api/chats/{cid}/messages',json=body)
        self.assertNotEqual(theirs['id'],sent['id'])

    def test_message_retry_still_enforces_membership_blocks_and_channel_permissions(self):
        group=self.call(4,'POST','/api/groups',json={'title':'Send permission regression','member_ids':[5]})['chat_id']
        channel=self.call(4,'POST','/api/groups',json={'title':'Read only send regression','member_ids':[5],'kind':'channel'})['chat_id']
        body={'text':'Permission test','client_id':'send-permission-regression'}
        def denied(uid,cid,body=body,status=403):
            response=self.client.post(f'/api/chats/{cid}/messages',headers={'Authorization':'Bearer '+self.tokens[uid]},json=body)
            self.assertEqual(response.status_code,status,response.text)
        denied(3,group)
        denied(5,channel)
        self.call(4,'POST',f'/api/chats/{channel}/messages',json=body)
        denied(4,group,status=409)
        denied(4,group,{**body,'client_id':'invalid reference!'},422)
        direct=self.server.get_or_create_direct_chat(4,5)
        with self.db() as conn:conn.execute('INSERT OR IGNORE INTO blocks(user_id,blocked_id) VALUES(5,4)')
        try:denied(4,direct,{**body,'client_id':'blocked-message'})
        finally:
            with self.db() as conn:conn.execute('DELETE FROM blocks WHERE user_id=5 AND blocked_id=4')

    def test_simultaneous_message_retries_commit_once(self):
        cid=self.call(4,'POST','/api/groups',json={'title':'Concurrent send regression','member_ids':[5]})['chat_id']
        def send(_):return self.call(4,'POST',f'/api/chats/{cid}/messages',json={'text':'One concurrent message','client_id':'concurrent-send-regression'})['id']
        with ThreadPoolExecutor(max_workers=2) as workers:ids=list(workers.map(send,range(2)))
        self.assertEqual(ids[0],ids[1])
        with self.db() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM messages WHERE sender_id=4 AND client_id=?',('concurrent-send-regression',)).fetchone()[0],1)

    def test_saved_message_confirmation_includes_validated_reply_and_attachment(self):
        cid=self.call(4,'POST','/api/groups',json={'title':'Message metadata regression','member_ids':[5]})['chat_id']
        reply=self.call(5,'POST',f'/api/chats/{cid}/messages',json={'text':'Original message'})
        with self.db() as conn:
            attachment=conn.execute('INSERT INTO attachments(chat_id,user_id,name,path,mime,size) VALUES(?,?,?,?,?,?)',(cid,4,'voice.webm','synthetic-metadata-fixture','audio/webm',123)).lastrowid
            conn.execute('UPDATE chats SET disappearing_seconds=86400 WHERE id=?',(cid,))
        body={'text':'A reply with a voice note','reply_to':reply['id'],'attachment_id':attachment,'client_id':'metadata-confirmation-regression'}
        sent=self.call(4,'POST',f'/api/chats/{cid}/messages',json=body)
        self.assertEqual(sent['reply'],{'id':reply['id'],'text':'Original message'})
        self.assertEqual(sent['attachment'],{'id':attachment,'name':'voice.webm','mime':'audio/webm','size':123})
        self.assertAlmostEqual(sent['expires_at'],time.time()+86400,delta=5)
        loaded=next(m for m in self.call(4,'GET',f'/api/v2/chats/{cid}/messages') if m['id']==sent['id'])
        self.assertEqual(loaded,sent)


if __name__ == '__main__':
    unittest.main()
