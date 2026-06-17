import network
import socket
import time
import json
import os
from machine import I2C, Pin
import TEA5767

# --- 1. Ініціалізація радіо та живлення ---
RADIO_POWER_PIN = Pin(12, Pin.OUT)
RADIO_POWER_PIN.value(1)

i2c = I2C(0, sda=Pin(4), scl=Pin(5), freq=400000)
radio = TEA5767.Radio(i2c, stereo=True, freq=87.5)
current_freq = 87.5
is_muted = False
MUTE_FREQ = 76.0 

# Змінні для неблокуючого сканування
is_scanning = False
scan_current_freq = 87.5
scan_raw_map = []

# Конфігурація пошуку
CONF_SCAN_STEP = 0.1
CONF_SIGNAL_THRESHOLD = 5

# --- 2. Налаштування пам'яті (JSON) ---
PRESETS_FILE = "radio_settings.json"

def load_settings():
    global CONF_SCAN_STEP, CONF_SIGNAL_THRESHOLD
    default_settings = {
        "all_stations": {},
        "favorites": {str(i): "" for i in range(1, 21)},
        "scan_step": 0.1,          
        "signal_threshold": 5      
    }
    
    if PRESETS_FILE in os.listdir():
        with open(PRESETS_FILE, "r", encoding="utf-8") as f:
            try:
                data = json.load(f)
                updated = False
                for key, val in default_settings.items():
                    if key not in data:
                        data[key] = val
                        updated = True
                if updated:
                    save_settings(data)
                
                CONF_SCAN_STEP = float(data.get("scan_step", 0.1))
                CONF_SIGNAL_THRESHOLD = int(data.get("signal_threshold", 5))
                return data
            except:
                pass
    save_settings(default_settings)
    CONF_SCAN_STEP = 0.1
    CONF_SIGNAL_THRESHOLD = 5
    return default_settings

def save_settings(data):
    with open(PRESETS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f)

settings = load_settings()

# --- 3. URL Декодер ---
def url_decode(s):
    res = bytearray()
    i = 0
    while i < len(s):
        if s[i] == '%':
            try:
                hex_val = s[i+1:i+3]
                res.append(int(hex_val, 16))
                i += 3
            except:
                res.append(ord('%'))
                i += 1
        elif s[i] == '+':
            res.append(ord(' '))
            i += 1
        else:
            res.append(ord(s[i]))
            i += 1
    try: 
        return res.decode('utf-8')
    except: 
        return s

# --- 4. Функція запуску неблокуючого сканування ---
def start_async_scan():
    global settings, is_scanning, scan_current_freq, scan_raw_map
    is_scanning = True
    scan_current_freq = 87.5
    scan_raw_map = []
    
    clean_stations = {}
    fav_frequencies = set(settings["favorites"].values())
    for f_str, name in settings["all_stations"].items():
        if f_str in fav_frequencies:
            clean_stations[f_str] = name
    settings["all_stations"] = clean_stations
    save_settings(settings)

# --- 5. Підключення до Wi-Fi ---
WIFI_SSID = 'назва мережі ВайФай'
WIFI_PASS = 'пароль до ВайФай'

wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect(WIFI_SSID, WIFI_PASS)

print("Підключення до Wi-Fi...", end="")
wifi_timeout = 30  
while not wlan.isconnected() and wifi_timeout > 0:
    print(".", end="")
    time.sleep(0.5)
    wifi_timeout -= 1

if wlan.isconnected():
    ip_address = wlan.ifconfig()[0]
    print(f"\nWi-Fi підключено! Адреса: http://{ip_address}")
else:
    ip_address = "127.0.0.1"
    print("\nНе вдалося підключитися до Wi-Fi. Автономний режим.")

