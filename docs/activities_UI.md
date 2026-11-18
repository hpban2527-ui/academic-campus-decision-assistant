# HCMUS UniLife — Student Activity Repository & 5-Day Carousel UI Handover

> **Technical Specification, Design Architecture & Final Code Integration Guide**  
> **Status:** Completed & Production Ready  
> **Target Deployments:** `web/index.html` (Integrated Dashboard Workspace) & `web/activities_ui.html` (Standalone Reference UI).

---

## 1. Executive Summary & Design Goals

The **Student Activity Repository** ("Kho Hoạt Động Sinh Viên") serves as the centralized activity exploration hub for students of VNU-HCM University of Science (HCMUS). Students rely on this view to monitor workshops, volunteer campaigns, academic competitions, and sports events while tracking upcoming registration deadlines.

### Main feature:
1. **5-Day Date Carousel (`1/5` Width Columns):** Replaces rigid monthly Gantt grids with a fluid 5-day horizon focused on a central focal date (Card #3) with a distinctive visual downward indicator arrow (`▼`).
2. **Continuous Multi-Day Spanning Banners:** Events spanning across multiple days (e.g., *LET IT SHINE 2026*) are rendered as single, continuous horizontal bars spanning columns.
3. **Uniform 38px Activity Pill Heights:** All timeline items maintain a `38px` height displaying only the custom circular clock icon and truncated title, preserving visual rhythm.

---

## 2. UI Components & Interaction Model

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│  HEADER: Title & Count Badge | [Hôm nay (25/10)] [📅 Chọn ngày] [🌓 Theme]       │
│  FILTERS: [🔍 Search...] [Lĩnh vực ▾] [Hình thức ▾] [☑ Còn hạn] [Xóa bộ lọc]     │
├───────────────────────────────────────────────────────┬──────────────────────────┤
│  AREA 2: 5-DAY CAROUSEL & ACTIVITY TIMELINE (9/12)    │ AREA 3: UNSCHEDULED      │
│  DÒNG THỜI GIAN HOẠT ĐỘNG         ● Còn hạn ● <24h ● Hết  │ TRAY (3/12)              │
│                                                       │ 📌 CHƯA CHỐT NGÀY [7]    │
│                        ▼ (Center Focused Day Arrow)   │ Mở đăng ký trước, ngày   │
│  ┌──────────┬──────────┬──────────┬──────────┬───────┐│ diễn ra thông báo sau     │
│  │ Thứ Ba   │ Thứ Tư   │ Thứ Năm  │ Thứ Sáu  │ Thứ 7 ││ ┌──────────────────────┐ │
│  │   27/10  │   28/10  │   29/10  │   30/10  │ 31/10 ││ │[Kỹ năng]    Trực tiếp│ │
│  │          │ [Hôm nay]│ (FOCUS)  │          │       ││ │BẢN LĨNH IT 2026      │ │
│  ├──────────┴──────────┴──────────┴──────────┴───────┤│ │🕐 Hết hạn            │ │
│  │ 🕐 LET IT SHINE 2026 (Continuous banner cols 1..5) ││ ├──────────────────────┤ │
│  ├──────────┬────────────────────────────────────────┤│ │[Khác]        Online │ │
│  │          │ 🕐 THÚC ĐẨY HỆ SINH THÁI (Cols 2..5)   ││ │HTTT                  │ │
│  ├──────────┼──────────┬──────────┬──────────┬───────┤│ │🕐 Còn hạn            │ │
│  │          │ 🕐 Pill  │ 🕐 Pill  │ 🕐 Pill  │       ││ └──────────────────────┘ │
│  └──────────┴──────────┴──────────┴──────────┴───────┘│ (Internal scroll, height│
│  💡 Tip: Mouse wheel shifts days; inside grid scrolls │  matched to left box)    │
└───────────────────────────────────────────────────────┴──────────────────────────┘
```

### 2.1. 5-Day Carousel Engine
* **Visible Date Window:** Evaluates 5 consecutive dates centered on `state.focusDate`:
  $$\text{Dates} = [\text{focus} - 2, \text{focus} - 1, \mathbf{focus}, \text{focus} + 1, \text{focus} + 2]$$
* **Focal Day Indicator:** Column #3 is styled with higher contrast and an overhead centered arrow (`▼`). Clicking any non-center date card smoothly shifts it into the central focus position.
* **Smart Wheel Navigation:**
  * Wheel on Date Header $\rightarrow$ Shifts calendar by $\pm 1$ day (debounced at 90ms).
### 2.2. Greedy Lane Packing for Continuous Spanning Bars
To prevent visual collisions across multi-day events, the layout calculates:
1. `colStart = max(1, min(5, dateMap[act.start] + 1))`
2. `colEnd = min(6, dateMap[act.end] + 2)`
3. `span = colEnd - colStart` (multi-day if `span > 1`).

Activities are sorted with multi-day banners first, then packed into the lowest non-overlapping horizontal lane:
```css
grid-column: colStart / colEnd;
grid-row: laneIndex + 1;
```

### 2.3. Custom SVG Clock Icons & Teeter Animation
Icons are loaded from `web/image/activitie_storage/`:

| Status | Condition | SVG Asset | Graphic Description & Animation |
| :--- | :--- | :--- | :--- |
| **Còn hạn** (Available) | `diff > 24h` | `reg-available.svg` | green style. |
| **Sắp hết hạn** (Urgent) | `0 < diff <= 24h` | `reg-urgent.svg` | red style, teeter rocking alarm animation. |
| **Hết hạn** (Expired) | `diff <= 0` | `reg-expired.svg` | gray style. |

---

## 3. Final Code Integration Guide for `web/index.html`

The native integration in `web/index.html` preserves full backwards compatibility while providing the new 5-day carousel as the primary interface.

### 3.1. File Layout & Role Directory
* `web/index.html`: Main UniLife application containing all workspaces (`#viewDashboard`, `#viewCalculator`, `#viewActivities`, `#viewSnapshot`, `#viewPlan`).
* `web/activities_ui.html`: Standalone reference implementation (preserved for isolated testing, demonstrations,...).
* `web/image/activitie_storage/`: Directory storing `reg-available.svg`, `reg-urgent.svg`, and `reg-expired.svg`.

### 3.2. Workspace 2 Sub-View Toggle Architecture
Inside `<div id="viewActivities" class="hidden space-y-4">`:
1. **Sub-View 1 (`#activitiesTimelineSection`):** Default view. Houses the filter bar, 5-day carousel `#timelineSectionInner`, and unscheduled tray `#timelineUnscheduledList`.
2. **Sub-View 2 (`#activitiesQaSection`):** Preserved for TA/reviewer grading and data auditing. Contains the original two-column data review queue (`#validActivitiesList`, `#sp3NewDraftsList`, `#reviewQueueList`, and local session path).
3. **Toggle Controller:**
   ```javascript
   function setActivitiesSubView(mode) {
     // Toggles visibility between #activitiesTimelineSection and #activitiesQaSection
     // Updates active state of #btnSubViewTimeline and #btnSubViewQa
   }
   ```

### 3.3. Data Pipeline Hook
In `loadActivitiesFromApi()` inside `web/index.html`:
```javascript
// Once validList is resolved from /api/sp3/catalog or /api/activities:
renderRecommendedActivities(validList);
syncTimelineActivities(validList.map(r => r.activity || r));
```
When `syncTimelineActivities()` executes, it loads the activities into `timelineState.allActivities`, binds wheel/filter listeners, and calls `renderTimelineView()`.

### 3.4. Modal Architecture
The detailed 14-field modal `#activityTimelineModal` is appended right after `#loginModal` in `web/index.html`. It is invoked globally via:
```javascript
openActivityTimelineModalById(activity_id);
```
It displays formatted dates, domain badge, fee badge, requirements, and direct external action links (`URL_registration` and `URL_post`).

---

## 4. Light & Dark Theme Adaptability

`web/activities_ui.html` support real-time theme switching:

### Theme Palette Rules:
```css
/* Dark Theme (Default) */
Backgrounds: #080c14, #0e1524, #080d18, #11192b
Borders:     #1b2537, #223046
Text:        #f8fafc (Title), #cbd5e1 (Body), #64748b (Muted)

/* Light Theme (.light-theme / #workspaceApp.light-theme) */
Backgrounds: #f1f5f9 (Page), #ffffff (Containers), #e2e8f0 (Pills & secondary)
Borders:     #cbd5e1
Text:        #0f172a (Title), #334155 (Body), #64748b (Muted)
Pill Text:   #ffffff !important (High contrast on saturated domain pills)
Card Hover:  rgba(226, 232, 240, 0.7)
Center Card: #e0e7ff with text #1e1b4b
```

Theme changes are synchronized across tabs and refreshes using:
```javascript
localStorage.setItem('unilife_theme', 'light' | 'dark');
```