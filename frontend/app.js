/**
 * AutoTube - Frontend Application
 * API 통신, WebSocket 연결, UI 상태 관리
 */

const API_BASE = window.location.origin;
let currentJobId = null;
let ws = null;
let pollInterval = null;

// ═══════════════════════════════════════
// 메인 생성 함수
// ═══════════════════════════════════════

async function startGeneration() {
    const urlInput = document.getElementById('urlInput');
    const url = urlInput.value.trim();

    if (!url) {
        showToast('❌ URL을 입력해주세요');
        urlInput.focus();
        return;
    }

    if (!url.startsWith('http://') && !url.startsWith('https://')) {
        showToast('❌ 올바른 URL을 입력해주세요 (http:// 또는 https://)');
        urlInput.focus();
        return;
    }

    // UI 상태 전환
    const btn = document.getElementById('generateBtn');
    btn.disabled = true;
    btn.querySelector('.btn-text').textContent = '처리 중...';

    // 옵션 수집
    const resolution = document.getElementById('optResolution').value.split('x');
    const payload = {
        url: url,
        language: document.getElementById('optLanguage').value,
        gemini_model: document.getElementById('optModel').value,
        tts_voice: document.getElementById('optVoice').value,
        tts_speed: 1.0,
        video_width: parseInt(resolution[0]),
        video_height: parseInt(resolution[1]),
        use_flow: document.getElementById('optFlow').checked,
        veo_quality: document.getElementById('optVeoQuality').value,
    };

    try {
        const resp = await fetch(`${API_BASE}/api/create`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });

        if (!resp.ok) {
            const error = await resp.json();
            throw new Error(error.detail || '서버 오류');
        }

        const data = await resp.json();
        currentJobId = data.job_id;

        // UI 전환
        showProgressUI();
        connectWebSocket(currentJobId);
        startPolling(currentJobId);

    } catch (err) {
        showError(err.message);
        btn.disabled = false;
        btn.querySelector('.btn-text').textContent = '생성 시작';
    }
}

// ═══════════════════════════════════════
// WebSocket 실시간 연결
// ═══════════════════════════════════════

function connectWebSocket(jobId) {
    const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${wsProtocol}//${window.location.host}/ws/${jobId}`;

    try {
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            console.log('🔌 WebSocket 연결됨');
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            handleWSMessage(data);
        };

        ws.onclose = () => {
            console.log('🔌 WebSocket 연결 해제');
        };

        ws.onerror = () => {
            console.warn('⚠️ WebSocket 연결 실패, 폴링 모드로 전환');
        };
    } catch (e) {
        console.warn('⚠️ WebSocket 미지원, 폴링 모드');
    }
}

function handleWSMessage(data) {
    if (data.type === 'progress') {
        updateProgress(data);
    } else if (data.type === 'complete') {
        clearPolling();
        fetchCreditStatus(); // Update credit after completion
        if (data.status === 'success') {
            showResult(data.result);
        } else {
            showError(data.result?.error || '알 수 없는 오류');
        }
    } else if (data.type === 'error') {
        clearPolling();
        showError(data.error);
    }
}

// ═══════════════════════════════════════
// 폴링 (WebSocket 폴백)
// ═══════════════════════════════════════

function startPolling(jobId) {
    pollInterval = setInterval(async () => {
        try {
            const resp = await fetch(`${API_BASE}/api/status/${jobId}`);
            const data = await resp.json();

            // 진행 상황 업데이트
            updateProgress({
                step: data.current_step,
                message: data.progress_message,
                steps_completed: data.steps_completed,
            });

            // 완료 처리
            if (data.status === 'success') {
                clearPolling();
                fetchCreditStatus(); // Update credit after completion
                showResult(data.result);
            } else if (data.status === 'error') {
                clearPolling();
                showError(data.error);
            }
        } catch (e) {
            console.warn('폴링 오류:', e);
        }
    }, 2000);
}

function clearPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
    if (ws) {
        ws.close();
        ws = null;
    }
}

// ═══════════════════════════════════════
// UI 업데이트
// ═══════════════════════════════════════

