/** Theme: system (auto), light, dark — persisted in localStorage. */
(function (global) {
    const STORAGE_KEY = 'mc-theme-preference';
    const MODES = ['system', 'light', 'dark'];
    const LABELS = {
        system: 'System theme',
        light: 'Light theme',
        dark: 'Dark theme',
    };

    function getPreference() {
        try {
            const stored = localStorage.getItem(STORAGE_KEY);
            return MODES.includes(stored) ? stored : 'system';
        } catch (e) {
            return 'system';
        }
    }

    function resolveTheme(preference) {
        if (preference === 'dark') return 'dark';
        if (preference === 'light') return 'light';
        return global.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
    }

    function apply(preference) {
        const root = document.documentElement;
        root.setAttribute('data-theme-pref', preference);
        root.setAttribute('data-theme', resolveTheme(preference));
    }

    function updateToggleButton() {
        const btn = document.getElementById('theme-toggle');
        if (!btn) return;
        const pref = getPreference();
        const iconMap = { system: 'monitor', light: 'sun', dark: 'moon' };
        const iconName = iconMap[pref] || 'monitor';
        if (typeof global.icon === 'function') {
            btn.innerHTML = `${global.icon(iconName)}<span class="theme-toggle-label">${LABELS[pref]}</span>`;
        }
        btn.setAttribute('aria-label', LABELS[pref]);
        btn.title = LABELS[pref];
    }

    function setPreference(preference) {
        try {
            localStorage.setItem(STORAGE_KEY, preference);
        } catch (e) {
            /* ignore */
        }
        apply(preference);
        updateToggleButton();
    }

    function cyclePreference() {
        const current = getPreference();
        const next = MODES[(MODES.indexOf(current) + 1) % MODES.length];
        setPreference(next);
    }

    function initToggle() {
        const btn = document.getElementById('theme-toggle');
        if (!btn) return;
        btn.addEventListener('click', cyclePreference);
        updateToggleButton();
    }

    apply(getPreference());

    global.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
        if (getPreference() === 'system') {
            apply('system');
        }
    });

    global.ThemeManager = {
        getPreference,
        setPreference,
        cyclePreference,
        initToggle,
        apply,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initToggle);
    } else {
        initToggle();
    }
})(typeof window !== 'undefined' ? window : this);
