# Free-first GOLDCHAT deployment

The app is prepared for Render, an external Turso SQLite database, private Supabase Storage, and Brevo email delivery. It is not deployed yet. Provider connections and real cloud delivery still require verification.

1. Create a Turso database. Save its libsql database URL and database auth token in Render as TURSO_DATABASE_URL and TURSO_AUTH_TOKEN.
2. Create a Supabase project and a **private** Storage bucket called goldchat-private. Set GOLDCHAT_STORAGE_URL to the project HTTPS URL and GOLDCHAT_STORAGE_KEY to its server-only service-role key. Never put this key in frontend code.
3. Create a Brevo account, verify a sender, enable transactional delivery, and create an API key. Enter the key as GOLDCHAT_EMAIL_API_KEY and verified sender email as GOLDCHAT_SMTP_FROM in Render. Free Render blocks SMTP ports, so the local Gmail SMTP settings cannot be used there.
4. Upload the clean release contents to your GitHub repository. Do not upload your local database, media folders, credentials, vendor runtime or verification key.
5. In Render select New > Blueprint and connect that repository. render.yaml selects the free web service. Enter the missing environment values privately in Render. Review the plan before creating the service.
6. Test signup code delivery, password recovery, two-user messaging, profiles, media access and a restart. Accounts and media must survive the restart. The cloud adapters have no live provider verification until these checks pass.
7. Open the HTTPS onrender.com address on your phone or computer and choose Install app / Add to Home Screen. This creates an installed web app; app-store packages are separate work.

The cloud database starts empty. Existing local accounts and uploads are not migrated automatically. Keep a local backup before any migration.

Free plans have quotas and may sleep or pause. WebSocket connections disconnect when the Render process sleeps or restarts. Calls still need separate TURN configuration for reliable connections across networks. Expired status records are hidden, but old stored media needs retention cleanup to control storage usage.

Keep all credentials in provider dashboards, never in chat or GitHub. Replace credentials previously shared in chat.

## Cloudflare Realtime TURN for voice and video calls

GOLDCHAT can make direct WebRTC calls using STUN without a TURN account, but some mobile networks, firewalls, or symmetric NATs require a relay. The server now supports Cloudflare Realtime TURN as a fallback for **both** voice and video calls.

1. In the Cloudflare dashboard, go to **Realtime → TURN**, create a TURN key, and copy its **TURN Key ID** and **TURN API Token**. These are permanent server-side secrets. See [Cloudflare's credential guide](https://developers.cloudflare.com/realtime/turn/generate-credentials/).
2. In **Render → GOLDCHAT service → Environment**, add `GOLDCHAT_TURN_KEY_ID` and `GOLDCHAT_TURN_API_TOKEN` with those values. Do this for each separately deployed backend used by the website. The Cloudflare Pages Worker currently proxies `/api` to the Frankfurt Render service.
3. Save the environment settings and let Render redeploy/restart. **Do not** commit the credentials, paste them into chat, or expose them as Cloudflare Pages frontend variables.
4. The authenticated `GET /api/calls/ice-config` endpoint asks Cloudflare for **temporary credentials** (24-hour expiry) on the backend. It responds with `Cache-Control: private, no-store`. The browser automatically uses them in `RTCPeerConnection`. A five-minute in-memory browser cache avoids repeated requests during closely spaced calls.
5. Test with two different accounts and devices: voice and video calls on Wi-Fi ↔ mobile data, accept, decline, mute, and hang up. If TURN is not configured or temporarily unavailable, calls fall back to direct STUN; restrictive networks may still fail.
6. Set a Cloudflare Realtime usage/billing alert and review costs before inviting many users. TURN is billed by outbound data after any applicable allowance; consult [current pricing](https://developers.cloudflare.com/realtime/sfu/platform/pricing/).

To confirm setup without seeing any secrets, sign in to GOLDCHAT and open a call; the call screen should say **Encrypted relay ready if direct connection fails**. Unauthenticated requests to the ICE endpoint are rejected.
