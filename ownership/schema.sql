PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'guest'
 CHECK(role IN ('owner','admin','guest')), active INTEGER NOT NULL DEFAULT 1,
 started INTEGER NOT NULL DEFAULT 0, invites INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS spaces (
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('personal','team')),
 creator INTEGER NOT NULL REFERENCES users(id), active INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS members (
 space_id INTEGER NOT NULL REFERENCES spaces(id), user_id INTEGER NOT NULL REFERENCES users(id),
 permissions TEXT NOT NULL, PRIMARY KEY(space_id,user_id));
CREATE TABLE IF NOT EXISTS routes (
 id INTEGER PRIMARY KEY, token TEXT NOT NULL UNIQUE, space_id INTEGER NOT NULL REFERENCES spaces(id),
 creator INTEGER NOT NULL REFERENCES users(id), assignee INTEGER NOT NULL REFERENCES users(id),
 name TEXT NOT NULL, purpose TEXT NOT NULL CHECK(purpose IN ('general','raise','both')),
 active INTEGER NOT NULL DEFAULT 1, expires REAL, max_uses INTEGER, uses INTEGER NOT NULL DEFAULT 0,
 bound_user INTEGER);
CREATE TABLE IF NOT EXISTS projects (
 id INTEGER PRIMARY KEY, space_id INTEGER NOT NULL REFERENCES spaces(id),
 submitter INTEGER NOT NULL REFERENCES users(id), project_key TEXT NOT NULL,
 general TEXT NOT NULL, fundraising TEXT NOT NULL DEFAULT '{}', version INTEGER NOT NULL DEFAULT 1,
 created_at REAL NOT NULL, updated_at REAL NOT NULL, archived_at REAL,
 UNIQUE(space_id,submitter,project_key));
CREATE TABLE IF NOT EXISTS cases (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 purpose TEXT NOT NULL CHECK(purpose IN ('general','raise')),
 source_admin INTEGER NOT NULL REFERENCES users(id), route_id INTEGER NOT NULL REFERENCES routes(id),
 assignee INTEGER NOT NULL REFERENCES users(id), status TEXT NOT NULL DEFAULT 'new'
 CHECK(status IN ('new','reviewing','followup','accepted','closed')), version INTEGER NOT NULL DEFAULT 1,
 UNIQUE(project_id,purpose));
CREATE TABLE IF NOT EXISTS activity (
 id INTEGER PRIMARY KEY, space_id INTEGER REFERENCES spaces(id), project_id INTEGER REFERENCES projects(id),
 purpose TEXT NOT NULL DEFAULT 'general', actor INTEGER NOT NULL REFERENCES users(id),
 action TEXT NOT NULL, details TEXT NOT NULL DEFAULT '{}', created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS threads (
 id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 purpose TEXT NOT NULL, actor INTEGER NOT NULL REFERENCES users(id), text TEXT NOT NULL,
 visibility TEXT NOT NULL CHECK(visibility IN ('internal','guest')), created_at REAL NOT NULL,
 version INTEGER NOT NULL DEFAULT 1, deleted_at REAL);
CREATE TABLE IF NOT EXISTS reply_tokens (
 token TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id), purpose TEXT NOT NULL,
 guest_id INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), csrf TEXT NOT NULL, expires REAL NOT NULL);
