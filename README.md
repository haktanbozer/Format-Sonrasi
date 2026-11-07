# Format Sonrası Kurulum Sihirbazı (Universal Edition v1.0)

Windows işletim sistemine format attıktan sonra ihtiyaç duyulan tüm temel, yazılımcı, mühendislik, tasarım, akademik ve sistem araçlarını tek tıkla, sessizce (arka planda) ve winget topluluk deposundaki en güncel sürümleriyle kuran kurumsal standartlarda masaüstü yönetim yazılımı. (Güvenlik ve bütünlük doğrulaması amacıyla RustDesk sürümü v1.5.1 ve SHA-256 özetine sabitlenmiştir).

Katalog bünyesinde **204 uygulama**, **14 ana kategori**, **14 sistem optimizasyon ayarı** ve **8 küratörlü hazır kullanım profili** yer almaktadır.

---

## Öne Çıkan Güvenilirlik ve Dayanıklılık Özellikleri

1. **Sistem Ön Kontrol Motoru (Pre-Flight Checks):**
   - Windows sürümü ve derleme numarası uygunluğu (Windows 10 1809+ / Windows 11; derleme >= 17763).
   - 64-bit işlemci ve işletim sistemi mimarisi teyidi.
   - Yönetici (Administrator) izni kontrolü ve bildirim entegrasyonu.
   - Gerçek DNS alan adı çözümlemesi ve `cdn.winget.microsoft.com` üzerinden 443 (HTTPS) erişim doğrulaması.
   - WinGet paket motoru erişilebilirlik ve sürüm doğrulaması.
   - `%SystemDrive%` üzerinde dinamik boş disk alanı güvencesi (seçilen uygulamaların toplam tahmini ağırlığına göre hesaplanır).
   - CBS ve Windows Update kaynaklı bekleyen yeniden başlatma tespiti.

2. **Kurulum Doğrulama Motoru (Post-Install Verifier):**
   - Yalnızca dönüş koduna (exit code) güvenilmez; sahte pozitifleri azaltan çok katmanlı doğrulama uygulanır.
   - Windows Kayıt Defteri (Uninstall HKLM/HKCU 32-bit ve 64-bit) DisplayName taraması lookaround regex ile yapılır (.NET, C++, Notepad++ gibi özel karakterli adlar çözülür).
   - Program Files ve AppData hedef dosya/yürütülebilir dosya varlığı kontrol edilir.
   - WhatsApp gibi modern Windows Mağazası / Appx paketlerinde açıkça tanımlı `appx_names` kuralları teyit edilir; diğer uygulamalarda sahte pozitif vermemesi için Appx taraması atlanır.
   - DISM `/English` parametresi ile sistem dilinden bağımsız özellik doğrulama (`NetFx3`).
   - WinGet sistem listesi üzerinden tam kimlik eşleşmesi teyit edilir.

3. **Yarım Kalan İşlemi Kurtarma (Session Manager):**
   - Elektrik kesintisi, ağ kopması veya plansız sistem kapanmalarında `session_state.json` dosyasına anlık durum ve tamamlanan paketler yazılır.
   - Uygulama yeniden başlatıldığında açık oturum otomatik tespit edilir ve kullanıcıya kalan paketleri kaldığı yerden devam ettirme imkanı sunulur.

4. **Yeniden Başlatma Yönetimi (Reboot Advisory):**
   - Yeniden başlatma gerektiren paketler (3010 kodu) tespit edildiğinde kurulum kuyruğu kesilmez; diğer işlemler tamamlanır ve oturum sonunda güvenli yeniden başlatma bildirimi verilir.

5. **Uygulama Çakışmaları Tespiti (Conflict Warnings):**
   - Dinamik `conflict_group` denetimi: Arşiv yöneticileri (7-Zip, NanaZip, PeaZip, Bandizip), ofis paketleri (ONLYOFFICE, LibreOffice, WPS Office), PDF okuyucular (Adobe Reader, Foxit Reader, PDFgear, SumatraPDF), codec paketleri (K-Lite Standard ve Mega) ve Visual Studio IDE sürümleri aynı anda seçildiğinde kullanıcı uyarılarak sistem çakışmaları önlenir.

