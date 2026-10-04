# FUTARCHIST image-only branding

The supplied banner and logo screenshot are stored unchanged. Their colors, embedded lettering and original JPEG bytes are retained. Image placement doesn't change interface colors, fonts or access rules. Copy revisions are recorded separately in the release notes. Ownership credits and MetaDAO assets remain in place.

## Web app

- The supplied banner appears on the login page, dashboard header and web guide.
- The supplied F logo replaces the old primary app icon. CSS displays the mark through a square window without editing the source image.
- Both images are public static assets. No session or private data is attached to their URLs.
- Original interface styles are retained. Image placement uses a separate stylesheet.

## Telegram profile

Run from the installed app directory:

```bash
runuser -u futarchist -- .venv/bin/python -B tools/brand_bot.py \
    --env .env --expected-bot-id 8911627546 --apply-profile
```

The tool checks the bot ID before uploading the supplied logo using `setMyProfilePhoto`. It changes only the profile photo. It does not poll updates, send messages, change descriptions or alter commands. Telegram controls the profile-image framing.

## Telegram description image

In the verified `@BotFather` chat, send `/mybots`, choose `@FutarchistBot`, open Edit Bot and select Edit Description Picture. Upload `ownership/static/assets/futarchist-banner.jpeg` as a photo. Leave all description text unchanged. The Bot API does not expose this BotFather image setting.

The original banner is 1536 by 512 pixels. If BotFather requests a different size, use the original in Telegram's image editor and retain its full width. Do not stretch the lettering or redraw the artwork.

## Existing VPS proxy

The deployed HTTPS origin uses port 9443 and the independent `futarchist-proxy.service`. An image-only update requires restarting `futarchist-web.service` after updating the source. It does not require rerunning the HTTPS installer or modifying Nginx, Xray, Memecult, certificates, `.env` or data.
