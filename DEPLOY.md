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
