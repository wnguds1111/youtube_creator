/**
 * AutoTube - Frontend Application
 * API 통신, WebSocket 연결, UI 상태 관리
 */

let API_BASE = window.location.origin;
if (API_BASE === 'file://' || API_BASE.includes('5500') || API_BASE.includes('5173')) {
    API_BASE = 'http://localhost:8500';
}
let currentJobId = null;
let ws = null;
let pollInterval = null;
const TOKEN_KEY = 'autotube_token';
let currentUser = null;
let currentContentData = null;

// ═══════════════════════════════════════
// Auth & History (마이페이지)
// ═══════════════════════════════════════

async function checkAuth() {
    const token = localStorage.getItem(TOKEN_KEY);
    if (!token) {
        showLoginSection();
        return;
    }
    
    try {
        const resp = await fetch(`${API_BASE}/api/auth/me`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        if (resp.ok) {
            const data = await resp.json();
            currentUser = data.username;
            
            document.getElementById('userName').textContent = data.name || currentUser;
            const avatar = document.getElementById('userAvatar');
            if (data.picture) {
                avatar.src = data.picture;
                avatar.style.display = 'block';
            } else {
                avatar.style.display = 'none';
            }
            
            showInputSection();
        } else {
            localStorage.removeItem(TOKEN_KEY);
            showLoginSection();
        }
    } catch (e) {
        showLoginSection();
    }
}

async function login() {
    const id = document.getElementById('loginId').value.trim();
    const pw = document.getElementById('loginPw').value;
    if (!id || !pw) return showToast('아이디와 비밀번호를 입력해주세요');

    try {
        const resp = await fetch(`${API_BASE}/api/auth/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: id, password: pw })
        });
        const data = await resp.json();
        if (resp.ok) {
            localStorage.setItem(TOKEN_KEY, data.token);
            checkAuth();
            showToast(`✅ 환영합니다!`);
        } else {
            showToast(`❌ ${data.detail}`);
        }
    } catch (e) {
        showToast('로그인 실패');
    }
}

async function register() {
    const id = document.getElementById('loginId').value.trim();
    const pw = document.getElementById('loginPw').value;
    if (!id || !pw) return showToast('아이디와 비밀번호를 입력해주세요');

    try {
        const resp = await fetch(`${API_BASE}/api/auth/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username: id, password: pw })
        });
        const data = await resp.json();
        if (resp.ok) {
            showToast('✅ 가입 성공! 이제 로그인 해주세요.');
        } else {
            showToast(`❌ ${data.detail}`);
        }
    } catch (e) {
        showToast('가입 실패');
    }
}

// 구글 로그인 콜백
async function handleGoogleLogin(response) {
    if (!response.credential) {
        showToast('구글 로그인 실패');
        return;
    }
    
    try {
        const resp = await fetch(`${API_BASE}/api/auth/google`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token: response.credential })
        });
        const data = await resp.json();
        if (resp.ok) {
            localStorage.setItem(TOKEN_KEY, data.token);
            checkAuth();
            showToast(`✅ ${data.name}님 환영합니다!`);
        } else {
            showToast(`❌ ${data.detail}`);
        }
    } catch (e) {
        showToast('구글 로그인 중 오류가 발생했습니다.');
    }
}

