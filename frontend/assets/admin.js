initThemeToggle();

let ME = null;
let PIN_LENGTH = 4;
const canUseWebAuthn = window.isSecureContext === true &&
    typeof navigator.credentials === 'object' &&
    typeof navigator.credentials.create === 'function';

async function boot() {
    ME = await requireAdmin();
    if (!canUseWebAuthn) document.getElementById('secure-warning').style.display = 'block';

    const status = await api('/api/auth/status');
    PIN_LENGTH = status.pinLength || 4;
    const pinLabel = document.getElementById('new-user-pin-label');
    const pinInput = document.getElementById('new-user-pin');
    pinLabel.textContent = `PIN (${PIN_LENGTH} digits)`;
    pinInput.maxLength = PIN_LENGTH;
    pinInput.placeholder = '•'.repeat(PIN_LENGTH);

    document.getElementById('logout-link').addEventListener('click', async (e) => {
        e.preventDefault();
        await api('/api/auth/logout', { method: 'POST' });
        window.location.href = '/index.html';
    });

    await loadUsers();
    await loadDrinks();
    await loadPasskeys();

    document.getElementById('add-user-btn').addEventListener('click', addUser);
    document.getElementById('add-drink-btn').addEventListener('click', addDrink);
    document.getElementById('add-passkey-btn').addEventListener('click', addPasskey);
}

// ---------------- Users ----------------
async function loadUsers() {
    const users = await api('/api/users');
    const body = document.getElementById('users-body');
    body.innerHTML = '';
    users.forEach(u => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${u.name}</td>
            <td><span class="badge ${u.role}">${u.role}</span></td>
            <td>${u.passkeyCount}</td>
            <td>${fmtTime(u.created_at)}</td>
            <td style="display:flex; gap:6px;">
                <button class="secondary" data-action="reset-pin" data-id="${u.id}" data-name="${u.name}">Reset PIN</button>
                <button class="danger-outline" data-action="delete" data-id="${u.id}" data-name="${u.name}">Delete</button>
            </td>`;
        body.appendChild(tr);
    });
    body.querySelectorAll('[data-action="reset-pin"]').forEach(btn => {
        btn.addEventListener('click', () => resetPin(btn.dataset.id, btn.dataset.name));
    });
    body.querySelectorAll('[data-action="delete"]').forEach(btn => {
        btn.addEventListener('click', () => deleteUser(btn.dataset.id, btn.dataset.name));
    });
}

async function addUser() {
    const name = document.getElementById('new-user-name').value.trim();
    const pin = document.getElementById('new-user-pin').value.trim();
    const role = document.getElementById('new-user-role').value;
    if (!name || pin.length !== PIN_LENGTH || !/^\d+$/.test(pin)) {
        showStatus('user-status', `Please enter a name and a ${PIN_LENGTH}-digit PIN`, 'error');
        return;
    }
    try {
        await api('/api/users', { method: 'POST', body: JSON.stringify({ name, pin, role }) });
        document.getElementById('new-user-name').value = '';
        document.getElementById('new-user-pin').value = '';
        showStatus('user-status', `User "${name}" added`, 'success');
        await loadUsers();
    } catch (e) {
        showStatus('user-status', e.message, 'error');
    }
}

async function resetPin(id, name) {
    const pin = prompt(`New PIN for ${name} (${PIN_LENGTH} digits):`);
    if (!pin) return;
    if (pin.length !== PIN_LENGTH || !/^\d+$/.test(pin)) {
        showStatus('user-status', `PIN must be exactly ${PIN_LENGTH} digits`, 'error');
        return;
    }
    try {
        await api(`/api/users/${id}`, { method: 'PATCH', body: JSON.stringify({ pin }) });
        showStatus('user-status', `PIN updated for ${name}`, 'success');
    } catch (e) {
        showStatus('user-status', e.message, 'error');
    }
}

async function deleteUser(id, name) {
    if (!confirm(`Delete user "${name}"? This also removes their events and webhook links.`)) return;
    try {
        await api(`/api/users/${id}`, { method: 'DELETE' });
        showStatus('user-status', `User "${name}" deleted`, 'success');
        await loadUsers();
    } catch (e) {
        showStatus('user-status', e.message, 'error');
    }
}

// ---------------- Drink types ----------------
async function loadDrinks() {
    const drinks = await api('/api/drinks?include_inactive=true');
    const body = document.getElementById('drinks-body');
    body.innerHTML = '';
    drinks.forEach(d => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><span class="color-dot" style="background:${d.color}"></span>${d.color}</td>
            <td>${d.name}</td>
            <td>${d.active ? 'Active' : 'Inactive'}</td>
            <td>
                <button class="secondary" data-action="toggle" data-id="${d.id}" data-active="${d.active}">
                    ${d.active ? 'Deactivate' : 'Activate'}
                </button>
            </td>`;
        body.appendChild(tr);
    });
    body.querySelectorAll('[data-action="toggle"]').forEach(btn => {
        btn.addEventListener('click', () => toggleDrink(btn.dataset.id, btn.dataset.active === 'true'));
    });
}

async function addDrink() {
    const name = document.getElementById('new-drink-name').value.trim();
    const color = document.getElementById('new-drink-color').value;
    if (!name) {
        showStatus('drink-status', 'Please enter a name', 'error');
        return;
    }
    try {
        await api('/api/drinks', { method: 'POST', body: JSON.stringify({ name, color }) });
        document.getElementById('new-drink-name').value = '';
        showStatus('drink-status', `Drink type "${name}" added`, 'success');
        await loadDrinks();
    } catch (e) {
        showStatus('drink-status', e.message, 'error');
    }
}

async function toggleDrink(id, isActive) {
    try {
        if (isActive) {
            await api(`/api/drinks/${id}`, { method: 'DELETE' });
        } else {
            await api(`/api/drinks/${id}`, { method: 'PATCH', body: JSON.stringify({ active: true }) });
        }
        await loadDrinks();
    } catch (e) {
        showStatus('drink-status', e.message, 'error');
    }
}

// ---------------- Passkeys (admin's own account) ----------------
async function loadPasskeys() {
    const keys = await api(`/api/users/${ME.id}/passkeys`);
    const body = document.getElementById('passkeys-body');
    body.innerHTML = '';
    if (keys.length === 0) {
        body.innerHTML = '<tr><td colspan="4" class="empty-message">No passkeys yet</td></tr>';
        return;
    }
    keys.forEach(k => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${k.name}</td>
            <td>${fmtTime(k.created_at)}</td>
            <td>${k.last_used_at ? fmtTime(k.last_used_at) : 'never'}</td>
            <td><button class="danger-outline" data-id="${k.id}">Remove</button></td>`;
        body.appendChild(tr);
    });
    body.querySelectorAll('button[data-id]').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm('Remove this passkey?')) return;
            await api(`/api/users/${ME.id}/passkeys/${btn.dataset.id}`, { method: 'DELETE' });
            await loadPasskeys();
        });
    });
}

async function addPasskey() {
    if (!canUseWebAuthn) {
        showStatus('passkey-status', 'Passkeys need HTTPS or localhost', 'error');
        return;
    }
    const name = document.getElementById('passkey-name').value.trim();
    if (!name) {
        showStatus('passkey-status', 'Please name this passkey', 'error');
        return;
    }
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
        showStatus('passkey-status', `Passkey "${name}" added`, 'success');
        await loadPasskeys();
    } catch (e) {
        if (e.name === 'NotAllowedError') {
            showStatus('passkey-status', 'Registration cancelled', 'error');
        } else {
            showStatus('passkey-status', e.message || 'Registration failed', 'error');
        }
    }
}

boot();
