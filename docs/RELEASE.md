# FUTARCHIST 2.1.1 release

Version: `2.1.1`. Database schema: `2`. Interface language: English only.

## Included application

- Native Telegram management and a browser dashboard using shared operations.
- Personal and team workspaces, two configured superadmins and explicit member permissions.
- Private access codes with limits, expiry, restrictions, rotation and individual revocation.
- Conditional project and raise intake with separate review branches and source attribution.
- Combined filters, saved views, assignments, notes and case-related guest replies.
- Programs, participation, outcomes, tasks and history.
- Verified group connections, opt-in DM destinations and confirmed invitation previews.
- Permission-aware Excel, CSV and multi-dataset exports.
- Editable bot copy, archive and restore, confirmation-based deletion, health and backups.

## English-only update

All built-in messages, questions, choices, errors, native admin screens, browser screens, sample content, guides and documentation use English. The language selector has been removed. The dashboard flows left to right and uses English date and number formatting.

The startup upgrade converts recognized legacy defaults and generated labels, removes historical language preferences and updates cached admin form titles. User-entered records, custom copy and draft answers stay as entered. Existing delivered messages are not rewritten.

## Recorded verification

The checked English build passed 303 unique backend cases and 35 DOM integration checks. Three backend passes ran separately. A fresh extraction of the distributable passed all 303 Python cases. Guide anchors, logo presence, Python, shell and JavaScript syntax, English copy and archive checksums were also checked.

The earlier 2.1.0 live Telegram API check confirmed the configured bot identity and English command descriptions. Its 32-second worker smoke test completed with healthy components, zero received updates and zero delivered messages. That historical result does not verify the new guide command on the user's VPS. The updated menus are registered after deploying 2.1.1. These results do not certify human chat or group workflows.

Detailed evidence is in [test results](../reports/test-results.json), [DOM results](../reports/dom-report.json), [live API results](../reports/live-telegram.json), [package results](../reports/package-check.json) and the [standalone test report](../reports/test-report.html).

## Acceptance and operating limits

The build environment did not complete graphical browser rendering, actual mobile layout, official Telegram client flows or production VPS acceptance. The earlier cloud browser blocked local access and Chromium installation failed. Follow the installation guide's acceptance checks before broad use.

This version targets one persistent VPS and a local SQLite database with independent bot and web services. Automatic recovery is bounded. Telegram outages, internet failure, code defects and disk damage can require intervention. Arbitrary data corruption and code rewriting are not automatic features.

## Guide access and dashboard deployment fixes

- Guide is on the Telegram home screen and every native management screen. `/guide` and `/help` work during an unfinished admin form without consuming the current answer or replacing its state.
- Guest, admin and superadmin guide sections follow account permissions. Opening a guide leaves submitted records and active form drafts unchanged.
- Admin home describes admin access rather than guest activation. It puts Open dashboard before Telegram management when HTTPS is configured and explains pending dashboard setup when it is not.
- Web Overview maps four steps: choose a workspace, collect information, review cases and plan the next action. Navigation follows these steps. Every page has How to use, numbered steps, a next action and the matching full-guide link.
- The Ubuntu/Debian HTTPS installer enables the independent web service, obtains a certificate using an IP-based hostname or configured domain, verifies the public live app, preserves private configuration, sets APP_URL and refreshes the menus.
- Installer service commands run in a temporary simulated host during tests. Certificate failure, a conflicting proxy, a wrong public endpoint and failure after origin changes are checked for safe rollback. Public DNS, certificate issuance and actual VPS activation still require running the installer on the target server.

## Repository packaging

The repository adds a requirements file, command help, release notes and navigation to the complete source. No third-party Python runtime packages are required. JavaScript test packages are pinned in `package.json` and `package-lock.json`.

Runtime databases, actual bot credentials, private environment files, installed dependencies and virtual environments are excluded from source and downloadable packages. Source and operations ZIPs keep their `v2` filenames for continuity and contain version 2.1.

Built by Ownership. Support: `@sobix13` / `@SrMessiSOL`.
