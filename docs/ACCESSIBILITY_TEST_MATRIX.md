# Accessibility test matrix

Target: WCAG 2.2 AA for learner-facing flows. Execute this matrix on root quiz, practice, mock catalog/test, syllabus map, dashboard, settings, privacy and terms pages at each production release candidate.

| Area | Procedure | Pass condition | Evidence owner |
|---|---|---|---|
| Keyboard | Use only Tab, Shift+Tab, Enter, Space, arrows and Escape through navigation, quiz answers, reports, catalog/syllabus filters, chapter disclosures and dialogs. | Logical order, visible focus, no trap, all actions operable; focus returns after a dialog. | QA |
| Screen reader | Test Bengali labels/live updates with current NVDA + Firefox or VoiceOver + Safari. | Page purpose, headings, controls, answer state, timer, errors and results are announced meaningfully. | QA + Bengali reviewer |
| 200% zoom | Zoom a 1280 CSS-pixel viewport to 200%. | No two-dimensional scrolling for ordinary content; controls and text remain usable. | QA |
| Reflow/mobile | Test at 320 CSS pixels and with large text. | Bengali text wraps without clipping/overlap; sticky UI does not hide focused controls. | QA |
| Contrast | Check text, icons, focus, selected/correct/incorrect and disabled states. | AA contrast; meaning never depends on color alone. | Design/QA |
| Reduced motion | Enable `prefers-reduced-motion`. | Nonessential motion is disabled and no information depends on animation. | QA |
| High contrast | Test Windows forced-colors/high-contrast mode. | Controls, focus and answer states remain perceivable. | QA |
| Timing | Pause/reconnect where supported and verify server-authoritative behavior. | Timer information is announced; client clock changes cannot alter official rank. | QA/Security |
| Error recovery | Trigger validation, offline, auth-expired and retry states. | Focus and live messages identify the error and recovery without exposing private data. | QA |
| Automated gate | Run the pinned Playwright plus axe suite on representative states at all four supported Android widths; any WCAG 2.2 A/AA violation fails CI. | Zero automated WCAG 2.2 A/AA violations. | Engineering |

The automated gate is installed in `tests/browser/accessibility.spec.js` and also checks interactive quiz, practice and mock-result states in their focused browser suites. It covers the preparation hub, quiz start, dashboard, settings, syllabus map and revision practice at 320×568, 360×800, 390×844 and 412×915. Automation does not replace the keyboard, Bengali screen-reader, zoom, forced-colors or real Telegram checks above; those remain required release evidence.