function logout() {
    const token = localStorage.getItem(TOKEN_KEY);
    if (token) {
        fetch(`${API_BASE}/api/auth/logout`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${token}` }
        }).catch(()=>{});
    }
    localStorage.removeItem(TOKEN_KEY);
    currentUser = null;
    showLoginSection();
}

function hideAllSections() {
    ['loginSection', 'inputSection', 'progressSection', 'resultSection', 'errorSection', 'historySection', 'uploadSection'].forEach(id => {
        document.getElementById(id).classList.add('hidden');
    });
}

function showLoginSection() {
    hideAllSections();
    document.getElementById('loginSection').classList.remove('hidden');
    document.getElementById('authNav').classList.add('hidden');
}

function showInputSection() {
    hideAllSections();
    document.getElementById('inputSection').classList.remove('hidden');
    document.getElementById('authNav').classList.remove('hidden');
}

function showHistorySection() {
    hideAllSections();
    document.getElementById('historySection').classList.remove('hidden');
    document.getElementById('authNav').classList.remove('hidden');
    fetchHistory();
}

async function fetchHistory() {
    const listEl = document.getElementById('historyList');
    listEl.innerHTML = '<div style="text-align:center; padding:20px; color:var(--colors-slate);">로딩 중...</div>';
    
    try {
        const resp = await fetch(`${API_BASE}/api/projects`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem(TOKEN_KEY)}` }
        });
        const projects = await resp.json();
        
        if (projects.length === 0) {
            listEl.innerHTML = '<div style="text-align:center; padding:20px; color:var(--colors-slate);">아직 생성된 영상이 없습니다.</div>';
            return;
        }

        listEl.innerHTML = '';
        projects.forEach(p => {
            const date = new Date(p.created_at).toLocaleString('ko-KR');
            let ytStatusHtml = '<span class="badge-success" style="background:var(--colors-surface-soft); color:var(--colors-slate);">업로드 전</span>';
            if (p.youtube_status === 'success') {
                const url = p.youtube_url || '#';
                ytStatusHtml = `<span class="badge-success">YouTube 완료</span> <a href="${url}" target="_blank" style="color:var(--colors-primary); font-size:12px; margin-left: 8px;">영상 보기</a>`;
            }
            
            const thumbUrl = p.has_thumbnail ? `/output/${p.project_id}/thumbnail.png` : '';
            
            listEl.innerHTML += `
                <div class="history-card" onclick="loadProject('${p.project_id}')">
                    ${thumbUrl ? `<img src="${thumbUrl}" class="history-thumb">` : `<div class="history-thumb" style="display:flex; align-items:center; justify-content:center; font-size:24px;">🎬</div>`}
                    <div class="history-info">
                        <div class="body-md-bold" style="margin-bottom: 4px;">${p.youtube_title || '제목 없음 (AutoTube Video)'}</div>
                        <div class="body-sm" style="color:var(--colors-slate); margin-bottom: 8px;">등록일: ${date}</div>
                        <div>${ytStatusHtml}</div>
                    </div>
                </div>
            `;
        });
    } catch (e) {
        listEl.innerHTML = '<div style="text-align:center; padding:20px; color:var(--colors-critical);">히스토리를 불러올 수 없습니다.</div>';
    }
}

async function loadProject(projectId) {
    // 임시로 상태 체크 API를 통해 프로젝트 결과를 가져옴
    currentJobId = projectId;
    try {
        // 백엔드에 단일 프로젝트 조회 API가 없으므로 상태 조회로 대체 (기존 폴링용)
        const resp = await fetch(`${API_BASE}/api/status/${projectId}`);
        const data = await resp.json();
        if (data.status === 'success') {
            showResult(data.result);
        } else {
            // 혹은 projects 목록에서 찾아서 구성 (간단히 처리)
            showToast('과거 프로젝트는 현재 목록에서 확인 가능합니다.');
        }
    } catch (e) {
        showToast('과거 프로젝트를 불러올 수 없습니다.');
    }
}

// ═══════════════════════════════════════
// 파이프라인
// ═══════════════════════════════════════

async function startPrepare() {
    const urlInput = document.getElementById('urlInput');
    const url = urlInput.value.trim();

    if (!url) {
        showToast('❌ URL을 입력해주세요');
        urlInput.focus();
        return;
    }

    const btn = document.getElementById('prepareBtn');
    btn.disabled = true;
    btn.textContent = '추출 중...';

    const payload = {
        url: url,
        language: 'ko', // 일단 한국어 고정, 필요시 UI 추가
        gemini_model: document.getElementById('optModel').value,
        tts_voice: document.getElementById('optVoice').value,
        tts_speed: 1.0,
        video_width: 1080,
        video_height: 1920,
        target_duration: 30,
        gemini_api_key: document.getElementById('optApiKey').value.trim() || undefined
    };

    try {
        const resp = await fetch(`${API_BASE}/api/prepare`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem(TOKEN_KEY)}`
            },
            body: JSON.stringify(payload),
        });

        if (!resp.ok) {
            const error = await resp.json();
            throw new Error(error.detail || '서버 오류');
        }

        const data = await resp.json();
        currentJobId = data.project_id;
        currentContentData = data.content;
        showUploadUI(data.content);

    } catch (err) {
        showError(err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '대본 및 프롬프트 추출하기';
    }
}

async function startAutoGenerate() {
    const urlInput = document.getElementById('urlInput');
    const url = urlInput.value.trim();

    if (!url) {
        showToast('❌ URL을 입력해주세요');
        urlInput.focus();
        return;
    }

    const btn = document.getElementById('prepareBtn');
    btn.disabled = true;
    btn.textContent = '영상 제작 중... (시간이 소요될 수 있습니다)';

    const payload = {
        url: url,
        language: 'ko',
        gemini_model: document.getElementById('optModel').value,
        tts_voice: document.getElementById('optVoice').value,
        tts_speed: 1.0,
        video_width: 1080,
        video_height: 1920,
        target_duration: 30,
        gemini_api_key: document.getElementById('optApiKey').value.trim() || undefined,
        omni_template: document.getElementById('optOmniTemplate').value || undefined
    };

    showProgressUI();

    try {
        const resp = await fetch(`${API_BASE}/api/auto-generate`, {
            method: 'POST',
            headers: { 
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem(TOKEN_KEY)}`
            },
            body: JSON.stringify(payload),
        });

        if (!resp.ok) {
            const error = await resp.json();
            throw new Error(error.detail || '서버 오류');
        }

        const data = await resp.json();
        currentJobId = data.job_id;
        
        connectWebSocket(currentJobId);
        startPolling(currentJobId);

    } catch (err) {
        showError(err.message);
    } finally {
        btn.disabled = false;
        btn.textContent = '원클릭 자동 영상 제작';
    }
}

