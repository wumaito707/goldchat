# GOLDCHAT Cloudflare Pages bundle

The live Pages deployment contains the files from `static.zip` plus `_worker.js` at the ZIP root. The Worker serves `/static/*` from Pages assets and forwards `/api/*`, `/ws`, and `/healthz` to the Frankfurt Render backend. Keep frontend requests same-origin so private-media cookies and WebSocket authentication work consistently.

`frontend/` contains the editable source for the five frontend files changed by the desktop navigation, Favorites filter, full-screen Updates and Calls views, attachment chooser, and earlier Pages routing fix. Those same files are packaged inside `static.zip`, which Render extracts during its Docker build.

To publish manually to Cloudflare Pages, create a ZIP containing the root entries of `static.zip` and `_worker.js` (without a parent folder), then upload it as a production deployment of `goldchat-app`. Check `/static/app.js`, `/healthz`, and an unauthenticated `/api/chats` request after deployment; they should return JavaScript, JSON health, and JSON 401 respectively.
