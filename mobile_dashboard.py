"""Tools for constructing a modern mobile delivery dashboard as a static HTML string.

The module exposes a single public helper – :func:`generate_mobile_html` – that builds
an attractive, responsive dashboard containing driver information, KPIs, a status
legend, and an interactive list of stops. Each stop supports expandable details,
localStorage persistence for dispatcher notes and phone numbers, and quick actions.

The function accepts either a combined payload dictionary::

    generate_mobile_html({
        "driver": {...},
        "stats": [...],
        "stops": [...],
        "meta": {...},
    })

or the individual arguments ``driver``, ``stops``, and the optional keyword-only
parameters ``stats`` and ``meta``. All arguments are plain dictionaries/lists to
keep the API lightweight and serialization-friendly.
"""

from __future__ import annotations

from datetime import datetime
from html import escape
import io
import re
from typing import Any, Iterable, Mapping, Sequence

__all__ = ["generate_mobile_html"]

_STATUS_THEMES: dict[str, dict[str, Any]] = {
    "delivered": {
        "label": "Доставлено",
        "color": "#34d399",
        "soft": "rgba(52, 211, 153, 0.25)",
        "icon": "✅",
        "aliases": {"done", "completed", "success", "delivered"},
    },
    "missed-call": {
        "label": "Недозвон",
        "color": "#fb923c",
        "soft": "rgba(251, 146, 60, 0.25)",
        "icon": "📵",
        "aliases": {"missed", "no-answer", "недозвон"},
    },
    "refused": {
        "label": "Отказ",
        "color": "#fb7185",
        "soft": "rgba(251, 113, 133, 0.25)",
        "icon": "❌",
        "aliases": {"refused", "cancelled", "отказ"},
    },
    "rescheduled": {
        "label": "Перенос",
        "color": "#facc15",
        "soft": "rgba(250, 204, 21, 0.25)",
        "icon": "🗓️",
        "aliases": {"rescheduled", "postponed", "перен"},
    },
    "in-progress": {
        "label": "В процессе",
        "color": "#818cf8",
        "soft": "rgba(129, 140, 248, 0.25)",
        "icon": "🟡",
        "aliases": {"in-progress", "in_transit", "process", "в процессе", "в пути"},
    },
    "pending": {
        "label": "Ожидает",
        "color": "#7dd3fc",
        "soft": "rgba(125, 211, 252, 0.25)",
        "icon": "🕒",
        "aliases": {"pending", "awaiting", "ожид"},
    },
    "default": {
        "label": "Статус",
        "color": "#a5b4fc",
        "soft": "rgba(165, 180, 252, 0.25)",
        "icon": "ℹ️",
        "aliases": set(),
    },
}

_DEFAULT_LEGEND_ORDER = [
    "delivered",
    "in-progress",
    "rescheduled",
    "missed-call",
    "refused",
]

_COMPLETE_STATUSES = {"delivered", "success"}

