# Web Fintech Interface and Ask Assistant

## Design goals

The Web UI uses one fintech presentation layer across light and dark themes: semantic colors, fine panel borders, ambient light, a subtle grid, and restrained motion. The shell can use up to 1920px on wide displays, while business pages can use up to 1600px, reducing dead space without changing responsive behavior.

Motion communicates hierarchy and state only: page entry, active navigation, button feedback, ambient lighting, and assistant transitions. Non-essential animations are disabled automatically when the operating system requests reduced motion.

## Global Ask assistant

- Ask no longer occupies a primary navigation slot. A bottom-right launcher opens it on desktop and mobile.
- The assistant reuses the existing `ChatPage`, Zustand conversation state, API requests, strategy picker, session history, and notification behavior. There is no parallel chat implementation.
- The `/chat` route remains available for deep links and the full-page workspace. The panel header links to that full view.
- `Ctrl + Shift + A` (`Command + Shift + A` on macOS) toggles the assistant, and `Escape` closes it.
- When an analysis finishes after the user leaves Ask, its unread state moves to the floating launcher and is cleared when the assistant opens.

## Stability boundary

This presentation-layer update does not change the Agent API, analysis pipeline, data schemas, model configuration, or report generation. Embedded assistant mode does not consume query parameters owned by the current business page; only the full `/chat` route processes the `stock`, `name`, and `recordId` follow-up parameters.

Primary implementation points:

- `apps/dsa-web/src/components/assistant/FloatingStockAssistant.tsx`
- `apps/dsa-web/src/components/layout/Shell.tsx`
- `apps/dsa-web/src/pages/ChatPage.tsx`
- `apps/dsa-web/src/index.css`