6. **Sıklet ve Ağırlık Sıralaması (Deterministic Queue Sorting):**
   - Tier 1: Hafif Sıklet (< 15 MB)
   - Tier 2: Orta Sıklet (15 - 150 MB)
   - Tier 3: Ağır Sıklet (150 - 600 MB)
   - Tier 4: Süper Ağır Sıklet (> 600 MB)
   - Paketler ağı ve diski bloke etmeyecek şekilde hafiften ağıra sıralanır; yerel deterministik ağırlık modeli kullanılır.

7. **Windows İnce Ayarları ve Gerçek Geri Alma (True Rollback):**
   - 14 kurumsal optimizasyon ayarı: Klasik sağ tık menüsü, dosya uzantılarını gösterme, telemetri azaltma, Bing aramasını kapatma, widget gizleme, Nihai Performans Güç Planı (Ultimate Performance) açma, Hızlı Başlatma (Fast Startup) yönetimi, işlemci güç ayarı, WSL2 Ubuntu kurulumu, uzun dosya yolu desteğini açma (MAX_PATH 260+) ve görev çubuğu saatinde saniyeleri gösterme. Güvenli masaüstü karartmasını düşüren UAC gevşetme ayarları güvenlik ilkeleri gereği kaldırılmıştır.
   - Gerçek geri alma (`tweaks_backup.json`): Yapılan değişiklikler öncesi anahtarların orijinal durumu (değer, tür, yokluk durumu) yedeklenir. Geri alırken fabrika varsayılanına dönmek yerine kullanıcının önceki yapılandırması birebir geri yüklenir; klasik menü geri alınırken eklenen CLSID kayıtları diskten tamamen temizlenir.
   - *Not:* Uygulama farklı bir yönetici hesabı üzerinden çalıştırıldığında `HKCU` kayıtları o yönetici profilinin hive'ına yazılır.

8. **Kurumsal ve Güvenilir Paket Sağlama:**
   - Topluluk çalışma zamanları (`abbodi1406.vcredist` ve `klite_codec`), resmi Microsoft WinGet topluluk deposunda manifest/hash denetimlerinden geçmiş popüler AIO paketleridir.
   - Doğrudan indirilen ikili dosyalarda (Direct EXE) HTTPS zorunludur. Veri tabanında SHA-256 hash sabitlenmişse hash bütünlük özeti, aksi halde veya yayıncı tanımlıysa Microsoft Authenticode dijital imzası ve yayıncı doğrulaması (örn. Tim Kosse / Microsoft Corporation) denetlenir.

9. **Kurulum Günlüğü Dışa Aktarma (Log Export):**
   - Tüm süreçler ayrıntılı zaman damgalarıyla loglanır ve tek tıkla `.txt` veya `.log` dosyası olarak dışarı aktarılabilir.

10. **Sistem ve Donanım Bilgisi (Hardware & System Diagnostics):**
    - PowerShell `Get-CimInstance` çağrısıyla tek seferde CPU, GPU, RAM, disk, BIOS, kasa tipi ve işletim sistemi bilgilerini toplar; WbemScripting/wmic bağımlılığı yoktur.
    - SMBIOS standartlarına uygun kasa tipi tespiti (Dizüstü, Masaüstü, Mini PC, Stick PC, All-in-One, Sunucu, Sanal Makine) ve pil varlığı doğrulaması.
    - Fiziksel takılı bellek modüllerinin toplamı ile Windows işletim sisteminin kullanılabilir bellek alanı ayrımı (örn. `16 GB (Kullanılabilir: 15.2 GB)`).
    - Disk türleri (NVMe SSD, SATA SSD, Sabit HDD, Harici USB) ve çift formatlı kapasite gösterimi (üretici ondalık GB/TB ve ikili GiB).
    - Grafik kartı sürücü denetimi: Microsoft Temel Görüntü Bağdaştırıcısı devredeyse sürücü eksik uyarısı verir; sanal ekran bağdaştırıcıları (Parsec, DisplayLink, Uzak Masaüstü vb.) gerçek kartlardan ayırt edilerek etiketlenir ve sürücü eksik uyarısını tetiklemesi engellenir.
    - Güvenli seri numarası yönetimi: Varsayılan olarak maskeli gösterilir (`SN12********`); tek tıkla "Seriyi Kopyala" veya "Göster/Gizle" seçeneği bulunur. Bilinen üretici yer tutucuları ("To Be Filled By O.E.M.", "Default string" vb.) elenerek anakart serisine güvenli düşüş sağlanır.
    - Resmi üretici destek portalları (Dell, Lenovo, HP, Asus, MSI, Acer, Monster, Casper, Gigabyte, Apple, Microsoft Surface, Samsung, Huawei, LG); Dell Service Tag ile doğrudan ürün sürücü sayfasına yönlendirme; tek tıkla Windows Update ayarlarına erişim. URL güvenliği için alan adı beyaz listesi ve karakter enjeksiyon denetimi uygulanır. Sanal makinelerin (Hyper-V) Surface ile ezilmesi engellenmiştir.