_BASE_STYLES = """
<style>
:root {
  color-scheme: dark;
  --font-family: 'Inter', 'SF Pro Display', 'Segoe UI', system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  --bg-gradient: radial-gradient(circle at 12% 20%, rgba(29, 78, 216, 0.55), transparent 55%),
                 radial-gradient(circle at 88% 5%, rgba(236, 72, 153, 0.45), transparent 45%),
                 linear-gradient(135deg, #050b18, #0f172a 45%, #080b16 100%);
  --surface: rgba(15, 23, 42, 0.92);
  --surface-muted: rgba(148, 163, 184, 0.12);
  --text-primary: #f8fafc;
  --text-muted: #c7d4f7;
  --border-color: rgba(255, 255, 255, 0.12);
  --accent: #7dd3fc;
  --accent-strong: #38bdf8;
  --shadow: 0 20px 45px rgba(2, 6, 23, 0.65);
  --danger: #fb7185;
}

@media (prefers-color-scheme: light) {
  :root {
    --bg-gradient: radial-gradient(circle at 10% 0%, rgba(59, 130, 246, 0.35), transparent 45%),
                   radial-gradient(circle at 90% 10%, rgba(236, 72, 153, 0.25), transparent 40%),
                   linear-gradient(135deg, #e0f2ff, #f4f7fb 55%, #eaf0ff);
    --surface: rgba(255, 255, 255, 0.9);
    --surface-muted: rgba(15, 23, 42, 0.06);
    --text-primary: #0f172a;
    --text-muted: #475569;
    --border-color: rgba(15, 23, 42, 0.12);
    --shadow: 0 20px 45px rgba(15, 23, 42, 0.1);
  }
}

* {
  box-sizing: border-box;
}

html, body {
  margin: 0;
  padding: 0;
  min-height: 100%;
  font-family: var(--font-family);
  background: var(--bg-gradient);
  color: var(--text-primary);
}

body {
  background-attachment: fixed;
}

.page-shell {
  min-height: 100vh;
  padding: clamp(1rem, 4vw, 2.8rem);
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  max-width: 960px;
  margin: 0 auto;
}

.glass-panel {
  background: var(--surface);
  border: 1px solid var(--border-color);
  border-radius: 24px;
  padding: clamp(1rem, 3vw, 1.5rem);
  box-shadow: var(--shadow);
  backdrop-filter: blur(26px);
  position: relative;
  overflow: hidden;
}

.glass-panel::after {
  content: "";
  position: absolute;
  inset: 0;
  border-radius: inherit;
  border: 1px solid rgba(255, 255, 255, 0.04);
  pointer-events: none;
}

.driver-card {
  display: flex;
  flex-direction: column;
  gap: 1.25rem;
  animation: floatIn 0.6s ease both;
}

.driver-headline {
  display: flex;
  gap: 1rem;
}

.driver-avatar {
  width: 72px;
  height: 72px;
  border-radius: 20px;
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.25), rgba(236, 72, 153, 0.35));
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.25rem;
  font-weight: 600;
  color: var(--text-primary);
  flex-shrink: 0;
}

.driver-avatar img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  border-radius: inherit;
}

.driver-info h1 {
  margin: 0;
  font-size: clamp(1.4rem, 5vw, 2rem);
}

.driver-info p {
  margin: 0.2rem 0 0;
  color: var(--text-muted);
}

.chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.35rem;
}

.chip {
  padding: 0.35rem 0.75rem;
  border-radius: 999px;
  background: var(--surface-muted);
  font-size: 0.85rem;
  color: var(--text-muted);
}

.driver-kpis {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(110px, 1fr));
  gap: 0.75rem;
}

.driver-kpi {
  padding: 0.75rem 1rem;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.03);
  border: 1px solid rgba(255, 255, 255, 0.05);
}

.driver-kpi span {
  display: block;
  font-size: 0.75rem;
  color: var(--text-muted);
}

.driver-kpi strong {
  font-size: 1.25rem;
  font-weight: 600;
}

.progress-wrapper {
  margin-top: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.3rem;
}

progress {
  width: 100%;
  height: 6px;
  border-radius: 999px;
  overflow: hidden;
  appearance: none;
}

progress::-webkit-progress-bar {
  background: rgba(255, 255, 255, 0.08);
}

progress::-webkit-progress-value {
  background: var(--accent-strong);
}

progress::-moz-progress-bar {
  background: var(--accent-strong);
}

.driver-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem;
  align-items: center;
}

.button {
  border: none;
  border-radius: 16px;
  padding: 0.65rem 1.1rem;
  font-size: 0.95rem;
  font-weight: 500;
  display: inline-flex;
  align-items: center;
  gap: 0.45rem;
  cursor: pointer;
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}

.button.primary {
  background: linear-gradient(120deg, #38bdf8, #7c3aed);
  color: #fff;
  box-shadow: 0 10px 25px rgba(56, 189, 248, 0.35);
}

.button.ghost {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text-primary);
}

.button:active {
  transform: translateY(1px);
}

.stats-section {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.section-title {
  margin: 0;
  font-size: 1.15rem;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 0.9rem;
}

.stat-card {
  padding: 1rem;
  border-radius: 20px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.05);
  position: relative;
  overflow: hidden;
}

.stat-card strong {
  font-size: 1.65rem;
  display: block;
}

.stat-card span {
  font-size: 0.85rem;
  color: var(--text-muted);
}

.stat-trend {
  position: absolute;
  top: 1rem;
  right: 1rem;
  padding: 0.2rem 0.6rem;
  border-radius: 999px;
  font-size: 0.75rem;
  background: rgba(255, 255, 255, 0.1);
}

.status-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.status-chip {
  padding: 0.3rem 0.75rem;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  font-size: 0.85rem;
  display: inline-flex;
  align-items: center;
  gap: 0.4rem;
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: currentColor;
}

.orders-section {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.orders-list {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.order-card {
  transition: transform 0.35s ease, border-color 0.35s ease, box-shadow 0.35s ease;
  border: 1px solid rgba(255, 255, 255, 0.07);
  padding-bottom: 1.25rem;
}

.order-card .order-header {
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
}

.order-title {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  flex-wrap: wrap;
  align-items: baseline;
}

.order-index {
  font-size: 0.85rem;
  color: var(--text-muted);
}

.order-address {
  margin: 0.25rem 0 0;
  color: var(--text-muted);
}

.status-badge {
  align-self: flex-start;
  padding: 0.3rem 0.8rem;
  border-radius: 999px;
  font-size: 0.85rem;
  display: inline-flex;
  gap: 0.4rem;
  align-items: center;
  background: rgba(255, 255, 255, 0.1);
}

.order-time {
  font-size: 0.85rem;
  color: var(--text-muted);
}

.order-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 0.35rem;
}

.order-tag {
  padding: 0.25rem 0.6rem;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.08);
  font-size: 0.75rem;
  color: var(--text-muted);
}

.card-toggle {
  margin-top: 0.4rem;
  display: inline-flex;
  gap: 0.3rem;
  align-items: center;
  background: transparent;
  color: var(--accent);
  border: none;
  font-weight: 600;
  cursor: pointer;
}

.card-toggle svg {
  width: 16px;
  height: 16px;
  transition: transform 0.3s ease;
}

.order-card.is-open .card-toggle svg {
  transform: rotate(180deg);
}

.order-body {
  max-height: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  opacity: 0;
  transition: max-height 0.5s ease, opacity 0.35s ease;
}

.order-card.is-open .order-body {
  opacity: 1;
}

.order-details-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 0.75rem;
}

.detail-card {
  padding: 0.75rem;
  border-radius: 16px;
  background: rgba(255, 255, 255, 0.02);
  border: 1px solid rgba(255, 255, 255, 0.04);
}

.detail-label {
  font-size: 0.75rem;
  color: var(--text-muted);
}

.detail-value {
  margin: 0.15rem 0 0;
  font-size: 0.95rem;
}

.order-notes {
  padding: 0.85rem;
  border-radius: 16px;
  background: rgba(58, 12, 163, 0.25);
  border: 1px solid rgba(128, 90, 213, 0.25);
}

.note-form {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.input-label {
  font-size: 0.85rem;
  color: var(--text-muted);
}

.input-row {
  display: flex;
  gap: 0.5rem;
}

.input-field {
  width: 100%;
  padding: 0.65rem 0.85rem;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(15, 23, 42, 0.6);
  color: var(--text-primary);
  font-size: 0.95rem;
}

textarea.input-field {
  resize: none;
  min-height: 70px;
}

.note-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.save-state {
  font-size: 0.8rem;
  color: var(--text-muted);
}

.note-buttons {
  display: flex;
  gap: 0.5rem;
}

.toast {
  position: fixed;
  left: 50%;
  bottom: 20px;
  transform: translateX(-50%) translateY(120%);
  background: rgba(15, 23, 42, 0.95);
  color: var(--text-primary);
  padding: 0.85rem 1.25rem;
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.08);
  box-shadow: var(--shadow);
  transition: transform 0.35s ease;
  z-index: 20;
}

.toast.is-visible {
  transform: translateX(-50%) translateY(0);
}

.empty-state {
  text-align: center;
  padding: 2rem 1.25rem;
  color: var(--text-muted);
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  border: 0;
}

@media (max-width: 600px) {
  .driver-headline {
    flex-direction: column;
  }
  .input-row {
    flex-direction: column;
  }
  .button {
    width: 100%;
    justify-content: center;
  }
}

@media (prefers-reduced-motion: reduce) {
  * {
    animation: none !important;
    transition: none !important;
  }
}

@keyframes floatIn {
  from {
    opacity: 0;
    transform: translateY(12px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/*__STATUS_RULES__*/
/*__CUSTOM_CARD_RULES__*/
</style>
"""

