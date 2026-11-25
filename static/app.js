const get = id => document.getElementById(id);
const scope = get('scope');
const image = get('screen-image');
const notice = get('notice');
const controlToggle = get('control-toggle');
const channelButtons = [...document.querySelectorAll('[data-channel]')];
const encoders = [...document.querySelectorAll('.encoder')];

let instrument = null;
let channel = 1;
let view = 'screen';
let generation = 0;
let working = false;
let polling = false;
let nextPoll = 0;
let controlToken = '';

function message(text, error = false) {
  notice.textContent = text;
  notice.dataset.error = String(error);
}

function connection(text, status = '') {
  get('device-status').textContent = text;
  get('device-status').dataset.status = status;
}

async function request(path, options = {}) {
  const response = await fetch(path, {...options, cache: 'no-store'});
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    const failure = new Error(error.error || `HTTP ${response.status}`);
    failure.status = response.status;
    throw failure;
  }
  return response;
}

function endpoint(name) {
  return `api/${scope.value}/${name}`;
}

function numericText(value) {
  return String(Number(value.toPrecision(9)));
}

function values() {
  const selected = instrument.channels[channel - 1];
  return {
    'channel-scale': selected.scale, 'channel-position': selected.position,
    'time-scale': instrument.time_scale, 'time-position': instrument.time_position,
  };
}

function render() {
  const ready = Boolean(instrument && !working);
  const enabled = Boolean(controlToken);
  const canOperate = ready && enabled;
  scope.disabled = working;
  get('connect').disabled = working;
  document.querySelectorAll('[data-ready], [data-channel]').forEach(el => { el.disabled = !ready; });
  document.querySelectorAll('.controls [data-ready]').forEach(el => { el.disabled = !canOperate; });
  controlToggle.disabled = working || (!instrument && !enabled);
  controlToggle.textContent = enabled ? 'Disable control' : 'Enable control';
  get('control-state').textContent = enabled ? 'Control enabled' : 'Viewing only';
  get('control-state').dataset.enabled = String(enabled);
  encoders.forEach(encoder => {
    const knob = encoder.querySelector('.knob');
    knob.tabIndex = canOperate ? 0 : -1;
    knob.setAttribute('aria-disabled', String(!canOperate));
  });
  const csv = get('csv');
  if (ready) {
    csv.href = endpoint(`waveform.csv?channel=${channel}`);
    csv.download = `CH${channel}-waveform.csv`;
  } else {
    csv.removeAttribute('href');
  }
  csv.setAttribute('aria-disabled', String(!ready));
  get('capture').textContent = `Capture CH${channel}`;
  get('vertical-channel').textContent = `CH${channel}`;

  if (!instrument) {
    channelButtons.forEach(button => button.classList.remove('channel-on'));
    get('trigger-type').textContent = '—';
    return;
  }
  get('identity').textContent = `TEXIO ${instrument.model} · ${instrument.firmware}`;
  channelButtons.forEach(button => {
    const number = Number(button.dataset.channel);
    button.setAttribute('aria-pressed', String(channel === number));
    button.classList.toggle('channel-on', instrument.channels[number - 1].enabled);
  });
  get('channel-enable').checked = instrument.channels[channel - 1].enabled;
  const settings = values();
  for (const encoder of encoders) {
    const field = encoder.querySelector('[data-value]');
    if (document.activeElement !== field) {
      field.value = numericText(settings[encoder.dataset.setting]);
    }
  }
  const trigger = instrument.trigger;
  get('trigger-type').textContent = trigger.type;
  get('trigger-source').value = trigger.source;
  get('trigger-mode').value = trigger.mode === 'NORM' ? 'NORMAL' : trigger.mode;
  get('trigger-slope').value = trigger.slope || '';
  get('trigger-slope').disabled = !canOperate || trigger.type !== 'EDGE';
  get('trigger-edge').hidden = trigger.type === 'EDGE';
  if (document.activeElement !== get('trigger-level')) {
    get('trigger-level').value = numericText(trigger.level);
  }
}

function clearImage() {
  if (image.src.startsWith('blob:')) URL.revokeObjectURL(image.src);
  image.removeAttribute('src');
  image.hidden = true;
  get('placeholder').hidden = false;
}

async function readState() {
  instrument = await (await request(endpoint('state'))).json();
}

async function connect() {
  generation += 1;
  working = true;
  instrument = null;
  clearImage();
  clearWave();
  message('');
  connection('Connecting…');
  render();
  try {
    await readState();
    connection('Connected', 'ready');
    nextPoll = 0;
  } catch (error) {
    connection('Unavailable', 'error');
    message(error.message, true);
  } finally {
    working = false;
    render();
  }
  if (instrument && view === 'screen') refreshScreen();
}

