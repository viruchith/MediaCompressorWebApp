/* MediaCompressorWebApp client */

const socket = io();

let profiles = {};
let currentFilePage = 1;
let filePageLimit = 20;
let fileStatusFilter = '';
let fileSearch = '';
let jobsPage = 1;
const fileProgressCache = new Map();
let refreshFilesTimer = null;
let refreshJobsTimer = null;

// --- Utilities ---

function debounceRefreshFiles() {
    if (refreshFilesTimer) clearTimeout(refreshFilesTimer);
    refreshFilesTimer = setTimeout(() => loadFiles(), 300);
}

function debounceRefreshJobs() {
    if (refreshJobsTimer) clearTimeout(refreshJobsTimer);
    refreshJobsTimer = setTimeout(() => loadJobs(), 300);
}

function formatSizeChange(inputBytes, outputBytes) {
    if (inputBytes == null || outputBytes == null) return '';
    const input = Number(inputBytes);
    const output = Number(outputBytes);
    if (!input || input <= 0) return `${formatBytes(output)}`;
    const ratio = output / input;
    const pct = Math.abs((ratio - 1) * 100);
    if (ratio < 0.9995) {
        return `${formatBytes(input)} → ${formatBytes(output)} (${pct.toFixed(1)}% smaller)`;
    }
    if (ratio > 1.0005) {
        return `${formatBytes(input)} → ${formatBytes(output)} (${pct.toFixed(1)}% larger)`;
    }
    return `${formatBytes(input)} → ${formatBytes(output)} (same size)`;
}

function formatRatioLabel(inputBytes, outputBytes, ratio) {
    if (inputBytes != null && outputBytes != null) {
        return formatSizeChange(inputBytes, outputBytes);
    }
    if (ratio == null) return '';
    const r = Number(ratio);
    const pct = Math.abs((r - 1) * 100);
    if (r < 0.9995) return `${pct.toFixed(1)}% smaller`;
    if (r > 1.0005) return `${pct.toFixed(1)}% larger`;
    return 'same size';
}

function formatJobSizeSummary(job) {
    if (!job.total_input_bytes || job.sized_completed_files === 0) return '';
    const summary = formatSizeChange(job.total_input_bytes, job.total_output_bytes);
    if (!summary) return '';
    return `<div class="job-size-summary">${escapeHtml(summary)}</div>`;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
}

function formatBytes(bytes) {
    if (!bytes && bytes !== 0) return '—';
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB';
    if (bytes < 1073741824) return (bytes / 1048576).toFixed(1) + ' MB';
    return (bytes / 1073741824).toFixed(2) + ' GB';
}

function showStatus(message, type) {
    const el = document.getElementById('status-message');
    if (!el) return;
    const cls = type === 'error' ? 'error' : type === 'warning' ? 'warning' : 'success';
    el.innerHTML = `<div class="${cls}">${escapeHtml(message)}</div>`;
}

function getStatusClass(status) {
    const s = parseInt(status);
    if (s === 1) return 'status-completed';
    if (s === -3) return 'status-cancelled';
    if (s === -1 || s === -2) return 'status-error';
    if (s === 2) return 'status-processing';
    return '';
}

function getStatusText(status) {
    switch (parseInt(status)) {
        case 1: return 'Completed';
        case -1: return 'Error';
        case -2: return 'Permanent Fail';
        case -3: return 'Cancelled';
        case 2: return 'Processing';
        case 0: return 'Pending';
        default: return 'Unknown';
    }
}

// --- Profiles ---

function profileOptionLabel(name, data) {
    return `${name.replace(/_/g, ' ')} — ${data.description}`;
}

function populateProfileSelect(select, selected = 'balanced') {
    if (!select) return;
    select.innerHTML = '';
    for (const [name, data] of Object.entries(profiles)) {
        const opt = document.createElement('option');
        opt.value = name;
        opt.textContent = profileOptionLabel(name, data);
        select.appendChild(opt);
    }
    select.value = selected;
}

function formatJobProfilesHtml(job) {
    const img = job.image_profile || job.profile || 'balanced';
    const vid = job.video_profile || job.profile || 'balanced';
    const fmt = (p) => escapeHtml(p.replace(/_/g, ' '));
    if (img === vid) {
        return `<div class="job-profiles"><div>${fmt(img)}</div></div>`;
    }
    return `<div class="job-profiles">
        <div><strong>Image:</strong> ${fmt(img)}</div>
        <div><strong>Video:</strong> ${fmt(vid)}</div>
    </div>`;
}