function showUploadUI(content) {
    document.getElementById('inputSection').classList.add('hidden');
    document.getElementById('uploadSection').classList.remove('hidden');
    
    const container = document.getElementById('scenesContainer');
    container.innerHTML = '';
    
    if (!content.scenes || content.scenes.length === 0) {
        container.innerHTML = '<p class="body-md">생성된 장면이 없습니다.</p>';
        return;
    }
    
    // 유튜브 정보 미리보기 세팅
    document.getElementById('previewTitle').textContent = content.youtube_title || '제목 없음';
    document.getElementById('previewDescription').textContent = content.youtube_description || '설명 없음';
    document.getElementById('previewHashtags').textContent = (content.hashtags || []).join(' ') + ' ' + (content.tags || []).join(' ');
    
    content.scenes.forEach((scene, index) => {
        const div = document.createElement('div');
        div.className = 'scene-card';
        div.innerHTML = `
            <div class="scene-header">
                <span class="scene-num">${index + 1}</span>
            </div>
            <p class="body-sm" style="margin-bottom: var(--spacing-sm); color: var(--colors-slate);"><strong>나레이션:</strong> ${scene.narration}</p>
            <div class="scene-prompt">
                ${scene.visual_prompt || "프롬프트 없음"}
            </div>
            <button class="button-ghost" style="padding: 4px 12px; font-size: 12px; margin-bottom: var(--spacing-sm);" onclick="navigator.clipboard.writeText('${(scene.visual_prompt||"").replace(/'/g, "\\'")}')">프롬프트 복사</button>
            <label class="body-sm-bold" style="display: block;">
                영상 첨부 (.mp4):
                <input type="file" accept="video/mp4" class="text-input vid-input" style="height: auto; padding: 8px; margin-top: 4px;">
            </label>
        `;
        container.appendChild(div);
    });
}

