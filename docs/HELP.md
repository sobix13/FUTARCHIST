# FUTARCHIST command help

FUTARCHIST uses English throughout the Telegram bot, admin screens, browser dashboard, forms and documentation. No AI services are used. All authority comes from numeric Telegram IDs and workspace permissions.

## Project representatives

| Command | Purpose |
| --- | --- |
| `/start` | Open the home screen |
| `/activate CODE` | Activate the private intake code supplied by your contact |
| `/resume` | Resume a saved form |
| `/projects` | View your submitted projects and open an available edit flow |
| `/back` | Return to the previous step in an active form |
| `/cancel` | Discard the active draft; existing submissions remain |
| `/stop` | Stop optional DM invitations; case replies remain available |
| `/help` | Open command help |
| `/guide` | Open the English section guide inside Telegram |
| `/support` | Show the configured support contacts |
| `/id` | Show your numeric Telegram ID |

Your contact can also share an intake link. The code or link activates its assigned route. A guest code never makes someone an admin. Continue through the consent screen, choose general information, raise review or both when offered, complete the short conditional form and review before submitting. Use Save and leave to keep a draft. Optional questions can be skipped.

Guide is visible on the guest home screen and every native management screen, including active forms. `/guide` opens sections for your role without changing drafts or the current admin step. Resume form or Resume admin step returns to that work. `/help` also opens the guide alongside the editable command-help text. No web service or HTTPS address is required for the Telegram guide.

If your code is inactive, expired or at capacity, ask the person who supplied it for a replacement. Keep using the newest message's buttons. Follow-up questions and invitation responses use links tied to the appropriate representative or project.

## Admins

| Command | Purpose |
| --- | --- |
| `/manage` | Open native Telegram management |
| `/admin` | Alias for native management |
| `/panel` | Open browser access when configured; otherwise open native management |
| `/code` | Manage intake codes in your selected workspace |
| `/export` | Choose a permitted dataset and Excel or CSV output |

Open `/manage`, choose your personal or team workspace, then use the inline controls. Cases, general and raise branches, assignments, filters, notes, guest questions, programs, tasks, invitations and exports follow the same permissions in Telegram and the browser.

A personal workspace remains separate from shared team workspaces. Every case branch keeps its source admin and current assignee. Reassignment changes the assignee while preserving the source. General-only access does not reveal financial fields, filters, notes or exports.

To invite teams, set the topic and timing, apply filters and create a preview. Review the actual recipients and personalized text before confirming. A group must first be connected through its binding flow by a verified group admin with application access. A DM destination must have started the bot and opted into invitations. A supplied numeric ID by itself does not authorize a DM.

## Superadmins

The configured superadmins are `@sobix13` (`313342234`) and `@SrMessiSOL` (`5691137098`). Both have equal authority. Usernames are display information, not an authentication method.

Superadmin controls in `/manage` include:

- Add or suspend admins and manage personal or shared team workspaces.
- Assign workspace permissions and manage code limits, expiry, rotation and individual access.
- Edit welcome, help, invitation template and question text while preserving field validation.
- Archive or restore records and confirm permitted permanent deletion.
- Review health, incidents, delivery queues and backup operations.

| Command | Purpose |
| --- | --- |
| `/health` | Open system health and troubleshooting |
| `/repair` | Run bounded safe recovery |

Safe recovery handles expired state and supported temporary failures. It does not rewrite code or repair arbitrary data corruption. An uncertain delivery is not retried automatically because it might already have arrived. Inspect its Telegram destination before deciding on another send.

## Browser and local simulator

The browser dashboard requires a configured HTTPS `APP_URL`. Open it through the bot's panel flow or a one-use login link. Native management remains available if the browser service is unavailable, provided the bot and its Telegram connection are functioning.

For a local demo, run `python -m futarchist --demo`. Open `/` for the dashboard, `/emulator` for the Telegram-shaped simulator and `/guide` for the full guide at `http://127.0.0.1:8765`. Demo data is synthetic. It never connects to Telegram. The simulator is disabled in live mode.

See [VPS installation](../extensions/DEPLOY.md), [architecture](ARCHITECTURE.md) and the [standalone guide](USER_GUIDE.html) for complete instructions. Download the HTML guide and open it in a browser to read the formatted version offline.