function setConnectionStatus(state) {
    const el = document.getElementById('connection-indicator');
    if (!el) return;
    const label = el.querySelector('.connection-label');
    const labels = {
        online: 'Online',
        offline: 'Offline',
        connecting: 'Connecting…',
    };
    el.className = `connection-indicator ${state}`;
    if (label) label.textContent = labels[state] || state;
}

async function loadProfiles() {
    try {
        const resp = await fetch('/api/v1/profiles');
        profiles = await resp.json();
        populateProfileSelect(document.getElementById('image-profile'), 'balanced');
        populateProfileSelect(document.getElementById('video-profile'), 'balanced');
        applyImageProfileToForm('balanced');
        applyVideoProfileToForm('balanced');
    } catch (e) {
        console.error('Failed to load profiles:', e);
    }
}

function applyImageProfileToForm(profileName) {
    const profile = profiles[profileName];
    if (!profile) return;

    const img = profile.image || {};

    setVal('image-format', img.output_format || 'webp');
    setVal('image-quality', img.quality || 75);
    setVal('image-quality-val', img.quality || 75);
    setVal('image-max-dim', img.max_dimension || '');
    setChecked('image-lossless', img.lossless || false);
    setChecked('image-strip-meta', img.strip_metadata || false);
}

function applyVideoProfileToForm(profileName) {
    const profile = profiles[profileName];
    if (!profile) return;

    const vid = profile.video || {};

    setVal('video-codec', vid.codec || 'libx265');
    setVal('video-container', vid.container || 'mkv');
    setVal('video-crf', vid.crf || 28);
    setVal('video-crf-val', vid.crf || 28);
    setVal('video-preset', vid.preset || 'slow');
    setVal('video-audio-codec', vid.audio_codec || 'aac');
    setVal('video-audio-bitrate', vid.audio_bitrate || '128k');
    setVal('video-resolution', vid.resolution || 'original');
}

function setVal(id, val) {
    const el = document.getElementById(id);
    if (el) el.value = val;
}

function setChecked(id, val) {
    const el = document.getElementById(id);
    if (el) el.checked = !!val;
}

function getFormSettings() {
    return {
        input_folder: document.getElementById('inputFolderPath').value,
        output_folder: document.getElementById('outputFolderPath').value,
        image_profile: document.getElementById('image-profile').value,
        video_profile: document.getElementById('video-profile').value,
        priority: parseInt(document.getElementById('priority').value),
        preserve_metadata: document.getElementById('preserve-metadata').checked,
        image_settings: {
            output_format: document.getElementById('image-format').value,
            quality: parseInt(document.getElementById('image-quality').value),
            max_dimension: document.getElementById('image-max-dim').value
                ? parseInt(document.getElementById('image-max-dim').value) : null,
            lossless: document.getElementById('image-lossless').checked,
            strip_metadata: document.getElementById('image-strip-meta').checked,
        },
        video_settings: {
            codec: document.getElementById('video-codec').value,
            container: document.getElementById('video-container').value,
            crf: parseInt(document.getElementById('video-crf').value),
            preset: document.getElementById('video-preset').value,
            audio_codec: document.getElementById('video-audio-codec').value,
            audio_bitrate: document.getElementById('video-audio-bitrate').value,
            resolution: document.getElementById('video-resolution').value,
        },
    };
}

// --- Jobs ---