function updateProgress(data) {
    const { step, message, steps_completed } = data;

    // 메시지 업데이트
    if (message) {
        document.getElementById('progressMessage').textContent = message;
    }

    // 단계 상태 업데이트
    const allSteps = [
        'article_extraction',
        'script_generation',
        'tts_narration',
        'image_generation',
        'thumbnail_creation',
        'subtitle_generation',
        'video_assembly',
    ];

    allSteps.forEach(s => {
        const el = document.getElementById(`step-${s}`);
        if (!el) return;

        el.classList.remove('active', 'completed');

        if (steps_completed && steps_completed.includes(s)) {
            el.classList.add('completed');
        } else if (s === step) {
            el.classList.add('active');
        }
    });
}

function showProgressUI() {
    document.getElementById('inputSection').classList.add('hidden');
    document.getElementById('progressSection').classList.remove('hidden');
    document.getElementById('resultSection').classList.add('hidden');
    document.getElementById('errorSection').classList.add('hidden');

    // 모든 단계 초기화
    document.querySelectorAll('.pipeline-step').forEach(el => {
        el.classList.remove('active', 'completed');
    });
}

function showResult(result) {
    document.getElementById('progressSection').classList.add('hidden');
    document.getElementById('resultSection').classList.remove('hidden');

    const projectId = result.project_id;
    const metadata = result.metadata || {};

    // 영상 프리뷰
    const videoPlayer = document.getElementById('videoPlayer');
    if (result.video_path) {
        videoPlayer.src = `/output/${projectId}/final_video.mp4`;
    }

    // 썸네일
    const thumbImg = document.getElementById('thumbnailImg');
    if (result.thumbnail_path) {
        thumbImg.src = `/output/${projectId}/thumbnail.png`;
    }

    // 메타데이터
    document.getElementById('ytTitle').textContent = metadata.youtube_title || '';
    document.getElementById('ytDescription').textContent = metadata.youtube_description || '';

    // 해시태그
    const hashtagsEl = document.getElementById('ytHashtags');
    hashtagsEl.innerHTML = '';
    (metadata.hashtags || []).forEach(tag => {
        const chip = document.createElement('span');
        chip.className = 'hashtag-chip';
        chip.textContent = tag;
        chip.onclick = () => copyText(chip);
        hashtagsEl.appendChild(chip);
    });

    // 태그
    const tagsEl = document.getElementById('ytTags');
    tagsEl.innerHTML = '';
    (metadata.tags || []).forEach(tag => {
        const chip = document.createElement('span');
        chip.className = 'tag-chip';
        chip.textContent = tag;
        tagsEl.appendChild(chip);
    });

    // 다운로드 링크
    document.getElementById('downloadVideo').href = `/output/${projectId}/final_video.mp4`;
    document.getElementById('downloadThumb').href = `/output/${projectId}/thumbnail.png`;
    document.getElementById('downloadSrt').href = `/output/${projectId}/subtitles.srt`;

    // 소요 시간
    document.getElementById('resultTime').textContent =
        `총 소요 시간: ${result.duration_sec || '?'}초`;

    showToast('🎉 영상이 완성되었습니다!');
}

function showError(message) {
    document.getElementById('progressSection').classList.add('hidden');
    document.getElementById('errorSection').classList.remove('hidden');
    document.getElementById('errorMessage').textContent = message || '알 수 없는 오류가 발생했습니다.';

    // 버튼 복원
    const btn = document.getElementById('generateBtn');
    btn.disabled = false;
    btn.querySelector('.btn-text').textContent = '생성 시작';
}

function resetUI() {
    clearPolling();

    document.getElementById('inputSection').classList.remove('hidden');
    document.getElementById('progressSection').classList.add('hidden');
    document.getElementById('resultSection').classList.add('hidden');
    document.getElementById('errorSection').classList.add('hidden');

    const btn = document.getElementById('generateBtn');
    btn.disabled = false;
    btn.querySelector('.btn-text').textContent = '생성 시작';

    document.getElementById('urlInput').value = '';
    document.getElementById('urlInput').focus();
}

// ═══════════════════════════════════════
// 유틸리티
// ═══════════════════════════════════════

function toggleOptions() {
    const panel = document.getElementById('optionsPanel');
    const arrow = document.getElementById('toggleArrow');
    panel.classList.toggle('open');
    arrow.classList.toggle('open');
}