_STATUS_RULE_TEMPLATE = """
.order-card[data-status="{slug}"],
.status-chip[data-status="{slug}"],
.status-badge[data-status="{slug}"] {{
  --status-color: {color};
  --status-soft: {soft};
}}
.order-card[data-status="{slug}"] {{
  border-color: {soft};
}}
.status-badge[data-status="{slug}"],
.status-chip[data-status="{slug}"] {{
  background: {soft};
  color: {color};
}}
.status-badge[data-status="{slug}"] .status-dot,
.status-chip[data-status="{slug}"] .status-dot {{
  background: {color};
}}
"""

_SCRIPT_TEMPLATE = """
<script>
(function () {
  const STORAGE_KEY = '__STORAGE_KEY__';

  const ready = (fn) => {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', fn);
    } else {
      fn();
    }
  };

  ready(() => {
    hydrateAccordions();
    hydrateNotes();
    hydrateProgress();
    autoResizeNotes();
  });

  function hydrateAccordions() {
    const cards = document.querySelectorAll('.order-card');
    cards.forEach((card) => {
      const toggle = card.querySelector('.card-toggle');
      const body = card.querySelector('.order-body');
      if (!toggle || !body) return;
      toggle.addEventListener('click', () => {
        const isOpen = card.classList.toggle('is-open');
        if (isOpen) {
          body.style.maxHeight = body.scrollHeight + 'px';
        } else {
          body.style.maxHeight = '0px';
        }
        toggle.setAttribute('aria-expanded', String(isOpen));
      });
    });

    window.addEventListener('resize', () => {
      document.querySelectorAll('.order-card.is-open .order-body').forEach((body) => {
        body.style.maxHeight = body.scrollHeight + 'px';
      });
    });
  }

  function loadState() {
    if (!window.localStorage) return {};
    try {
      const raw = localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (error) {
      console.warn('Не удалось прочитать localStorage', error);
      return {};
    }
  }

  function persistState(state) {
    if (!window.localStorage) return;
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (error) {
      console.warn('Не удалось сохранить localStorage', error);
    }
  }

  function hydrateNotes() {
    const state = loadState();
    const toast = document.querySelector('.toast');

    const showToast = (message) => {
      if (!toast) return;
      toast.textContent = message;
      toast.classList.add('is-visible');
      window.setTimeout(() => toast.classList.remove('is-visible'), 2600);
    };

    document.querySelectorAll('.order-card[data-order-id]').forEach((card) => {
      const orderId = card.dataset.orderId;
      const phoneInput = card.querySelector('.phone-input');
      const noteInput = card.querySelector('.note-input');
      const saveButton = card.querySelector('.save-note');
      const clearButton = card.querySelector('.clear-note');
      const indicator = card.querySelector('[data-role="save-state"]');
      const callLink = card.querySelector('[data-role="call-link"]');

      const defaults = {
        phone: phoneInput ? (phoneInput.dataset.default || phoneInput.value || '') : '',
        comment: noteInput ? (noteInput.dataset.default || noteInput.value || '') : '',
      };

      const hydrateInputs = () => {
        const saved = state[orderId];
        if (saved && phoneInput) {
          phoneInput.value = saved.phone || '';
        }
        if (saved && noteInput) {
          noteInput.value = saved.comment || '';
        }
        updateIndicator(saved ? saved.savedAt : null);
        syncCallHref();
      };

      const syncCallHref = () => {
        if (!callLink || !phoneInput) return;
        const value = phoneInput.value.trim();
        const tel = value ? value.replace(/[^+\\d]/g, '') : '';
        callLink.href = tel ? `tel:${tel}` : '#';
      };

      const updateIndicator = (savedAt) => {
        if (!indicator) return;
        indicator.textContent = savedAt
          ? `Сохранено ${new Date(savedAt).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}`
          : 'Не сохранено';
      };

      saveButton?.addEventListener('click', () => {
        state[orderId] = {
          phone: phoneInput ? phoneInput.value.trim() : '',
          comment: noteInput ? noteInput.value.trim() : '',
          savedAt: new Date().toISOString(),
        };
        persistState(state);
        updateIndicator(state[orderId].savedAt);
        showToast(`Заявка ${orderId} сохранена`);
        syncCallHref();
      });

      clearButton?.addEventListener('click', () => {
        if (phoneInput) phoneInput.value = defaults.phone;
        if (noteInput) noteInput.value = defaults.comment;
        delete state[orderId];
        persistState(state);
        updateIndicator(null);
        showToast(`Заявка ${orderId} очищена`);
        syncCallHref();
      });

      phoneInput?.addEventListener('input', syncCallHref);
      hydrateInputs();
    });
  }

  function hydrateProgress() {
    document.querySelectorAll('progress').forEach((el) => {
      el.setAttribute('aria-hidden', 'true');
    });
  }

  function autoResizeNotes() {
    const resize = (el) => {
      el.style.height = 'auto';
      el.style.height = `${el.scrollHeight}px`;
    };
    document.querySelectorAll('.note-input').forEach((textarea) => {
      textarea.addEventListener('input', () => resize(textarea));
      resize(textarea);
    });
  }
})();
</script>
"""


