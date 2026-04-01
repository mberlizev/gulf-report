# UAE Air Defence Dashboard — Recipe for Claude

## Context
This is a self-reference script for Claude to recreate the UAE/Iran 2026 
air defence Telegram Mini App dashboard from scratch.

---

## 1. DATA SOURCES

### Primary (check in order)
1. **MOD UAE** — @modgovae on X/Twitter (daily statements)
2. **Gulf News** — gulfnews.com (confirms MOD figures)
3. **The National** — thenationalnews.com (narrative context)
4. **Khaleej Times** — khaleejtimes.com (daily tallies)
5. **Wikipedia** — "2026 Iranian strikes on the United Arab Emirates"
   - Most complete running log, updated multiple times per day
   - Use as cross-reference, not primary

### Secondary (context/comparison)
- Al Jazeera live tracker (regional casualties)
- CSIS Firepower Strike Tracker (Ukraine comparison data)
- OHCHR UN (Ukraine civilian casualties)
- WhichSchoolAdvisor (school/IB exam news)
- Iran International (Iranian visa/diplomatic news)

### Search queries that work well
```
UAE MOD "March 31 2026" missiles drones intercepted
UAE air defence today April 2026 casualties latest
"gulf_defense" site:khaleejtimes.com
```

---

## 2. DATA STRUCTURE

### Daily arrays (index 0 = Feb 28, each +1 day)
```javascript
var DAYS = ['28ф','1м','2м',...,'31м','1апр*'];  // date labels
var DR   = [209, 311, 148, ...];  // drones per day
var BM   = [137,  20,  28, ...];  // ballistic missiles per day
var CM   = [  0,   2,   0, ...];  // cruise missiles per day
var TOT  = DR.map((d,i) => d + BM[i] + CM[i]);

// Cumulative casualties (MOD checkpoints)
var CK = [1,1,3,...,11,11];   // killed (running total)
var CI = [7,12,58,...,188,188]; // injured (running total)
```

### Cumulative totals (as of last confirmed MOD statement)
- BM total = sum of BM array
- DR total = sum of DR array  
- CM total = sum of CM array
- Grand total = BM + DR + CM

### Key stats to display
| Stat | Value | Color |
|------|-------|-------|
| Total launches | sum | white |
| Ballistic | BM total | #2d7dd2 blue |
| Cruise | CM total | #c47c0a amber |
| Drones | DR total | #1fa06a green |
| Intercept % | ~97% | green |
| Killed | 11 | #d63a3a red |
| Injured | 188 | #c47c0a amber |
| Launches/death | total/11 | green |

---

## 3. COMPARISON DATA (static, update rarely)

```javascript
// Killed per million population
// UAE 2026: 8 civilian / 9.7M = 0.82
// Moscow 2024-25: <10 / 12.5M = <0.8
// Kyiv 2024: ~35 / 2.95M = 11.9
// Russia 2025: ~400 / 144M = 2.8
// Ukraine 2025: 2514 / 38M = 66  (OHCHR verified)
// Israel Oct 7 2023: ~1200 / 9.5M = 126
// London Blitz 1940: ~30000 / 8.6M = 3488

// Intercept rates
// UAE drones: ~95%
// UAE ballistic: ~97% (THAAD + PAC-3)
// Kyiv drones: ~95%
// Ukraine drones 2025: ~85%
// Ukraine ballistic 2025: ~18% (Iskander/Kinzhal)
// Moscow drones: ~93%
```

---

## 4. NEWS TAB CONTENT (update with each refresh)

### Always include (if current):
1. **School/IB status** — distance learning deadline, exam changes
   - IB May 2026: CANCELLED → NECM (as of March 30)
   - GCSE/A Level: still on plan (May-June 2026)
   - Distance learning: until April 17 (review weekly)
   
2. **Ceasefire/negotiations** — Trump deadlines, Pakistan channel
   - April 6 deadline for Iran energy strikes
   - 15-point US plan vs Iran 5-point counter
   
3. **New attack types** — any escalation in tactics
   - Cruise missile spike (15→19, March 31)
   - Tanker attack at Dubai Port (March 31)
   
4. **Visa/residency** — Iranian visa cancellations
   - UAE cancelled Iranian residence visas abroad incl. Golden Visa
   - Iran cancelled 1200 Emirati visas in retaliation
   
5. **Aviation/travel** — for Phuket planning
   - DXB/AUH operational with unscheduled closures
   - Wait for April 6 deadline before booking

### News item template:
```html
<div class="news">
  <div class="ntag t-r">TAG · URGENCY</div>
  <div class="ntit">Title</div>
  <div class="nbod">Body text. Specific facts. Actionable.</div>
  <div class="nmeta">Date · Source</div>
</div>
```
Tag colors: `t-r` red (urgent), `t-a` amber (important), `t-b` blue (info)

---

## 5. HTML FILE STRUCTURE