CREATE TABLE IF NOT EXISTS login_links (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL,
 used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS flows (
 user_id INTEGER PRIMARY KEY REFERENCES users(id), data TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS inbox (
 update_id INTEGER PRIMARY KEY, payload TEXT NOT NULL, done INTEGER NOT NULL DEFAULT 0,
 attempts INTEGER NOT NULL DEFAULT 0, error TEXT, received_at REAL NOT NULL, next_at REAL NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS outbox (
 id INTEGER PRIMARY KEY, method TEXT NOT NULL, payload TEXT NOT NULL, dedupe TEXT UNIQUE,
 state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
 next_at REAL NOT NULL DEFAULT 0, error TEXT, telegram_message_id INTEGER,
 space_id INTEGER, actor INTEGER, permission TEXT, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS groups (
 chat_id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL UNIQUE REFERENCES projects(id),
 name TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, consent_actor INTEGER NOT NULL REFERENCES users(id));
CREATE TABLE IF NOT EXISTS bindings (
 token TEXT PRIMARY KEY, project_id INTEGER NOT NULL REFERENCES projects(id),
 actor INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS campaigns (
 id INTEGER PRIMARY KEY, space_id INTEGER NOT NULL REFERENCES spaces(id), creator INTEGER NOT NULL REFERENCES users(id),
 topic TEXT NOT NULL, when_text TEXT NOT NULL, template TEXT NOT NULL, filters TEXT NOT NULL,
 state TEXT NOT NULL DEFAULT 'draft' CHECK(state IN ('draft','queued','cancelled')),
 created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS recipients (
 id INTEGER PRIMARY KEY, campaign_id INTEGER NOT NULL REFERENCES campaigns(id),
 project_id INTEGER NOT NULL REFERENCES projects(id), chat_id INTEGER NOT NULL,
 kind TEXT NOT NULL CHECK(kind IN ('group','dm')), text TEXT NOT NULL, token TEXT NOT NULL UNIQUE,
 response TEXT CHECK(response IN ('yes','no','later')), responder INTEGER, responded_at REAL,
 outbox_id INTEGER REFERENCES outbox(id), UNIQUE(campaign_id,chat_id));
CREATE TABLE IF NOT EXISTS views (
 id INTEGER PRIMARY KEY, space_id INTEGER NOT NULL REFERENCES spaces(id), user_id INTEGER NOT NULL REFERENCES users(id),
 name TEXT NOT NULL, filters TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS access_grants (
 user_id INTEGER NOT NULL REFERENCES users(id), route_id INTEGER NOT NULL REFERENCES routes(id),
 created_at REAL NOT NULL, active INTEGER NOT NULL DEFAULT 1, PRIMARY KEY(user_id,route_id));
CREATE TABLE IF NOT EXISTS native_flows (
 user_id INTEGER PRIMARY KEY REFERENCES users(id), data TEXT NOT NULL, updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS events (
 id INTEGER PRIMARY KEY, space_id INTEGER NOT NULL REFERENCES spaces(id), creator INTEGER NOT NULL REFERENCES users(id),
 title TEXT NOT NULL, kind TEXT NOT NULL, topic TEXT NOT NULL DEFAULT '', starts_at REAL NOT NULL,
 timezone TEXT NOT NULL DEFAULT 'UTC', status TEXT NOT NULL DEFAULT 'planned'
 CHECK(status IN ('planned','confirmed','completed','cancelled')), description TEXT NOT NULL DEFAULT '',
 outcome TEXT NOT NULL DEFAULT '', version INTEGER NOT NULL DEFAULT 1, archived_at REAL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS event_projects (
 event_id INTEGER NOT NULL REFERENCES events(id), project_id INTEGER NOT NULL REFERENCES projects(id),
 participation TEXT NOT NULL DEFAULT 'planned' CHECK(participation IN ('planned','invited','confirmed','attended','declined')),
 PRIMARY KEY(event_id,project_id));
CREATE TABLE IF NOT EXISTS tasks (
 id INTEGER PRIMARY KEY, space_id INTEGER NOT NULL REFERENCES spaces(id), creator INTEGER NOT NULL REFERENCES users(id),
 assignee INTEGER NOT NULL REFERENCES users(id), project_id INTEGER REFERENCES projects(id), event_id INTEGER REFERENCES events(id),
 purpose TEXT NOT NULL DEFAULT 'general', title TEXT NOT NULL, due_at REAL,
 status TEXT NOT NULL DEFAULT 'open' CHECK(status IN ('open','doing','done','cancelled')),
 version INTEGER NOT NULL DEFAULT 1, archived_at REAL, created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS incidents (
 id INTEGER PRIMARY KEY, component TEXT NOT NULL, code TEXT NOT NULL, severity TEXT NOT NULL,
 summary TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'open', count INTEGER NOT NULL DEFAULT 1,
 created_at REAL NOT NULL, updated_at REAL NOT NULL, resolved_at REAL);
CREATE TABLE IF NOT EXISTS heartbeats (
 component TEXT PRIMARY KEY, state TEXT NOT NULL, last_at REAL NOT NULL, detail TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS operation_tokens (
 token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), action TEXT NOT NULL,
 data TEXT NOT NULL, expires REAL NOT NULL, used INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS text_settings (
 key TEXT PRIMARY KEY, value TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 1,
 editor INTEGER REFERENCES users(id), updated_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS events_space ON events(space_id,starts_at);
CREATE INDEX IF NOT EXISTS tasks_space ON tasks(space_id,status,due_at);
CREATE INDEX IF NOT EXISTS incidents_active ON incidents(state,component);
CREATE INDEX IF NOT EXISTS projects_space ON projects(space_id);
CREATE INDEX IF NOT EXISTS activity_space ON activity(space_id,id);
CREATE INDEX IF NOT EXISTS outbox_ready ON outbox(state,next_at);
PRAGMA user_version=2;
