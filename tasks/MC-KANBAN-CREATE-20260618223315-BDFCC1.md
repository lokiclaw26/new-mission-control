---
task_id: MC-KANBAN-CREATE-20260618223315-BDFCC1
title: do a quick research and give me 5 ideas for a DIY electronics idea with ESP32 and TFT display....make it to be innovative and fun
project: mission-control
status: done
kanban_status: archived
priority: high
created: 2026-06-18T22:33:15+00:00
created_by: thor
assigned_to: thor
current_assignment: MC-KANBAN-CREATE-20260618223315-BDFCC1
approval_required: true
approval_status: pending
---

## Research started (auto-process)

The auto-process cron picked up this task on 2026-06-19T02:35:19+04:00 Dubai. v1 auto-process does not perform real research yet — it just moves the card out of triage and sets the assignee via the title heuristic (research→thor, qa/test/verify→argus, else→forge; `auto_assign:` frontmatter overrides). For v2 (real LLM research), see MC-AUTO-PROCESS-1 follow-up.

# do a quick research and give me 5 ideas for a DIY electronics idea with ESP32 and TFT display....make it to be innovative and fun

## Result (delivered 2026-06-19T02:39 by thor)

Five innovative + fun ESP32 + TFT DIY ideas. All run on ESP32 (C3 Super Mini works for the lean ones, original ESP32/WROOM for anything WiFi-heavy or that needs PSRAM for framebuffers). Common TFT: 2.8" ILI9341 or 1.8" ST7789.

---

**1. Pocket Retro Arcade Cabinet (Mini-Arcade-You-Can-Hold)**
A 3D-printed handheld the size of a small phone, with the TFT as the screen, a tiny speaker, 6–8 tactile buttons, and a LiPo with USB-C charging. Runs an emulator frontend (ESP32-32E or ESP32-S3 with PSRAM) loaded with NES/Game Boy / Doom-era ROMs from SPI flash or SD. Add a tilt sensor for "motion controls" on simple games.
*Why it's fun:* the build itself is a weekend, and you're immediately playing games on something you made. Custom splash screens, save states, gyro controls. Endless tinkering.

**2. Live Plant Mood Dashboard ("The Plant That Texts You")**
Soil moisture + temperature + humidity + light sensors → TFT shows a custom illustrated "face" of the plant (happy, thirsty, sunbathing, shivering, dramatic). ESP32 pushes the same data to a simple MQTT/HTTP endpoint so the plant "complains" on Telegram when ignored. Animated weather icon, tap-to-water history graph.
*Why it's fun:* anthropomorphizes a houseplant, makes watering visible, easy to extend with a small peristaltic pump for auto-watering. Genuinely useful AND cute.

**3. Air Quality / Weather "Magic Mirror" Puck**
A wall-mountable or desk puck with a TFT behind a one-way acrylic mirror film. Shows time, weather, indoor AQI, CO2, VOC (BME680 or SGP40 + SCD30), and a subtle animated gradient that reflects outdoor conditions (clear blue → stormy purple → smoggy amber). Touch any zone to drill in. No camera, no mic — just data.
*Why it's fun:* makes invisible air quality tangible. The "magic mirror" aesthetic is satisfying, and watching the room's mood shift is a conversation starter. Real-world impact (sleep, focus, headaches).

**4. WiFi Wardriving / Network Wardial Art Visualizer**
ESP32 scans WiFi + BLE continuously, the TFT renders a real-time "constellation map" of nearby networks — each AP a glowing node, signal strength = size/brightness, channel = color. Save runs to SD to map your neighborhood over time. Optional GPS add-on to plot on a map later. Acts as a portable cybersecurity teaching tool too.
*Why it's fun:* you walk around watching the radio world light up. Educational (real networking concepts), visually striking, useful for pentesters and the curious. Plays into the "hacker aesthetic" without being sketchy if framed right.

**5. Smart Desk Companion / Pomodoro "Pet" (Tamagotchi Reborn)**
A TFT-faced desktop buddy that lives on your desk. Starts as an egg, hatches based on how consistently you focus. Feed it by completing Pomodoro sessions, pet it (touch) to refill "social" meter, dim the room (light sensor) and it gets sleepy. Fully customizable sprite art on the TFT. Optional: integrates with your calendar — meetings stress it out, focus time makes it dance.
*Why it's fun:* gamifies focus without the dark patterns of phone apps. The hatching / evolution arc gives a long-term reward loop. Genuinely makes you smile when it wiggles. Easy to ship as a kit or PCB for friends.

---

### Cross-cutting add-ons (any of the above)
- **SD card slot** for assets, logs, ROMs
- **Battery + USB-C charging** (TP4056) for portable builds
- **Custom PCB** (ESP32-DevKitC footprint is breadboard-friendly; KiCad + JLCPCB for production)
- **3D-printed enclosure** (PETG for heat resistance, TPU for soft-touch buttons)
- **LVGL** for richer UIs than raw TFT_eSPI

### My pick for "ship first"
**Idea 2 (Plant Mood Dashboard)** — cheapest BOM (~AED 80–100), highest "wow" per build hour, hardest to find off-the-shelf, real utility. Strong Etsy/kit potential if NOFI ever wants to productize.

## Active work (MC-AUTO-20260619023628-C86507)

This task was auto-dispatched at dispatch time. The actual work is happening in the child task `MC-AUTO-20260619023628-C86507` (assignee `thor`). Re-dispatch is suppressed for 60s via a dotfile; this file's `kanban_status` is `running_now` so subsequent cron runs skip it.
