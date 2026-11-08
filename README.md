# Format Sonrası Kurulum Sihirbazı (Universal Edition v1.0)

[![CI & Test Suite](https://github.com/owner/Format-Sonrasi/actions/workflows/ci.yml/badge.svg)](https://github.com/owner/Format-Sonrasi/actions/workflows/ci.yml)
[![Build & Release](https://github.com/owner/Format-Sonrasi/actions/workflows/release.yml/badge.svg)](https://github.com/owner/Format-Sonrasi/actions/workflows/release.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Windows kurulumu veya format sonrası ihtiyaç duyulan temel yazılımları, geliştirici araçlarını, mühendislik paketlerini ve sistem optimizasyonlarını pratik, güvenilir ve toplu bir şekilde kurmanızı sağlayan açık kaynaklı bir masaüstü uygulamasıdır. 

Katalog bünyesinde **204 uygulama**, **14 ana kategori**, **14 sistem optimizasyon ayarı** ve **8 hazır profil** yer almaktadır. Paketler öncelikli olarak Microsoft WinGet topluluk deposu üzerinden, istisnai durumlarda ise resmi üretici HTTPS bağlantılarıyla doğrulanarak kurulur.

---

## Genel Özellikler ve Mimari

1. **Sistem Ön Kontrolleri (Pre-Flight Checks):**
   - Windows 10 (1809+, Derleme >= 17763) ve Windows 11 64-bit mimari uyumluluğu kontrol edilir.
   - Yönetici (Administrator) yetkisi sorgulanır.
   - `cdn.winget.microsoft.com` üzerinden HTTPS (443) ve DNS erişilebilirliği teyit edilir.
   - Seçilen uygulamaların tahmini boyutuna göre `%SystemDrive%` üzerindeki boş disk alanı doğrulanır.
   - CBS ve Windows Update kaynaklı bekleyen yeniden başlatma durumu tespit edilir.

2. **Çok Katmanlı Kurulum Doğrulama (Post-Install Verifier):**
   - Yalnızca süreç çıkış koduna güvenilmez; Windows Uninstall Kayıt Defteri (32-bit ve 64-bit HKLM/HKCU), hedef Program Files dizini, Appx paket manifestosu veya DISM sorguları ile uygulamanın gerçekten kurulduğu doğrulanır.

3. **Oturum Yönetimi ve Kesinti Kurtarma (Session Manager):**
   - Kurulum durumu (`session_state.json`) her adımda diske kaydedilir.
   - Beklenmedik bir kapanma veya elektrik kesintisi sonrası uygulama açıldığında yarım kalan oturum tespit edilir ve kullanıcıya kaldığı yerden devam etme imkanı sunulur.
   - Kurulum esnasında sistem yeniden başlatması gerektiren paketler (3010 veya 1641 dönüş kodu) oluştuğunda, sistem yeniden başladıktan sonra uygulamanın kullanıcı oturumunda devam edebilmesi için Windows Zamanlanmış Görevi (`onlogon`) oluşturulur.

4. **Yeniden Başlatma Yönetimi (Reboot Advisory):**
   - Yeniden başlatma isteyen paketler kuyruğu kesmez; diğer uyumlu kurulumlar tamamlandıktan sonra kullanıcı bilgilendirilir.
   - 0 (Başarılı), 3010 (Yeniden başlatma gerekli) ve 1641 (Yeniden başlatma başlatıldı) kodları standart başarı kodları olarak ele alınır.

5. **Uygulama Çakışma Denetimi (Conflict Warnings):**
   - Aynı işlevi gören arşiv yöneticileri, ofis paketleri, PDF okuyucular veya codec paketleri aynı anda seçildiğinde çakışmaları önlemek için kullanıcı uyarılır.

6. **Boyut Sıralaması:**
   - Paketler disk ve ağ darboğazlarını en aza indirmek için dosya boyutuna göre hafiften ağıra doğru otomatik sıralanır.

7. **Windows İnce Ayarları ve Geri Alma (Rollback):**
   - Klasik sağ tık menüsü, dosya uzantılarını gösterme, telemetri azaltma, Bing arama kutusunu kapatma, gereksiz widget'ları gizleme, Nihai Performans Güç Planı, hızlı başlatma yönetimi ve uzun dosya yolu desteği (MAX_PATH) gibi ayarları içerir.
   - **Geri Yükleme Noktası:** Ayarlar uygulanmadan önce Windows Sistem Geri Yükleme Noktası (`Checkpoint-Computer`) oluşturulması denenir. *(Not: Temiz Windows kurulumlarında Sistem Koruması varsayılan olarak kapalı gelebilir veya Windows 24 saatlik sıklık kısıtlaması uygulayabilir).*
   - **Kayıt Defteri Yedeği:** Yapılan değişikliklerin önceki orijinal değerleri `tweaks_backup.json` dosyasına kaydedilir ve "Tüm Ayarları Geri Al" seçeneğiyle orijinal hallerine döndürülür. Bozuk yedek dosyaları `.corrupt` uzantısıyla korunur.
   - **Telemetri Seviyesi:** `AllowTelemetry=0` politikası Enterprise ve Education sürümlerinde tam kapatma sağlar; Home ve Pro sürümlerinde Windows bu değeri en düşük seviye olan Temel (1) olarak kabul eder.

8. **İndirme ve Süreç Güvenliği:**
   - Doğrudan indirilen ikili dosyalarda yalnızca HTTPS kullanılır ve alan adı yönlendirme denetimi (`StrictHTTPSRedirectHandler`) uygulanır.
   - İndirmeler yalnızca yöneticilerin erişebildiği güvenli dizinde tutulur.
   - İndirme boyutu güvenlik katsayısı (`min(max(size*3, 50), 4096) MB`) ile beklenmeyen aşırı büyük veri transferleri engellenir.
   - Çalıştırma öncesi hash kontrolü yapılarak yarış durumu (TOCTOU) riskleri önlenir.

---

## 8 Hazır Kullanım Profili

| Profil Adı | Uygulama Sayısı | Yaklaşık Boyut | Açıklama |
|---|---|---|---|
| **Ev ve Temel Kullanıcı** | 10 Uygulama | ~0.3 GB | Visual C++ AIO, .NET Runtime, Chrome, 7-Zip, VLC, Everything, PDF24 |
| **Yazılımcı ve Geliştirici** | 39 Uygulama | ~5.0 GB | VS Code, Visual Studio, Git, Python, Node.js, Docker/Ollama, DBeaver, Postman |
| **Mimar ve Mühendis** | 17 Uygulama | ~4.1 GB | DWG TrueView, FreeCAD, LibreCAD, KiCad EDA, QGIS, Blender, Cura |
| **Sistem ve Ağ Yönetimi** | 26 Uygulama | ~0.7 GB | Sysinternals Suite, Advanced IP Scanner, Nmap, MobaXterm, Rufus, Wireshark |
| **Grafik ve Video Kurgu** | 15 Uygulama | ~2.1 GB | CapCut, Shotcut, Kdenlive, Krita, Inkscape, Blender, OBS Studio, HandBrake |
| **Eğitim ve Araştırma** | 16 Uygulama | ~1.6 GB | Zotero, Obsidian, Notion, Anki, GeoGebra, MiKTeX, OnlyOffice |
| **Oyuncu Paketi** | 18 Uygulama | ~0.8 GB | Steam, Epic Games, Discord, DirectX, .NET 3.5, 7-Zip, Spotify |
| **Ofis ve Çalışma** | 13 Uygulama | ~1.3 GB | ONLYOFFICE, Chrome, PDF24, 7-Zip, Zoom, WhatsApp |

---

## Güvenlik ve Doğrulama

- **GitHub Actions ile Otomatik Derleme:** Uygulama ikilileri doğrudan yerel geliştirici makinesinde değil, GitHub Actions üzerinde şeffaf biçimde derlenir ve Release olarak yayınlanır. Artifact provenance (attestation) ile dağıtılan arşivin ilgili commit'ten üretildiği doğrulanabilir.
- **SmartScreen Uyarısı:** Açık kaynaklı ve bağımsız projeler pahalı ticari kod imzalama sertifikalarına sahip olmadığı için Windows SmartScreen ilk açılışta uyarı verebilir. GitHub Release sayfasında yayınlanan SHA-256 özetini kontrol ederek güvenle çalıştırabilirsiniz.
- **Özet Doğrulama (PowerShell):**
  ```powershell
  Get-FileHash .\FormatSonrasiKurulum-v1.0.zip -Algorithm SHA256
  ```
- **Gizlilik:** Uygulama hiçbir telemetri, kullanıcı takibi veya kullanım analitiği toplamaz. Ağ bağlantıları yalnızca paket depoları (Microsoft WinGet CDN, Chocolatey, GitHub Releases ve ilgili yazılımların resmi siteleri) ile kurulur.

---

## Çalıştırma Yöntemleri

### 1. Dağıtım Paketini Çalıştırma (Son Kullanıcı)
GitHub Releases üzerinden indirilen arşivi açıp `FormatSonrasiKurulum.exe` veya `baslat.bat` dosyasını çalıştırın.

### 2. Kaynak Koddan Çalıştırma (Geliştirici)
Gereksinimler: Python 3.10+ ve Windows 10/11.

```powershell
# Bağımlılıkları yükleyin
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Uygulamayı başlatın
python main.py
```

### 3. Testleri Çalıştırma
```powershell
# Birim testleri çalıştırın
python -m unittest discover -v

# Katalog sözdizimi ve statik kuralları denetleyin
python catalog_check.py --offline
```

### 4. Yerel Olarak Paket Derleme
```powershell
python build_single_exe.py
```

---

## Nasıl Katkı Sağlanır? (Contributing)

Katkılarınızı memnuniyetle kabul ediyoruz! Projeye katkı sağlamak için aşağıdaki adımları izleyebilirsiniz:

1. **Depoyu Çatallayın (Fork) ve Klonlayın:**
   ```bash
   git clone https://github.com/<kullanici-adiniz>/Format-Sonrasi.git
   cd Format-Sonrasi
   ```

2. **Kataloğa Yeni Uygulama Ekleme:**
   - Katalog tanımları `data/catalog.json` dosyasında tutulmaktadır.
   - Yeni uygulama tanımını ilgili kategori ve ağırlık değerleriyle birlikte ekleyin:
     ```json
     {
       "id": "yeni_uygulama",
       "name": "Uygulama Adı",
       "desc": "Uygulama açıklaması.",
       "category": "developer",
       "winget_id": "Yayıncı.Uygulama",
       "weight": 2,
       "size_mb": 120,
       "profiles": ["developer"]
     }
     ```

3. **Doğrulama ve Testleri Çalıştırma:**
   - Değişikliklerinizin mevcut testleri bozmadığından emin olun:
     ```bash
     python -m unittest discover
     python catalog_check.py --offline
     ```

4. **Anlamlı Commit Mesajları ile PR Açın:**
   - Commit mesajlarınızı Conventional Commits standardına uygun olarak yazın (`feat: ...`, `fix: ...`, `docs: ...`).
   - Bir Pull Request (PR) açarak sunduğunuz geliştirmeyi kısaca açıklayın.
