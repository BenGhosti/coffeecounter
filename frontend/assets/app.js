// Shared helpers used by every page.

function currentTheme() {
    return document.documentElement.getAttribute('data-theme') || 'dark';
}

// Toggle the moon/sun glyphs of every .theme-toggle on the page to match
// the active theme. Icons are swapped in JS (not CSS) for reliable
// cross-browser behaviour inside inline SVG.
function applyThemeIcons() {
    const dark = currentTheme() === 'dark';
    document.querySelectorAll('.icon-moon').forEach(el => { el.style.display = dark ? 'none' : ''; });
    document.querySelectorAll('.icon-sun').forEach(el => { el.style.display = dark ? '' : 'none'; });
}

function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem('theme', theme); } catch (e) { /* private mode */ }
    applyThemeIcons();
}

// Dark is the default look (roasted coffee); a saved light choice wins.
const savedTheme = (() => {
    try { return localStorage.getItem('theme') || 'dark'; } catch (e) { return 'dark'; }
})();
document.documentElement.setAttribute('data-theme', savedTheme);
applyThemeIcons();

function initThemeToggle(buttonId = 'theme-toggle') {
    const btn = document.getElementById(buttonId);
    if (!btn) return;
    btn.addEventListener('click', () => {
        setTheme(currentTheme() === 'dark' ? 'light' : 'dark');
    });
}

// Small non-blocking toasts (replaces alert()/one-off status flashes).
function showToast(text, type = 'info') {
    let box = document.querySelector('.toast-container');
    if (!box) {
        box = document.createElement('div');
        box.className = 'toast-container';
        document.body.appendChild(box);
    }
    const toast = document.createElement('div');
    toast.className = 'toast ' + type;
    toast.textContent = text;
    toast.setAttribute('role', 'status');
    box.appendChild(toast);
    setTimeout(() => {
        toast.classList.add('hide');
        setTimeout(() => toast.remove(), 350);
    }, 3200);
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
