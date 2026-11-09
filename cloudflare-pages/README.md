# GOLDCHAT Cloudflare Pages bundle

The live Pages deployment contains the files from `static.zip` plus `_worker.js` at the ZIP root. The Worker serves `/static/*` from Pages assets and forwards `/api/*`, `/ws`, and `/healthz` to the Frankfurt Render backend. Keep frontend requests same-origin so private-media cookies and WebSocket authentication work consistently.

`frontend/` contains editable source for the frontend, including the public marketing pages under `about/`. Render extracts `static.zip` during its Docker build and then overlays this source directory, so text changes in `frontend/` are not lost when a previously built bundle is present.

For search engines, `https://goldchat-app.pages.dev/about/` and its linked marketing pages are the preferred public URLs. The `/` sign-in and authenticated app screen and the sponsorship-payment screen have `noindex` metadata. Render's `/static/about/*` URLs are alternative copies of the same marketing content and use canonicals pointing to Cloudflare Pages. The public `sitemap.xml` lists the marketing pages and privacy details, not accounts, chats, API endpoints or payment screens. Keep those signals consistent across deployments.

To produce matching Render and Cloudflare assets, run `python scripts/package_release.py --output ../goldchat-pages.zip`. To publish manually to Cloudflare Pages, upload that ZIP (with no parent folder) as a production deployment of `goldchat-app`. Check `/static/app.js`, `/about/`, `/sitemap.xml`, `/healthz`, and an unauthenticated `/api/chats` request afterward; the API request should return JSON 401.
