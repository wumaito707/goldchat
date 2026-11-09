# GOLDCHAT user guide

GOLDCHAT is a messaging app available at https://goldchat.onrender.com. Its Android app opens the same live service. Messaging requires an internet connection. This guide describes the current implementation; it does not promise that every feature has been tested on every phone.

## Install or open

Open the website on a phone or computer. Download the current Android APK at https://goldchat.onrender.com/static/downloads/goldchat-1.0.1.apk. Android may ask permission to install from the browser. On iPhone, open the website in Safari and use Share → Add to Home Screen. There is no published Play Store or Apple App Store listing yet.

## Create an account and sign in

Choose Create one, enter your display name, username, email and password, then request a verification code. Enter the six-digit code emailed to you and choose Verify & create account. Registration uses email verification, not SMS. Usernames use letters, numbers and underscores; passwords need at least eight characters.

Codes last 60 minutes. You can resend after 60 seconds; while a code remains valid, resending keeps that code and refreshes its expiry. Check spam if delivery is delayed. Too many requests or wrong guesses temporarily limit verification.

Sign in with your username or verified email and password. Forgot password sends an email code so you can choose a new password. Existing accounts can verify their email under Features → Profile & privacy → Verify email for password recovery.

## Find people and manage contacts

Use + / New chat to search GOLDCHAT users by username or display name and start a conversation. Features → Contacts lets you find and save users. Home shows one entry per person, including when older duplicate conversations exist.

Import phone contacts opens a contact chooser on supported Android browsers. Select contacts, review matching GOLDCHAT accounts and add them. It does not automatically import your whole address book. If unsupported, use username search.

Delete contact removes that person from your saved contacts but keeps messages and their account. Contact backup downloads a JSON file; Restore contact backup restores saved GOLDCHAT contacts from that file.

## Send messages

Open a conversation, type and press Send. The composer includes emoji. The app shows unread counts and typing indicators. Double check marks turn blue when the recipient reads the message. Drafts are saved in the current browser, not synchronized between devices.

Open the menu beside a message to reply, copy text, share text, forward, star, pin, react or delete for yourself. Your own messages also support editing and deleting for everyone. Deleting for yourself only hides your copy; deleting for everyone leaves a deleted-message placeholder. Forwarding sends a copy to another chat.

Features → Starred messages shows saved favourites. Chat menu → Pinned messages shows important messages pinned in that conversation. Chat menu → Search messages searches the conversation. Load older messages retrieves earlier history.

## Photos, videos, audio and files

Use the attachment button to send a photo, video, audio file or document. The current limit is 10 MB per file. Supported images, video and audio appear with previews or playback controls; other files use download links.

Tap the microphone to record a voice note, allow microphone access and tap again to stop and send. Recording stops automatically after two minutes. Recipients play it with the audio controls in the conversation.

## Profiles and privacy

Features → Profile & privacy lets you change your display name, about text and profile picture. Save after making changes. Tap a person's name or picture in a conversation to view their public profile and start a message or add them as a contact. Their email address is not displayed publicly.

Privacy controls manage status and presence visibility. Blocking prevents direct messaging between the two accounts. Use the chat menu to block or unblock, or Features → Blocked users to unblock later.

## Status updates

Features → Status updates lets you post text, photos, videos or audio, with an optional caption. Record audio status records and posts an audio update. Each status expires after 24 hours; its author can delete it earlier.

Statuses are not a public feed for every GOLDCHAT account. Viewers need to save the author as a contact. My contacts visibility also requires the author to save the viewer. For friends to see each other's statuses, save each other and choose a suitable privacy setting. Blocked users cannot see each other's statuses.

## Groups and channels

New group lets you name a group, select users and create it. Group members can send messages. Features → Create channel creates a channel where the owner posts updates for members.

Chat menu → Members shows the member list. Owners can rename the space, add or remove users and transfer ownership. Other members can leave. These are selected-member groups and channels; public channel discovery and communities are not implemented.

