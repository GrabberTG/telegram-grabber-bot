# MyGrab — Telegram Grabber and Automatic Channel Reposting

[Русский](README.md) · **English**

[![Release](https://img.shields.io/badge/release-v2026.10.17.1-blue)](https://github.com/GrabberTG/telegram-grabber-bot/releases/latest) [![Downloads](https://img.shields.io/github/downloads/GrabberTG/telegram-grabber-bot/total?label=downloads)](https://github.com/GrabberTG/telegram-grabber-bot/releases) [![Stars](https://img.shields.io/github/stars/GrabberTG/telegram-grabber-bot?label=stars&color=blue)](https://github.com/GrabberTG/telegram-grabber-bot/stargazers)

**MyGrab Free** is a free Telegram grabber for automatically copying messages between Telegram channels. Repost text, photos, videos and albums, replace links and mentions, and review posts before publication.

**[⬇ Download Free for Windows](https://github.com/GrabberTG/telegram-grabber-bot/releases/latest/download/MyGrab_Free_Windows.zip)** · **[Get MyGrab Premium](https://t.me/mygrab_premium_bot)** · **[Project channel](https://t.me/mygrab_tg)**

![MyGrab — Telegram auto reposting, channel messages, filters and moderation in Premium](assets/mygrab-premium.png)

## Free Telegram bot features

- Automatic reposting of new messages from selected source channels.
- Text, photos, videos, documents and media albums.
- Multiple sources; **one destination per source**.
- One common replacement link and one replacement `@username` in the configuration.
- Replacement of plain URLs and HTML links while keeping link labels.
- Optional moderation through a private technical channel: preview, text/caption editing and approval.
- Telegram channel history copying with `/last_messages`.
- Channels, routes, moderation state and pending posts saved in a local SQLite database.
- Channel and route changes take effect without restarting. Removing a channel also removes its routes.
- Owner-only controls, protection against routing cycles and duplicate processing of new posts.
- English and Russian interface; your own Telegram account and bot.

Project promotion appears in the welcome message, help and management menu. **No promotional footer is added to reposted content.** Joining the project channel is optional.

> ⭐ **If MyGrab helps you, [give it a star](https://github.com/GrabberTG/telegram-grabber-bot)** (the Star button at the top). It helps others find the project.

## Windows installation — no Python required

1. Download **[MyGrab_Free_Windows.zip](https://github.com/GrabberTG/telegram-grabber-bot/releases/latest/download/MyGrab_Free_Windows.zip)** from the [latest release](https://github.com/GrabberTG/telegram-grabber-bot/releases/latest) and extract the complete archive into a new permanent folder (right-click → Extract All). Keep `_internal` next to `main.exe`.
2. Run **`1_setup.bat`** to open `config.json`. Enter your own credentials using the table below, then save.
3. Run **`2_authorize.bat`**. Enter your Telegram account's phone number, login code and two-step verification password if enabled. Do not run another copy at the same time.
4. Close the authorization window and run **`3_start.bat`**.
5. Open your bot and send `/start` from the owner's account.

Archive check: [VirusTotal](https://www.virustotal.com/gui/file/ed4352837c8796202bd97ccb1545d0723466301c248296ac0d98d462ea4d6787) · SHA-256 in [`SHA256SUMS.txt`](SHA256SUMS.txt). The executable includes Python and its libraries. A system-wide Python installation is not required for this package. The binary targets **Windows x64**.

## Run the Python source

Download the repository using **Code → Download ZIP**, extract it into a separate folder, and install **Python 3.11 x64 with Python Launcher** from [python.org](https://www.python.org/downloads/windows/). Use the same three launchers: `1_setup.bat`, `2_authorize.bat`, `3_start.bat`.

The setup script creates a separate environment and installs the pinned dependencies from `requirements.txt`. Alternatively:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item config.example.json config.json
# Fill in config.json before proceeding.
.venv\Scripts\python.exe main.py --authorize
.venv\Scripts\python.exe main.py
```

Copy the example only for a new installation. Do not overwrite an existing configured file.

## Configuration

Create your own bot with [@BotFather](https://t.me/BotFather). Obtain `api_id` and `api_hash` for your own application at [my.telegram.org](https://my.telegram.org).

| `config.json` field | Value |
|---|---|
| `api_id` | Your numeric API ID, without quotes |
| `api_hash` | Your API hash as a quoted string |
| `bot_token` | Your bot's token |
| `my_id` | Numeric owner ID; only this user can manage the bot |
| `technical_channel_id` | Private moderation channel ID starting with `-100`; use `0` if moderation is not needed |
| `new_link` | Common replacement URL starting with `https://`; an empty string keeps original links |
| `new_username` | Replacement `@username`; an empty string keeps original mentions |
| `language` | Set **`en`** for English or `ru` for Russian |

The authorized account must be a member of source channels and have posting rights in destinations. For moderation, give the account posting/editing rights in the technical channel and allow the bot to post messages with controls there. The technical channel cannot be used as a source or destination.

This release uses `config.json` and `mygrab_free.db`. Older `config.py` and `.pickle` settings are not imported automatically. Install it separately from the older executable. Do not use another person's Telegram session.

## Set up automatic forwarding between Telegram channels

Use the `/start` menu to add a source, a destination and a route. Both `@username` and full numeric IDs are supported. Example:

```text
/add_channel -1001111111111
/add_destination_channel -1002222222222
/set_channel_mapping -1001111111111 -1002222222222
/show_mapping
```

Publish a **new** source post to test it. Automatic reposting accepts messages created after the program starts. Messages published while the program was stopped are not automatically replayed.

Keep the computer on, the program running, and both Telegram connections available. Free does not include proxy configuration; provide network access at the computer level. A home computer does not require a rented server.

## Copy Telegram channel history

```text
/last_messages -1001111111111 5
/last_messages 5
/last_messages -1001111111111 all
/cancel_copy
```

The first command processes the last five messages from one source **only to its configured destination**. The second processes five messages from each configured source, using each source's own route. `all` processes the accessible history. Albums are kept together and count as one send; a boundary album may include messages outside the specified N.

Manual history processing has a fixed one-second pause between posts. Mandatory Telegram waits are applied in addition. The summary separates sent, queued, skipped and failed posts. New automatic posts can be processed alongside the copy job; sends to the same destination are coordinated.

## Moderation before publishing

Configure a technical channel and enable moderation in the menu. The prepared post and approval controls appear there. Edit the preview text/caption if needed, then publish. Multiple edited album captions are joined into one caption. Replacing the media itself through the preview is not supported.

`/pending` lists saved pending posts. Moderation state and the queue survive a restart. If the preview could not be delivered, its queue record remains available. Only the owner can approve or reject posts.

## Free vs Premium

| Feature | MyGrab Free | MyGrab Premium |
|---|---|---|
| Text, photos, videos and albums | Yes | Yes |
| Channel routing | One destination per source | Multiple destinations per source |
| Link and `@username` replacement | One common value each in `config.json` | Common values plus any word → word, link → link and wildcard rules in the bot menu |
| Pre-publication moderation | Yes | Yes |
| Standard emoji | Yes | Yes |
| **Preserving custom emoji through the customized `addon`** | Standard Unicode fallback | **Yes** |
| Blacklist / whitelist and text removal | No | Yes |
| FS contest invitation filter | No | Yes, with exceptions for results |
| Per-destination footer | No | Yes |
| Manual history copying | `/last_messages`, fixed pause | `/last`, `/last_save`, configurable intervals, batches and rest |
| Fallback source polling | No | Yes |
| External MTProto/HTTP proxy configuration | No | Yes |

Premium uses the customized `addon` module for formatting and custom emoji. Sending a particular custom emoji also depends on Telegram account capabilities and restrictions. Free keeps the standard Unicode symbol. Updates are installed manually in both editions.

## FAQ

### What is a Telegram grabber?
A program that automatically copies new posts from selected Telegram channels into your own channels. MyGrab is a free, open-source grabber: auto posting, reposting without the "Forwarded from" label, link replacement and moderation.

### How do I automatically repost from someone else's channel to mine?
Your account must be a member of the source channel and be allowed to post in your channel. Add the source and the destination in the bot menu and link them. New posts are copied automatically while the program runs.

### Can I copy a private channel?
Yes, if your account is a member of it. If the channel owner restricted saving content, Telegram may refuse to send its media.

### Will posts show "Forwarded from"?
No. Each post is published by your channel as a new message, with no link to the source. Links and `@username` can be replaced with yours.

### Do I need to be an admin of the source channel?
No. Your account only needs to be subscribed to the source. Posting rights are required only in your destination channels.

### Is it free?
Yes. MyGrab Free is free, with no subscription and no ads added to your posts. Advanced features are in [Premium](#buy-mygrab-premium).

### Do I need a server or VPS?
No. A Windows computer running the program is enough. For 24/7 operation use a Windows VPS or run the Python source.

### How do I copy old posts of a channel?
Use `/last_messages` — see [Copy Telegram channel history](#copy-telegram-channel-history).

### My antivirus flags main.exe. Is it a virus?
No. Antivirus software sometimes falsely flags programs built with PyInstaller. The full source code is in this repository. [VirusTotal report](https://www.virustotal.com/gui/file/ed4352837c8796202bd97ccb1545d0723466301c248296ac0d98d462ea4d6787) for the release archive: 1 of 66 — a Zillya heuristic; the other 65 engines found nothing. If in doubt, run it from the Python source.

### Is it safe for my account?
The program runs on your computer; your keys and session are never sent anywhere. Telegram may limit very frequent sending, so avoid copying huge archives without pauses.

## Buy MyGrab Premium

Premium is a ready-to-run Windows 10/11 program (no Python required) sold as a subscription. Updates are included.

| Term | Price |
|---|---|
| 1 month | RUB 490 |
| 3 months | RUB 1,290 |
| 12 months | RUB 3,990 |

1. Open **[@mygrab_premium_bot](https://t.me/mygrab_premium_bot)** — it sends you the program.
2. Run `КОД КОМПЬЮТЕРА.bat` (machine code) and send the code to the bot.
3. Pay by card or cryptocurrency — the manager sends payment details. The key arrives in the bot once payment is confirmed.

A key is bound to one computer; renewals add days to the current term. **Full Premium source code — RUB 20,000.** Custom development by agreement.

**[Subscribe: @mygrab_premium_bot](https://t.me/mygrab_premium_bot)** · **[Questions or bot offline: @every_manager](https://t.me/every_manager)** · **[News: @mygrab_tg](https://t.me/mygrab_tg)**

## Checks and backups

Run an installation check without connecting to Telegram:

```text
main.exe --self-check
```

For source code, use `py -3.11 main.py --self-check`. Run local regression tests with `python -m unittest discover -s tests -v` in the installed environment. These use simulated connections; actual Telegram connectivity and channel permissions must be checked separately.

Start with two test channels. Stop the program with `Ctrl+C`. For a backup, stop it and copy its complete folder. Never publish your `config.json`, `MyGrab_Free.session` or `mygrab_free.db`. If a connection fails while a send is being acknowledged, inspect the destination before retrying.

The program works with channels accessible to your account and does not guarantee avoidance of Telegram restrictions.