async function loadJobs() {
    const container = document.getElementById('jobs-list');
    if (!container) return;

    try {
        const resp = await fetch(`/api/v1/jobs?page=${jobsPage}&limit=10`);
        const data = await resp.json();
        container.innerHTML = '';

        if (!data.jobs || data.jobs.length === 0) {
            container.innerHTML = '<p>No jobs yet.</p>';
            return;
        }

        data.jobs.forEach(job => {
            const done = job.completed_files + job.failed_files + (job.cancelled_files || 0);
            const progress = job.total_files > 0
                ? Math.round((done / job.total_files) * 100)
                : 0;
            const sizeSummary = formatJobSizeSummary(job);
            const card = document.createElement('div');
            card.className = 'job-card';
            card.id = 'job-card-' + job.id;
            card.innerHTML = `
                <div class="job-card-header">
                    <div>
                        <h4>Job #${job.id} <span class="badge badge-${job.status}">${job.status}</span></h4>
                        ${formatJobProfilesHtml(job)}
                        <div class="job-meta">
                            ${job.completed_files}/${job.total_files} done
                            ${job.failed_files ? ` · ${job.failed_files} failed` : ''}
                            ${job.cancelled_files ? ` · ${job.cancelled_files} cancelled` : ''}
                        </div>
                        ${sizeSummary}
                        <div class="job-meta">${escapeHtml(job.input_folder)} → ${escapeHtml(job.output_folder)}</div>
                    </div>
                    <div class="job-actions">
                        ${job.status === 'active' ? `<button class="small secondary" onclick="pauseJob(${job.id})">Pause</button>` : ''}
                        ${job.status === 'paused' ? `<button class="small" onclick="resumeJob(${job.id})">Resume</button>` : ''}
                        ${job.failed_files > 0 ? `<button class="small" onclick="retryFailed(${job.id})">Retry Failed</button>` : ''}
                        ${job.status === 'completed' ? `<a class="btn small" href="/api/v1/jobs/${job.id}/manifest" target="_blank">Manifest</a>` : ''}
                        <a class="btn small secondary" href="/jobs/${job.id}">Details</a>
                        <button class="small danger" onclick="deleteJob(${job.id})">Delete</button>
                    </div>
                </div>
                <div class="progress-bar"><div class="progress-fill" style="width:${progress}%"></div></div>
            `;
            container.appendChild(card);
        });
    } catch (e) {
        console.error('Failed to load jobs:', e);
    }
}

async function pauseJob(id) {
    await fetch(`/api/v1/jobs/${id}/pause`, { method: 'PUT' });
    loadJobs();
}

async function resumeJob(id) {
    await fetch(`/api/v1/jobs/${id}/resume`, { method: 'PUT' });
    loadJobs();
}

async function retryFailed(id) {
    const resp = await fetch(`/api/v1/jobs/${id}/retry_failed`, { method: 'POST' });
    const data = await resp.json();
    showStatus(data.message, 'success');
    loadJobs();
    loadFiles();
}

async function deleteJob(id) {
    if (!confirm('Delete this job and all its files?')) return;
    await fetch(`/api/v1/jobs/${id}`, { method: 'DELETE' });
    loadJobs();
    loadFiles();
}

// --- Files ---

async function loadFiles() {
    const fileList = document.getElementById('file-list');
    if (!fileList) return;

    let url = `/api/v1/files?page=${currentFilePage}&limit=${filePageLimit}`;
    if (fileStatusFilter !== '') url += `&status=${fileStatusFilter}`;

    try {
        const resp = await fetch(url);
        const data = await resp.json();
        fileList.innerHTML = '';

        let files = data.files || [];
        if (fileSearch) {
            const q = fileSearch.toLowerCase();
            files = files.filter(f => f.input_file_path.toLowerCase().includes(q));
        }

        files.forEach(file => {
            const li = document.createElement('li');
            li.id = 'file-' + file.id;
            li.className = getStatusClass(file.status);

            const ratioText = formatRatioLabel(file.input_size, file.output_size, file.compression_ratio);
            const cached = fileProgressCache.get(Number(file.id));

            li.innerHTML = `
                <div><strong>${escapeHtml(file.input_file_path)}</strong></div>
                <div class="file-meta">${escapeHtml(file.output_file_path || '—')}</div>
                <div class="file-meta">
                    ${getStatusText(file.status)} · ${file.file_type}
                    ${file.input_size ? ' · ' + formatBytes(file.input_size) : ''}
                    ${file.output_size ? ' → ' + formatBytes(file.output_size) : ''}
                    ${ratioText ? ' · ' + ratioText : ''}
                </div>
                <div class="progress-bar">
                    <div class="progress-fill" id="progress-${file.id}" style="width:0%"></div>
                </div>
                <div class="status-text" id="status-${file.id}">Status: ${getStatusText(file.status)}</div>
            `;
            fileList.appendChild(li);
            if (cached) {
                applyProgressUpdate(cached);
            } else {
                updateFileProgress(file.id, file.status, null);
            }
        });

        updatePagination(data);
    } catch (e) {
        console.error('Error loading files:', e);
    }
}

