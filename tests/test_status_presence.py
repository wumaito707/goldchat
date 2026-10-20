"""Regression checks for per-post status privacy and chat presence."""
import os
import gc
import tempfile
import time
import unittest
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
            for name in ('author', 'viewer', 'other'):
                conn.execute('INSERT INTO users(username,display_name,password_hash,salt,avatar_initial,created_at) VALUES(?,?,?,?,?,?)',
                             (name, name.title(), 'unused', 'unused', name[0].upper(), server.now_iso()))
            conn.execute('INSERT INTO contacts(user_id,contact_id) VALUES(2,1)')
            conn.execute('INSERT INTO contacts(user_id,contact_id) VALUES(3,1)')
            conn.execute('INSERT INTO contacts(user_id,contact_id) VALUES(1,2)')
        cls.tokens = {uid: server.create_session(uid) for uid in (1, 2, 3)}
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


if __name__ == '__main__':
    unittest.main()
