// M1, шаг 2: только запрос манифеста и отображение. Скачивание/установка/
// запуск Minecraft подключатся в play() на следующих шагах плана — сейчас
// кнопка "Играть" разблокируется после успешного refresh(), но ничего не
// скачивает.
const { invoke } = window.__TAURI__.core;

const els = {
  panelUrl: document.getElementById('panel-url'),
  serverId: document.getElementById('server-id'),
  username: document.getElementById('username'),
  refreshBtn: document.getElementById('refresh-btn'),
  playBtn: document.getElementById('play-btn'),
  status: document.getElementById('status'),
  card: document.getElementById('server-card'),
  name: document.getElementById('srv-name'),
  ip: document.getElementById('srv-ip'),
  version: document.getElementById('srv-version'),
};

function setStatus(text, isError) {
  els.status.textContent = text;
  els.status.classList.toggle('error', Boolean(isError));
}

async function refresh() {
  setStatus('Запрашиваю манифест…');
  els.card.style.display = 'none';
  els.playBtn.disabled = true;

  const serverId = Number(els.serverId.value);
  if (!Number.isInteger(serverId) || serverId <= 0) {
    setStatus('Некорректный ID сервера', true);
    return;
  }

  try {
    const manifest = await invoke('get_manifest', {
      panelUrl: els.panelUrl.value.trim(),
      serverId,
    });
    els.name.textContent = manifest.name;
    els.ip.textContent = manifest.ip || '—';
    els.version.textContent = manifest.mc_version +
      (manifest.modloader && manifest.modloader !== 'vanilla' ? ' · ' + manifest.modloader : '');
    els.card.style.display = 'flex';
    setStatus('Готово');
    els.playBtn.disabled = false;
  } catch (e) {
    setStatus('Ошибка: ' + e, true);
  }
}

function play() {
  setStatus('Скачивание и запуск Minecraft — ещё не реализовано (следующий шаг плана).');
}

els.refreshBtn.addEventListener('click', refresh);
els.playBtn.addEventListener('click', play);

refresh();