function updatePagination(data) {
    const el = document.getElementById('file-pagination');
    if (!el) return;
    el.innerHTML = `
        <button ${data.page <= 1 ? 'disabled' : ''} onclick="changeFilePage(${data.page - 1})">Prev</button>
        <span>Page ${data.page} of ${data.pages} (${data.total} files)</span>
        <button ${data.page >= data.pages ? 'disabled' : ''} onclick="changeFilePage(${data.page + 1})">Next</button>
    `;
}

function changeFilePage(page) {
    currentFilePage = page;
    loadFiles();
}

function updateFileProgress(fileId, status, percent) {
    const progressFill = document.getElementById('progress-' + fileId);
    const statusEl = document.getElementById('status-' + fileId);
    const li = document.getElementById('file-' + fileId);
    if (!progressFill || !statusEl) return;

    li.className = getStatusClass(status);
    const s = parseInt(status);

    if (s === 1) {
        progressFill.style.width = '100%';
        progressFill.className = 'progress-fill complete';
        statusEl.textContent = 'Status: Completed';
    } else if (s === -1 || s === -2) {
        progressFill.style.width = '100%';
        progressFill.className = 'progress-fill error';
        statusEl.textContent = 'Status: Error';
    } else if (s === -3) {
        progressFill.style.width = '100%';
        progressFill.className = 'progress-fill cancelled';
        statusEl.textContent = 'Status: Cancelled';
    } else if (s === 2) {
        const pct = percent != null ? percent : 0;
        progressFill.style.width = pct + '%';
        progressFill.className = 'progress-fill';
        statusEl.textContent = `Status: Processing (${pct}%)`;
    } else {
        progressFill.style.width = '0%';
        statusEl.textContent = 'Status: Pending';
    }
}

function updateQueueCounts(counts) {
    const fields = ['total', 'pending', 'processing', 'completed', 'errors', 'cancelled'];
    fields.forEach(f => {
        const el = document.getElementById(f + '-count');
        if (el) el.textContent = counts[f] ?? 0;
    });
}

// --- Form submit ---

function initForm() {
    const form = document.getElementById('folder-form');
    if (!form) return;

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        const settings = getFormSettings();

        try {
            const resp = await fetch('/api/v1/jobs', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings),
            });
            const data = await resp.json();
            if (!resp.ok) {
                showStatus(data.error || 'Failed to create job', 'error');
                return;
            }
            showStatus(data.message, 'success');
            currentFilePage = 1;
            fileStatusFilter = '';
            fileSearch = '';
            const filterEl = document.getElementById('file-status-filter');
            const searchEl = document.getElementById('file-search');
            if (filterEl) filterEl.value = '';
            if (searchEl) searchEl.value = '';
            loadFiles();
            loadJobs();
        } catch (err) {
            showStatus('Error: ' + err, 'error');
        }
    });

    document.getElementById('image-profile')?.addEventListener('change', (e) => {
        applyImageProfileToForm(e.target.value);
    });

    document.getElementById('video-profile')?.addEventListener('change', (e) => {
        applyVideoProfileToForm(e.target.value);
    });

    document.getElementById('image-quality')?.addEventListener('input', (e) => {
        setVal('image-quality-val', e.target.value);
    });

    document.getElementById('video-crf')?.addEventListener('input', (e) => {
        setVal('video-crf-val', e.target.value);
    });

    document.getElementById('clear-completed-btn')?.addEventListener('click', async () => {
        if (!confirm('Clear all completed files from the database?')) return;
        const resp = await fetch('/api/v1/clear_completed', { method: 'POST' });
        const data = await resp.json();
        showStatus(data.message, 'success');
        loadFiles();
    });

    document.getElementById('cancel-queue-btn')?.addEventListener('click', async () => {
        if (!confirm(
            'Are you sure you want to cancel all pending and in-progress files? ' +
            'Files currently being processed will be stopped.'
        )) return;
        const resp = await fetch('/api/v1/cancel_queue', { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) {
            showStatus(data.error || 'Failed to cancel queue', 'error');
            return;
        }
        showStatus(data.message, 'warning');
        loadFiles();
        loadJobs();
    });

    document.getElementById('clear-history-btn')?.addEventListener('click', async () => {
        if (!confirm(
            'WARNING: This will stop all processing and permanently delete ALL records ' +
            'from the database. This cannot be undone. Continue?'
        )) return;
        const resp = await fetch('/api/v1/clear_history', { method: 'POST' });
        const data = await resp.json();
        if (!resp.ok) {
            showStatus(data.error || 'Failed to clear history', 'error');
            return;
        }
        showStatus(data.message, 'error');
        loadFiles();
        loadJobs();
    });

    document.getElementById('file-status-filter')?.addEventListener('change', (e) => {
        fileStatusFilter = e.target.value;
        currentFilePage = 1;
        loadFiles();
    });

    document.getElementById('file-search')?.addEventListener('input', (e) => {
        fileSearch = e.target.value;
        loadFiles();
    });

    document.getElementById('refresh-jobs')?.addEventListener('click', loadJobs);
}

