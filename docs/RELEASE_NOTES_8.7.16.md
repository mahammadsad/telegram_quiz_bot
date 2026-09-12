# 8.7.16 — candidate, not deployed

Settings UX follow-up to the original Mini App audit: preserve changes made
during a pending save and prevent overlapping preference writes.

- The page now marks only the snapshot actually sent as saved, rather than
  whatever happens to be in the form when a delayed response returns.
- Further edits stay visible and dirty. Bengali feedback distinguishes the
  confirmed older save from newer unsaved changes.
- A pending save cannot be restarted by another input, Enter or a duplicate
  submit event. Browser/Telegram closing protection remains active while saving.
- Failures leave the current draft retryable, including changes back to the
  originally loaded value. Local sound/vibration preferences are updated only
  from the successful submitted values.
- Shell cache and worker registration advance to 8.7.16-ui1 so installed Mini
  Apps can receive the corrected settings code.

The two original race scenarios failed before the fix. The new browser checks
hold the PUT response while editing, explicitly trigger a duplicate submit,
and exercise a failed save followed by an explicit retry. Existing privacy,
selector, branding, mobile and service-worker checks remain release gates.

No new database migration, production write or reminder activation is part of
this follow-up. It is stacked on PR #112 / 8.7.15, whose production migration
remains blocked until a recent backup is verified. Do not bypass that gate or
merge this dependent branch directly into main. After its prerequisite release,
repeat full CI, authenticated staging and rollback/restore, then exact-SHA
production smoke. Pin the actual prerequisite production merge as the rollback
target before promotion; no new rollback SHA is assumed here.

This serializes saves within one page. It does not claim optimistic concurrency
across devices or browser tabs, or that native Telegram/Bengali screen-reader
acceptance is complete.
