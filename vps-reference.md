# VPS Reference — vps-main

## Mac Project Directory

All project files live at:
```
~/Desktop/Projects/Voice journal/voice_journal_vps/
```

When deploying updates from your Mac, always `cd` here first:
```bash
cd ~/Desktop/Projects/Voice\ journal/voice_journal_vps/
```

Deploying a script update:
```bash
scp voice_journal.py YOUR_USER@YOUR_VPS_IP:/tmp/
ssh vps
sudo cp /tmp/voice_journal.py /opt/voice-journal/
sudo chown journal:journal /opt/voice-journal/voice_journal.py
```

---

## Server

| | |
|---|---|
| Provider | Hetzner CX23 |
| IP | YOUR_VPS_IP |
| OS | Ubuntu 24.04 |
| Location | Nuremberg, DE |
| Cost | ~€4.15/mo |
| Domain | YOUR_DOMAIN |
| SSL | Let's Encrypt (auto-renews, expires 2026-07-17) |

---

## SSH Access

```bash
ssh vps   # after adding to ~/.ssh/config (see below)
```

**Mac ~/.ssh/config entry:**
```
Host vps
    HostName YOUR_VPS_IP
    User michal
    IdentityFile ~/.ssh/id_ed25519
```

---

## Voice Journal

### What it does
iPhone shortcut records memo → uploads to VPS → **02:00 CET/CEST** processing → Notion entry ready for morning debrief.

### Key paths
| | |
|---|---|
| App directory | `/opt/voice-journal/` |
| Config | `/opt/voice-journal/.env` |
| Inbox (pending) | `/opt/voice-journal/inbox/` |
| Processed audio | `/opt/voice-journal/archive/audio/YYYY-MM-DD/` |
| Journal markdown | `/opt/voice-journal/archive/markdown/` |
| Processing log | `/opt/voice-journal/voice_journal.log` |
| Upload log | `/opt/voice-journal/receiver.log` |

### Upload endpoint
```
POST https://YOUR_DOMAIN/upload
Authorization: Bearer YOUR_UPLOAD_TOKEN
```

### iOS Shortcut config
- URL: `https://YOUR_DOMAIN/upload`
- Method: POST
- Header: `Authorization: Bearer YOUR_UPLOAD_TOKEN`
- Body: Form — key `file`, type File, value Recorded Audio

### Notion
- Database ID: `YOUR_NOTION_DB_ID`
- Integration: Voice Journal (notion.so/my-integrations)

### API keys location
```bash
sudo nano /opt/voice-journal/.env
```

---

## Routine Commands

### Check everything is running
```bash
sudo systemctl status voice-journal-receiver
sudo systemctl list-timers | grep voice-journal
```

### View logs
```bash
tail -20 /opt/voice-journal/voice_journal.log   # processing
tail -20 /opt/voice-journal/receiver.log         # uploads
journalctl -u voice-journal-receiver -f          # receiver live
```

### Trigger processing manually
```bash
sudo systemctl start voice-journal-process
```

### Restart receiver (after .env changes)
```bash
sudo systemctl restart voice-journal-receiver
```

### Check pending inbox files
```bash
ls /opt/voice-journal/inbox/
```

---

## Updating the App

```bash
# From your Mac (example — replace filename/path as needed)
scp voice_journal.py YOUR_USER@YOUR_VPS_IP:/tmp/
scp weekly_report.py YOUR_USER@YOUR_VPS_IP:/tmp/
scp debrief/main.py YOUR_USER@YOUR_VPS_IP:/tmp/

# On the VPS
sudo cp /tmp/voice_journal.py /opt/voice-journal/
sudo cp /tmp/weekly_report.py /opt/voice-journal/
sudo cp /tmp/main.py /opt/voice-journal/debrief/
sudo chown journal:journal /opt/voice-journal/voice_journal.py /opt/voice-journal/weekly_report.py /opt/voice-journal/debrief/main.py
sudo systemctl restart voice-journal-receiver   # only needed if receiver.py changed
```

Files owned by `journal:journal`. `michal` user needs sudo for the cp + chown steps.

---

## System Maintenance

### OS updates
```bash
sudo apt update && sudo apt upgrade -y
sudo reboot   # if kernel update pending
```

### Check disk space
```bash
df -h /
du -sh /opt/voice-journal/archive/audio/   # grows over time
```

### SSL certificate
Auto-renews via certbot. To check:
```bash
sudo certbot certificates
```

Manual renewal if needed:
```bash
sudo certbot renew
```

### DuckDNS
- URL: duckdns.org (log in with Google)
- Subdomain: `YOUR_SUBDOMAIN`
- IP must point to: `YOUR_VPS_IP`
- Hetzner IP is static — only update if you rebuild the server

---

## If Something Breaks

**Receiver not responding:**
```bash
sudo systemctl restart voice-journal-receiver
journalctl -u voice-journal-receiver -n 50
```

**Processing failed / no Notion entry:**
```bash
sudo systemctl start voice-journal-process
cat /opt/voice-journal/voice_journal.log
```

**Inbox stuck (files not being processed):**
```bash
ls /opt/voice-journal/inbox/        # files still here?
sudo systemctl start voice-journal-process   # force a run
```

**SSL expired:**
```bash
sudo certbot renew --force-renewal
sudo systemctl reload nginx
```

**Full reboot:**
```bash
sudo reboot
# wait 30s then:
ssh vps
sudo systemctl status voice-journal-receiver
```

---

## Directory Structure on VPS

```
/opt/voice-journal/
├── .env                          # All API keys (shared by all scripts)
├── voice_journal.py
├── receiver.py
├── weekly_report.py
├── cli.py
├── ai_client.py
├── analytics.py
├── models.py
├── backfill_workouts.py
├── pipeline/
├── debrief/
│   ├── main.py
│   ├── config.py
│   ├── formatter.py
│   ├── sender.py
│   ├── synthesis.py
│   ├── service-account.json      # Google Calendar service account (keep secret)
│   └── collectors/
├── venv/                         # Shared Python virtualenv
├── inbox/                        # Pending audio files
├── buffer/                       # Daily transcript JSON (auto-cleaned)
├── archive/
│   ├── audio/YYYY-MM-DD/
│   └── markdown/
├── reports/                      # workouts.xlsx (weekly Excel export)
├── voice_journal.log
├── weekly_report.log
└── debrief/logs/debrief.log
```
