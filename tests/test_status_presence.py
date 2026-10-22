"""Regression checks for per-post status privacy and chat presence."""
import os
import gc
import json
import tempfile
import time
import unittest
from unittest.mock import patch
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient


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

    def test_google_signup_and_existing_email_protection(self):
        from google.oauth2 import id_token
        with patch.dict(os.environ, {'GOLDCHAT_GOOGLE_CLIENT_ID': 'test-web-client'}), patch.object(id_token, 'verify_oauth2_token') as verify:
            verify.return_value={'sub':'google-test-123','email':'new-google-user@gmail.com','email_verified':True,'name':'Google User'}
            created=self.client.post('/api/auth/google',json={'credential':'signed-test-token'})
            self.assertEqual(created.status_code,200,created.text)
            self.assertEqual(created.json()['user']['display_name'],'Google User')
            self.assertEqual(self.client.post('/api/auth/google',json={'credential':'signed-test-token'}).json()['user']['id'],created.json()['user']['id'])
            with self.db() as conn:
                conn.execute('UPDATE users SET verified_email=? WHERE id=1',('existing@gmail.com',))
            verify.return_value={'sub':'google-test-456','email':'existing@gmail.com','email_verified':True}
            conflict=self.client.post('/api/auth/google',json={'credential':'another-signed-token'})
            self.assertEqual(conflict.status_code,409)
            linked=self.client.post('/api/auth/google',json={'credential':'another-signed-token'},headers={'Authorization':'Bearer '+self.tokens[1]})
            self.assertEqual(linked.status_code,200,linked.text)
            self.assertEqual(linked.json()['user']['id'],1)
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
            self.assertTrue(any(event['type'] == 'chat_changed' for event in socket.events))
        finally:
            server.mgr.active.pop(ws_id, None)
            server.ONLINE.get(5, set()).discard(ws_id)
            if not server.ONLINE.get(5):
                server.ONLINE.pop(5, None)


if __name__ == '__main__':
    unittest.main()
