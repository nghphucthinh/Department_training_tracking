# Deployment Guide — Django + IIS (wfastcgi) on Intel Cloud VM

This document captures every configuration step required to deploy and access this Django app via IIS on an Intel corporate cloud (VDI) machine. Use it as a reference for future projects with the same stack.

---

## Stack Overview

| Component | Detail |
|---|---|
| Web framework | Django (WSGI) |
| Server | IIS + wfastcgi (FastCGI bridge) |
| Python env | `.venv` virtualenv |
| Host OS | Windows Server / Intel Cloud VM |
| Access URL | `http://tegaf-jtp.intel.com` |

---

## 1. IIS Site Setup

### 1.1 Application Pool

- Name: `TEGAF_JTP`
- Managed runtime: *No Managed Code* (unmanaged, since Python handles execution)
- Identity: a user account with access to the project directory

### 1.2 Site Bindings

Add bindings for every hostname the site should respond to. In IIS Manager → Site → Bindings:

| Protocol | IP | Port | Hostname |
|---|---|---|---|
| http | * | 80 | `tegaf-jtp.intel.com` |
| http | * | 80 | *(blank — catch-all)* |
| http | `10.109.81.178` | 80 | *(blank)* |
| http | * | 80 | `tegaf-generic.gar.corp.intel.com` |

> **Why the catch-all?** Short hostnames like `tegaf-jtp` (no dots) don't match any specific binding and fall through to the catch-all. The FQDN `tegaf-jtp.intel.com` is matched by its specific binding.

### 1.3 Handler (wfastcgi)

In `web.config` under `<system.webServer><handlers>`:

```xml
<remove name="TEGAF_JTP" />
<add name="TEGAF_JTP"
     path="*"
     verb="*"
     modules="FastCgiModule"
     scriptProcessor="D:\...\venv\Scripts\python.exe|D:\...\venv\Lib\site-packages\wfastcgi.py"
     resourceType="Unspecified"
     requireAccess="Script" />
```

---

## 2. `web.config` — Environment Variables via `appSettings`

`wfastcgi` passes every `<appSettings>` key as an **environment variable** to the FastCGI Python process. This is how Django settings (e.g. `ALLOWED_HOSTS`) are injected without a `.env` file.

```xml
<appSettings>
  <add key="WSGI_HANDLER"          value="config.wsgi.application" />
  <add key="PYTHONPATH"            value="D:\...\Department_training_tracking" />
  <add key="DJANGO_SETTINGS_MODULE" value="config.settings" />
  <add key="WSGI_LOG"              value="D:\...\logs\wfastcgi.log" />
  <add key="ALLOWED_HOSTS"         value="tegaf-jtp.intel.com,tegaf-jtp,tegaf-generic.gar.corp.intel.com,10.109.81.178,localhost,127.0.0.1" />
</appSettings>
```

### ⚠ ALLOWED_HOSTS is critical

Django validates the HTTP `Host` header against `ALLOWED_HOSTS`. If the hostname in the browser URL is not listed here, Django returns a **400 Bad Request** — even if DNS and IIS are configured correctly.

- Default fallback in `settings.py` is `localhost,127.0.0.1` (insufficient for FQDN access).
- Always include **every hostname and IP** that the site will be accessed from.
- After changing `web.config`, recycle the app pool:
  ```
  %windir%\system32\inetsrv\appcmd.exe recycle apppool /apppool.name:"TEGAF_JTP"
  ```

---

## 3. Windows Hosts File

**File:** `C:\Windows\System32\drivers\etc\hosts`

Add entries so the server can resolve its own FQDNs locally (required for loopback access):

```
127.0.0.1    tegaf-jtp
127.0.0.1    tegaf-jtp.intel.com
127.0.0.1    tegaf-jtp.com
```

> Without these entries, accessing the site from the server itself would require the hostname to resolve through external DNS, which may not return `127.0.0.1`.

---

## 4. Corporate Proxy Configuration (Intel Cloud VM Problem)

### The Problem

Intel Cloud VMs use **WPAD auto-detect** to discover a corporate PAC file that routes `*.intel.com` traffic through the **DMZ proxy** (`proxy-dmz.intel.com:912`). This proxy blocks internal Intel addresses. The result:

- `http://tegaf-jtp` ✅ — Short names (no dots) are treated as "local" by `<local>` in the proxy bypass list and bypass the proxy automatically.
- `http://tegaf-jtp.intel.com` ❌ — FQDN has dots, matches `*.intel.com` in the PAC file, gets sent to the DMZ proxy → **blocked**.

The Windows `ProxyOverride` bypass list is **completely ignored** when the proxy source is WPAD/PAC auto-detect.

### The Fix — Switch from WPAD to Manual Proxy

Run once in PowerShell on the cloud VM:

```powershell
$reg = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings'

# Enable manual proxy pointing to the same DMZ proxy WPAD was using
Set-ItemProperty $reg ProxyEnable 1
Set-ItemProperty $reg ProxyServer "proxy-dmz.intel.com:912"

# Bypass list — now enforced because we're not using WPAD
Set-ItemProperty $reg ProxyOverride "tegaf-jtp.intel.com;tegaf-jtp;tegaf-jtp.com;<local>"

# Disable WPAD auto-detect (byte 8: 9 = auto-detect ON → 3 = manual proxy only)
$conn = (Get-ItemProperty "$reg\Connections").DefaultConnectionSettings
$conn[8] = 3
Set-ItemProperty "$reg\Connections" DefaultConnectionSettings $conn
```

**Restart the browser** after running this.

| Byte 8 value | Meaning |
|---|---|
| `1` | Direct (no proxy) |
| `3` | Manual proxy |
| `9` | WPAD auto-detect (+ direct) |
| `11` | PAC URL configured |

> **Note:** If group policy resets these settings after reboot, the permanent fix is to ask IT to add `tegaf-jtp.intel.com` as a `DIRECT` entry in the corporate PAC file.

---

## 5. Windows Security Zone — Automatic Windows Authentication

### The Problem

Browsers use Windows zones to decide whether to send Windows credentials (NTLM/Kerberos) automatically:

- **Zone 1 (Intranet)** → credentials sent silently (no login prompt)
- **Zone 3 (Internet)** → browser prompts for username/password

Short hostnames (no dots) are auto-detected as Intranet via the `IntranetName = 1` ZoneMap setting. FQDNs like `tegaf-jtp.intel.com` are treated as Internet unless explicitly mapped.

### The Fix — Add to Intranet Zone

Run once in PowerShell:

```powershell
$path = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings\ZoneMap\Domains\intel.com\tegaf-jtp'
New-Item -Path $path -Force | Out-Null
Set-ItemProperty -Path $path -Name 'http'  -Value 1 -Type DWord
Set-ItemProperty -Path $path -Name 'https' -Value 1 -Type DWord
```

This sets `http://tegaf-jtp.intel.com` and `https://tegaf-jtp.intel.com` to **Zone 1 (Intranet)**.

**Restart the browser** after running this.

> **Zone value reference:** 0 = My Computer, 1 = Intranet, 2 = Trusted Sites, 3 = Internet, 4 = Restricted

---

## 6. Summary — Accessing the App from the Hosting Server Itself

On other machines on the corporate network, steps 4 and 5 are typically pre-configured by IT group policy. On a cloud VM hosting the app, you need to apply them manually:

| Step | What it fixes | Command/Location |
|---|---|---|
| `ALLOWED_HOSTS` in `web.config` | Django 400 error for FQDN | `web.config` → `appSettings` |
| Hosts file entry | Local DNS resolution | `C:\Windows\System32\drivers\etc\hosts` |
| Manual proxy + bypass list | Corporate DMZ proxy blocking internal FQDN | PowerShell (Section 4) |
| Intranet zone mapping | Browser prompting for credentials | PowerShell (Section 5) |

---

## 7. Diagnosing Future Issues

### Check which proxy is used for a URL
```powershell
$proxy = [System.Net.WebRequest]::GetSystemWebProxy()
$proxy.GetProxy([Uri]"http://your-site.intel.com")
```

### Check WPAD auto-detect state
```powershell
$conn = (Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings\Connections').DefaultConnectionSettings
"Proxy flags byte: " + $conn[8]   # 9 = WPAD on
```

### Check zone for a hostname
The registry path `HKCU:\...\ZoneMap\Domains\<domain>\<subdomain>` holds the zone value for each protocol.

### Recycle the IIS app pool
```
%windir%\system32\inetsrv\appcmd.exe recycle apppool /apppool.name:"<AppPoolName>"
```

### View wfastcgi logs
```
D:\...\logs\wfastcgi.log
```