# --- 6. Генерація HTML сторінки ---
def get_html():
    global settings, is_muted, current_freq, CONF_SCAN_STEP, CONF_SIGNAL_THRESHOLD
    f_current_str = f"{current_freq:.1f}"
    station_title = settings["all_stations"].get(f_current_str, "Ручне налаштування")
    
    try:
        radio.read()
        sig_level = radio.signal_adc_level
        stereo_mode = "STEREO" if radio.is_stereo else "MONO"
    except:
        sig_level = 0
        stereo_mode = "UNKNOWN"
        
    if is_muted: station_title = "[ВИМКНЕНО ЗВУК] " + station_title

    fav_grid_html = ""
    for i in range(1, 21):
        idx_str = str(i)
        fav_f = settings["favorites"].get(idx_str, "")
        if fav_f:
            try: formatted_fav_check = f"{float(fav_f):.1f}"
            except: formatted_fav_check = fav_f
            name = settings["all_stations"].get(formatted_fav_check, "FM Станція")
            btn_class = "fav-btn active" if formatted_fav_check == f_current_str and not is_muted else "fav-btn saved"
            
            fav_grid_html += f"""
            <button onclick="playFreq('{formatted_fav_check}')" id="fav-btn-{idx_str}" class="{btn_class}" data-freq="{formatted_fav_check}">
                <b>{idx_str} <span style="font-size:11px; font-weight:normal; opacity:0.85;">({formatted_fav_check})</span></b>
                <small style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 90px;">{name}</small>
            </button>"""
        else:
            fav_grid_html += f'<div class="fav-btn empty"><b>{idx_str}</b><small>—</small></div>'

    table_rows_html = ""
    row_counter = 1
    for f_str in sorted(settings["all_stations"].keys(), key=float):
        name = settings["all_stations"][f_str]
        current_slot = "0"
        for slot, freq in settings["favorites"].items():
            try: formatted_fav_check = f"{float(freq):.1f}"
            except: formatted_fav_check = freq
            if formatted_fav_check == f_str:
                current_slot = slot
                break
                
        select_options = f'<option value="0" {"selected" if current_slot=="0" else ""}>Немає</option>'
        for i in range(1, 21):
            select_options += f'<option value="{i}" {"selected" if current_slot==str(i) else ""}>Кнопка {i}</option>'
            
        is_playing = "background:#d4edda; font-weight:bold;" if f_str == f_current_str and not is_muted else ""
        
        table_rows_html += f"""
        <tr id="row-{f_str}" style="{is_playing}">
            <td style="color: #666; font-weight: bold; text-align: center;">{row_counter}</td>
            <td style="text-align: center;"><span style="font-size:16px; font-weight:bold;">{f_str} МГц</span></td>
            <td style="text-align: center;"><button onclick="playFreq('{f_str}')" class="action-btn" style="background:#007bff;">▶ Грати</button></td>
            <form action="/update_station" method="get">
                <input type="hidden" name="f" value="{f_str}">
                <td><input type="text" name="name" value="{name}" style="width:100%; box-sizing: border-box; padding:6px; border:1px solid #ccc; border-radius:4px;"></td>
                <td style="text-align: center;"><select name="slot" style="padding:5px; border-radius:4px; border:1px solid #ccc;">{select_options}</select></td>
                <td style="text-align: center;"><button type="submit" class="action-btn" style="background:#28a745;">💾</button></td>
            </form>
            <td style="text-align: center;"><a href="/delete?f={f_str}" class="action-btn" style="background:#dc3545;">❌</a></td>
        </tr>
        """
        row_counter += 1

    manual_row_html = f"""
    <tr id="manual-row" style="display:none; background: #fff3cd;">
        <td style="color: #666; font-weight: bold; text-align: center;">{row_counter}</td>
        <td style="text-align: center; vertical-align: middle;">
            <div style="display: inline-flex; align-items: center; gap: 4px; justify-content: center; width: 100%;">
                <form id="manual-form" action="/add_manual" method="get" style="margin:0; display:inline-block;">
                    <input type="number" name="freq" step="0.1" min="87.5" max="108.0" placeholder="104.6" style="width:64px; padding:5px; font-weight:bold; text-align:center; border:1px solid #ccc; border-radius:4px;" required>
                </form>
                <span style="font-weight:bold; font-size:14px; white-space: nowrap;">МГц</span>
            </div>
        </td>
        <td style="text-align: center; color: #666; font-style: italic; font-size: 13px;">Нова хвиля</td>
        <td><span style="color: #856404; font-style: italic; font-size: 13px; padding-left: 5px;">Назва згенерується автоматично</span></td>
        <td style="text-align: center; color: #999; font-size: 13px;">—</td>
        <td style="text-align: center;"><button type="submit" form="manual-form" class="action-btn" style="background:#28a745;">💾</button></td>
        <td style="text-align: center;"><button onclick="document.getElementById('manual-row').style.display='none'" class="action-btn" style="background:#6c757d;">❌</button></td>
    </tr>
    """
    table_rows_html += manual_row_html

    if row_counter == 1 and settings["all_stations"] == {}:
        table_rows_html = '<tr><td colspan="7" style="text-align:center; color:#999; padding:20px;">База даних порожня. Налаштуйте параметри пошуку та запустіть сканування ефіру.</td></tr>' + manual_row_html

    mute_btn_bg = "#dc3545" if is_muted else "#ffc107"
    mute_btn_color = "white" if is_muted else "#212529"
    mute_btn_text = "🔔 Звук Увімкн" if is_muted else "🔇 Звук Вимкн (Mute)"
    disp_freq_text = "MUTED" if is_muted else f"{current_freq:.1f}"

    return f"""<!DOCTYPE html>
    <html lang="uk">
    <head>
        <meta charset="utf-8">
        <title>ESP32 FM Radio Console Workspace</title>
        <style>
            body {{ font-family: 'Segoe UI', Arial, sans-serif; background-color: #f0f3f5; margin: 0; padding: 20px; color: #333; }}
            .pc-container {{ display: flex; max-width: 1350px; margin: 0 auto; gap: 20px; }}
            .left-panel {{ flex: 1; background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); min-width: 410px; height: fit-content; }}
            .right-panel {{ flex: 1.8; background: white; padding: 20px; border-radius: 12px; box-shadow: 0 4px 12px rgba(0,0,0,0.05); }}
            .display {{ background-color: #111; color: #00ff66; padding: 20px; border-radius: 8px; font-family: monospace; text-align: center; }}
            .display .freq {{ font-size: 46px; font-weight: bold; color: #fff; margin: 5px 0; }}
            .display .title {{ font-size: 18px; color: #00e1ff; font-weight: bold; }}
            .main-ctrls {{ display: flex; gap: 10px; margin: 20px 0; }}
            .btn {{ flex: 1; padding: 12px; font-size: 15px; color: white; background-color: #4f5d75; border: none; border-radius: 6px; cursor: pointer; text-decoration: none; font-weight: bold; text-align: center; }}
            .btn-mute {{ background-color: {mute_btn_bg}; color: {mute_btn_color}; }}
            .fav-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; }}
            
            .fav-btn {{ display: flex; flex-direction: column; justify-content: center; align-items: center; background: #fff; border: 1px solid #ccc; border-radius: 6px; height: 55px; text-decoration: none; color: #333; text-align: center; font-size: 12px; width:100%; cursor:pointer; box-sizing: border-box; }}
            .fav-btn.saved {{ background: #e2f4e9 !important; border-color: #a3cfbb !important; color: #0f5132 !important; }}
            .fav-btn.saved:hover {{ background: #d1ebd9 !important; }}
            .fav-btn.active {{ background: #28a745 !important; color: white !important; border-color: #218838 !important; font-weight: bold !important; box-shadow: 0 0 8px rgba(40,167,69,0.5); }}
            .fav-btn.empty {{ color: #aaa; background: #fafafa; border-style: dashed; cursor: default; }}
            
            table {{ width: 100%; border-collapse: collapse; }}
            th, td {{ padding: 10px 6px; border-bottom: 1px solid #ddd; font-size: 14px; word-break: break-all; }}
            th {{ background-color: #f8f9fa; color: #495057; font-weight: bold; }}
            
            .action-btn {{ padding: 6px 0; width: 100%; max-width: 80px; color: white; text-decoration: none; border-radius: 4px; border: none; cursor: pointer; display: inline-block; font-weight: bold; text-align: center; box-sizing: border-box; }}
            .add-manual-btn {{ background: #28a745; color: white; padding: 10px 15px; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; margin-top: 15px; display: inline-block; text-decoration: none; }}
            .scan-status {{ display: none; background: #d1ecf1; color: #0c5460; padding: 15px; border-radius: 6px; margin-bottom: 15px; font-weight: bold; text-align: center; }}
            
            .scan-bar-container {{ display: flex; gap: 8px; margin-top: 15px; }}
            .btn-scan-main {{ flex: 1; background-color: #17a2b8; color: white; padding: 12px; font-size: 15px; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; }}
            .btn-gear-toggle {{ width: 48px; background-color: #6c757d; color: white; border: none; border-radius: 6px; font-size: 20px; cursor: pointer; display: flex; align-items: center; justify-content: center; }}
            
            .config-dropdown {{ display: none; background: #ffffff; border: 1px solid #ced4da; border-radius: 8px; padding: 15px; margin-top: 10px; box-shadow: 0 4px 8px rgba(0,0,0,0.05); }}
            .config-title {{ font-size: 14px; font-weight: bold; margin: 0 0 10px 0; color: #495057; border-bottom: 1px solid #eee; padding-bottom: 5px; }}
            .form-row {{ display: flex; gap: 10px; margin-bottom: 10px; }}
            .form-field {{ flex: 1; }}
            .form-field label {{ display: block; font-size: 12px; font-weight: bold; color: #495057; margin-bottom: 4px; }}
            .form-field select {{ width: 100%; padding: 6px; border: 1px solid #ced4da; border-radius: 4px; font-size: 13px; box-sizing: border-box; background-color: #fff; }}
            .config-actions {{ display: flex; gap: 8px; margin-top: 12px; }}
            .cfg-btn {{ flex: 1; padding: 8px; border: none; border-radius: 4px; font-size: 13px; font-weight: bold; cursor: pointer; text-align: center; text-decoration: none; }}
        </style>
        <script>
            function playFreq(f) {{
                fetch('/api/set?f=' + f)
                .then(r => r.json())
                .then(data => {{
                    let playedFreq = data.freq; 
                    document.getElementById('disp-title').innerText = data.title;
                    document.getElementById('disp-freq').innerHTML = playedFreq + ' <span style="font-size:20px; color:#666;">МГц</span>';
                    document.getElementById('disp-sig').innerText = 'Сигнал: ' + data.signal + '/15';
                    document.getElementById('disp-stereo').innerText = data.stereo;
                    
                    document.querySelectorAll('tbody tr').forEach(tr => tr.style.background = '');
                    document.querySelectorAll('tbody tr').forEach(tr => tr.style.fontWeight = 'normal');
                    let activeRow = document.getElementById('row-' + playedFreq);
                    if(activeRow) {{
                        activeRow.style.background = '#d4edda';
                        activeRow.style.fontWeight = 'bold';
                    }}
                    
                    document.querySelectorAll('.fav-btn').forEach(btn => {{
                        let btnFreq = btn.getAttribute('data-freq');
                        if (btnFreq) {{
                            if (btnFreq === playedFreq) {{
                                btn.className = 'fav-btn active';
                            }} else {{
                                btn.className = 'fav-btn saved';
                            }}
                        }}
                    }});
                }});
            }}

            function startScan() {{
                document.getElementById('scan-status').style.display = 'block';
                fetch('/api/start_scan').then(() => {{
                    let checkInterval = setInterval(() => {{
                        fetch('/api/scan_status').then(r => r.json()).then(data => {{
                            if(!data.scanning) {{
                                clearInterval(checkInterval);
                                location.reload();
                            }}
                        }});
                    }}, 800);
                }});
            }}
            function showManualRow() {{
                let r = document.getElementById('manual-row');
                r.style.display = 'table-row';
                r.scrollIntoView({{ behavior: 'smooth', block: 'center' }});
            }}
            function toggleConfig() {{
                let box = document.getElementById('configBox');
                box.style.display = (box.style.display === 'none' || box.style.display === '') ? 'block' : 'none';
            }}
        </script>
    </head>
    <body>
        <div class="pc-container">
            <div class="left-panel">
                <div class="display">
                    <div id="disp-title" class="title">{station_title}</div>
                    <div id="disp-freq" class="freq">{disp_freq_text} <span style="font-size:20px; color:#666;">МГц</span></div>
                    <div style="display:flex; justify-content:space-between; color:#666; font-size:11px; margin-top:5px;">
                        <span id="disp-sig">Сигнал: {sig_level}/15</span>
                        <span id="disp-stereo">{stereo_mode}</span>
                    </div>
                </div>
                <div class="main-ctrls">
                    <button onclick="playFreq('prev')" class="btn">◀ Попередня</button>
                    <a href="/mute" class="btn btn-mute">{mute_btn_text}</a>
                    <button onclick="playFreq('next')" class="btn">Наступна ▶</button>
                </div>
                <div style="display:flex; justify-content:space-between; align-items:center; background:#e2e6ea; padding:8px; border-radius:6px; margin-bottom:15px; font-size:14px;">
                    <b>Крок частоти:</b>
                    <div>
                        <button onclick="playFreq('down')" class="btn" style="padding:4px 10px;">-0.1 МГц</button>
                        <button onclick="playFreq('up')" class="btn" style="padding:4px 10px;">+0.1 МГц</button>
                    </div>
                </div>
                <div class="fav-grid">{fav_grid_html}</div>
                
                <div class="scan-bar-container">
                    <button onclick="startScan()" class="btn-scan-main">🔍 Розумне сканування ефіру</button>
                    <button onclick="toggleConfig()" class="btn-gear-toggle" title="Налаштування пошуку">⚙️</button>
                </div>
                
                <div id="configBox" class="config-dropdown">
                    <div class="config-title">⚙️ Параметри пошуку станцій</div>
                    <form action="/save_search_config" method="get">
                        <div class="form-row">
                            <div class="form-field">
                                <label>Крок частоти:</label>
                                <select name="scan_step">
                                    <option value="0.05" {"selected" if CONF_SCAN_STEP==0.05 else ""}>0.05 МГц</option>
                                    <option value="0.1" {"selected" if CONF_SCAN_STEP==0.1 else ""}>0.1 МГц</option>
                                    <option value="0.2" {"selected" if CONF_SCAN_STEP==0.2 else ""}>0.2 МГц</option>
                                </select>
                            </div>
                            <div class="form-field">
                                <label>Поріг сигналу:</label>
                                <select name="signal_threshold">
                                    <option value="3" {"selected" if CONF_SIGNAL_THRESHOLD==3 else ""}>3 (Шумні)</option>
                                    <option value="5" {"selected" if CONF_SIGNAL_THRESHOLD==5 else ""}>5 (Норма)</option>
                                    <option value="7" {"selected" if CONF_SIGNAL_THRESHOLD==7 else ""}>7 (Чисті)</option>
                                    <option value="10" {"selected" if CONF_SIGNAL_THRESHOLD==10 else ""}>10 (Потужні)</option>
                                </select>
                            </div>
                        </div>
                        <div class="config-actions">
                            <a href="/reset_search_config" class="cfg-btn" style="background:#e2e6ea; color:#495057;">Скинути</a>
                            <input type="submit" value="Застосувати" class="cfg-btn" style="background:#28a745; color:white;">
                        </div>
                    </form>
                </div>

                <a href="/factory_reset" class="btn" style="background-color:#dc3545; display:block; margin-top:20px; font-size:12px; padding:6px;">🧨 Повне скидання всієї пам'яті</a>
            </div>
            
            <div class="right-panel">
                <div id="scan-status" class="scan-status">⏳ Йде інтелектуальний аналіз ефіру (крок {CONF_SCAN_STEP} МГц, поріг чутливості {CONF_SIGNAL_THRESHOLD})... Зачекайте...</div>
                <h3 style="margin-top:0;">📋 Збережена база даних радіостанцій (Всього: {row_counter - 1 if row_counter > 1 else 0})</h3>
                <table>
                    <thead>
                        <tr>
                            <th style="width:5%;">№</th>
                            <th style="width:18%;">Частота</th>
                            <th style="width:12%;">Слухати</th>
                            <th style="width:33%;">Назва станції</th>
                            <th style="width:16%;">Швидка кнопка</th>
                            <th style="width:8%;">Зберегти</th>
                            <th style="width:8%;">Видалити</th>
                        </tr>
                    </thead>
                    <tbody>{table_rows_html}</tbody>
                </table>
                <button onclick="showManualRow()" class="add-manual-btn">➕ Додати станцію вручну</button>
            </div>
        </div>
    </body>
    </html>
    """

