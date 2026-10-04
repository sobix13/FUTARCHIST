# FUTARCHIST 2.1.2 release

Version: `2.1.2`. Database schema: `2`.

## What changed

- README and command help start with the representative, admin and superadmin entry points.
- Guide copy focuses on workspace selection, intake codes, Cases and follow-up actions. Repeated interface-policy statements are removed.
- Browser help explains which invitation fields are substituted and how Bot text edits work.
- The web guide explains that Telegram and the dashboard share records and permissions.
- Offline guide packaging includes both stylesheets, the favicon and all supplied images. Source and operations ZIPs are rebuilt with matching documentation.
- Verification includes branding and copy regressions in the full release suite.

## Compatibility

This is a documentation, help-copy and packaging update. Business operations, form rules, permissions, callbacks and database schema are unchanged. Existing credentials, projects, source tags, drafts and custom bot copy remain in place. No new migration is required.

Already delivered Telegram messages aren't rewritten. A superadmin's saved welcome or help text isn't silently replaced. Edit custom copy through Bot text when needed.

## Verification

Current results are in [backend and static checks](../reports/test-results.json), [DOM checks](../reports/dom-report.json), [package checks](../reports/package-check.json) and the [test report](../reports/test-report.html). Package verification extracts a fresh ZIP and runs the full Python suite from that copy.

DOM tests verify interactive behavior against local HTTP. They don't measure graphical layout or prove official Telegram client behavior. Live API evidence in `reports/live-telegram.json` comes from the earlier 2.1.0 check, not a new production acceptance test. VPS deployment and human mobile/group flows remain separate checks.

## Earlier updates

Version 2.1.1 made guides discoverable in Telegram, preserved unfinished admin steps, added page-specific instructions and mapped dashboard navigation to the workflow. It also added guarded HTTPS installation with rollback checks.

The subsequent image patch applied the supplied banner and F logo without restyling the interface. Original artwork remains unchanged in this release.

## Deployment

Update source and restart `futarchist-bot.service` and `futarchist-web.service`. This copy update doesn't need `--configure-bot`, a new token, a certificate change or the HTTPS installer. Preserve `.env` and the data directory.

The current VPS uses a separate `futarchist-proxy.service` on port 9443. Leave that proxy and unrelated services in place. Fresh installations should follow [DEPLOY.md](../extensions/DEPLOY.md).

Built by Ownership. Support: `@sobix13` / `@SrMessiSOL`.