async function startAssemble() {
    const scenesContainer = document.getElementById('scenesContainer');
    const fileInputs = scenesContainer.querySelectorAll('input.vid-input');
    
    const formData = new FormData();
    let fileCount = 0;
    
    for (const input of fileInputs) {
        if (input.files.length > 0) {
            formData.append('files', input.files[0]);
            fileCount++;
        } else {
            showToast('❌ 모든 장면의 영상을 첨부해주세요.');
            return;
        }
    }

    document.getElementById('uploadSection').classList.add('hidden');
    showProgressUI();
    
    try {
        const resp = await fetch(`${API_BASE}/api/assemble/${currentJobId}`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${localStorage.getItem(TOKEN_KEY)}`
            },
            body: formData,
        });

        if (!resp.ok) {
            const error = await resp.json();
            throw new Error(error.detail || '서버 오류');
        }

        connectWebSocket(currentJobId);
        startPolling(currentJobId);

    } catch (err) {
        showError(err.message);
    }
}

// ═══════════════════════════════════════
// 상태 추적
// ═══════════════════════════════════════

function connectWebSocket(jobId) {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/${jobId}`;

    try {
        ws = new WebSocket(wsUrl);
        ws.onopen = () => console.log('🔌 WebSocket 연결됨');
        ws.onmessage = (event) => handleWSMessage(JSON.parse(event.data));
        ws.onclose = () => console.log('🔌 WebSocket 연결 해제');
        ws.onerror = () => console.warn('⚠️ WebSocket 오류');
    } catch (e) {
        console.warn('⚠️ WebSocket 미지원, 폴링 모드');
    }
}

function handleWSMessage(data) {
    if (data.type === 'progress') updateProgress(data);
    else if (data.type === 'complete') {
        clearPolling();
        if (data.status === 'success') showResult(data.result);
        else showError(data.result?.error || '알 수 없는 오류');
    } else if (data.type === 'error') {
        clearPolling();
        showError(data.error);
    }
}

function startPolling(jobId) {
    pollInterval = setInterval(async () => {
        try {
            const resp = await fetch(`${API_BASE}/api/status/${jobId}`);
            const data = await resp.json();
            updateProgress({
                step: data.current_step,
                message: data.progress_message,
                steps_completed: data.steps_completed,
            });
            if (data.status === 'success') {
                clearPolling();
                showResult(data.result);
            } else if (data.status === 'error') {
                clearPolling();
                showError(data.error);
            }
        } catch (e) {}
    }, 2000);
}

function clearPolling() {
    if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
    if (ws) { ws.close(); ws = null; }
}

function showProgressUI() {
    document.getElementById('inputSection').classList.add('hidden');
    document.getElementById('progressSection').classList.remove('hidden');
    document.getElementById('resultSection').classList.add('hidden');
    document.getElementById('errorSection').classList.add('hidden');
    document.querySelectorAll('.pipeline-step').forEach(el => el.classList.remove('active', 'completed'));
}

function updateProgress(data) {
    const { step, message, steps_completed } = data;
    if (message) document.getElementById('progressMessage').textContent = message;

    const allSteps = ['prepare', 'video_generation', 'tts_narration', 'video_assembly'];
    let completedCount = 0;
    allSteps.forEach(s => {
        const el = document.getElementById(`step-${s}`);
        if (!el) return;
        el.classList.remove('active', 'completed');
        
        let isCompleted = steps_completed && steps_completed.includes(s);
        let isActive = s === step;

        // subtitle_generation is part of tts_narration step in UI
        if (s === 'tts_narration') {
            if (steps_completed && steps_completed.includes('subtitle_generation')) isCompleted = true;
            if (step === 'subtitle_generation') isActive = true;
        }

        if (isCompleted) {
            el.classList.add('completed');
            completedCount++;
        }
        else if (isActive) {
            el.classList.add('active');
            completedCount += 0.5;
        }
    });
    
    const percentage = Math.min(100, Math.floor((completedCount / allSteps.length) * 100));
    const pctEl = document.getElementById('progressPercent');
    if (pctEl) pctEl.textContent = `${percentage}%`;
}

function showResult(result) {
    document.getElementById('progressSection').classList.add('hidden');
    document.getElementById('resultSection').classList.remove('hidden');

    const projectId = result.project_id;
    currentJobId = projectId;
    const metadata = result.metadata || currentContentData || {};

    const videoPlayer = document.getElementById('videoPlayer');
    if (result.video_path) videoPlayer.src = `/output/${projectId}/final_video.mp4`;

    document.getElementById('ytTitle').textContent = metadata.youtube_title || '';
    document.getElementById('ytDescription').textContent = metadata.youtube_description || '';
    document.getElementById('ytHashtags').textContent = (metadata.hashtags || []).join(' ') + ' ' + (metadata.tags || []).join(' ');

    document.getElementById('downloadVideo').href = `/output/${projectId}/final_video.mp4`;
    document.getElementById('resultTime').textContent = `소요 시간: ${result.duration_sec || '?'}초`;
}

function showError(message) {
    document.getElementById('progressSection').classList.add('hidden');
    document.getElementById('errorSection').classList.remove('hidden');
    document.getElementById('errorMessage').textContent = message || '알 수 없는 오류가 발생했습니다.';
}

function resetUI() {
    clearPolling();
    showInputSection();
    document.getElementById('urlInput').value = '';
    document.getElementById('urlInput').focus();
}

// ═══════════════════════════════════════
// 토스트 및 업로드
// ═══════════════════════════════════════

function showToast(message) {
    // 간단한 alert 대신 토스트 (없으면 alert로 대체)
    alert(message);
}

function showUploadPreview() {
    if (!currentJobId) { showToast('❌ 업로드할 프로젝트가 없습니다'); return; }
    document.getElementById('modalTitle').textContent = document.getElementById('ytTitle').textContent;
    document.getElementById('uploadModal').classList.remove('hidden');
}

function closeUploadPreview() {
    document.getElementById('uploadModal').classList.add('hidden');
}

async function confirmUploadToYoutube() {
    closeUploadPreview();
    const privacy = document.getElementById('modalPrivacy').value || 'private';

    try {
        const resp = await fetch(`${API_BASE}/api/upload/${currentJobId}?privacy=${privacy}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${localStorage.getItem(TOKEN_KEY)}` }
        });
        const data = await resp.json();

        if (resp.ok && data.status === 'success') {
            showToast(`✅ YouTube 업로드 완료!`);
            window.open(data.url, '_blank');
        } else {
            showToast(`❌ ${data.detail || data.error || '업로드 실패'}`);
        }
    } catch (err) {
        showToast(`❌ ${err.message}`);
    }
}

document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
});