// --- Socket.IO ---

function applyProgressUpdate(data) {
    const fileId = Number(data.file_id);
    data = { ...data, file_id: fileId };
    fileProgressCache.set(fileId, data);

    const fileElement = document.getElementById('file-' + fileId);
    const statusEl = document.getElementById('status-' + fileId);
    const progressFill = document.getElementById('progress-' + fileId);
    if (!fileElement || !statusEl || !progressFill) {
        return false;
    }

    const pct = data.percent != null ? data.percent : (data.status === 'completed' ? 100 : 0);

    fileElement.className = '';
    switch (data.status) {
        case 'processing':
            fileElement.classList.add('status-processing');
            statusEl.textContent = 'Status: Processing — ' + data.message + ` (${pct}%)`;
            progressFill.style.width = pct + '%';
            progressFill.className = 'progress-fill';
            break;
        case 'completed':
            fileElement.classList.add('status-completed');
            let msg = 'Status: Completed — ' + data.message;
            const sizeLabel = formatRatioLabel(data.input_size, data.output_size, data.compression_ratio);
            if (sizeLabel) msg += ` · ${sizeLabel}`;
            statusEl.textContent = msg;
            progressFill.style.width = '100%';
            progressFill.className = 'progress-fill complete';
            fileProgressCache.delete(fileId);
            break;
        case 'error':
            fileElement.classList.add('status-error');
            statusEl.textContent = 'Status: Error — ' + data.message;
            progressFill.style.width = '100%';
            progressFill.className = 'progress-fill error';
            fileProgressCache.delete(fileId);
            break;
        case 'cancelled':
            fileElement.classList.add('status-cancelled');
            statusEl.textContent = 'Status: Cancelled — ' + data.message;
            progressFill.style.width = '100%';
            progressFill.className = 'progress-fill cancelled';
            fileProgressCache.delete(fileId);
            break;
    }
    return true;
}

const TERMINAL_PROGRESS = new Set(['completed', 'error', 'cancelled']);

socket.on('progress_update', (data) => {
    const applied = applyProgressUpdate(data);
    if (!applied) {
        debounceRefreshFiles();
    }
    if (data.job_id && TERMINAL_PROGRESS.has(data.status)) {
        debounceRefreshJobs();
    }
});

socket.on('queue_cancelled', (data) => {
    showStatus(data.message, 'warning');
    loadFiles();
    loadJobs();
});

socket.on('history_cleared', (data) => {
    showStatus(data.message, 'error');
    loadFiles();
    loadJobs();
});

socket.on('queue_counts', updateQueueCounts);

socket.on('connect', () => setConnectionStatus('online'));
socket.on('disconnect', () => setConnectionStatus('offline'));
socket.on('connect_error', () => setConnectionStatus('offline'));
socket.on('connection_status', () => setConnectionStatus('online'));

// --- Init ---

document.addEventListener('DOMContentLoaded', () => {
    initForm();
    loadProfiles();
    loadFiles();
    loadJobs();
    if (document.getElementById('connection-indicator')) {
        setConnectionStatus(socket.connected ? 'online' : 'connecting');
    }
    socket.emit('request_queue_counts');
    setInterval(loadJobs, 30000);
});
