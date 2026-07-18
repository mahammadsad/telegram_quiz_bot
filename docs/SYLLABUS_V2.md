# Syllabus v2 catalogue

The application keeps the existing 13 Telegram quiz subjects and historical
`YYYYMMDD-subject-key` quiz IDs. It no longer treats seven chapters per subject
as the complete competitive-exam syllabus.

## Coverage

- 13 canonical subjects
- 162 subject-specific chapters
- 648 curated v2 micro-topics
- 11 exam mappings: WBCS, WBPSC Clerkship, WBPSC Miscellaneous, WBP
  Constable, WBP SI, Kolkata Police, Primary TET, Upper Primary TET, SSC,
  Railway, and Banking
- Per-micro-topic priority, ten-question difficulty mix, target coverage, and
  mastery relevance

The first catalogue pass was checked against representative official exam
syllabi, including [SSC CGL](https://ssc.gov.in/api/attachment/uploads/masterData/NoticeBoards/Notice_of_adv_cgl_2025.pdf),
[SSC CHSL](https://ssc.gov.in/api/attachment/uploads/masterData/NoticeBoards/Notice_of_adv_chsl_2025.pdf),
[RRB JE](https://www.rrbcdg.gov.in/uploads/2024/03-JE/CEN%2003%202024_JE.pdf),
the [West Bengal Primary TET](https://www.wbbpeonline.com/ImageHandler.ashx?FileExt=.pdf&ID=24&Type=NoticeDoc),
and the [WBPSC syllabus catalogue](https://psc.wb.gov.in/syllabus.jsp). Exam
notifications remain authoritative; the catalogue should receive a versioned
update when an official syllabus changes.

The migration also retains the 91 existing hashed `:core` micro-topics. Those
rows remain valid because historical questions and the approved Computer
Education source pilot already refer to them.

## Rotation and source gate

`ALL_CHAPTERS` exposes the complete curriculum. `CHAPTERS` contains only the
currently generation-enabled rotation chapters. The original seven chapters
per subject remain in that generation view for backward compatibility; newly
catalogued chapters start with `rotation_enabled = false`.

This is deliberate. A new chapter must not enter daily generation merely
because its title exists. It becomes eligible only after:

1. its official or primary source bundle has been reviewed and imported;
2. every intended micro-topic has reusable verified facts;
3. its configuration and database `rotation_enabled` flag are enabled in an
   idempotent migration;
4. a staging quiz passes generation, independent verification, delivery, and
   answer-review checks.

The existing `get_grounding_bundle` function continues to ignore micro-topics
without verified source documents, so the 648 new rows cannot weaken the
fail-closed integrity policy.

## Computer Education expansion bundle

`sources/computer_education_expansion_v2.json` is the first gated expansion
bundle. Its 26 reviewed records cover all 20 micro-topics in the five inactive
Computer Education chapters: number systems, architecture and memory,
programming and algorithms, cloud and emerging technology, and digital
services and e-governance. Composite topics use separate facts for their
distinct concepts, including bit/character encoding, control structures,
blockchain/big data/robotics, and digital identity/citizen safety.

The bundle uses official or primary material from NIOS, CBSE, NIST, MeitY,
CCA, NPCI, UIDAI, and the National Cyber Crime Reporting Portal. Validate it
without credentials before any environment import:

```bash
python scripts/import_source_documents.py \
  sources/computer_education_expansion_v2.json --validate-only
```

Importing the bundle does not enable the chapters. Rotation remains off until
the staging generation, independent verification, delivery, and answer-review
gate has passed and a later idempotent activation migration is applied.

## Indian Polity expansion bundle

`sources/polity_expansion_v2.json` contains 30 reviewed official-source
records covering all 24 micro-topics in the six inactive Indian Polity
chapters: constitution-making and citizenship, Prime Minister and Council of
Ministers, State government, Union-State relations and emergencies, local
government, and amendments, Schedules, and elections.

The bundle grounds constitutional propositions in the Legislative
Department's Constitution current to 1 May 2026 and supplements composite
topics with Parliament, Ministry of Home Affairs, Cabinet Secretariat,
Ministry of Panchayati Raj, Ministry of Housing and Urban Affairs, Ministry of
Jal Shakti, Election Commission of India, and West Bengal government sources.
Citizenship amendments and OCI, Cabinet committees and the Attorney-General,
inter-State disputes, West Bengal local administration, and election statutes
therefore retain independent source records.

Validate it without credentials before importing it into an environment:

```bash
python scripts/import_source_documents.py \
  sources/polity_expansion_v2.json --validate-only
```

As with the Computer Education bundle, import and cache readiness do not
activate the chapters. All six Polity chapters remain fail-closed until the
separate staging quiz and answer-review gate succeeds.

## English expansion bundle

`sources/english_expansion_v2.json` contains 31 reviewed official or primary
records covering all 20 micro-topics in the five inactive English chapters:
parts of speech and tense, error detection and sentence improvement, spelling
and one-word substitution, cloze and reading comprehension, and sentence
rearrangement and para-jumbles.

The bundle uses the current CBSE 2026-27 English curricula to preserve exam
scope, NIOS lessons for grammar and sequencing rules, Cambridge University
Press dictionary and grammar entries for spelling and vocabulary, and
institutional writing guidance for parallelism, modifiers, usage, and
concision. Composite topics retain separate records so a vocabulary definition
or sentence rule is never inferred from an unrelated source.

Validate it without credentials before importing it into an environment:

```bash
python scripts/import_source_documents.py \
  sources/english_expansion_v2.json --validate-only
```

Importing and caching the records does not enable the five chapters. English
rotation remains fail-closed until a separate staging quiz passes generation,
independent verification, Telegram delivery, and answer review.

## Data model

`quiz_chapters` gains stable keys, exam relevance, priority, rotation state,
and syllabus version. `quiz_micro_topics` gains priority and syllabus version;
its existing exam relevance, difficulty targets, target coverage, last-used
date, mastery relevance, and source relationships remain authoritative.

The migration is generated deterministically from
`config/syllabus_catalog.py` by `scripts/render_syllabus_v2_migration.py`.
Future catalogue changes require a new migration rather than editing an
already-applied migration.

## Rollout order

After this foundation is deployed, source coverage should be expanded one
subject bundle at a time. The cached learning-resource foundation and Bengali
`📚 আগে প্রস্তুতি নিন` entry point are tied to these micro-topic keys. Only
active, operator-verified metadata is served; discovery remains a separate
review queue and never runs on a learner click.