def generate_mobile_html(
    driver_or_payload: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    stops: Sequence[Mapping[str, Any]] | None = None,
    *,
    stats: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None = None,
    meta: Mapping[str, Any] | None = None,
) -> str:
    """Return a fully inlined HTML string for the mobile delivery dashboard.

    Parameters
    ----------
    driver_or_payload:
        Either a mapping with the ``driver``/``stops``/``stats``/``meta`` keys or a
        mapping describing the driver when the remaining arguments are provided
        separately.
    stops:
        A sequence of dictionaries describing route stops/orders.
    stats:
        Optional list or mapping with KPI/stat cards.
    meta:
        Optional mapping with ``title``, ``storage_key``, ``last_updated`` and other
        presentation details.
    """

    driver, stops_data, stats_data, meta_data = _normalize_payload(
        driver_or_payload, stops, stats, meta
    )

    stats_list = _normalize_stats(stats_data)
    status_css, status_slugs = _build_status_css(stops_data, stats_list)

    driver_section = _build_driver_section(driver, stops_data, meta_data)
    stats_section = _build_stats_section(stats_list)
    legend_section = _build_status_legend(status_slugs)
    orders_markup = _build_orders_section(stops_data)

    html = io.StringIO()
    html.write("<!DOCTYPE html>\n<html lang=\"ru\">\n<head>\n")
    html.write("<meta charset=\"utf-8\" />\n")
    html.write(
        '<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1" />\n'
    )
    title_override = meta_data.get("title") if isinstance(meta_data, Mapping) else None
    driver_name = driver.get("name") if isinstance(driver, Mapping) else None
    if driver_name is not None:
        driver_name = str(driver_name).strip()
    base_title = title_override or (
        f"Маршрут {driver_name}" if driver_name else "Мобильная панель доставки"
    )
    html.write(f"<title>{escape(base_title)}</title>\n")

    styles = _BASE_STYLES.replace("/*__STATUS_RULES__*/", status_css).replace(
        "/*__CUSTOM_CARD_RULES__*/", ""
    )
    html.write(styles)
    html.write("</head>\n<body>\n")
    html.write('<div class="page-shell">')
    html.write(driver_section)
    html.write(stats_section)
    html.write(legend_section)
    html.write(orders_markup)
    html.write('</div>\n<div class="toast" role="status" aria-live="polite"></div>\n')

    storage_key = "linch-mobile-notes-v2"
    if isinstance(meta_data, Mapping):
        storage_key = meta_data.get("storage_key", storage_key)
    script = _SCRIPT_TEMPLATE.replace("__STORAGE_KEY__", escape(storage_key, quote=True))
    html.write(script)
    html.write("</body>\n</html>")
    return html.getvalue()