---

## 8 Özel Hazır Profil

1. **Ev ve Temel Kullanıcı (10 Uygulama, ~0.3 GB):** Visual C++ AIO, .NET 10 Runtime, Chrome, 7-Zip, VLC, Everything, PDF24 vb.
2. **Yazılımcı ve Geliştirici (39 Uygulama, ~5.0 GB):** VS Code, VS Community 2026, Git, Python 3.14, Node.js, R, RStudio, JDK 21, Claude Desktop, Ollama, DBeaver, Postman, FileZilla, VC++ AIO vb.
3. **Mimar ve Mühendis (17 Uygulama, ~4.1 GB):** Autodesk DWG TrueView, FreeCAD, LibreCAD, KiCad EDA, QGIS Desktop, Ultimaker Cura, PrusaSlicer, MeshLab, Blender, PDF24, 7-Zip vb.
4. **Sistem ve Ağ Yönetimi (26 Uygulama, ~0.7 GB):** Microsoft Sysinternals Suite, Advanced IP Scanner, Nmap, MobaXterm, Rufus, Ventoy, AnyDesk, TeamViewer, Wireshark, VirtualBox vb.
5. **Grafik ve Video Kurgu (15 Uygulama, ~2.1 GB):** CapCut Desktop, Shotcut, Kdenlive, Krita, Inkscape, FontBase, GIMP, Paint.NET, Blender, OBS Studio, HandBrake, ShareX vb.
6. **Eğitim ve Araştırma (16 Uygulama, ~1.6 GB):** Zotero, Obsidian, Notion, Anki, GeoGebra, MiKTeX, OnlyOffice, PDF24, Chrome, Everything vb.
7. **Oyuncu Paketi (18 Uygulama, ~0.8 GB):** Steam, Epic Games, Discord, VC++ AIO, DirectX, .NET 3.5, Java 8, 7-Zip, Spotify, qBittorrent, Opera GX vb.
8. **Ofis ve Çalışma (13 Uygulama, ~1.3 GB):** ONLYOFFICE, Chrome, PDF24 Creator, 7-Zip, Zoom, WhatsApp, VC++ AIO vb.

---

## Güvenlik, Gizlilik ve Uyarılar

