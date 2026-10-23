# GOLDCHAT owner dashboard

Open `https://goldchat-app.pages.dev/?admin=1` and sign in with the designated owner account. The same dashboard is available from **More → Owner dashboard** after signing in.

The project owner selected the existing **Johns** account, whose sign-in username is **Jos**. Startup provisions that exact record using its ID, username and original creation timestamp in `admin_console.OWNER_ACCOUNT`. A matching display name, new registration, profile field or browser setting cannot grant owner access. Changing the designated owner requires a reviewed server configuration change; there is no public role-grant endpoint.

## Available controls

- Overview: registration, conversation, retained-message, active-status and session totals; recent registrations and configuration indicators.
- Users: search names, usernames and verified email addresses; filter active, banned and deleted accounts; view each account's conversations.
- Account management: ban/unban, sign out all devices, recoverably delete/restore. Ban and delete revoke sessions and disconnect sockets on the server handling the action. Other server instances recheck sessions when their short authentication cache expires. Restoring an account requires the user to sign in again. A banned account stays banned if its deleted state alone is restored.
- Conversations: review retained messages with a support or moderation reason; load earlier messages and explicitly open shared media. Reviews do not mark participant messages as read.
- Statuses: review active status text and media with a reason.
- Calls: participant, time, outcome and duration metadata. GOLDCHAT does not record call audio or video.
- Audit log: recorded content reviews and account actions, including owner, time, reason and reference. The dashboard has no audit-edit or audit-delete endpoint.

## Access and retention

Administrative endpoints freshly verify the session, account state and owner role on every request, return `Cache-Control: no-store`, and expose only selected account fields. Password hashes, password salts, session tokens and provider credentials are not returned. Owner accounts are protected from the dashboard's ban, delete and sign-out-all controls; use Linked devices to manage owner sessions.

Content and media review requires a reason of 10–500 characters. The audit must be saved before content is returned. Expired content is excluded, deleted message text is replaced with a tombstone, and files attached only to deleted or expired messages cannot be reviewed. This does not restore content already removed by expiry cleanup.

Administrative deletion is **recoverable account disablement**, not permanent data erasure. Retained conversation history remains available for moderation. The interface requires the exact username before deletion or restoration and explains this retention.

GOLDCHAT currently stores chats on its servers without end-to-end encryption. The sign-in screen, signed-in app and Privacy & admin access page disclose administrative access. Presence and read-receipt settings apply to other users; they do not prevent authorized moderation review.

## Verification

Run `python -m unittest discover -s tests -v`. The synthetic-data regression checks cover exact-record provisioning, anonymous/non-owner rejection, immediate role checks, reason validation, pagination, audit-before-media access, failure when audit storage is unavailable, expiry/deletion exclusions, unchanged read state, owner protection and session revocation on ban/deletion/sign-out. Existing status, presence, delivery and Google identity checks run in the same suite.
