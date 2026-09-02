// Shared helpers used by every page.

const savedTheme = localStorage.getItem('theme') ||
    (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
document.documentElement.setAttribute('data-theme', savedTheme);

function initThemeToggle(buttonId = 'theme-toggle') {
    const btn = document.getElementById(buttonId);
    if (!btn) return;
    btn.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme');
        const next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        localStorage.setItem('theme', next);
    });
}

async function api(path, options = {}) {
    const response = await fetch(path, {
        credentials: 'include',
        headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
        ...options,
    });
    if (response.status === 401) {
        window.location.href = '/index.html';
        throw new Error('Not authenticated');
    }
    let data = null;
    try { data = await response.json(); } catch (e) { /* no body */ }
    if (!response.ok) {
        throw new Error((data && data.detail) || `Request failed (${response.status})`);
    }
    return data;
}

async function requireAuth() {
    try {
        return await api('/api/auth/me');
    } catch (e) {
        window.location.href = '/index.html';
        throw e;
    }
}

async function requireAdmin() {
    const me = await requireAuth();
    if (me.role !== 'admin') {
        window.location.href = '/dashboard.html';
        throw new Error('Not admin');
    }
    return me;
}

function showStatus(elId, text, type) {
    const el = document.getElementById(elId);
    if (!el) return;
    el.textContent = text;
    el.className = 'status-message ' + type;
    setTimeout(() => { el.className = 'status-message'; }, 4000);
}

function fmtTime(iso) {
    return new Date(iso).toLocaleString();
}