async function refreshScreen() {
  if (!instrument || polling || working || view !== 'screen') return;
  const requestGeneration = generation;
  polling = true;
  try {
    const blob = await (await request(endpoint('screen'))).blob();
    if (requestGeneration !== generation) return;
    clearImage();
    image.src = URL.createObjectURL(blob);
    image.hidden = false;
    get('placeholder').hidden = true;
    connection('Connected', 'ready');
    nextPoll = Date.now() + 1500;
  } catch (error) {
    if (requestGeneration === generation) {
      connection('Display update failed', 'error');
      message(error.message, true);
      nextPoll = Date.now() + 6000;
    }
  } finally {
    polling = false;
  }
}

async function operate(action, value, target = channel) {
  if (working || !instrument || !controlToken) return;
  working = true;
  render();
  try {
    const result = await (await request(endpoint('control'), {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Oscillo-Session': controlToken},
      body: JSON.stringify({action, channel: target, value}),
    })).json();
    const label = action.replaceAll('-', ' ');
    const applied = result.value === null ? `${label.toUpperCase()} sent.` : `${label}: ${result.value}`;
    try {
      await readState();
      message(applied);
    } catch (error) {
      instrument = null;
      message(`${applied} Refresh to read the full settings: ${error.message}`, true);
      connection('Settings read failed', 'error');
    }
    if (document.activeElement?.matches('[data-value], #trigger-level')) {
      document.activeElement.blur();
    }
  } catch (error) {
    message(error.message, true);
    if (error.status === 403) {
      controlToken = '';
    } else {
      try { await readState(); }
      catch {
        instrument = null;
        connection('Unavailable', 'error');
      }
    }
  } finally {
    working = false;
    render();
  }
  refreshScreen();
}

function controlSession(enabled, token, keepalive = false) {
  return request('api/control-session', {
    method: 'POST', keepalive,
    headers: {'Content-Type': 'application/json', 'X-Oscillo-Session': token},
    body: JSON.stringify({enabled}),
  });
}

async function toggleControl() {
  if (controlToggle.disabled) return;
  const enabled = !controlToken;
  working = true;
  render();
  try {
    const session = await (await controlSession(enabled, controlToken)).json();
    controlToken = enabled ? session.token : '';
    message('');
  } catch (error) {
    message(`Could not ${enabled ? 'enable' : 'disable'} control: ${error.message}`, true);
  } finally {
    working = false;
    render();
  }
}

function step(setting, direction) {
  if (!instrument || working || !controlToken) return;
  const settings = values();
  const current = settings[setting];
  let next;
  if (setting.endsWith('-scale')) {
    const magnitude = 10 ** Math.floor(Math.log10(current));
    const ranges = [.1, .2, .5, 1, 2, 5, 10, 20].map(factor => magnitude * factor);
    next = direction > 0 ? ranges.find(v => v > current * 1.000001)
      : ranges.reverse().find(v => v < current * .999999);
  } else {
    const scale = settings[setting.replace('-position', '-scale')];
    next = current + direction * scale / 5;
  }
  if (next !== undefined) operate(setting, numericText(next));
}

function setView(next) {
  view = next;
  get('display-screen').hidden = next !== 'screen';
  get('display-wave').hidden = next !== 'wave';
  get('screen-tools').hidden = next !== 'screen';
  get('wave-tools').hidden = next !== 'wave';
  get('screen-tab').setAttribute('aria-pressed', String(next === 'screen'));
  get('wave-tab').setAttribute('aria-pressed', String(next === 'wave'));
  if (next === 'screen') refreshScreen();
}

function clearWave() {
  const canvas = get('waveform');
  canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
  get('wave-info').textContent = 'Capture samples from the selected channel.';
}

