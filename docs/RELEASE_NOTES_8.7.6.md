# 8.7.6

- Expands the reviewed current-affairs rotation from National and Science &
  Technology to include Economy, Reports and Indices.
- Classifies first-party RBI releases into monetary/economic policy, banking and
  markets, reports, or surveys and indices while retaining exact-source,
  freshness, provenance, and topic-diversity gates.
- Reports PIB endpoint health independently from RBI and ISRO, so loss of the
  primary government release feed can no longer be hidden by healthy
  supplementary sources.
- Lets the protected refresh worker pass the exact schema and rotation gate
  while coverage is being replenished, then retains the strict all-chapter
  database readback as the final deployment gate.
- Builds current-affairs grounding inside the requested chapter before applying
  a limit, preventing a high-volume category from starving National, Science,
  or Economy despite valid evidence being present.

Production migrations passed protected run `33948369731`. The application
schema and platform `1.5.0` contracts are ready, with eight usable grounding
rows returned for each of the three current-affairs rotation chapters and all
32 reviewed rotation chapters enabled. Post-migration advisors reported only
informational findings: 75 service-owned tables with RLS and no client policies,
and 72 unused indexes. Application deployment verification is still pending.
