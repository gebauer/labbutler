---
name: verify
description: Drive LabButler end-to-end over HTTP to verify a change at its real surface (login, CSRF, form posts, uploads, emails). Use after code changes to observe runtime behaviour, not to rerun tests.
---

# Verify a LabButler change end-to-end

Launch via the `dev-server` skill (project Postgres on 55432, `runserver` on 8000).
With `.env` containing `CELERY_TASK_ALWAYS_EAGER=true` and the console email backend,
notification emails execute inline and print into the runserver log — grep the log to
assert on recipients, subjects, bodies, and attachments.

## Seed users/data

Use `uv run python manage.py shell -c "..."` with `apps.tenancy.services.create_lab` /
`add_member` (template role names: "Lab manager", "Member", "Purchase coordinator",
"Viewer"). Set passwords explicitly; `get_current_lab` falls back to the user's first
lab, so no session fiddling is needed.

## Drive authenticated flows with curl

```bash
csrf() { curl -s -c "$JAR" -b "$JAR" "$BASE$1" \
  | grep -o 'name="csrfmiddlewaretoken" value="[^"]*"' | head -1 | sed 's/.*value="//;s/"//'; }
T=$(csrf /accounts/login/)
curl -s -c "$JAR" -b "$JAR" -X POST "$BASE/accounts/login/" \
  -d "csrfmiddlewaretoken=$T" -d "username=$EMAIL" -d "password=$PW"   # 302 = success
```

- Fetch a fresh CSRF token from the page that hosts the form before each POST.
- File uploads: `-F "po_pdf=@file.pdf;type=application/pdf"` alongside
  `-F "csrfmiddlewaretoken=$T"`.
- **Do not use `-L` on POSTs** — curl re-POSTs the 302 target without the form body and
  the CSRF middleware 403s, which looks like a failure that isn't. POST, then GET the
  redirect target separately (messages render there).
- 403 diagnosis: the runserver log distinguishes `Forbidden (CSRF token missing.)`
  from `Forbidden (Permission denied)`.
