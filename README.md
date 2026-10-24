# GOLDCHAT

Messaging app with email verification and private cloud media. See DEPLOY.md. Web assets are packaged in static.zip and extracted by Docker.

Run backend regression checks with `python -m unittest discover -s tests -q` after installing `requirements.txt`. For client message-flow checks, run `npm ci --prefix tests/frontend`, then `npm --prefix tests/frontend test`. These use synthetic accounts and a controllable network to exercise slow sends, retries, refresh races, privacy receipts and sign-out.

Build matching Render assets and a Cloudflare Pages upload with `python scripts/package_release.py --output ../goldchat-instant-messages-pages.zip`.
