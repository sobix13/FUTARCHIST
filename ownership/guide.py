"""Section guidance for Telegram users. This module never changes app data."""
from __future__ import annotations

SECTIONS = {
    'start': ('Getting started', 'guest',
        'FUTARCHIST collects project information and raise details, and helps approved admins manage reviews, teams and programs.\n\n'
        'Project representative: get an access code or intake link from your contact. Open it, agree to the destination workspace, complete the form and review before Submit.\n\n'
        'Admin: open /manage, select a workspace and create an intake link under Access codes. Submitted information appears under Cases in that workspace.\n\n'
        'An intake code lets a person submit information. It does not grant admin access.'),
    'forms': ('Submit and update', 'guest',
        'Open your contact\'s intake link, or send /activate CODE. The code determines the workspace, reviewer and available form.\n\n'
        'General information covers the project, areas, reason for building, product stage, network, product link and team contacts. Raise review adds conditional questions about the raise, platform, amounts, retry plans and MetaDAO. Both combines the two.\n\n'
        'Use the buttons for choices. Skip optional questions. Back changes an earlier answer. Save and leave keeps your draft. /resume continues it. /cancel discards the draft, not submitted records.\n\n'
        'Review your answers before Submit. /projects opens your submissions and available edits. Edits require active access to the same workspace. An inactive or expired code needs a replacement from your contact.'),
    'replies': ('Questions and invitations', 'guest',
        'A reviewer\'s question includes a personal reply link. Open it and send your answer in one message. The answer returns to the same case for authorized reviewers.\n\n'
        'After submission, choose whether to receive DM invitations. /stop disables those invitations. It does not delete your case or prevent replies to reviewer questions.\n\n'
        'Invitation replies are Yes, No or Later. Only your contact\'s authorized group connections or opted-in representatives receive invitations.'),
    'workspaces': ('Workspaces', 'admin',
        'Open /manage. The name at the top is your selected workspace. Switch workspace chooses a personal or shared team space.\n\n'
        'Cases, codes, filters, programs, tasks and invitations belong to the selected workspace. A personal space stays separate from a team space. Use a team-space intake link for shared work.\n\n'
        'A management team contains approved admins. It is different from the project team submitting a form. You see only spaces and data covered by your permissions.'),
    'codes': ('Access codes', 'admin',
        'Open Access codes, then Create code. Set a route name, choose General, Raise or Both and select an initial reviewer. Share its code or private intake link.\n\n'
        'Optional limits control activation count, expiry and a specific Telegram ID. Manage code access revokes or restores one person\'s access. Rotate code replaces the code without deleting cases or source history.\n\n'
        'The code\'s workspace controls where information is stored. The creator remains the source admin even if the reviewer changes.'),
    'cases': ('Cases and reviews', 'admin',
        'Open Cases and choose a project. General and Raise are separate review branches, each with its source admin, current assignee and status. Financial details require Raise read permission.\n\n'
        'Status options are New, Under review, Follow-up, Accepted and Closed. Assignee changes the eligible reviewer without changing the original source.\n\n'
        'Note / question creates an internal note or a question for the representative. Internal notes stay private. History and notes shows earlier work and replies.\n\n'
        'Connect group creates a short-lived binding code. An authorized group admin sends /bind CODE in the group after adding this bot.\n\n'
        'Superadmins archive and restore cases. Permanent deletion is available only for archived cases and requires confirmation.'),
    'filters': ('Filters', 'admin',
        'Open Filters in your selected workspace. Combine areas, product stage, network, branch, review status, source admin, assignee and authorized Raise criteria.\n\n'
        'Selected areas match any chosen area. Different criteria apply together. Money filters require a currency and compare only that currency.\n\n'
        'Save a view to reuse your criteria. Clear filters returns to the full permitted list. Current filters also select invitation recipients and linked case export records.'),
    'programs': ('Programs', 'admin',
        'Open Programs and create a program. Set its title, type, topic, time and timezone. Types include Radio, Roadshow, Podcast, Meeting, Campaign, Raise and Other.\n\n'
        'Link projects from the same workspace. Track Planned, Invited, Confirmed, Attended or Declined participation, and record results afterward.\n\n'
        'Creating a program does not send invitations. Use Invitations for a separate preview and confirmation. Program records keep past activity and upcoming plans.'),
    'tasks': ('Tasks', 'admin',
        'Open Tasks and create a task with a title, branch, assignee and optional due date. Link a project or program from the same workspace if needed.\n\n'
        'Statuses are Open, In progress, Done and Cancelled. Due dates appear in UTC. Stored dates are for tracking. This version does not send automatic deadline reminders.\n\n'
        'Changing the assignee requires assignment permission. Superadmins also archive and restore tasks.'),
    'invitations': ('Invitations and groups', 'admin',
        'First choose your recipient Filters. Open Invitations, then New invitation with current filters. Enter the topic, time and message.\n\n'
        'Templates support {project}, {topic}, {when} and {sector}. Review the personalized messages, destinations and unavailable recipients before confirming. Changed filters need a new preview.\n\n'
        'A DM recipient must have started the bot and opted in. A group must have an active, verified connection from its case. Adding the bot to a group alone does not connect a project.\n\n'
        'Cancel stops remaining queued deliveries. Already delivered messages stay in their chats. Check an Uncertain delivery in its destination before resending.'),
    'exports': ('Excel and CSV', 'admin',
        'Open Export Excel / CSV or send /export. Choose a dataset and format. All permitted datasets includes only information you have permission to read.\n\n'
        'Available datasets include projects, review branches, Raise, notes, programs, tasks, invitations, activity, route metadata and groups. Multiple Excel datasets use separate sheets. Multiple CSV datasets arrive in a ZIP.\n\n'
        'Current filters apply to cases and linked records. Workspace-wide route/group metadata and unlinked programs or tasks keep their workspace scope. Access codes and login credentials are excluded.'),
    'admins': ('Admins and permissions', 'owner',
        'Admins > Add admin requires the person\'s numeric Telegram ID and display name. They obtain their ID with /id. A new admin receives a personal workspace and intake code.\n\n'
        'Create team makes a shared management workspace. Select it, then use Membership and permissions to add existing admins and choose their access.\n\n'
        'Read general, Edit general, Read Raise, Edit Raise, Send, Assign, Export and Routes are separate permissions. Export alone does not grant financial access.\n\n'
        'Manage workspaces renames, disables or reactivates a space. Disabling preserves its data. Both configured superadmins have equal authority based on their numeric IDs.'),
    'texts': ('Bot text', 'owner',
        'Open Bot text to edit the welcome message, command help, invitation template or question wording.\n\n'
        'Question edits preserve field types, required answers and conditional logic. This screen changes wording, not the form schema. Previously delivered messages stay unchanged.\n\n'
        'Invitation templates use only {project}, {topic}, {when} and {sector}. Public name, description and Telegram command menus use the deployment command --configure-bot.'),
    'health': ('Health and recovery', 'owner',
        'Open Health and troubleshooting or send /health. Check database integrity, worker heartbeats, delivery queues, failed updates and incidents.\n\n'
        'Safe recovery or /repair clears expired state and retries eligible temporary failures. It does not rewrite code, repair arbitrary database corruption or resend Uncertain deliveries.\n\n'
        'Review a failed update\'s cause before retrying. Acknowledge an incident after review. This marks the review, not a repair.\n\n'
        'Create verified backup saves a consistent local snapshot on the VPS. Database files are not sent to chat. Restore requires stopped processes and a fresh destination.'),
    'browser': ('Browser dashboard', 'admin',
        'Native management works with /manage and does not need a website.\n\n'
        'Browser access requires a configured HTTPS address and a running web service. Once configured, choose Open dashboard on the home screen. /panel creates a personal one-use browser login link valid for 5 minutes.\n\n'
        'If home shows Dashboard setup, ask a superadmin to finish the web installation. Admin access does not require a guest intake code.\n\n'
        'If no HTTPS address is configured, /panel opens native management. Workspace permissions apply in both interfaces. Typing an ID into a browser does not grant access.'),
    'support': ('Support and privacy', 'guest',
        'Information is stored in the workspace shown before you agree to submit. Authorized reviewers and permitted team members have access. Share only contact information you want them to use.\n\n'
        'Ordinary group conversations are not collected.\n\n'
        'Send /support for @sobix13 and @SrMessiSOL. For an error, include its reference and the action you were taking. Keep private intake and browser login links private.\n\n'
        'Built by Ownership.'),
}


def visible_sections(role):
    allowed = {'guest'}
    if role in ('admin', 'owner'):
        allowed.add('admin')
    if role == 'owner':
        allowed.add('owner')
    return [(key, title, text) for key, (title, access, text) in SECTIONS.items() if access in allowed]
