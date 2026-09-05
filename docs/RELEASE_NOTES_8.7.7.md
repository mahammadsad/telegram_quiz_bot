# 8.7.7

- Pressing Enter on a practice answer selects that answer through the native
  button action. It no longer submits a previously selected answer.
- Practice number shortcuts run only on a loaded, editable question. Loading,
  errors, form fields, browser shortcuts and repeated/composition events cannot
  change an answer or trigger an undefined-question error.
- Quiz and practice selection uses a double border; practice review uses
  distinct correct/incorrect border shapes that survive forced-colors mode.
- Telegram Back closes a settings subject/exam selector, discards its temporary
  draft and returns focus to the opening control.
- Quiz and mock submission confirmations use modal dialogs with bounded
  keyboard focus and Escape dismissal. Mock shortcuts cannot edit answers or
  move questions behind the dialog. Quiz question headings can receive focus
  after navigation or cancellation, including with Telegram native controls.
- The service-worker shell version advances so returning clients receive the
  updated interaction code through the existing tested upgrade path.

No database migration is required. Application rollback targets production
release `68c37776edad3112a302b4c465a259bafc5b5176` (8.7.6), which supports the
current platform 1.5.0 contract. Leave all database migrations in place.
