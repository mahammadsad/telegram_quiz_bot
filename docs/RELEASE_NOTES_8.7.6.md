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
