# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Katalog Bakım Denetçisi (CI)

Kullanım:
  python catalog_check.py --offline                 # Yalnızca statik tutarlılık kontrolleri (her OS)
  python catalog_check.py                           # + winget show ile ID doğrulama (Windows + winget)
  python catalog_check.py --skip-download           # SHA-256 sabitli dosyaları yeniden indirmeden
  python catalog_check.py --write-evidence winget_kanit.csv

Çıktılar: catalog_report.json, catalog_report.md
Çıkış kodu: 0 = temiz, 1 = katalog hatası (ID yok, bozuk girdi, indirme/hash hatası),
            2 = altyapı sorunu (denetimlerin %20+'ı geçici hata verdi; winget/ağ bozuk olabilir)
"""

import argparse
import concurrent.futures as cf
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import apps_data  # noqa: E402

NO_MATCH_CODE = 0x8A150014  # APPINSTALLER_CLI_ERROR_NO_APPLICATIONS_FOUND
KNOWN_INSTALL_TYPES = {"winget", "direct_exe", "filezilla_clean", "dism_feature"}
KNOWN_VERIFY_KEYS = {"files", "registry_names", "appx_names"}
REQUIRED_FIELDS = ("id", "name", "desc", "category", "winget_id", "weight", "size_mb", "profiles")
WINGET_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_+\-]*(\.[A-Za-z0-9_+\-]+)+$")
MSSTORE_ID_RE = re.compile(r"^[A-Z0-9]{12}$")
UA = {"User-Agent": "FormatSonrasi-CatalogCheck/1.0"}


# ───────────────────────── Statik kontroller ─────────────────────────

def _tier(size_mb: float) -> int:
    if size_mb < 15:
        return 1
    if size_mb <= 150:
        return 2
    if size_mb <= 600:
        return 3
    return 4


def static_checks(apps: List[Dict[str, Any]]) -> List[Tuple[str, str, str]]:
    """(seviye, uygulama_id, mesaj) listesi döner. Seviye: ERROR | WARN."""
    out: List[Tuple[str, str, str]] = []
    cat_ids = {c["id"] for c in apps_data.CATEGORIES}
    profile_ids = {p["id"] for p in apps_data.PROFILES}
    conflict_groups = set(getattr(apps_data, "CONFLICT_GROUPS", {}).keys())

    seen_ids: Dict[str, int] = {}
    seen_wid: Dict[str, str] = {}
    group_members: Dict[str, int] = {}

    for app in apps:
        aid = app.get("id", "<?>")
        for f in REQUIRED_FIELDS:
            if f not in app or app[f] in (None, ""):
                out.append(("ERROR", aid, f"Zorunlu alan eksik: {f}"))

        seen_ids[aid] = seen_ids.get(aid, 0) + 1
        wid = str(app.get("winget_id", "")).lower()
        if wid:
            if wid in seen_wid:
                out.append(("ERROR", aid, f"winget_id '{wid}' ayrıca '{seen_wid[wid]}' tarafından kullanılıyor"))
            seen_wid[wid] = aid

        if app.get("category") not in cat_ids:
            out.append(("ERROR", aid, f"Bilinmeyen kategori: {app.get('category')}"))
        for p in app.get("profiles", []):
            if p not in profile_ids:
                out.append(("ERROR", aid, f"Bilinmeyen profil: {p}"))

        weight, size = app.get("weight"), app.get("size_mb")
        if weight not in (1, 2, 3, 4):
            out.append(("ERROR", aid, f"Geçersiz weight: {weight}"))
        elif isinstance(size, (int, float)) and _tier(size) != weight:
            out.append(("WARN", aid, f"weight={weight} ama size_mb={size} için beklenen sıklet {_tier(size)}"))

        itype = app.get("install_type", "winget")
        if itype not in KNOWN_INSTALL_TYPES:
            out.append(("ERROR", aid, f"Bilinmeyen install_type: {itype}"))

        if itype == "winget":
            src = app.get("source", "winget")
            pattern = MSSTORE_ID_RE if src == "msstore" else WINGET_ID_RE
            if not pattern.match(str(app.get("winget_id", ""))):
                out.append(("ERROR", aid, f"winget_id biçimi geçersiz ({src}): {app.get('winget_id')}"))

        if itype == "direct_exe":
            url = app.get("download_url", "")
            if not url.lower().startswith("https://"):
                out.append(("ERROR", aid, "direct_exe download_url HTTPS değil"))
            if not app.get("sha256") and not app.get("publisher"):
                out.append(("ERROR", aid, "direct_exe için sha256 veya publisher zorunlu"))
            if not app.get("silent_args"):
                out.append(("WARN", aid, "direct_exe silent_args tanımsız"))
        if app.get("sha256") and not re.fullmatch(r"[0-9a-fA-F]{64}", app["sha256"]):
            out.append(("ERROR", aid, "sha256 64 hex karakter olmalı"))

        bad_keys = set(app.get("verify", {})) - KNOWN_VERIFY_KEYS
        if bad_keys:
            out.append(("WARN", aid, f"Bilinmeyen verify anahtarları: {sorted(bad_keys)}"))

        grp = app.get("conflict_group")
        if grp:
            group_members[grp] = group_members.get(grp, 0) + 1
            if conflict_groups and grp not in conflict_groups:
                out.append(("ERROR", aid, f"conflict_group CONFLICT_GROUPS içinde yok: {grp}"))

    for aid, n in seen_ids.items():
        if n > 1:
            out.append(("ERROR", aid, f"id {n} kez tanımlı"))
    for grp, n in group_members.items():
        if n < 2:
            out.append(("WARN", grp, "conflict_group tek üyeli (çakışma uyarısı hiç tetiklenmez)"))

    # Profil açıklamalarındaki "(N Uygulama)" sayıları gerçek sayıyla uyuşuyor mu?
    for p in apps_data.PROFILES:
        m = re.search(r"\((\d+)\s*Uygulama\)", p.get("desc", ""))
        if m:
            actual = sum(1 for a in apps if p["id"] in a.get("profiles", []))
            if int(m.group(1)) != actual:
                out.append(("WARN", p["id"], f"Profil açıklaması {m.group(1)} uygulama diyor, katalogda {actual} var"))

    # README'deki sayılar (uygulama / kategori / ayar / profil) katalogla uyuşuyor mu?
    readme = os.path.join(os.path.dirname(os.path.abspath(__file__)), "README.md")
    if os.path.isfile(readme):
        text = open(readme, encoding="utf-8").read()
        for label, actual in (("uygulama", len(apps)), ("ana kategori", len(apps_data.CATEGORIES)),
                              ("küratörlü hazır kullanım profili", len(apps_data.PROFILES))):
            m = re.search(r"\*\*(\d+)\s+" + re.escape(label) + r"\*\*", text)
            if m and int(m.group(1)) != actual:
                out.append(("WARN", "README", f"README {m.group(1)} {label} diyor, katalogda {actual} var"))
    return out


# ───────────────────────── winget kontrolü ─────────────────────────

def find_winget(explicit: Optional[str]) -> Optional[str]:
    return explicit or os.environ.get("WINGET_BIN") or shutil.which("winget")


def winget_show(winget: str, pkg_id: str, source: str, timeout: int = 90, retries: int = 2
                ) -> Tuple[str, Optional[str], str]:
    """(durum, sürüm, ayrıntı). Durum: OK | NOT_FOUND | ERROR."""
    cmd = [winget, "show", "--id", pkg_id, "-e", "--source", source,
           "--accept-source-agreements", "--disable-interactivity"]
    last = ""
    for attempt in range(retries + 1):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=timeout)
        except subprocess.TimeoutExpired:
            last = "zaman aşımı"
            continue
        except OSError as e:
            return "ERROR", None, f"winget çalıştırılamadı: {e}"
        text = (r.stdout or "") + (r.stderr or "")
        rc = r.returncode & 0xFFFFFFFF
        if rc == 0:
            m = re.search(r"^(?:Version|Sürüm):\s*(.+)$", text, re.M)
            return "OK", (m.group(1).strip() if m else None), ""
        low = text.lower()
        if rc == NO_MATCH_CODE or "no package found" in low or "hiçbir paket bulunamadı" in low:
            return "NOT_FOUND", None, "winget kaynağında paket bulunamadı"
        last = f"çıkış kodu 0x{rc:08X}"
        time.sleep(2 * (attempt + 1))
    return "ERROR", None, last


# ───────────────────────── Doğrudan indirme kontrolü ─────────────────────────

def check_url(url: str, expect_sha: Optional[str], skip_download: bool,
              max_bytes: int = 400 * 1024 * 1024) -> Tuple[str, str]:
    """(durum, ayrıntı). Durum: OK | FAIL | ERROR."""
    if not url.lower().startswith("https://"):
        return "FAIL", "URL HTTPS değil"
    try:
        req = urllib.request.Request(url, method="HEAD", headers=UA)
        try:
            resp = urllib.request.urlopen(req, timeout=30)
        except urllib.error.HTTPError as e:
            if e.code in (403, 405, 501):  # HEAD desteklenmiyor → GET ile dene
                resp = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=30)
            else:
                return "FAIL", f"HTTP {e.code}"
        with resp:
            final = resp.geturl()
            if urlparse(final).scheme != "https":
                return "FAIL", f"HTTPS'ten HTTP'ye yönlendirme: {final}"
            if resp.status != 200:
                return "FAIL", f"HTTP {resp.status}"
            if expect_sha and not skip_download:
                h, total = hashlib.sha256(), 0
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as dl:
                    while True:
                        chunk = dl.read(1 << 20)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > max_bytes:
                            return "FAIL", "Dosya beklenenden büyük"
                        h.update(chunk)
                if h.hexdigest().lower() != expect_sha.lower():
                    return "FAIL", f"SHA-256 uyuşmuyor (gerçek: {h.hexdigest()})"
            return "OK", ""
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        return "ERROR", f"Ağ hatası: {e}"


def latest_github_tag(url: str) -> Optional[str]:
    m = re.match(r"https://github\.com/([^/]+)/([^/]+)/releases/download/", url)
    if not m:
        return None
    api = f"https://api.github.com/repos/{m.group(1)}/{m.group(2)}/releases/latest"
    headers = dict(UA, Accept="application/vnd.github+json")
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = f"Bearer {os.environ['GITHUB_TOKEN']}"
    try:
        with urllib.request.urlopen(urllib.request.Request(api, headers=headers), timeout=20) as r:
            return json.load(r).get("tag_name", "").lstrip("v") or None
    except Exception:
        return None


# ───────────────────────── Ana akış ─────────────────────────

def catalog_hash(apps: List[Dict[str, Any]]) -> str:
    return hashlib.sha256(json.dumps(apps, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def main() -> int:
    if sys.stdout and hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if sys.stderr and hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Katalog bakım denetçisi")
    ap.add_argument("--offline", action="store_true", help="Yalnızca statik kontroller")
    ap.add_argument("--winget", help="winget.exe yolu (varsayılan: PATH / WINGET_BIN)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--skip-download", action="store_true", help="SHA-256 sabitli dosyaları indirme")
    ap.add_argument("--strict", action="store_true", help="Geçici (ERROR) sonuçları da hata say")
    ap.add_argument("--report-dir", default="report")
    ap.add_argument("--write-evidence", metavar="CSV", help="winget_kanit.csv biçiminde kanıt dosyası yaz")
    args = ap.parse_args()

    apps = apps_data.APPLICATIONS
    static = static_checks(apps)
    results: List[Dict[str, Any]] = []
    infos: List[str] = []

    if not args.offline:
        winget = find_winget(args.winget)
        if not winget:
            print("[HATA] winget bulunamadı. --offline kullanın veya --winget ile yol verin.", file=sys.stderr)
            return 2

        def work(app: Dict[str, Any]) -> Dict[str, Any]:
            itype = app.get("install_type", "winget")
            base = {"id": app["id"], "name": app["name"], "winget_id": app["winget_id"], "type": itype}
            if itype == "winget":
                src = app.get("source", "winget")
                status, ver, detail = winget_show(winget, app["winget_id"], src)
                pinned = app.get("pinned_version")
                if status == "OK" and pinned and ver and ver != pinned:
                    infos.append(f"{app['name']}: sabit sürüm {pinned}, kaynakta {ver}")
                return dict(base, source=src, status=status, version=ver, detail=detail)
            if itype == "direct_exe":
                status, detail = check_url(app["download_url"], app.get("sha256"), args.skip_download)
                tag = latest_github_tag(app["download_url"])
                pinned = app.get("pinned_version")
                if tag and pinned and tag != pinned:
                    infos.append(f"{app['name']}: sabit sürüm {pinned}, GitHub'da son sürüm {tag}")
                return dict(base, source="direct", status="OK" if status == "OK" else
                            ("ERROR" if status == "ERROR" else "NOT_FOUND"), version=pinned, detail=detail)
            return dict(base, source=itype, status="SKIPPED", version=None, detail="Özel kurulum, otomatik doğrulanmaz")

        with cf.ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
            results = list(ex.map(work, apps))

    # ── Özet ve çıkış kodu ──
    counts = {k: sum(1 for r in results if r["status"] == k) for k in ("OK", "NOT_FOUND", "ERROR", "SKIPPED")}
    static_errors = [s for s in static if s[0] == "ERROR"]
    static_warns = [s for s in static if s[0] == "WARN"]
    checked = counts["OK"] + counts["NOT_FOUND"] + counts["ERROR"]

    code = 0
    if static_errors or counts["NOT_FOUND"]:
        code = 1
    if args.strict and counts["ERROR"]:
        code = 1
    if code == 0 and checked and counts["ERROR"] / checked >= 0.20:
        code = 2

    report = {
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "catalog_sha": catalog_hash(apps),
        "app_count": len(apps),
        "category_count": len(apps_data.CATEGORIES),
        "summary": counts,
        "static": [{"level": l, "id": i, "message": m} for l, i, m in static],
        "results": results,
        "info": sorted(set(infos)),
        "exit_code": code,
    }
    os.makedirs(args.report_dir, exist_ok=True)
    with open(os.path.join(args.report_dir, "catalog_report.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    md = ["# Katalog Denetim Raporu", "",
          f"- Tarih (UTC): {report['generated_utc']}",
          f"- Katalog özeti: `{report['catalog_sha']}` | {len(apps)} uygulama, {report['category_count']} kategori"]
    if not args.offline:
        md.append(f"- winget/indirme: [OK] {counts['OK']} | [BULUNAMADI] {counts['NOT_FOUND']} | "
                  f"[GECICI HATA] {counts['ERROR']} | [ATLANDI] {counts['SKIPPED']}")
    md.append("")
    for title, rows in (("Bulunamayan paketler", [r for r in results if r["status"] == "NOT_FOUND"]),
                        ("Geçici hata veren paketler", [r for r in results if r["status"] == "ERROR"])):
        if rows:
            md += [f"## {title}", ""] + [f"- **{r['name']}** (`{r['winget_id']}`): {r['detail']}" for r in rows] + [""]
    if static_errors:
        md += ["## Statik hatalar", ""] + [f"- `{i}`: {m}" for _, i, m in static_errors] + [""]
    if static_warns:
        md += ["## Statik uyarılar", ""] + [f"- `{i}`: {m}" for _, i, m in static_warns] + [""]
    if infos:
        md += ["## Bilgi (güncelleme adayları)", ""] + [f"- {x}" for x in sorted(set(infos))] + [""]
    if code == 0 and not static_warns and not infos:
        md.append("Tum kontroller temiz. [OK]")
    with open(os.path.join(args.report_dir, "catalog_report.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md) + "\n")

    if args.write_evidence and results:
        label = {"OK": "OK", "NOT_FOUND": "BULUNAMADI", "ERROR": "HATA", "SKIPPED": "ATLANDI-OZEL"}
        with open(args.write_evidence, "w", encoding="utf-8", newline="\n") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(["id", "winget_id", "kaynak", "durum", f"katalog_sha={report['catalog_sha']}"])
            for r in results:
                kaynak = r["source"] if r["type"] == "winget" else r["type"]
                w.writerow([r["id"], r["winget_id"], kaynak, label[r["status"]]])

    print("\n".join(md))
    return code


if __name__ == "__main__":
    sys.exit(main())
