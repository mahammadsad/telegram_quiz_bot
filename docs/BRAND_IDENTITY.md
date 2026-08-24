# Citizen Affairs visual identity

The Mini App uses the public Citizen Affairs Bengali site as its parent brand.
The reviewed browser fallbacks match the live site assets checked on 24 August
2026:

- editorial primary: `#b42318`;
- editorial primary hover: `#8f1c13`;
- editorial link blue: `#0a5aa6`;
- canvas: `#ffffff` / `#f7f7f6`;
- text: `#222222` with muted `#666666`.

Telegram-supplied theme variables still take precedence inside the Mini App so
controls remain native and accessible in user-selected Telegram themes. The
Citizen Affairs palette is the deterministic browser/PWA fallback, theme color,
admin-console identity and external-link color. The focus ring remains amber so
keyboard focus is not conveyed by brand color alone.

The parent-site link must remain visible on the daily quiz introduction before a
learner starts. It uses campaign-tagged HTTPS navigation and is not loaded as a
third-party script inside authenticated or timed assessment pages.
