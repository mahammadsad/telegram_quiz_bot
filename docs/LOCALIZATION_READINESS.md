# Localization readiness

The production learner interface is Bengali (`bn`) only. English question
content, bilingual English-subject material, and previous-year language filters
are content metadata; they do not mean the application interface is translated.

The authenticated preferences API accepts only `bn`, matching the only option
shown in Settings. This prevents a crafted client from saving `hi` or `en` and
creating a false expectation while navigation, validation, error, offline,
legal, accessibility, search-normalization, and Telegram states remain Bengali.

Hindi or English UI support can be enabled only after all of the following are
complete for that locale:

- every learner-facing HTML and JavaScript string is in a reviewed catalogue;
- dynamic API errors and accessibility names use the selected locale;
- dates, numbers, search normalization, wrapping, and fonts pass mobile QA;
- offline/PWA and Telegram launch/error states are translated;
- privacy and terms text has qualified review;
- the complete browser and manual assistive-technology matrix passes.

Until then, no language switcher or unsupported saved preference should be
advertised. Assessment content languages continue to use their separate,
existing validation rules.
