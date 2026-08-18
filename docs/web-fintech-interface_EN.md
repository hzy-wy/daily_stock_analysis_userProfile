# Web Fintech Interface and Ask Assistant

## Design goals

The Web UI uses one fintech presentation layer across light and dark themes: semantic colors, fine panel borders, ambient light, a subtle grid, and restrained motion. The shell can use up to 1920px on wide displays, while business pages can use up to 1760px, reducing dead space without changing responsive behavior.

Motion communicates hierarchy and state only: page entry, active navigation, button feedback, ambient lighting, and assistant transitions. Non-essential animations are disabled automatically when the operating system requests reduced motion.

## Global navigation and responsive layout

- Desktop no longer uses a fixed left sidebar. A floating top command bar keeps Home, Screening, Portfolio, AI signals, and Backtest as primary destinations; Alerts, Usage, Settings, and logout live in the compact More menu.
- Screening remains conditional on the real AlphaSift enabled state and still refreshes after system configuration events. The redesign does not alter feature-flag semantics.
- Theme and interface language are compact top-right utilities rather than business navigation items. The theme menu still supports light, dark, and system modes.
- Viewports below 1280px use a floating bottom dock for frequent destinations and a top-right menu for the complete route set. The dock reserves safe spacing for the Ask launcher.
- The command bar, dock, menus, and expanded canvas all reuse the original routes, so changing layout does not reset business-page state or introduce parallel implementations.

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
- `apps/dsa-web/src/components/layout/CommandNavigation.tsx`
- `apps/dsa-web/src/components/layout/Shell.tsx`
- `apps/dsa-web/src/pages/ChatPage.tsx`
- `apps/dsa-web/src/index.css`
