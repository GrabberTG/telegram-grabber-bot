# MyGrab Free — quick start

1. Extract the **complete** folder into a new permanent location. For the Windows binary, keep `_internal` next to `main.exe`.
2. Run `1_setup.bat`. Fill in your own `api_id`, `api_hash`, `bot_token` and `my_id` in `config.json`. Obtain API credentials for your own application at my.telegram.org and create your own bot with @BotFather. Numbers have no quotes; strings use double quotes.
3. For moderation, enter a private technical channel ID in `technical_channel_id`. Leave `0` if moderation is not needed. Give the account and bot posting permissions there.
4. `new_link` and `new_username` set one common replacement URL and mention. Empty strings keep the original values. Set **`language` to `en`** for the English menu, or `ru` for Russian.
5. Save the configuration. Run `2_authorize.bat` and enter your account's phone number, Telegram login code and two-step verification password if enabled.
6. Close the authorization window. Run `3_start.bat`, then send `/start` to your bot from the owner account specified by `my_id`.
7. Add a test source, a test destination and their route. Publish a new source post and inspect the result.

Your account must have source access and destination posting rights. Keep the computer on and the program running. Do not run two copies in the same folder. The Windows executable needs no Python installation; source code requires Python 3.11 x64.

Commands:

```text
/add_channel -1001111111111
/add_destination_channel -1002222222222
/set_channel_mapping -1001111111111 -1002222222222
/last_messages -1001111111111 5
/pending
/cancel_copy
/help
```

Automatic reposting accepts new messages after launch. Offline history is not automatically replayed. Copy history explicitly; each source uses its own route. Free supports one destination per source. Settings and pending posts are saved in `mygrab_free.db`.

Free uses a standard Unicode fallback for custom emoji. Preserving custom emoji through the customized addon, content filters, multiple destinations and advanced settings are available in Premium.

Premium: RUB 4,000 for the current version. Cryptocurrency payments are available by agreement. Confirm currency, network, amount and payment details privately before paying: **@every_manager**. Project channel: **@mygrab_tg**.

Check the installation without connecting to Telegram: `main.exe --self-check`, or `python main.py --self-check` for source code. Validate configuration with `--check-config`. Application log: `mygrab.log`.

Stop with `Ctrl+C`. Stop the program before copying its complete folder for a backup. Never share or commit `config.json`, `MyGrab_Free.session`, `mygrab_free.db` or logs. Old `.py` configurations and `.pickle` settings are not imported automatically.
