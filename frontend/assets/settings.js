initThemeToggle();

let ME = null;

const canUseWebAuthn = window.isSecureContext === true &&
    typeof navigator.credentials === 'object' &&
    typeof navigator.credentials.create === 'function';

function esc(s) {
    return String(s).replace(/[&<>"']/g, c => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
}

async function boot() {
    try {
        ME = await requireAuth();
    } catch (e) {
        return; // requireAuth already redirected to the login page
    }
    // Admins manage their passkeys in the Admin panel.
    if (ME.role === 'admin') {
        window.location.href = '/admin.html';
        return;
    }

    document.getElementById('who').textContent = ME.name;
    document.getElementById('logout-link').addEventListener('click', async (e) => {
        e.preventDefault();
        await api('/api/auth/logout', { method: 'POST' });
        window.location.href = '/index.html';
    });

    const warning = document.getElementById('secure-warning');
    const addBtn = document.getElementById('add-passkey-btn');
    if (!canUseWebAuthn) {
        warning.style.display = 'block';
        addBtn.disabled = true;
    } else {
        addBtn.addEventListener('click', addPasskey);
    }
    await loadPasskeys();
}

async function loadPasskeys() {
    const body = document.getElementById('passkeys-body');
    let keys;
    try {
        keys = await api(`/api/users/${ME.id}/passkeys`);
    } catch (e) {
        showToast(e.message || 'Could not load passkeys', 'error');
        return;
    }
    body.innerHTML = '';
    if (keys.length === 0) {
        body.innerHTML = '<tr><td colspan="4" class="empty-message">No passkeys yet</td></tr>';
        return;
    }
    keys.forEach(k => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${esc(k.name)}</td>
            <td>${fmtTime(k.created_at)}</td>
            <td>${k.last_used_at ? fmtTime(k.last_used_at) : 'never'}</td>
            <td><button class="danger-outline" data-id="${k.id}" data-name="${esc(k.name)}">Remove</button></td>`;
        body.appendChild(tr);
    });
    body.querySelectorAll('button[data-id]').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm(`Remove passkey "${btn.dataset.name}"?`)) return;
            try {
                await api(`/api/users/${ME.id}/passkeys/${btn.dataset.id}`, { method: 'DELETE' });
                showToast('Passkey removed', 'success');
                await loadPasskeys();
            } catch (e) {
                showToast(e.message || 'Could not remove passkey', 'error');
            }
        });
    });
}

async function addPasskey() {
    if (!canUseWebAuthn) {
        showToast('Passkeys need HTTPS or localhost', 'error');
        return;
    }
    const name = document.getElementById('passkey-name').value.trim();
    if (!name) {
        showToast('Please name this passkey', 'error');
        return;
    }
    const addBtn = document.getElementById('add-passkey-btn');
    addBtn.disabled = true;
    try {
        const { challengeId, options } = await api(`/api/users/${ME.id}/passkeys/register-options`, {
            method: 'POST', body: JSON.stringify({}),
        });
        const credential = await navigator.credentials.create({ publicKey: toRegistrationOptions(options) });
        await api(`/api/users/${ME.id}/passkeys/register-verify`, {
            method: 'POST',
            body: JSON.stringify({ challengeId, response: registrationToJSON(credential), name }),
        });
        document.getElementById('passkey-name').value = '';
        showToast(`Passkey "${name}" added`, 'success');
        await loadPasskeys();
    } catch (e) {
        if (e.name === 'NotAllowedError') {
            showToast('Registration cancelled', 'info');
        } else {
            showToast(e.message || 'Registration failed', 'error');
        }
    } finally {
        addBtn.disabled = false;
    }
}

boot();
