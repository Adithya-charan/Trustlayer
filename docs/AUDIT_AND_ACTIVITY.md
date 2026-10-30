# Audit, "why", activity history and the assistant

Everything on this page is read from the audit trail (`audit_events`). The trail holds names, kinds, strategies, policies and decisions, never data values (`audit.logger.scrub` is applied to the reason and to every string in `detail`).

## What is recorded

| Event (`operation`) | When | Decision | Structured `detail` |
|---|---|---|---|
| `b1_query` | every query | ALLOW / MASK / DENY (refused filter) | per field: kind, strategy, result word, policy path, policy source, reason |
| `b1_access_denied` | a query asked for a column the policy withholds | DENY | the withheld fields with the same explanation; links to the query event |
| `b1_policy_change` | an Admin changes or resets a user/role policy | ALLOW | old -> new, subject, kind, the Admin's optional reason. Re-saving the same strategy is **not** recorded |
| `b1_review` | classification review / clear | ALLOW / DENY | (reason text) |
| `b1_scan` | discovery scan | ALLOW | (reason text) |
| `auth_login` | sign-in, or a wrong password for a **known** username | ALLOW / DENY | none. Unknown usernames are not recorded |

`audit_events.detail` is a nullable JSON column (migration `e1a0c0de0004`). Older events have no `detail`; they are explained from their stored fields and reason text.

## The "why" chain

`app/b1/activity.py::why_field` produces, for each field of a result: `policy_path` (e.g. `Analyst -> AADHAAR -> DENY`), the decision word (ALLOWED, MASKED, HASHED, REDACTED, WITHHELD), where the policy came from (built-in role policy, role policy edited by an Admin, personal policy) and a sentence saying why. The same text is returned with every query (`columns[].why`, `withheld[].why`), stored in the audit event, and shown by the "Why this result?" card in the UI.

## Endpoints

- `GET /api/b1/activity` (Admin): recent activity, filters `user`, `decision`, `operation`, `field`, `hours`.
- `GET /api/b1/activity/users/{username}` (Admin): one user's history, including policy changes made to them.
- `GET /api/b1/me/activity` (any B1 role): the caller's **own** actions. The identity comes from the token; there is no user parameter.
- `GET /api/b1/policy/history` (Admin): latest policy changes with old -> new, who, and the reason.
- `GET /api/b1/overview` now includes `audit.today` (24 h): access events, masked requests, blocked attempts, policy changes, sign-ins. Each is a COUNT over the trail.
- `PUT /api/b1/policy/overrides` accepts an optional `note`; the response says `changed: false` when nothing changed.

## Assistant

Three read-only tools over the same functions: `recent_policy_changes`, `access_history` (user, decision, operation, field, hours, `after_change_of`), `followup_on_last_answer`. The model only chooses a tool and arguments; the reply text and the items come from the trail. The last answer is remembered per signed-in user on the server (1 h), so "who made the first one?" resolves against what that user was shown. Policy-change tools are Admin-only; other roles can only ask about their own activity, and the router refuses a tool the role may not use even if the model asks for it.

## Not done / limits

- The assistant needs `GROQ_API_KEY`. Groq rate limits (429) are retried by the SDK; a persistent provider error is reported as "AI service unavailable".
- Opening a page (for example the Data Explorer) is not recorded; the queries it runs are.
- No browser walkthrough of the new screens was performed in this round (sign-in needs the demo password).
