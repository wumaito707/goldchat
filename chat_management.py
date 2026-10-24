"""Personal conversation actions. Never remove another member's messages."""
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field


def init_schema(conn):
    columns = {r[1] for r in conn.execute('PRAGMA table_info(chat_preferences)')}
    for name, definition in [('hidden_through_id', 'INTEGER'), ('manual_unread', 'INTEGER NOT NULL DEFAULT 0')]:
        if name not in columns:
            conn.execute(f'ALTER TABLE chat_preferences ADD COLUMN {name} {definition}')


class BulkAction(BaseModel):
    chat_ids: list[int] = Field(min_length=1, max_length=100)
    action: str


def install(app, b):
    @app.post('/api/chats/bulk')
    async def manage_chats(body: BulkAction, token: str = Depends(b['session_token'])):
        uid = b['auth_user'](token)['id']
        actions = {'mark_read', 'mark_unread', 'mute', 'unmute', 'archive', 'unarchive', 'clear', 'delete'}
        if body.action not in actions:
            raise HTTPException(400, 'Choose a supported chat action')
        ids = list(dict.fromkeys(body.chat_ids))
        marks = ','.join('?' for _ in ids)
        conn = b['get_db']()
        try:
            with conn:
                conn.execute('BEGIN IMMEDIATE')
                # Validate the entire selection before applying any change.
                members = {r[0] for r in conn.execute(
                    f'SELECT chat_id FROM chat_members WHERE user_id=? AND chat_id IN ({marks})', (uid, *ids))}
                if members != set(ids):
                    raise HTTPException(403, 'You can only manage your own conversations')
                conn.execute(f'INSERT OR IGNORE INTO chat_preferences(chat_id,user_id) SELECT chat_id,user_id FROM chat_members WHERE user_id=? AND chat_id IN ({marks})', (uid, *ids))
                if body.action in {'clear', 'delete'}:
                    conn.execute(f'INSERT OR IGNORE INTO message_hidden(message_id,user_id) SELECT id,? FROM messages WHERE chat_id IN ({marks})', (uid, *ids))
                    conn.execute(f'UPDATE chat_preferences SET manual_unread=0 WHERE user_id=? AND chat_id IN ({marks})', (uid, *ids))
                    if body.action == 'delete':
                        conn.execute(f'UPDATE chat_preferences SET hidden_through_id=(SELECT COALESCE(MAX(id),0) FROM messages WHERE chat_id=chat_preferences.chat_id) WHERE user_id=? AND chat_id IN ({marks})', (uid, *ids))
                elif body.action == 'mark_unread':
                    conn.execute(f'UPDATE chat_preferences SET manual_unread=1 WHERE user_id=? AND chat_id IN ({marks})', (uid, *ids))
                elif body.action in {'mute', 'unmute', 'archive', 'unarchive'}:
                    column = 'muted' if body.action in {'mute', 'unmute'} else 'archived'
                    enabled = int(body.action in {'mute', 'archive'})
                    conn.execute(f'UPDATE chat_preferences SET {column}=? WHERE user_id=? AND chat_id IN ({marks})', (enabled, uid, *ids))
        finally:
            conn.close()
        if body.action == 'mark_read':
            # The normal read path retains the recipient's receipt/privacy rules.
            for cid in ids:
                await b['mark_read'](cid, token)
        await b['mgr'].send_to_user(uid, {'type': 'personal_chats_changed', 'chat_ids': ids, 'action': body.action})
        return {'ok': True, 'count': len(ids)}