function copyText(element) {
    const text = element.textContent;
    navigator.clipboard.writeText(text).then(() => {
        showToast('📋 복사되었습니다!');
    }).catch(() => {
        // 폴백
        const ta = document.createElement('textarea');
        ta.value = text;
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showToast('📋 복사되었습니다!');
    });
}

function copyAllMeta() {
    const title = document.getElementById('ytTitle').textContent;
    const description = document.getElementById('ytDescription').textContent;
    const hashtags = Array.from(document.querySelectorAll('.hashtag-chip'))
        .map(el => el.textContent).join(' ');
    const tags = Array.from(document.querySelectorAll('.tag-chip'))
        .map(el => el.textContent).join(', ');

    const text = `제목: ${title}\n\n설명:\n${description}\n\n해시태그: ${hashtags}\n\n태그: ${tags}`;

    navigator.clipboard.writeText(text).then(() => {
        showToast('📋 전체 메타데이터가 복사되었습니다!');
    });
}

let toastTimer = null;
function showToast(message) {
    const toast = document.getElementById('toast');
    toast.textContent = message;
    toast.classList.remove('hidden');
    toast.classList.add('show');

    if (toastTimer) clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
        toast.classList.remove('show');
        setTimeout(() => toast.classList.add('hidden'), 300);
    }, 3000);
}

// 크레딧 조회
async function fetchCreditStatus() {
    try {
        const resp = await fetch(`${API_BASE}/api/credit/status`);
        if (resp.ok) {
            const data = await resp.json();
            const valSpan = document.getElementById('creditValue');
            if (valSpan) {
                valSpan.textContent = Math.floor(data.remaining).toLocaleString() + ' (예상: ' + data.estimates.basic_videos_remaining + '건)';
                if (data.status === 'warning') valSpan.style.color = 'var(--accent-yellow)';
                if (data.status === 'critical') valSpan.style.color = 'var(--accent-red)';
            }
        }
    } catch (e) {
        console.warn('크레딧 조회 실패:', e);
    }
}

// Enter 키로 생성 시작 + Flow 토글 핸들러
document.addEventListener('DOMContentLoaded', () => {
    fetchCreditStatus();

    document.getElementById('urlInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            startGeneration();
        }
    });

    // Flow 토글 → Veo Quality 활성화
    const flowCheckbox = document.getElementById('optFlow');
    const veoSelect = document.getElementById('optVeoQuality');
    if (flowCheckbox && veoSelect) {
        flowCheckbox.addEventListener('change', () => {
            veoSelect.disabled = !flowCheckbox.checked;
        });
    }
});

// YouTube 업로드 승인 모달
function showUploadPreview() {
    if (!currentJobId) {
        showToast('❌ 업로드할 프로젝트가 없습니다');
        return;
    }
    const title = document.getElementById('ytTitle').textContent;
    document.getElementById('modalTitle').textContent = title || 'AutoTube Video';
    document.getElementById('uploadModal').classList.add('show');
}

function closeUploadPreview() {
    document.getElementById('uploadModal').classList.remove('show');
}

async function confirmUploadToYoutube() {
    closeUploadPreview();

    const btn = document.getElementById('uploadYtBtn');
    btn.disabled = true;
    btn.innerHTML = '<span>⏳</span> 업로드 중...';
    
    const privacy = document.getElementById('modalPrivacy').value || 'private';

    try {
        const resp = await fetch(`${API_BASE}/api/upload/${currentJobId}?privacy=${privacy}`, {
            method: 'POST',
        });

        const data = await resp.json();

        if (resp.ok && data.status === 'success') {
            showToast(`✅ YouTube 업로드 완료! ${data.url}`);
            btn.innerHTML = '<span>✅</span> 업로드 완료';
            btn.onclick = () => window.open(data.url, '_blank');
        } else {
            const errMsg = data.detail || data.error || 'YouTube 업로드 실패';
            showToast(`❌ ${errMsg}`);
            btn.disabled = false;
            btn.innerHTML = '<span>📤</span> YouTube 업로드 다시 시도';
        }
    } catch (err) {
        showToast(`❌ ${err.message}`);
        btn.disabled = false;
        btn.innerHTML = '<span>📤</span> YouTube 업로드 다시 시도';
    }
}