def _normalize_payload(
    driver_or_payload: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
    stops: Sequence[Mapping[str, Any]] | None,
    stats: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None,
    meta: Mapping[str, Any] | None,
) -> tuple[Mapping[str, Any], list[Mapping[str, Any]], Mapping[str, Any] | Sequence[Mapping[str, Any]] | None, Mapping[str, Any]]:
    driver: Mapping[str, Any]
    stops_data: list[Mapping[str, Any]]
    meta_data: Mapping[str, Any]

    if (
        stops is None
        and isinstance(driver_or_payload, Mapping)
        and ("driver" in driver_or_payload or "stops" in driver_or_payload)
    ):
        payload = driver_or_payload
        driver = payload.get("driver", {}) or {}
        stops_data = list(payload.get("stops", []) or [])
        stats_data = payload.get("stats", stats)
        meta_data = payload.get("meta", meta) or {}
    else:
        driver = driver_or_payload or {}
        stops_data = list(stops or [])
        stats_data = stats
        meta_data = meta or {}

    return driver, stops_data, stats_data, meta_data


def _normalize_stats(
    stats: Sequence[Mapping[str, Any]] | Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    if not stats:
        return []

    normalized: list[dict[str, Any]] = []
    items: Iterable[Any]
    if isinstance(stats, Mapping):
        items = stats.items()
    else:
        items = stats

    for entry in items:
        if isinstance(entry, tuple) and len(entry) == 2 and not isinstance(entry[1], Mapping):
            label, value = entry
            normalized.append({"label": str(label), "value": value, "status": str(label)})
            continue

        if isinstance(entry, Mapping):
            normalized.append(
                {
                    "label": entry.get("label") or entry.get("title") or entry.get("status"),
                    "value": entry.get("value") or entry.get("count") or 0,
                    "status": entry.get("status") or entry.get("key"),
                    "sub_label": entry.get("sub_label") or entry.get("subtitle"),
                    "percent": entry.get("percent") or entry.get("percentage"),
                    "delta": entry.get("delta"),
                }
            )
            continue

        normalized.append({"label": str(entry), "value": entry, "status": str(entry)})

    return normalized


def _status_slug(value: Any) -> str:
    if value is None:
        return "default"
    raw = str(value).strip()
    if not raw:
        return "default"
    lowered = raw.lower()
    keyword_map = [
        ("delivered", ("deliver", "достав")),
        ("missed-call", ("missed", "недозвон", "no answer")),
        ("refused", ("refus", "отказ")),
        ("rescheduled", ("resched", "перен")),
        ("in-progress", ("process", "в процессе", "в пути")),
        ("pending", ("pending", "awaiting", "ожид")),
    ]
    for slug, keywords in keyword_map:
        if any(keyword in lowered for keyword in keywords):
            return slug

    normalized = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return normalized or "default"


def _status_theme(slug: str) -> dict[str, Any]:
    if slug in _STATUS_THEMES:
        return _STATUS_THEMES[slug]
    for key, theme in _STATUS_THEMES.items():
        if slug in theme.get("aliases", set()):
            return theme
    return _STATUS_THEMES["default"]


def _build_status_css(
    stops: Sequence[Mapping[str, Any]], stats: Sequence[Mapping[str, Any]]
) -> tuple[str, list[str]]:
    slugs: list[str] = []

    for collection in (stops, stats):
        for item in collection:
            slug = _status_slug(item.get("status")) if isinstance(item, Mapping) else "default"
            if slug not in slugs:
                slugs.append(slug)

    if not slugs:
        slugs = list(_DEFAULT_LEGEND_ORDER)

    css_parts = []
    for slug in slugs:
        theme = _status_theme(slug)
        css_parts.append(
            _STATUS_RULE_TEMPLATE.format(
                slug=slug,
                color=theme.get("color", "#a5b4fc"),
                soft=theme.get("soft", "rgba(165, 180, 252, 0.25)"),
            )
        )

    return "\n".join(css_parts), slugs


def _build_driver_section(
    driver: Mapping[str, Any],
    stops: Sequence[Mapping[str, Any]],
    meta: Mapping[str, Any],
) -> str:
    driver_data = driver or {}
    stops = list(stops or [])
    name_raw = str(driver_data.get("name") or "Водитель").strip() or "Водитель"
    role_raw = str(driver_data.get("role") or "Маршрут")
    display_name = escape(name_raw)
    role_label = escape(role_raw)

    avatar_url = driver_data.get("avatar") or driver_data.get("photo")
    initials = "".join(part[:1] for part in name_raw.split()[:2]).upper() or name_raw[:2].upper()
    avatar_alt = escape(name_raw, quote=True)
    if avatar_url:
        avatar_html = (
            f'<img src="{escape(str(avatar_url), quote=True)}" alt="{avatar_alt}" />'
        )
    else:
        avatar_html = f"<span>{escape(initials)}</span>"

    chips = []
    for key in ("vehicle", "car", "route", "region", "shift", "hub"):
        value = driver_data.get(key)
        if value:
            chips.append(f'<span class="chip">{escape(str(value))}</span>')
    chips_html = "".join(chips)

    total_stops = driver_data.get("total_stops")
    if total_stops is None and stops:
        total_stops = len(stops)
    completed = driver_data.get("completed_stops")
    if completed is None:
        completed = sum(
            1 for stop in stops if _status_slug(stop.get("status")) in _COMPLETE_STATUSES
        )
    remaining = None
    if total_stops is not None and completed is not None:
        remaining = max(int(total_stops) - int(completed), 0)

    progress_value = 0.0
    if total_stops:
        try:
            progress_value = max(0.0, min(100.0, (float(completed or 0) / float(total_stops)) * 100))
        except ZeroDivisionError:
            progress_value = 0.0

    progress_block = (
        f'<div class="progress-wrapper"><progress value="{progress_value:.2f}" max="100" data-label="Прогресс маршрута"></progress>'
        f'<span class="detail-label">Выполнено: {int(completed or 0)} из {int(total_stops or 0)}</span></div>'
        if total_stops
        else ""
    )

    kpi_items = []
    kpi_rows = [
        (
            "Выполнено",
            f"{int(completed or 0)}/{int(total_stops or len(stops))}"
            if total_stops
            else str(completed or len(stops)),
        ),
        ("Осталось", str(remaining) if remaining is not None else None),
        ("Дистанция", driver_data.get("distance")),
        ("Время в пути", driver_data.get("duration") or driver_data.get("time_on_road")),
    ]
    for label, value in kpi_rows:
        if value:
            kpi_items.append(
                f'<div class="driver-kpi"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'
            )
    kpi_html = "".join(kpi_items)

    actions = []
    for action_key, icon in (("phone", "📞"), ("assistant_phone", "🤝")):
        phone = driver_data.get(action_key)
        if phone:
            tel_href = _sanitize_phone(phone)
            actions.append(
                f'<a class="button ghost" href="tel:{escape(tel_href, quote=True)}">{icon} {escape(str(phone))}</a>'
            )
    share_url = meta.get("share_url") if isinstance(meta, Mapping) else None
    if share_url:
        actions.append(
            f'<a class="button primary" target="_blank" rel="noopener" href="{escape(str(share_url), quote=True)}">Открыть карту</a>'
        )
    actions_html = "".join(actions)

    last_updated = meta.get("last_updated") if isinstance(meta, Mapping) else None
    if isinstance(last_updated, datetime):
        last_updated = last_updated.strftime("%d.%m %H:%M")
    last_updated_html = (
        f"<span class='detail-label'>Обновлено: {escape(str(last_updated))}</span>"
        if last_updated
        else ""
    )

    return "".join(
        [
            '<section class="driver-card glass-panel">',
            '<div class="driver-headline">',
            f'<div class="driver-avatar">{avatar_html}</div>',
            '<div class="driver-info">',
            f"<p class='detail-label'>{role_label}</p>",
            f"<h1>{display_name}</h1>",
            f"<div class='chip-row'>{chips_html}</div>" if chips_html else '',
            progress_block,
            '</div></div>',
            f"<div class='driver-kpis'>{kpi_html}</div>" if kpi_html else '',
            f"<div class='driver-actions'>{actions_html}</div>" if actions_html else '',
            last_updated_html,
            '</section>',
        ]
    )


def _build_stats_section(stats: Sequence[Mapping[str, Any]]) -> str:
    if not stats:
        return ''

    cards = []
    for stat in stats:
        label = escape(str(stat.get('label', '—')))
        value = escape(str(stat.get('value', '0')))
        sub_label = stat.get('sub_label')
        delta = stat.get('delta')
        percent = stat.get('percent')
        badge = f"<span class='stat-trend'>{escape(str(delta))}</span>" if delta else ''
        progress = ''
        if percent is not None:
            try:
                pct = max(0, min(100, float(percent)))
                progress = f"<progress value='{pct:.2f}' max='100' data-label='{label}'></progress>"
            except (TypeError, ValueError):
                progress = ''
        cards.append(
            "".join(
                [
                    '<article class="stat-card">',
                    badge,
                    f'<span>{label}</span>',
                    f'<strong>{value}</strong>',
                    f"<span>{escape(str(sub_label))}</span>" if sub_label else '',
                    progress,
                    '</article>',
                ]
            )
        )

    return (
        '<section class="stats-section glass-panel">'
        '<div class="section-header"><p class="section-title">Итоги по маршруту</p></div>'
        f'<div class="stats-grid">{''.join(cards)}</div>'
        '</section>'
    )


def _build_status_legend(slugs: Sequence[str]) -> str:
    chips = []
    for slug in slugs:
        theme = _status_theme(slug)
        label = escape(theme.get('label', slug.title()))
        icon = theme.get('icon', '')
        chips.append(
            f'<span class="status-chip" data-status="{slug}"><span class="status-dot"></span>{escape(icon)} {label}</span>'
        )
    return (
        '<section class="glass-panel">'
        '<p class="section-title">Статусы</p>'
        f'<div class="status-legend">{''.join(chips)}</div>'
        '</section>'
    )


def _build_orders_section(stops: Sequence[Mapping[str, Any]]) -> str:
    if not stops:
        return (
            '<section class="orders-section glass-panel">'
            '<p class="section-title">Заявки</p>'
            '<div class="empty-state">Нет заявок для отображения</div>'
            '</section>'
        )

    cards = []
    for idx, stop in enumerate(stops, start=1):
        cards.append(_render_order_card(idx, stop))

    return (
        '<section class="orders-section">'
        '<p class="section-title">Заявки</p>'
        f'<div class="orders-list">{''.join(cards)}</div>'
        '</section>'
    )


def _render_order_card(position: int, stop: Mapping[str, Any]) -> str:
    stop_data = stop or {}
    slug = _status_slug(stop_data.get("status"))
    theme = _status_theme(slug)

    order_id = stop_data.get("order_id") or stop_data.get("id") or position
    order_id_text = str(order_id)
    order_id_attr = escape(order_id_text, quote=True)
    order_id_display = escape(order_id_text)

    timestamp = _format_datetime(stop_data.get("timestamp") or stop_data.get("time"))
    address_text = str(stop_data.get("address") or "Адрес не указан")
    customer_text = str(stop_data.get("customer") or stop_data.get("client") or "Клиент")

    tags = stop_data.get("tags") or stop_data.get("labels") or []
    if isinstance(tags, str):
        tags = [tags]
    tags_html = "".join(
        f'<span class="order-tag">{escape(str(tag))}</span>' for tag in tags if tag
    )
    if tags_html:
        tags_html = f'<div class="order-tags">{tags_html}</div>'

    detail_specs = [
        ("Клиент", customer_text),
        ("Время статуса", timestamp),
        ("Окно доставки", stop_data.get("window") or stop_data.get("time_window")),
        ("План прибытия", stop_data.get("eta") or stop_data.get("planned_time")),
        ("Оплата", stop_data.get("payment") or stop_data.get("cod")),
        ("Груз", stop_data.get("weight") or stop_data.get("load")),
    ]
    detail_html = "".join(
        f'<div class="detail-card"><p class="detail-label">{escape(label)}</p>'
        f'<p class="detail-value">{escape(str(value))}</p></div>'
        for label, value in detail_specs
        if value
    )
    if detail_html:
        detail_html = f'<div class="order-details-grid">{detail_html}</div>'

    instructions = stop_data.get("instructions") or stop_data.get("note")
    notes_html = (
        f'<div class="order-notes">{escape(str(instructions))}</div>' if instructions else ""
    )

    default_phone = stop_data.get("phone") or ""
    default_comment = stop_data.get("dispatcher_note") or stop_data.get("comment") or ""
    tel_href = _sanitize_phone(default_phone)
    card_id = f"order-{position}"

    note_section = "".join(
        [
            '<div class="note-form">',
            f'<label class="input-label" for="phone-{card_id}">Телефон клиента</label>',
            '<div class="input-row">',
            f'<input id="phone-{card_id}" class="input-field phone-input" type="tel" '
            f'data-default="{escape(str(default_phone), quote=True)}" '
            f'value="{escape(str(default_phone), quote=True)}" '
            'autocomplete="tel" inputmode="tel" placeholder="+7 (___) ___-__-__" />',
            f'<a class="button ghost" data-role="call-link" href="tel:{escape(tel_href, quote=True)}">Позвонить</a>',
            '</div>',
            f'<label class="input-label" for="note-{card_id}">Комментарий диспетчера</label>',
            f'<textarea id="note-{card_id}" class="input-field note-input" rows="2" '
            f'data-default="{escape(str(default_comment), quote=True)}" '
            f'placeholder="Добавьте важные детали">{escape(str(default_comment))}</textarea>',
            '<div class="note-actions">',
            '<span class="save-state" data-role="save-state">Не сохранено</span>',
            '<div class="note-buttons">',
            '<button type="button" class="button ghost clear-note">Очистить</button>',
            '<button type="button" class="button primary save-note">Сохранить</button>',
            '</div></div></div>',
        ]
    )

    customer_html = escape(customer_text)
    timestamp_html = escape(timestamp)
    address_html = escape(address_text)
    status_label = escape(theme.get("label", slug.title()))
    status_icon = escape(theme.get("icon", ""))

    return "".join(
        [
            f'<article class="order-card glass-panel" data-status="{slug}" data-order-id="{order_id_attr}">',
            '<div class="order-header">',
            '<div class="order-title">',
            f'<div><p class="order-index">Точка {position}</p><h3>Заказ {order_id_display}</h3>'
            f'<p class="order-address">{address_html}</p></div>',
            '<div class="order-status">',
            f'<span class="status-badge" data-status="{slug}"><span class="status-dot"></span>{status_icon} {status_label}</span>',
            f'<p class="order-time">{timestamp_html}</p>',
            '</div></div>',
            f'<p class="detail-label">{customer_html}</p>',
            tags_html or '',
            f'<button type="button" class="card-toggle" aria-expanded="false" aria-controls="body-{card_id}" id="toggle-{card_id}">'
            '<span>Подробнее</span>'
            '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 9l6 6 6-6" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg>'
            '</button>',
            f'<div class="order-body" id="body-{card_id}" role="region" aria-labelledby="toggle-{card_id}">',
            detail_html or '',
            notes_html,
            note_section,
            '</div></article>',
        ]
    )


def _format_datetime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime('%d.%m.%Y %H:%M')
    if not value:
        return ''
    return str(value)


def _sanitize_phone(value: Any) -> str:
    if not value:
        return ''
    cleaned = re.sub(r'[^+\d]', '', str(value))
    if cleaned.startswith('8') and not cleaned.startswith('+') and len(cleaned) == 11:
        cleaned = '+7' + cleaned[1:]
    return cleaned or str(value)