# --- 7. Запуск веб-сервера ---
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
s.bind(('', 80))
s.listen(2)
s.settimeout(0.02)

print("Мережевий інтерфейс повністю готовий!")

# --- 8. Головний цикл з асинхронним кроковим скануванням ---
while True:
    if is_scanning:
        if scan_current_freq <= 108.0:
            radio.set_frequency(scan_current_freq)
            time.sleep_ms(30)
            radio.read()
            if radio.signal_adc_level >= CONF_SIGNAL_THRESHOLD:
                scan_raw_map.append((scan_current_freq, radio.signal_adc_level))
            
            scan_current_freq = round(scan_current_freq + CONF_SCAN_STEP, 2)
        else:
            verified_peaks = []
            for item in scan_raw_map:
                f_curr, adc_curr = item
                is_peak = True
                for neighbor in scan_raw_map:
                    f_nei, adc_nei = neighbor
                    if abs(f_nei - f_curr) <= 0.5:
                        if adc_nei > adc_curr:
                            is_peak = False
                            break
                        elif adc_nei == adc_curr and f_nei < f_curr:
                            is_peak = False
                            break
                if is_peak and (87.5 <= f_curr <= 108.0):
                    verified_peaks.append(f_curr)

            for p_freq in verified_peaks:
                f_str = f"{p_freq:.1f}"
                if f_str not in settings["all_stations"]:
                    settings["all_stations"][f_str] = f"Станція {f_str}"
            
            save_settings(settings)
            radio.set_frequency(current_freq)
            is_scanning = False

    try:
        try:
            conn, addr = s.accept()
        except OSError:
            continue

        request = b""
        try:
            conn.settimeout(0.4)
            request = conn.recv(2048)
        except OSError: 
            pass
            
        req_str = request.decode('utf-8', 'ignore')
        if not req_str or "GET" not in req_str:
            conn.close()
            continue
            
        if "favicon.ico" in req_str:
            conn.send(b"HTTP/1.1 404 Not Found\r\n\r\n")
            conn.close()
            continue

        redirect = False
        
        if "GET /api/set?" in req_str or "GET /api/set " in req_str:
            try:
                target = "next"
                if "f=" in req_str:
                    start = req_str.find("f=") + 2
                    end = req_str.find(" ", start)
                    if end == -1: end = len(req_str)
                    target = req_str[start:end].split('&')[0].strip()

                saved_freqs = sorted([float(x) for x in settings["all_stations"].keys()])
                
                if target == "next":
                    if saved_freqs: current_freq = min((x for x in saved_freqs if x > current_freq), default=saved_freqs[0])
                elif target == "prev":
                    if saved_freqs: current_freq = max((x for x in saved_freqs if x < current_freq), default=saved_freqs[-1])
                elif target == "up":
                    current_freq = min(round(current_freq + 0.1, 1), 108.0)
                elif target == "down":
                    current_freq = max(round(current_freq - 0.1, 1), 87.5)
                else:
                    current_freq = float(target)

                is_muted = False
                RADIO_POWER_PIN.value(1)
                radio.set_frequency(current_freq)
                
                radio.read()
                f_str = f"{current_freq:.1f}"
                title = settings["all_stations"].get(f_str, "Ручне налаштування")
                stereo = "STEREO" if radio.is_stereo else "MONO"
                
                res_dict = {
                    "freq": f_str,
                    "title": title,
                    "signal": radio.signal_adc_level,
                    "stereo": stereo,
                    "fav_map": settings["favorites"]
                }
                conn.send(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n" + json.dumps(res_dict))
            except:
                conn.send(b"HTTP/1.1 400 Bad Request\r\n\r\n")
            conn.close()
            continue
        
        elif "GET /api/start_scan" in req_str:
            start_async_scan()
            conn.send(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n{\"status\":\"started\"}")
            conn.close()
            continue
            
        elif "GET /api/scan_status" in req_str:
            res_json = "{\"scanning\": true}" if is_scanning else "{\"scanning\": false}"
            conn.send(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\n\r\n" + res_json)
            conn.close()
            continue

        if "GET /save_search_config?" in req_str:
            try:
                step_start = req_str.find("scan_step=") + 10
                step_end = req_str.find("&", step_start)
                step_val = float(req_str[step_start:step_end])
                
                th_start = req_str.find("signal_threshold=", step_end) + 17
                th_end = req_str.find(" ", th_start)
                th_val = int(req_str[th_start:th_end].split('&')[0])
                
                settings["scan_step"] = step_val
                settings["signal_threshold"] = th_val
                save_settings(settings)
                CONF_SCAN_STEP = step_val
                CONF_SIGNAL_THRESHOLD = th_val
            except: pass
            redirect = True

        elif "GET /reset_search_config" in req_str:
            settings["scan_step"] = 0.1
            settings["signal_threshold"] = 5
            save_settings(settings)
            CONF_SCAN_STEP = 0.1
            CONF_SIGNAL_THRESHOLD = 5
            redirect = True
            
        elif "GET /mute" in req_str:
            is_muted = not is_muted
            if is_muted:
                RADIO_POWER_PIN.value(0)
                radio.set_frequency(MUTE_FREQ)
            else:
                RADIO_POWER_PIN.value(1)
                time.sleep_ms(50)
                radio.set_frequency(current_freq)
            redirect = True

        elif "GET /update_station?" in req_str:
            try:
                f_start = req_str.find("f=") + 2
                f_end = req_str.find("&", f_start)
                f_str = req_str[f_start:f_end]
                
                n_start = req_str.find("name=", f_end) + 5
                n_end = req_str.find("&", n_start)
                name = url_decode(req_str[n_start:n_end])
                
                slot_start = req_str.find("slot=", n_end) + 5
                slot_end = req_str.find(" ", slot_start)
                slot_str = req_str[slot_start:slot_end].split('&')[0].strip()
                
                f_str_formatted = f"{float(f_str):.1f}"
                settings["all_stations"][f_str_formatted] = name
                
                if slot_str != "0":
                    for k, v in settings["favorites"].items():
                        if v == f_str_formatted: settings["favorites"][k] = ""
                    settings["favorites"][slot_str] = f_str_formatted
                else:
                    for k, v in settings["favorites"].items():
                        if v == f_str_formatted: settings["favorites"][k] = ""
                save_settings(settings)
            except: pass
            redirect = True

        elif "GET /add_manual?" in req_str:
            try:
                f_start = req_str.find("freq=") + 5
                f_end = req_str.find(" ", f_start)
                raw_freq = float(req_str[f_start:f_end].split('&')[0])
                f_str = f"{raw_freq:.1f}"
                settings["all_stations"][f_str] = f"Станція {f_str}"
                save_settings(settings)
            except: pass
            redirect = True

        elif "GET /delete?" in req_str:
            try:
                start = req_str.find("f=") + 2
                end = req_str.find(" ", start)
                f_str = req_str[start:end].split('&')[0]
                f_str_formatted = f"{float(f_str):.1f}"
                if f_str_formatted in settings["all_stations"]:
                    del settings["all_stations"][f_str_formatted]
                for k, v in settings["favorites"].items():
                    if v == f_str_formatted: settings["favorites"][k] = ""
                save_settings(settings)
            except: pass
            redirect = True

        elif "GET /factory_reset" in req_str:
            if PRESETS_FILE in os.listdir(): os.remove(PRESETS_FILE)
            settings = load_settings() 
            current_freq = 87.5
            is_muted = False
            RADIO_POWER_PIN.value(1)
            radio.set_frequency(current_freq)
            redirect = True

        if redirect:
            conn.send(b"HTTP/1.1 303 See Other\r\nLocation: /\r\n\r\n")
        else:
            response_bytes = get_html().encode('utf-8')
            conn.send(b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n\r\n")
            
            pos = 0
            while pos < len(response_bytes):
                chunk = response_bytes[pos:pos+1024]
                conn.sendall(chunk)
                pos += 1024
                
        conn.close()
        
    except OSError: 
        pass