- **Windows SmartScreen Uyarısı (İmzasız İkili):** Dağıtım ikili dosyaları açık kaynaklı topluluk projesi olup pahalı ticari kod imzalama sertifikaları yerine SHA-256 bütünlük özetleri ve açık derleme manifestosu (`SHA256SUMS.txt`) ile korunmaktadır. Windows SmartScreen ("Windows bilgisayarınızı korudu") uyarısı verirse *"Ek bilgi"* -> *"Yine de çalıştır"* seçeneğiyle başlatabilirsiniz.
- **Oturum Kurtarma (`FormatSonrasiResume` ve `%ProgramData%\FormatSonrasi`):** Elektrik kesintisi veya plansız yeniden başlatmalarda yarım kalan kurulumun devam edebilmesi için `%ProgramData%\FormatSonrasi\bin` altında Administrators/SYSTEM kilitli güvenli bir kopya tutulur ve `onlogon` zamanlanmış görevi oluşturulur. Kurulum tamamlandığında veya iptal edildiğinde bu görev kaydı ve `%ProgramData%\FormatSonrasi\bin` altındaki kopyalanan ikili dosyalar temizlenir (yedek kayıtları ve indirilenler güvenli `%ProgramData%\FormatSonrasi` kökünde korunur).
- **Gizlilik Politikası (Telemetri Yok):** Uygulama hiçbir telemetri, analitik, kullanıcı takibi veya kullanım verisi toplamaz. Gerçekleşen ağ trafiği yalnızca Microsoft WinGet CDN (`cdn.winget.microsoft.com`), GitHub API / Releases, Chocolatey topluluk sunucuları (`community.chocolatey.org`) ve winget manifestlerindeki ilgili paketlerin resmi üretici sunucuları ile TLS/HTTPS üzerinden gerçekleşir.
- **Antivirüs ve Güvenlik Yazılımı Uyarıları (False Positive / PUA):** RustDesk, AnyDesk veya MobaXterm gibi uzak masaüstü ve yönetim araçları, bazı antivirüs yazılımları (Windows Defender, ESET vb.) tarafından uzaktan yönetim yetenekleri sebebiyle "Riskware" veya "Potentially Unwanted Application (PUA)" olarak işaretlenebilir. Bu bildirimler uygulamanın kendi yapısından değil, seçilen ilgili uzaktan erişim aracının işlevsellik profilinden kaynaklanmaktadır.
- **Sistem Düzeyi Değişiklik Uyarısı:** İnce ayarlar sistem kayıt defteri (`HKLM`/`HKCU`) ve sistem güç yönetimi bileşenlerine etki eder. Yapılan her ayar `tweaks_backup.json` dosyasına tam olarak yedeklenir ve "Tüm Ayarları Geri Al" butonu ile önceki durumuna eksiksiz döndürülebilir.

---

## Çalıştırma ve Derleme

- **Son Kullanıcı Modunda Çalıştırma:** `FormatSonrasiKurulum\FormatSonrasiKurulum.exe` veya doğrudan `baslat.bat` çift tıklanır.
  - *Güvenlik ve Bütünlük Tavsiyesi:* `--onedir` dağıtımlarında `_internal` altındaki kütüphanelerin kullanıcı yazılabilir dizinlerde manipülasyonunu engellemek için, kurumsal veya paylaşımlı ortamlarda klasörün yönetici izinli bir konuma (örn. `C:\Program Files\FormatSonrasi`) yerleştirilmesi önerilir.
  - *Kanal Dışı (Out-of-Band) Özet Doğrulama:* Arşivle aynı klasörde bulunan `.sha256` dosyaları tek başına yetersiz kalabileceğinden, dağıtım ZIP paketinin SHA-256 özeti mutlaka bağımsız bir kanal (GitHub Release notu, ayrı web sayfası veya GPG/minisign imzası) üzerinden teyit edilmelidir:
    ```cmd
    certutil -hashfile FormatSonrasiKurulum-v1.0.zip SHA256
    ```
    veya PowerShell ile:
    ```powershell
    Get-FileHash .\FormatSonrasiKurulum-v1.0.zip -Algorithm SHA256
    ```
    Klasör içi tüm dosyaların doğrulanması (Linux/Git Bash):
    ```bash
    sha256sum -c SHA256SUMS.txt
    ```
- **Geliştirici Modunda Çalıştırma:** Önce bağımlılıkları yükleyin: `python -m pip install -r requirements.txt`. Ardından `python main.py` veya `baslat.bat --python` komutuyla başlatın (klasörde derlenmiş exe olsa dahi doğrudan Python kaynak kodlarını çalıştırır).
  - *Güvenlik Uyarısı:* Geliştirici modunda Python betikleri ve modüller yerel çalışma dizininden yönetici haklarıyla yürütülür. Bu bayrak yalnızca geliştirme ve test amacıyla, güvenilir kaynak klasörlerinde kullanılmalıdır. Normal son kullanıcılar için daima bağımsız derlenmiş uygulama önerilir.
- **Hızlı Bağımsız (--onedir) Derleme:** `python build_single_exe.py`
  - Çıktı: `FormatSonrasiKurulum/FormatSonrasiKurulum.exe` (UAC Administrator onaylı, `%TEMP%` açma gecikmesi olmadan anında açılan bağımsız dağıtım paketi), `FormatSonrasiKurulum-v1.0.zip`, LF satır sonlu `SHA256SUMS.txt` ve `FormatSonrasiKurulum-v1.0.zip.sha256`.