## Polls, tasks and events

Chat menu → Polls lets you create a question with 2–10 options. Members vote and can change their vote. Shared tasks lets you add tasks and mark them complete or incomplete. Events lets you save a title, date, time and description in a conversation. Events do not yet provide full calendar integration or automatic reminders.

## Organize your home page

The chat menu lets you pin a conversation near the top, archive it or mute its notifications. Use the archived view to find archived chats and unarchive them. Muting does not delete a conversation. Previous conversations provides access to older conversation records where relevant.

## Notifications and phone access

The bell or Features → Notifications opens your notification inbox. Tap a notification to open its related item, or choose Mark all read.

Features → Settings & accessibility → Phone permissions provides notification, microphone, camera and contact-import controls. Enable notifications for alerts; microphone access supports voice notes and calls; camera access supports scanning and video calls. Background notifications require a compatible browser and operating-system permission.

On Android, hold the GOLDCHAT icon → App info → Notifications to allow alerts. Some camera and microphone controls are under Chrome → Settings → Site settings → goldchat.onrender.com because the Android app uses Chrome to run the website. Contact import uses a chooser for selected contacts. Actual notification delivery still needs checking on your phone.

## QR codes and linked devices

Features → My QR & share displays your contact QR code and profile link. Share or copy the link so another user can find you. Features → Scan code supports the camera, a QR image or a pasted GOLDCHAT link.

To sign in on another device, choose Link device with QR on its login screen and generate a QR code. On your signed-in device, open Features → Linked devices, scan that device QR and approve it. Device-login codes are single-use and expire after five minutes. Approve only your own devices: this QR grants account access.

Linked devices lists sessions and lets you unlink a device. Chats stored on the server are accessible from other signed-in devices; local drafts and browser preferences are separate.

## Disappearing messages

Chat menu → Disappearing messages lets you choose an available expiry setting or turn it off. Expiring messages are removed according to the configured timer. This cannot erase screenshots or copies that someone already saved.

## Calls and call history

The conversation header has voice and video call buttons. Recipients can accept or decline, and call controls include mute and hang up. Features → Call history shows incoming and outgoing call records, missed calls and available durations.

Call signalling and local-network peer-to-peer controls exist, but reliable calls across different internet networks are not finished: STUN/TURN connectivity support still needs configuration and real-device testing. Do not advertise universal internet-call reliability yet.

## Export and import

Features → Export messages & contacts downloads JSON data for chats, messages and contacts. Chat menu → Export this chat exports one conversation. These are data exports, not a complete backup of all uploaded media.

Import messages accepts a GOLDCHAT single-chat JSON export up to 5 MB. It creates labelled text copies posted by the importing user. It does not restore original sender identities, timestamps or media and does not import WhatsApp history.

## Appearance and accessibility

Settings & accessibility includes gold dark and gold light themes, larger text, reduced animation and notification preferences. Save settings after changing them. These preferences apply to the current browser/device. Use Log out to end your session.

## How the service works and current limits

Render runs the website and application server, Turso stores account and chat data, Supabase stores uploaded media, and Brevo sends verification emails. The website and Android app use the same accounts and online conversations. The free Render server can sleep when unused, delaying the first request while it starts again.

GOLDCHAT has email verification, password hashing, expiring sessions and access checks, but it does not currently provide end-to-end encryption. Offline messaging, complete automatic backups and native iOS distribution are not implemented.

Payments, wallets, premium subscriptions, marketplaces, creator monetization, live streaming, voice rooms, watch parties, AI agents, bots, mini-apps, a public developer platform, transcription, call translation and enterprise workspaces remain future possibilities.

## Content for the future information website

Use this guide to create Home, Features, How to use GOLDCHAT, Download and Help/FAQ pages. Keep current features, limitations and future plans clearly labelled. Privacy and terms pages must describe the actual service and data handling.