function drawWave(data) {
  const canvas = get('waveform');
  const context = canvas.getContext('2d');
  const left = 100;
  const top = 28;
  const width = canvas.width - left - 30;
  const height = canvas.height - top - 53;
  const points = data.points;
  const values = points.map(point => point[1]);
  const extent = Math.max(...values) - Math.min(...values);
  const margin = extent * .08 || Math.max(Math.abs(values[0]) * .05, 1e-6);
  const low = Math.min(...values) - margin;
  const high = Math.max(...values) + margin;
  const duration = Math.max(data.interval, (data.count - 1) * data.interval);

  context.clearRect(0, 0, canvas.width, canvas.height);
  context.strokeStyle = '#303a4c';
  context.fillStyle = '#a2afc2';
  context.font = '15px ui-monospace, monospace';
  for (let i = 0; i <= 5; i++) {
    const x = left + width * i / 5;
    const y = top + height * i / 5;
    context.beginPath();
    context.moveTo(x, top);
    context.lineTo(x, top + height);
    context.moveTo(left, y);
    context.lineTo(left + width, y);
    context.stroke();
    context.fillText(`${(high - (high - low) * i / 5).toPrecision(3)} ${data.unit}`, 6, y + 5);
    context.fillText((duration * i / 5).toPrecision(3), x - 15, top + height + 21);
  }
  context.fillText('Seconds from first sample', left, canvas.height - 7);
  context.strokeStyle = getComputedStyle(document.documentElement).getPropertyValue(`--ch${channel}`).trim();
  context.lineWidth = 1.5;
  context.beginPath();
  points.forEach(([time, value], index) => {
    const x = left + width * time / duration;
    const y = top + height * (high - value) / (high - low);
    if (index === 0) context.moveTo(x, y);
    else context.lineTo(x, y);
  });
  context.stroke();
  get('wave-info').textContent = `CH${channel} · ${data.count.toLocaleString()} samples · ${data.interval.toPrecision(4)} s/sample`;
}

async function capture() {
  if (working || !instrument) return;
  working = true;
  render();
  try {
    const data = await (await request(endpoint(`waveform?channel=${channel}`))).json();
    drawWave(data);
    message('');
  } catch (error) {
    message(error.message, true);
  } finally {
    working = false;
    render();
  }
}

for (const channelButton of channelButtons) {
  channelButton.addEventListener('click', () => {
    channel = Number(channelButton.dataset.channel);
    clearWave();
    render();
  });
}

for (const encoder of encoders) {
  const setting = encoder.dataset.setting;
  const input = encoder.querySelector('[data-value]');
  const knob = encoder.querySelector('.knob');
  encoder.querySelectorAll('[data-step]').forEach(button => {
    button.addEventListener('click', () => step(setting, Number(button.dataset.step)));
  });
  input.addEventListener('keydown', event => {
    if (event.key === 'Enter') operate(setting, input.value);
  });
  encoder.querySelector('[data-apply]').addEventListener('click', () => operate(setting, input.value));
  knob.addEventListener('wheel', event => {
    if (!instrument || working || !controlToken) return;
    event.preventDefault();
    step(setting, event.deltaY < 0 ? 1 : -1);
  }, {passive: false});
  knob.addEventListener('keydown', event => {
    if (!instrument || working || !controlToken) return;
    if (event.key === 'ArrowUp' || event.key === 'ArrowDown') {
      event.preventDefault();
      step(setting, event.key === 'ArrowUp' ? 1 : -1);
    }
  });
}

for (const button of document.querySelectorAll('[data-acquire]')) {
  button.addEventListener('click', () => operate(button.dataset.acquire));
}
for (const name of ['trigger-source', 'trigger-slope', 'trigger-mode']) {
  const input = get(name);
  input.addEventListener('change', () => operate(name, input.value));
}
get('trigger-level').addEventListener('keydown', event => {
  if (event.key === 'Enter') operate('trigger-level', event.target.value);
});
get('apply-trigger-level').addEventListener('click', () => operate('trigger-level', get('trigger-level').value));
get('trigger-edge').addEventListener('click', () => operate('trigger-edge'));
get('channel-enable').addEventListener('change', event => {
  operate('channel-display', event.target.checked ? 'ON' : 'OFF');
});

scope.addEventListener('change', connect);
controlToggle.addEventListener('click', toggleControl);
window.addEventListener('pagehide', () => {
  if (!controlToken) return;
  controlSession(false, controlToken, true).catch(() => {});
  controlToken = '';
  render();
});
get('connect').addEventListener('click', connect);
get('refresh').addEventListener('click', connect);
get('screen-tab').addEventListener('click', () => setView('screen'));
get('wave-tab').addEventListener('click', () => setView('wave'));
get('capture').addEventListener('click', capture);
get('live').addEventListener('change', event => {
  if (event.target.checked) refreshScreen();
});

setInterval(() => {
  if (!document.hidden && get('live').checked && Date.now() >= nextPoll) refreshScreen();
}, 500);

async function start() {
  try {
    const devices = await (await request('api/scopes')).json();
    for (const device of devices) {
      scope.add(new Option(`Oscilloscope ${device.id} · ${device.address}`, device.id));
    }
    await connect();
  } catch (error) {
    message(error.message, true);
  }
}

start();
