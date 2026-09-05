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
and 72 unused indexes. Render deployment `dep-dadr0m95efls739dbeig` serves
`68c37776edad3112a302b4c465a259bafc5b5176`, with live/ready probes and canonical
smoke `33948826481` passing. Production source refresh `33948770167` passed
the strict readback of 32 chapters and 134 documents despite PIB/RBI being
unavailable from that runner. Wider category coverage remains open.

The staging National gap was subsequently repaired by importing four existing
verified public sources and their 15 exact-span claims across four National
micro-topics. The standard source-bundle validator accepted the inputs; staging
now reports schema, source coverage and platform readiness and returns eight
National grounding rows. No learner data was copied.