```
uae_telegram.html
├── <head>
│   ├── Telegram WebApp SDK: https://telegram.org/js/telegram-web-app.js
│   ├── Chart.js CDN: https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js
│   └── CSS with Telegram theme variables (--tg-theme-bg-color etc.)
├── Header (sticky): title + badge "День N"
├── Tabs (3): Цифры МО | Театры | Тренды
├── Tab 0: Stats grid + 3 charts
├── Tab 1: Comparison log chart + table
├── Tab 2: Deadline banner + trend block + 4-5 news cards
└── <script>
    ├── Telegram.WebApp.ready() + expand()
    ├── Data arrays
    ├── Chart.js chart definitions
    └── sw(i) tab switcher
```

### Critical CSS variables (Telegram theming)
```css
:root {
  --bg:  var(--tg-theme-bg-color, #1c1c1e);
  --sec: var(--tg-theme-secondary-bg-color, #2c2c2e);
  --txt: var(--tg-theme-text-color, #ffffff);
  --sub: var(--tg-theme-hint-color, #8e8e93);
  --lnk: var(--tg-theme-link-color, #2d7dd2);
}
```

### Chart.js compatibility rules (ES5 safe)
```javascript
// NEVER use spread operators: {...obj} or [...arr]
// Use Object.assign({}, obj) instead
// Use function() {} not arrow functions () => {}
// Use var not const/let in chart definitions
// All canvas heights must be fixed px (not aspect ratio)
```

---

## 6. CHART DEFINITIONS

### c0 — Daily stacked bar (main chart)
- Type: bar, stacked
- Datasets: DR (green), BM (blue), CM (amber)  
- Last 2 days highlighted with 50% opacity (pending/recent)
- Height: 190px

### c1 — Weekly totals
- Type: bar
- Labels: ['нед1','нед2','нед3','нед4','нед5']
- Colors: [red, amber, blue, green, amber-faded]
- Height: 145px

### c2 — Casualties + volume
- Type: mixed (bar + 2 lines)
- Bar: cumulative total launches (right axis)
- Line 1: CI (injured, amber)
- Line 2: CK×10 (killed ×10, red dashed)
- Height: 180px

### c3 — Per million log scale
- Type: bar, logarithmic Y
- Labels: short country names (NO emoji flags)
- Log axis labels: [0.1, 1, 10, 100, 1000, 10000]
- Height: 195px

### c4 — Launches per killed
- Type: bar
- Labels: ['ОАЭ','Москва','Киев','Украина','Россия']
- Height: 150px

### c5 — Intercept %
- Type: bar, Y max 100, callback adds '%'
- Labels: 6 items, maxRotation:0, autoSkip:false
- Height: 150px

---

## 7. UPDATE PROCEDURE

When user says "обнови данные":

1. **Search**: `UAE MOD missiles drones [today's date] intercepted`
2. **Extract**: daily BM, CM, DR counts from MOD statement
3. **Update arrays**: append new day to DR[], BM[], CM[], CK[], CI[]
4. **Update badge**: increment day counter
5. **Update subtitle**: new date + source
6. **Update stats**: recalculate totals
7. **Update news**: search for latest school/ceasefire/visa/aviation news
8. **Rebuild file**: write complete new HTML

### Python patch script pattern:
```python
with open('uae_telegram.html', 'r') as f:
    html = f.read()

# Replace array values exactly
html = html.replace(
    'var DR = [209,...,old_last];',
    'var DR = [209,...,new_last];'
)
# etc.

with open('uae_telegram.html', 'w') as f:
    f.write(html)
```

---

## 8. DEPLOYMENT

```
Repository: github.com/mberlizev/gulf-report
Branch: main
File: uae_telegram.html
Live URL: https://mberlizev.github.io/gulf-report/uae_telegram.html

Telegram Mini App:
- Bot: @anna_berg_bot
- Short name: gulf_defense
- Direct link: t.me/anna_berg_bot/gulf_defense
```

---

## 9. ASSETS

```
uae_tg_cover.png  — 640×360 cover image for BotFather
uae_tg_demo.gif   — 640×360 animated demo GIF for BotFather
uae_v4.html       — Full desktop dashboard (5 tabs, all charts)
uae_telegram.html — Telegram Mini App (3 tabs, mobile-optimized)
```

---

## 10. QUICK REFERENCE — LAST KNOWN VALUES

```
As of: April 1, 2026 (Day 34)
BM: 433  CM: 19  DR: 1977  TOTAL: 2429
Killed: 11 (8 civilian + 3 military)
Injured: 188
Intercept rate: ~97%
Launches per death: ~221

Key event: April 6 Trump deadline on Iran energy strikes
IB exams: CANCELLED → NECM
Schools: distance learning until April 17
Iranian visas: mass cancellation for those abroad
Dubai Port: tanker Al-Salmi hit by drone (March 31)
```
