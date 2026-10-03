# FUTARCHIST 2.1 release

Version: `2.1.0`. Database schema: `2`. Interface language: English only.

## Included application

- Native Telegram management and an optional browser dashboard using shared operations.
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

The checked English build passed 268 unique backend cases and 32 DOM integration checks. Three backend passes ran separately. A fresh extraction of the distributable passed all 268 Python cases. Guide anchors, logo presence, Python and JavaScript syntax, English copy and archive checksums were also checked.

A real Telegram API check confirmed the configured bot identity and English command descriptions. A 32-second worker smoke test completed with healthy components, zero received updates and zero delivered messages. These results do not certify human chat or group workflows.

Detailed evidence is in [test results](../reports/test-results.json), [DOM results](../reports/dom-report.json), [live API results](../reports/live-telegram.json), [package results](../reports/package-check.json) and the [standalone test report](../reports/test-report.html).

## Acceptance and operating limits

The build environment did not complete graphical browser rendering, actual mobile layout, official Telegram client flows or production VPS acceptance. The earlier cloud browser blocked local access and Chromium installation failed. Follow the installation guide's acceptance checks before broad use.

This version targets one persistent VPS and a local SQLite database with independent bot and web services. Automatic recovery is bounded. Telegram outages, internet failure, code defects and disk damage can require intervention. Arbitrary data corruption and code rewriting are not automatic features.

## Repository packaging

The repository adds a requirements file, command help, release notes and navigation to the complete source. No third-party Python runtime packages are required. JavaScript test packages are pinned in `package.json` and `package-lock.json`.

Runtime databases, actual bot credentials, private environment files, installed dependencies and virtual environments are excluded from source and downloadable packages. Source and operations ZIPs keep their `v2` filenames for continuity and contain version 2.1.

Built by Ownership. Support: `@sobix13` / `@SrMessiSOL`.
