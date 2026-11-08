# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Profesyonel Masaüstü Arayüzü
Sade, modern ve kurumsal tasarım standardı.
"""

import os
import sys
import json
import time
import threading
import queue
import webbrowser
from typing import Optional
import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk

from apps_data import CATEGORIES, APPLICATIONS, PROFILES, CONFLICT_GROUPS
from installer_core import is_admin, request_admin_elevation, InstallationWorker, detect_installed_packages
from tweaks import TWEAKS, TWEAK_ACTIONS, restart_explorer, revert_all_tweaks
from system_checks import run_all_preflight_checks
from session_manager import SessionManager, SESSION_DIR
from verifier import verify_application_installed, get_all_installed_display_names
from hardware_info import get_system_hardware_info
from manufacturer_support import resolve_support_info
from version import VERSION_DISPLAY
from ui.app_row import AppItemRow
from app_logger import get_logger

logger = get_logger('gui')

ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class AppItemRow(tk.Frame):
    """
    Yüksek performanslı, düz native Tk satırı.
    Gereksiz ara çerçeve katmanları ve 1000+ olay bağlayıcısı kaldırılmış,
    doğrudan grid üzerinde çalışan ultra hızlı bileşen.
    """

    def __init__(self, master, app_data, on_toggle_callback, fonts=None, **kwargs):
        scale = getattr(ctk.ScalingTracker, "get_widget_scaling", lambda w: 1.0)(master)
        row_height = max(46, int(round(46 * scale)))
        super().__init__(
            master,
            height=row_height,
            bg="#1f2329",
            highlightthickness=1,
            highlightbackground="#282d35",
            **kwargs,
        )
        self.pack_propagate(False)
        self.grid_propagate(False)
        self.grid_columnconfigure(1, weight=1)

        self.app_data = app_data
        self.on_toggle_callback = on_toggle_callback
        self.is_installed = False
        self.visible = True
        self.selected = False
        self.theme_gen = 0
        self.fonts = fonts or {
            "title": ("Segoe UI", 10, "bold"),
            "tag": ("Segoe UI", 8, "bold"),
            "desc": ("Segoe UI", 9),
            "status": ("Segoe UI", 9),
        }

        # Onay kutusu
        self.box = tk.Label(
            self,
            text="☐",
            font=("Segoe UI Symbol", 13),
            cursor="hand2",
            bg="#1f2329",
            fg="#6b7280",
            width=2,
            anchor="center",
        )
        self.box.grid(row=0, column=0, rowspan=2, padx=(10, 4), sticky="w")
        self.box.bind("<Button-1>", lambda e: self.toggle())

        # Başlık etiketi
        self.title_label = tk.Label(
            self,
            text=app_data["name"],
            font=self.fonts["title"],
            fg="#f3f4f6",
            bg="#1f2329",
            anchor="w",
            cursor="hand2",
        )
        self.title_label.grid(row=0, column=1, sticky="w", pady=(2, 0))
        self.title_label.bind("<Button-1>", lambda e: self.toggle())

        # "Sistemde Mevcut" rozeti
        self.installed_tag = tk.Label(
            self,
            text="",
            font=self.fonts["tag"],
            fg="#10b981",
            bg="#1f2329",
            cursor="hand2",
        )
        self.installed_tag.grid(row=0, column=2, padx=6, sticky="w", pady=(2, 0))
        self.installed_tag.bind("<Button-1>", lambda e: self.toggle())

        # Açıklama etiketi
        self.desc_label = tk.Label(
            self,
            text=app_data["desc"],
            font=self.fonts["desc"],
            fg="#9ca3af",
            bg="#1f2329",
            anchor="w",
            cursor="hand2",
        )
        self.desc_label.grid(row=1, column=1, columnspan=2, sticky="w", pady=(0, 2))
        self.desc_label.bind("<Button-1>", lambda e: self.toggle())

        # Durum rozeti
        self.status_badge = tk.Label(
            self,
            text="",
            font=self.fonts["status"],
            fg="#6b7280",
            bg="#1f2329",
            width=12,
            anchor="e",
        )
        self.status_badge.grid(row=0, column=3, rowspan=2, padx=12, sticky="e")

        self.bind("<Button-1>", lambda e: self.toggle())

    def _apply_colors(self):
        is_dark = (ctk.get_appearance_mode() == "Dark")
        self.refresh_theme_fast(is_dark)

    def refresh_theme_fast(self, is_dark: bool, gen: Optional[int] = None):
        if gen is not None:
            self.theme_gen = gen
        bg = ("#262c36" if self.selected else "#1f2329") if is_dark else ("#dbeafe" if self.selected else "#f9fafb")
        border = ("#2563eb" if self.selected else "#282d35") if is_dark else ("#3b82f6" if self.selected else "#e5e7eb")
        fg_title = "#ffffff" if is_dark else "#111827"
        fg_desc = "#9ca3af" if is_dark else "#6b7280"
        box_fg = ("#3b82f6" if self.selected else "#6b7280") if is_dark else ("#2563eb" if self.selected else "#9ca3af")

        self.configure(bg=bg, highlightbackground=border)
        self.box.configure(bg=bg, text="☑" if self.selected else "☐", fg=box_fg)
        self.title_label.configure(bg=bg, fg=fg_title)
        self.installed_tag.configure(bg=bg)
        self.desc_label.configure(bg=bg, fg=fg_desc)
        self.status_badge.configure(bg=bg)

    def refresh_theme(self, gen: int):
        is_dark = (ctk.get_appearance_mode() == "Dark")
        self.refresh_theme_fast(is_dark, gen)

    def update_theme(self, mode: str):
        self._apply_colors()

    def toggle(self):
        self.set_selected(not self.selected)

    def set_selected(self, selected: bool, notify: bool = True):
        if selected == self.selected:
            return
        self.selected = selected
        self._apply_colors()
        if notify:
            self.on_toggle_callback(self.app_data["id"], selected)

    def mark_installed(self, installed: bool):
        if installed == self.is_installed:
            return
        self.is_installed = installed
        if installed:
            self.installed_tag.configure(text="Sistemde Mevcut")
        else:
            self.installed_tag.configure(text="")

    def set_status(self, status: str, color_type: str = "normal"):
        color_map = {
            "normal": "#6b7280",
            "working": "#3b82f6",
            "success": "#10b981",
            "error": "#ef4444",
        }
        self.status_badge.configure(text=status, fg=color_map.get(color_type, "#6b7280"))


class MainWindow(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Windows Kurulum ve Yapılandırma Yöneticisi")
        self.geometry("1160x780")
        self.minsize(980, 640)
        self._deactivate_windows_window_header_manipulation = True

        # Durum değişkenleri
        self.selected_apps = set()
        self.app_rows = {}
        self.category_count_labels = {}
        self.installed_set = set()
        self.current_category_filter = "all"
        self.worker = None
        self._search_timer = None
        self._theme_gen = 0
        self._tweaks_built = False
        self._hardware_built = False
        self._hardware_loaded = False
        self._hardware_info = None
        self._show_serial_unmasked = False
        self.log_history = []
        self._log_q = queue.SimpleQueue()
        self._ui_q = queue.SimpleQueue()
        self._all_installed_found = set()

        # Paylaşımlı font havuzu (500+ CTkFont yerine 4 adet ortak nesne)
        self.fonts = {
            "title": ctk.CTkFont(size=12, weight="bold"),
            "tag": ctk.CTkFont(size=10, weight="bold"),
            "desc": ctk.CTkFont(size=11),
            "status": ctk.CTkFont(size=11),
        }

                # Açılışta önceki oturumlardan kalan artık geçici dosyaları temizle
        SessionManager.cleanup_stale_temp_files()
        self._build_top_bar()
        self._build_body_layout()
        self._build_bottom_bar()

        # Log ve UI kuyruğu dinleyicilerini başlat (Tümüyle iş parçacığı güvenli mimari)
        self.after(100, self._poll_logs)
        self.after(30, self._poll_ui_queue)

    def dispatch_ui(self, fn, *args, **kwargs):
        """Worker thread'lerden UI güncellemelerini thread-safe kuyruğa ekler."""
        self._ui_q.put((fn, args, kwargs))

    def _poll_ui_queue(self):
        """Ana iş parçacığında UI kuyruğundaki bekleyen işleri tüketir."""
        while not self._ui_q.empty():
            try:
                fn, args, kwargs = self._ui_q.get_nowait()
                fn(*args, **kwargs)
            except Exception as e:
                sys.stderr.write(f"[UYARI] UI kuyruk görevi hatası: {e}\n")
        try:
            self.after(30, self._poll_ui_queue)
        except Exception as e:
            logger.debug(f"_poll_ui_queue sonlandırıldı: {e}")

    def _build_top_bar(self):
        top = ctk.CTkFrame(self, height=60, corner_radius=0, fg_color=("gray88", "#16191d"))
        top.pack(fill="x", padx=0, pady=0)
        top.pack_propagate(False)

        title_frame = ctk.CTkFrame(top, fg_color="transparent")
        title_frame.pack(side="left", padx=20, pady=12)

        title = ctk.CTkLabel(
            title_frame,
            text="Kurulum Yöneticisi",
            font=ctk.CTkFont(size=18, weight="bold"),
        )
        title.pack(side="left")

        version_badge = ctk.CTkLabel(
            title_frame,
            text=VERSION_DISPLAY,
            font=ctk.CTkFont(size=11),
            text_color=("gray45", "gray60"),
        )
        version_badge.pack(side="left", padx=(8, 0), pady=(3, 0))

        right_actions = ctk.CTkFrame(top, fg_color="transparent")
        right_actions.pack(side="right", padx=16, pady=12)

        self.is_admin_user = is_admin()
        self.elevation_mismatch = detect_elevation_user_mismatch()
        if self.elevation_mismatch:
            p_user, c_user = self.elevation_mismatch
            mismatch_lbl = ctk.CTkLabel(
                right_actions,
                text=f"Oturum: {p_user} ({c_user})",
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color="#f59e0b",
            )
            mismatch_lbl.pack(side="left", padx=4)

        if self.is_admin_user:
            admin_lbl = ctk.CTkLabel(
                right_actions,
                text="Yönetici Yetkisi",
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color="#10b981",
            )
            admin_lbl.pack(side="left", padx=8)
        else:
            admin_btn = ctk.CTkButton(
                right_actions,
                text="Yönetici Olarak Başlat",
                width=140,
                height=28,
                fg_color="#f59e0b",
                hover_color="#d97706",
                text_color="black",
                font=ctk.CTkFont(size=11, weight="bold"),
                command=self._elevate_admin,
            )
            admin_btn.pack(side="left", padx=8)

        self.theme_btn = ctk.CTkButton(
            right_actions,
            text="Tema Değiştir",
            width=90,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color=("gray75", "#2a3038"),
            hover_color=("gray65", "#373e48"),
            command=self._toggle_theme,
        )
        self.theme_btn.pack(side="left", padx=(4, 0))

    def _build_body_layout(self):
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=0, pady=0)

        # ------------------ SOL KENAR ÇUBUĞU (KATEGORİLER) ------------------
        self.sidebar = ctk.CTkFrame(body, width=240, corner_radius=0, fg_color=("gray92", "#1a1d22"))
        self.sidebar.pack(side="left", fill="y", padx=0, pady=0)
        self.sidebar.pack_propagate(False)

        side_title = ctk.CTkLabel(
            self.sidebar,
            text="KATEGORİLER",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=("gray50", "gray55"),
            anchor="w",
        )
        side_title.pack(fill="x", padx=18, pady=(16, 8))

        self.cat_buttons_frame = ctk.CTkScrollableFrame(self.sidebar, corner_radius=0, fg_color="transparent")
        self.cat_buttons_frame.pack(fill="both", expand=True, padx=4, pady=0)

        # Tüm Programlar butonu
        self.cat_btns = {}
        all_btn = ctk.CTkButton(
            self.cat_buttons_frame,
            text="Tüm Programlar",
            anchor="w",
            height=34,
            corner_radius=4,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#2563eb",
            command=lambda: self._select_category_view("all"),
        )
        all_btn.pack(fill="x", padx=6, pady=2)
        self.cat_btns["all"] = all_btn

        for cat in CATEGORIES:
            cid = cat["id"]
            count = len([a for a in APPLICATIONS if a["category"] == cid])
            btn = ctk.CTkButton(
                self.cat_buttons_frame,
                text=f"{cat['name']} ({count})",
                anchor="w",
                height=32,
                corner_radius=4,
                font=ctk.CTkFont(size=12),
                fg_color="transparent",
                text_color=("gray20", "gray85"),
                hover_color=("gray85", "#242930"),
                command=lambda c=cid: self._select_category_view(c),
            )
            btn.pack(fill="x", padx=6, pady=1)
            self.cat_btns[cid] = btn

        # Alt kısım: İnce Ayarlar Menü Butonu
        tweak_btn = ctk.CTkButton(
            self.sidebar,
            text="Windows İnce Ayarları",
            anchor="w",
            height=36,
            corner_radius=4,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=("gray80", "#272c34"),
            hover_color=("gray70", "#323842"),
            command=self._show_tweaks_view,
        )
        tweak_btn.pack(fill="x", padx=10, pady=(12, 4))
        self.tweak_nav_btn = tweak_btn

        # Alt kısım: Sistem Bilgisi Menü Butonu
        hw_btn = ctk.CTkButton(
            self.sidebar,
            text="Sistem ve Donanım",
            anchor="w",
            height=36,
            corner_radius=4,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color=("gray80", "#272c34"),
            hover_color=("gray70", "#323842"),
            command=self._show_hardware_view,
        )
        hw_btn.pack(fill="x", padx=10, pady=(0, 10))
        self.hw_nav_btn = hw_btn

        # ------------------ SAĞ İÇERİK ALANI ------------------
        self.content_container = ctk.CTkFrame(body, fg_color="transparent")
        self.content_container.pack(side="left", fill="both", expand=True, padx=0, pady=0)

        # Görünüm 1: Program Listesi Görünümü
        self.apps_view = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self.apps_view.pack(fill="both", expand=True, padx=0, pady=0)

        # Görünüm 2: İnce Ayarlar Görünümü (Tembel yükleme: buton tıklandığında inşa edilir)
        self.tweaks_view = ctk.CTkFrame(self.content_container, fg_color="transparent")

        # Görünüm 3: Donanım ve Sistem Bilgisi (Tembel yükleme: buton tıklandığında inşa edilir)
        self.hardware_view = ctk.CTkFrame(self.content_container, fg_color="transparent")

        self._build_apps_view_content()

    def _build_apps_view_content(self):
        # Üst Araç Çubuğu: Arama, Hazır Profil, Toplu Aksiyonlar
        toolbar = ctk.CTkFrame(self.apps_view, height=48, corner_radius=0, fg_color=("gray90", "#181b20"))
        toolbar.pack(fill="x", padx=0, pady=0)
        toolbar.pack_propagate(False)

        # Arama kutusu
        self.search_var = ctk.StringVar()
        self.search_var.trace_add("write", lambda *args: self._on_search_debounced())
        self.search_entry = ctk.CTkEntry(
            toolbar,
            placeholder_text="Program ara...",
            width=200,
            height=30,
            font=ctk.CTkFont(size=12),
            textvariable=self.search_var,
        )
        self.search_entry.pack(side="left", padx=14, pady=9)

        # Hazır Paket Açılır Kutusu
        p_label = ctk.CTkLabel(toolbar, text="Hazır Paket:", font=ctk.CTkFont(size=12))
        p_label.pack(side="left", padx=(6, 4))

        self.profile_names = [p["name"] for p in PROFILES]
        self.profile_var = ctk.StringVar(value=self.profile_names[0])
        self.profile_dropdown = ctk.CTkOptionMenu(
            toolbar,
            values=self.profile_names,
            variable=self.profile_var,
            width=200,
            height=30,
            font=ctk.CTkFont(size=12),
            command=self._on_profile_selected,
            fg_color="#2563eb",
            button_color="#1d4ed8",
        )
        self.profile_dropdown.pack(side="left", padx=4)

        # Sağ Taraftaki Yardımcı Butonlar
        btn_clear = ctk.CTkButton(
            toolbar,
            text="Seçimi Temizle",
            width=95,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color=("gray75", "#2e343d"),
            hover_color=("gray65", "#39404b"),
            command=self.clear_selection,
        )
        btn_clear.pack(side="right", padx=(4, 14))

        btn_failed = ctk.CTkButton(
            toolbar,
            text="Başarısızları Seç",
            width=115,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color=("gray75", "#2e343d"),
            hover_color=("gray65", "#39404b"),
            command=self.load_failed_apps,
        )
        btn_failed.pack(side="right", padx=4)

        btn_select_all = ctk.CTkButton(
            toolbar,
            text="Görünenleri Seç",
            width=100,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color=("gray75", "#2e343d"),
            hover_color=("gray65", "#39404b"),
            command=self.select_visible,
        )
        btn_select_all.pack(side="right", padx=4)

        btn_uncheck_inst = ctk.CTkButton(
            toolbar,
            text="Kurulu Olanları Ayıkla",
            width=135,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color=("gray75", "#2e343d"),
            hover_color=("gray65", "#39404b"),
            command=self.uncheck_installed,
        )
        btn_uncheck_inst.pack(side="right", padx=4)

        btn_save_prof = ctk.CTkButton(
            toolbar,
            text="Dışa Aktar",
            width=80,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color=("gray75", "#2e343d"),
            hover_color=("gray65", "#39404b"),
            command=self.export_profile_json,
        )
        btn_save_prof.pack(side="right", padx=4)

        btn_load_prof = ctk.CTkButton(
            toolbar,
            text="İçe Aktar",
            width=75,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color=("gray75", "#2e343d"),
            hover_color=("gray65", "#39404b"),
            command=self.import_profile_json,
        )
        btn_load_prof.pack(side="right", padx=4)

        # Kaydırılabilir Liste
        self.apps_scroll = ctk.CTkScrollableFrame(self.apps_view, corner_radius=0, fg_color="transparent")
        self.apps_scroll.pack(fill="both", expand=True, padx=12, pady=10)
        self.apps_scroll.grid_columnconfigure(0, weight=1)

        # Tam ekran yaparken 129 satırın ara çözünürlüklerde tekrar tekrar
        # hesaplanarak donma (yükleme gecikmesi) yapmasını önleyen debounced boyutlandırıcı
        self._scroll_fit_timer = None

        def _debounced_fit_scroll(event):
            if self._scroll_fit_timer:
                try:
                    self.after_cancel(self._scroll_fit_timer)
                except Exception:
                    pass

            def _do_fit():
                try:
                    canvas = self.apps_scroll._parent_canvas
                    cw = canvas.winfo_width()
                    if cw > 50:
                        canvas.itemconfigure(self.apps_scroll._create_window_id, width=cw)
                except Exception:
                    pass

            self._scroll_fit_timer = self.after(35, _do_fit)

        self.apps_scroll._parent_canvas.bind("<Configure>", _debounced_fit_scroll)

        # Satırları gruplar halinde oluştur (pencere anında açılır, donma yaşanmaz)
        self._pending_apps_queue = list(enumerate(APPLICATIONS))
        self._batch_create_rows(batch_size=20)

    def _batch_create_rows(self, batch_size: int = 20):
        """Uygulama satırlarını 20'şerli gruplarla oluşturarak UI döngüsünü serbest bırakır."""
        if not hasattr(self, "_pending_apps_queue") or not self._pending_apps_queue:
            self._on_rows_ready()
            return

        batch = self._pending_apps_queue[:batch_size]
        self._pending_apps_queue = self._pending_apps_queue[batch_size:]

        for idx, app in batch:
            row = AppItemRow(
                self.apps_scroll,
                app,
                on_toggle_callback=self._on_app_toggled,
                fonts=self.fonts,
            )
            row.grid(row=idx, column=0, sticky="ew", padx=4, pady=2)
            row.visible = True
            self.app_rows[app["id"]] = row

        if self._pending_apps_queue:
            self.after(1, lambda: self._batch_create_rows(batch_size))
        else:
            self._on_rows_ready()

    def _on_rows_ready(self):
        if getattr(self, "_rows_ready_done", False):
            return
        self._rows_ready_done = True

        if SessionManager.get_interrupted_session() is None:
            self.apply_profile("basic")  # yarım oturum varsa varsayılanı ezme
        self._on_filter_changed()  # aktif filtreyi yeni satırlara uygula
        # Açılışta UI çizimini engellememek için arka plan paket taramasını 1.5 sn gecikmeyle başlat
        self.after(1500, lambda: threading.Thread(target=self._detect_installed_background_worker, daemon=True).start())
        self.after(100, self._check_resume_session)

    def _build_tweaks_view_content(self):
        head = ctk.CTkFrame(self.tweaks_view, height=48, corner_radius=0, fg_color=("gray90", "#181b20"))
        head.pack(fill="x", padx=0, pady=0)
        head.pack_propagate(False)

        title = ctk.CTkLabel(
            head,
            text="Windows İnce Ayarları ve Sistem Optimizasyonu",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        title.pack(side="left", padx=16, pady=12)

        # Kapsam Seçici (Tüm Bilgisayar vs Sadece Mevcut Kullanıcı)
        scope_frame = ctk.CTkFrame(head, fg_color="transparent")
        scope_frame.pack(side="left", padx=20)

        scope_lbl = ctk.CTkLabel(scope_frame, text="Kapsam:", font=ctk.CTkFont(size=11, weight="bold"), text_color=("gray30", "gray70"))
        scope_lbl.pack(side="left", padx=(0, 6))

        self.tweak_scope_var = ctk.StringVar(value="all")
        self.scope_menu = ctk.CTkOptionMenu(
            scope_frame,
            values=["Tüm Bilgisayar (Sistem Geneli)", "Sadece Mevcut Kullanıcı"],
            font=ctk.CTkFont(size=11),
            width=210,
            height=28,
            fg_color="#1e293b",
            button_color="#334155",
            command=self._on_tweak_scope_changed,
        )
        self.scope_menu.pack(side="left")

        back_btn = ctk.CTkButton(
            head,
            text="Program Listesine Dön",
            width=140,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color="#2563eb",
            command=self._show_apps_view,
        )
        back_btn.pack(side="right", padx=16, pady=10)

        scroll = ctk.CTkScrollableFrame(self.tweaks_view, corner_radius=0, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=14, pady=10)

        self.tweak_vars = {}
        for tw in TWEAKS:
            t_id = tw["id"]
            var = ctk.BooleanVar(value=tw.get("default", True))
            self.tweak_vars[t_id] = var

            card = ctk.CTkFrame(scroll, corner_radius=6, fg_color=("gray92", "#1f2329"), border_width=1, border_color=("gray80", "#2d333b"))
            card.pack(fill="x", padx=4, pady=4)

            cb = ctk.CTkCheckBox(
                card,
                text=tw["name"],
                variable=var,
                font=ctk.CTkFont(size=13, weight="bold"),
                checkbox_width=18,
                checkbox_height=18,
                corner_radius=3,
            )
            cb.pack(anchor="w", padx=14, pady=(10, 2))

            d_lbl = ctk.CTkLabel(
                card,
                text=tw["desc"],
                font=ctk.CTkFont(size=11),
                text_color=("gray45", "gray65"),
                anchor="w",
            )
            d_lbl.pack(anchor="w", padx=42, pady=(0, 10))

        btn_box = ctk.CTkFrame(scroll, fg_color="transparent")
        btn_box.pack(fill="x", padx=4, pady=16)

        apply_btn = ctk.CTkButton(
            btn_box,
            text="Seçili Ayarları Uygula",
            font=ctk.CTkFont(size=13, weight="bold"),
            height=36,
            fg_color="#10b981",
            hover_color="#059669",
            command=self._apply_tweaks,
        )
        apply_btn.pack(side="left", padx=(0, 8))

        restart_exp_btn = ctk.CTkButton(
            btn_box,
            text="Windows Gezginini Yeniden Başlat",
            font=ctk.CTkFont(size=12),
            height=36,
            fg_color=("gray75", "#2e343d"),
            hover_color=("gray65", "#39404b"),
            command=self._restart_explorer_action,
        )
        restart_exp_btn.pack(side="left", padx=8)

        revert_btn = ctk.CTkButton(
            btn_box,
            text="Ayarları Varsayılana Döndür (Geri Al)",
            font=ctk.CTkFont(size=12),
            height=36,
            fg_color="#dc2626",
            hover_color="#b91c1c",
            command=self._revert_tweaks,
        )
        revert_btn.pack(side="left", padx=8)

    def _build_hardware_view_content(self):
        head = ctk.CTkFrame(self.hardware_view, height=48, corner_radius=0, fg_color=("gray90", "#181b20"))
        head.pack(fill="x", padx=0, pady=0)
        head.pack_propagate(False)

        title = ctk.CTkLabel(
            head,
            text="Sistem ve Donanım Bilgisi",
            font=ctk.CTkFont(size=14, weight="bold"),
        )
        title.pack(side="left", padx=16, pady=12)

        self.hw_refresh_btn = ctk.CTkButton(
            head,
            text="Yeniden Tara",
            width=100,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color=("gray75", "#2e343d"),
            command=self._load_hardware_async,
        )
        self.hw_refresh_btn.pack(side="right", padx=(6, 16), pady=10)

        back_btn = ctk.CTkButton(
            head,
            text="Program Listesine Dön",
            width=140,
            height=28,
            font=ctk.CTkFont(size=11),
            fg_color="#2563eb",
            command=self._show_apps_view,
        )
        back_btn.pack(side="right", padx=6, pady=10)

        # Alt Gövde: Kaydırılabilir Kart Alanı
        self.hw_scroll = ctk.CTkScrollableFrame(self.hardware_view, corner_radius=0, fg_color="transparent")
        self.hw_scroll.pack(fill="both", expand=True, padx=14, pady=10)

        # Yükleniyor Göstergesi
        self.hw_loading_label = ctk.CTkLabel(
            self.hw_scroll,
            text="Donanım bilgileri okunuyor, lütfen bekleyin...",
            font=ctk.CTkFont(size=13),
            text_color=("gray40", "gray70"),
        )
        self.hw_loading_label.pack(pady=40)

        # Kart konteyneri
        self.hw_cards_frame = ctk.CTkFrame(self.hw_scroll, fg_color="transparent")

        # Alt Aksiyon Çubuğu
        hw_action_bar = ctk.CTkFrame(self.hardware_view, height=52, corner_radius=0, fg_color=("gray90", "#181b20"))
        hw_action_bar.pack(fill="x", padx=0, pady=0)
        hw_action_bar.pack_propagate(False)

        btn_box = ctk.CTkFrame(hw_action_bar, fg_color="transparent")
        btn_box.pack(side="left", padx=14, pady=8)

        self.hw_copy_btn = ctk.CTkButton(
            btn_box,
            text="Özet Bilgiyi Kopyala",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=34,
            fg_color="#2563eb",
            command=self._copy_hardware_summary,
        )
        self.hw_copy_btn.pack(side="left", padx=(0, 8))

        self.hw_support_btn = ctk.CTkButton(
            btn_box,
            text="Resmi Destek Sayfası",
            font=ctk.CTkFont(size=12),
            height=34,
            fg_color=("gray75", "#2e343d"),
            command=self._open_manufacturer_support,
        )
        self.hw_support_btn.pack(side="left", padx=8)

        self.hw_wu_btn = ctk.CTkButton(
            btn_box,
            text="Windows Update Aç",
            font=ctk.CTkFont(size=12),
            height=34,
            fg_color=("gray75", "#2e343d"),
            command=self._open_windows_update,
        )
        self.hw_wu_btn.pack(side="left", padx=8)

        self.hw_status_lbl = ctk.CTkLabel(
            hw_action_bar,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=("gray30", "gray75"),
            anchor="e",
        )
        self.hw_status_lbl.pack(side="right", padx=16, pady=12)

    def _load_hardware_async(self):
        self._hardware_loaded = True
        if hasattr(self, "hw_refresh_btn"):
            self.hw_refresh_btn.configure(state="disabled")
        if hasattr(self, "hw_loading_label"):
            self.hw_loading_label.pack(pady=40)
        if hasattr(self, "hw_cards_frame"):
            self.hw_cards_frame.pack_forget()
        if hasattr(self, "hw_status_lbl"):
            self.hw_status_lbl.configure(text="Sistem bilgileri taranıyor...")
        threading.Thread(target=self._hardware_worker, daemon=True).start()

    def _hardware_worker(self):
        try:
            info = get_system_hardware_info(timeout_sec=25)
            self.dispatch_ui(self._populate_hardware_ui, info)
        except Exception as e:
            self.dispatch_ui(self._on_hardware_error, str(e))

    def _on_hardware_error(self, err_msg: str):
        if hasattr(self, "hw_refresh_btn"):
            self.hw_refresh_btn.configure(state="normal")
        if hasattr(self, "hw_loading_label"):
            self.hw_loading_label.pack_forget()
        if hasattr(self, "hw_status_lbl"):
            self.hw_status_lbl.configure(text=f"Donanım bilgisi alınamadı: {err_msg}")

    def _populate_hardware_ui(self, info: dict):
        if hasattr(self, "hw_refresh_btn"):
            self.hw_refresh_btn.configure(state="normal")
        self._hardware_info = info
        if hasattr(self, "hw_loading_label"):
            self.hw_loading_label.pack_forget()

        # Eski kartları temizle
        for child in self.hw_cards_frame.winfo_children():
            child.destroy()

        self.hw_cards_frame.pack(fill="both", expand=True)

        def _make_card(title_text: str):
            c = ctk.CTkFrame(self.hw_cards_frame, corner_radius=6, fg_color=("gray92", "#1f2329"), border_width=1, border_color=("gray80", "#2d333b"))
            c.pack(fill="x", padx=4, pady=6)
            h = ctk.CTkLabel(c, text=title_text, font=ctk.CTkFont(size=13, weight="bold"), anchor="w")
            h.pack(fill="x", padx=14, pady=(10, 6))
            return c

        def _add_kv(parent, k_text, v_text, is_warn=False, extra_fn=None):
            row = ctk.CTkFrame(parent, fg_color="transparent")
            row.pack(fill="x", padx=14, pady=2)
            k = ctk.CTkLabel(row, text=k_text, width=150, anchor="w", font=ctk.CTkFont(size=12, weight="bold"), text_color=("gray35", "gray65"))
            k.pack(side="left")
            color = "#ef4444" if is_warn else ("gray10", "gray95")
            v = ctk.CTkLabel(row, text=v_text, anchor="w", font=ctk.CTkFont(size=12), text_color=color)
            v.pack(side="left", fill="x", expand=True)
            if extra_fn:
                extra_fn(row)
            return v

        # Kart 1: Sistem ve Anakart
        c1 = _make_card("Sistem ve Anakart")
        _add_kv(c1, "Üretici:", info.get("manufacturer", "Bilinmiyor"))
        _add_kv(c1, "Model:", info.get("model", "Bilinmiyor"))
        if info.get("sku"):
            _add_kv(c1, "SKU / Ürün Kodu:", info.get("sku"))
        _add_kv(c1, "Kasa Tipi:", info.get("chassis", "Standart Sistem"))

        # Seri numarası satırı (Göster / Gizle ve Seriyi Kopyala düğmeli)
        def _add_mask_button(row):
            if info.get("has_valid_serial"):
                copy_btn = ctk.CTkButton(
                    row,
                    text="Seriyi Kopyala",
                    width=85,
                    height=22,
                    font=ctk.CTkFont(size=10),
                    fg_color=("gray75", "#2e343d"),
                    command=self._copy_unmasked_serial,
                )
                copy_btn.pack(side="right", padx=(6, 0))

                btn = ctk.CTkButton(
                    row,
                    text="Göster",
                    width=55,
                    height=22,
                    font=ctk.CTkFont(size=10),
                    fg_color=("gray75", "#2e343d"),
                    command=self._toggle_serial_mask,
                )
                btn.pack(side="right", padx=(8, 0))
                self.hw_mask_btn = btn

        self.hw_serial_val_lbl = _add_kv(c1, "Seri Numarası:", info.get("masked_serial", ""), extra_fn=_add_mask_button)
        _add_kv(c1, "BIOS Sürümü:", info.get("bios_version", "Bilinmiyor"))
        _add_kv(c1, "İşletim Sistemi:", info.get("os_display", "Windows"))

        # Kart 2: İşlemci ve Bellek
        c2 = _make_card("İşlemci ve Bellek (CPU & RAM)")
        _add_kv(c2, "İşlemci (CPU):", info.get("cpu", "Bilinmiyor"))
        _add_kv(c2, "Bellek (RAM):", info.get("ram_detail", info.get("ram_total", "Bilinmiyor")))

        # Kart 3: Grafik Kartları (GPU)
        c3 = _make_card("Grafik Kartları (Ekran Kartı / GPU)")
        gpus = info.get("gpus", [])
        if gpus:
            for idx, g in enumerate(gpus, 1):
                warn = g.get("warning", "")
                is_virt = g.get("is_virtual", False)
                virt_tag = " (Sanal Bağdaştırıcı)" if is_virt else ""
                detail = f"{g['name']}{virt_tag} (Sürücü Sürümü: {g['driver']})"
                _add_kv(c3, f"Ekran Kartı {idx}:", detail)
                if warn:
                    _add_kv(c3, "Durum:", warn, is_warn=True)
        else:
            _add_kv(c3, "Ekran Kartı:", "Bilinmiyor")

        # Kart 4: Depolama Birimleri (Diskler)
        c4 = _make_card("Depolama Birimleri (Disk Sürücüleri)")
        disks = info.get("disks", [])
        if disks:
            for idx, d in enumerate(disks, 1):
                d_info = f"{d['name']} [{d['type']}] - Kapasite: {d['size_dec']} ({d['size_bin']})"
                _add_kv(c4, f"Disk {idx}:", d_info)
        else:
            _add_kv(c4, "Depolama:", "Bilinmiyor")

        if hasattr(self, "hw_status_lbl"):
            self.hw_status_lbl.configure(text="Donanım bilgileri başarıyla güncellendi.")

    def _toggle_serial_mask(self):
        if not self._hardware_info:
            return
        self._show_serial_unmasked = not self._show_serial_unmasked
        if hasattr(self, "hw_serial_val_lbl"):
            txt = self._hardware_info["display_serial"] if self._show_serial_unmasked else self._hardware_info["masked_serial"]
            self.hw_serial_val_lbl.configure(text=txt)
        if hasattr(self, "hw_mask_btn"):
            self.hw_mask_btn.configure(text="Gizle" if self._show_serial_unmasked else "Göster")

    def _copy_unmasked_serial(self):
        if not self._hardware_info:
            return
        serial = self._hardware_info.get("serial_number") or self._hardware_info.get("display_serial", "")
        if serial and not serial.startswith("Okunamadı"):
            try:
                self.clipboard_clear()
                self.clipboard_append(serial)
                if hasattr(self, "hw_status_lbl"):
                    self.hw_status_lbl.configure(text="Seri numarası panoya kopyalandı.")
            except Exception as e:
                if hasattr(self, "hw_status_lbl"):
                    self.hw_status_lbl.configure(text=f"Panoya kopyalanamadı: {e}")

    def _copy_hardware_summary(self):
        if not self._hardware_info:
            if hasattr(self, "hw_status_lbl"):
                self.hw_status_lbl.configure(text="Donanım bilgisi henüz hazır değil.")
            return
        text = self._hardware_info.get("clipboard_text", "")
        if text:
            try:
                self.clipboard_clear()
                self.clipboard_append(text)
                if hasattr(self, "hw_status_lbl"):
                    self.hw_status_lbl.configure(text="Tüm donanım özeti panoya kopyalandı.")
            except Exception as e:
                if hasattr(self, "hw_status_lbl"):
                    self.hw_status_lbl.configure(text=f"Panoya kopyalanamadı: {e}")

    def _open_manufacturer_support(self):
        if not self._hardware_info:
            if hasattr(self, "hw_status_lbl"):
                self.hw_status_lbl.configure(text="Donanım bilgisi henüz hazır değil.")
            return
        info = self._hardware_info
        res = resolve_support_info(
            manufacturer=info.get("manufacturer", ""),
            model=info.get("model", ""),
            serial_number=info.get("serial_number", ""),
            is_vm=info.get("is_vm", False),
        )
        if res.get("clipboard_text"):
            try:
                self.clipboard_clear()
                self.clipboard_append(res["clipboard_text"])
            except Exception as e:
                logger.debug(f"Panoya kopyalanamadı: {e}")

        status_msg = res.get("status_message", "")
        if hasattr(self, "hw_status_lbl"):
            self.hw_status_lbl.configure(text=status_msg)

        if res.get("can_open") and res.get("url"):
            try:
                webbrowser.open(res["url"])
            except Exception as e:
                if hasattr(self, "hw_status_lbl"):
                    self.hw_status_lbl.configure(text=f"Tarayıcı açılamadı: {e}")

    def _open_windows_update(self):
        try:
            os.startfile("ms-settings:windowsupdate")
            if hasattr(self, "hw_status_lbl"):
                self.hw_status_lbl.configure(text="Windows Update ayarları açıldı.")
        except Exception as e:
            if hasattr(self, "hw_status_lbl"):
                self.hw_status_lbl.configure(text=f"Açılamadı: {e}")

    def _build_bottom_bar(self):
        bottom = ctk.CTkFrame(self, fg_color=("gray88", "#16191d"), corner_radius=0)
        bottom.pack(fill="x", padx=0, pady=0)

        bar = ctk.CTkFrame(bottom, fg_color="transparent")
        bar.pack(fill="x", padx=16, pady=8)

        self.count_label = ctk.CTkLabel(
            bar,
            text="Seçilen: 0 Program",
            font=ctk.CTkFont(size=13, weight="bold"),
            width=130,
            anchor="w",
        )
        self.count_label.pack(side="left")

        mid_box = ctk.CTkFrame(bar, fg_color="transparent")
        mid_box.pack(side="left", fill="x", expand=True, padx=16)

        self.status_label = ctk.CTkLabel(
            mid_box,
            text="Hazır.",
            font=ctk.CTkFont(size=11),
            text_color=("gray40", "gray60"),
            anchor="w",
        )
        self.status_label.pack(fill="x")

        self.progress_bar = ctk.CTkProgressBar(mid_box, height=8, corner_radius=2)
        self.progress_bar.pack(fill="x", pady=(2, 0))
        self.progress_bar.set(0)

        right_box = ctk.CTkFrame(bar, fg_color="transparent")
        right_box.pack(side="right")

        self.log_toggle_btn = ctk.CTkButton(
            right_box,
            text="İşlem Detayları",
            width=110,
            height=34,
            font=ctk.CTkFont(size=11),
            command=self._toggle_console,
            fg_color=("gray75", "#2e343d"),
            hover_color=("gray65", "#39404b"),
        )
        self.log_toggle_btn.pack(side="left", padx=4)

        self.export_log_btn = ctk.CTkButton(
            right_box,
            text="Logları Kaydet",
            width=100,
            height=34,
            font=ctk.CTkFont(size=11),
            command=self._export_logs,
            fg_color=("gray75", "#2e343d"),
            hover_color=("gray65", "#39404b"),
        )
        self.export_log_btn.pack(side="left", padx=4)

        self.cancel_btn = ctk.CTkButton(
            right_box,
            text="İptal Et",
            width=90,
            height=34,
            font=ctk.CTkFont(size=12, weight="bold"),
            fg_color="#ef4444",
            hover_color="#dc2626",
            command=self._cancel_installation,
        )
        self.cancel_btn.pack(side="left", padx=4)
        self.cancel_btn.pack_forget()

        self.install_btn = ctk.CTkButton(
            right_box,
            text="Kurulumu Başlat (0)",
            font=ctk.CTkFont(size=13, weight="bold"),
            width=170,
            height=34,
            fg_color="#2563eb",
            hover_color="#1d4ed8",
            command=self._start_installation,
        )
        self.install_btn.pack(side="left", padx=4)

        # Açılır Konsol Paneli (Tembel yükleme: sadece tıklandığında inşa edilir, açılışta 440ms tasarruf sağlar)
        self.console_frame = ctk.CTkFrame(bottom, fg_color="transparent")
        self.console_text = None
        self.console_visible = False

    # ------------------ KATEGORİ VE GÖRÜNÜM GEÇİŞLERİ ------------------

    def _select_category_view(self, cat_id: str):
        self._show_apps_view()
        self.current_category_filter = cat_id

        # Sol butonların aktif rengini güncelle
        for cid, btn in self.cat_btns.items():
            if cid == cat_id:
                btn.configure(fg_color="#2563eb", text_color="white")
            else:
                btn.configure(fg_color="transparent", text_color=("gray20", "gray85"))

        self._on_filter_changed()

    def _show_apps_view(self):
        self.tweaks_view.pack_forget()
        self.hardware_view.pack_forget()
        self.apps_view.pack(fill="both", expand=True, padx=0, pady=0)
        self.tweak_nav_btn.configure(fg_color=("gray80", "#272c34"))
        self.hw_nav_btn.configure(fg_color=("gray80", "#272c34"))

    def _show_tweaks_view(self):
        self.apps_view.pack_forget()
        self.hardware_view.pack_forget()
        if not getattr(self, "_tweaks_built", False):
            self._build_tweaks_view_content()
            self._tweaks_built = True
        self.tweaks_view.pack(fill="both", expand=True, padx=0, pady=0)
        self.tweak_nav_btn.configure(fg_color="#2563eb")
        self.hw_nav_btn.configure(fg_color=("gray80", "#272c34"))

        # Kategori butonlarının seçimini kaldır
        for btn in self.cat_btns.values():
            btn.configure(fg_color="transparent", text_color=("gray20", "gray85"))

    def _show_hardware_view(self):
        self.apps_view.pack_forget()
        self.tweaks_view.pack_forget()
        if not getattr(self, "_hardware_built", False):
            self._build_hardware_view_content()
            self._hardware_built = True
        self.hardware_view.pack(fill="both", expand=True, padx=0, pady=0)
        self.hw_nav_btn.configure(fg_color="#2563eb")
        self.tweak_nav_btn.configure(fg_color=("gray80", "#272c34"))

        # Kategori butonlarının seçimini kaldır
        for btn in self.cat_btns.values():
            btn.configure(fg_color="transparent", text_color=("gray20", "gray85"))

        if not getattr(self, "_hardware_loaded", False):
            self._load_hardware_async()

    def _on_search_debounced(self):
        """Arama sırasında her tuş vuruşunda arayüzün kilitlenmesini önleyen tamponlayıcı (debounce)."""
        if self._search_timer:
            self.after_cancel(self._search_timer)
        self._search_timer = self.after(180, self._on_filter_changed)

    def _on_filter_changed(self):
        query = self.search_var.get().strip().lower()
        active_cat = self.current_category_filter

        for app in APPLICATIONS:
            row = self.app_rows.get(app["id"])
            if not row:
                continue

            matches_cat = (active_cat == "all") or (app["category"] == active_cat)
            matches_search = (
                (query in app["name"].lower())
                or (query in app["desc"].lower())
                or (query in app.get("winget_id", "").lower())
            )
            show = matches_cat and matches_search

            if show:
                if row.theme_gen != self._theme_gen:
                    row.refresh_theme(self._theme_gen)
                if not row.visible:
                    row.grid()
                    row.visible = True
            elif not show and row.visible:
                row.grid_remove()
                row.visible = False

        # Liste yenilendiğinde kaydırma çubuğunu en üste sıfırla (Boş ekran kalmasını önler)
        try:
            self.apps_scroll._parent_canvas.yview_moveto(0.0)
        except Exception as e:
            logger.debug(f"apps_scroll yview_moveto hatası: {e}")

    # ------------------ SEÇİM VE PROFİL YÖNETİMİ ------------------

    def _on_app_toggled(self, app_id: str, is_selected: bool):
        if is_selected:
            self.selected_apps.add(app_id)
        else:
            self.selected_apps.discard(app_id)
        self._update_selection_ui()

    def _update_selection_ui(self):
        count = len(self.selected_apps)
        self.count_label.configure(text=f"Seçilen: {count} Program")
        self.install_btn.configure(text=f"Kurulumu Başlat ({count})")

    def _on_profile_selected(self, choice_name):
        for p in PROFILES:
            if p["name"] == choice_name:
                self.apply_profile(p["id"])
                break

    def apply_profile(self, profile_id: str):
        self.selected_apps.clear()
        for app in APPLICATIONS:
            row = self.app_rows.get(app["id"])
            should_select = profile_id in app.get("profiles", [])
            if row:
                row.set_selected(should_select, notify=False)
            if should_select:
                self.selected_apps.add(app["id"])
        self._update_selection_ui()

    def select_visible(self):
        query = self.search_var.get().strip().lower()
        active_cat = self.current_category_filter

        for app in APPLICATIONS:
            matches_cat = (active_cat == "all") or (app["category"] == active_cat)
            matches_search = (
                (query in app["name"].lower())
                or (query in app["desc"].lower())
                or (query in app.get("winget_id", "").lower())
            )
            if matches_cat and matches_search:
                row = self.app_rows.get(app["id"])
                if row:
                    row.set_selected(True, notify=False)
                self.selected_apps.add(app["id"])
        self._update_selection_ui()

    def clear_selection(self):
        self.selected_apps.clear()
        for row in self.app_rows.values():
            row.set_selected(False, notify=False)
        self._update_selection_ui()

    def uncheck_installed(self):
        removed_count = 0
        for app in APPLICATIONS:
            row = self.app_rows.get(app["id"])
            if row and row.is_installed and row.selected:
                row.set_selected(False, notify=False)
                self.selected_apps.discard(app["id"])
                removed_count += 1
        self._update_selection_ui()
        if removed_count > 0:
            self.status_label.configure(text=f"{removed_count} adet kurulu program seçimden çıkarıldı.")

    def export_profile_json(self):
        if not self.selected_apps:
            messagebox.showinfo("Bilgi", "Kaydedilecek herhangi bir program seçilmedi.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON Dosyası", "*.json")],
            title="Özel Paketi Kaydet",
            initialfile="Kurulum_Paketi.json",
        )
        if path:
            data = {"app_ids": list(self.selected_apps)}
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                messagebox.showinfo("Başarılı", f"Paket kaydedildi:\n{path}")
            except Exception as e:
                messagebox.showerror("Hata", f"Dosya kaydedilemedi: {e}")

    def import_profile_json(self):
        path = filedialog.askopenfilename(
            filetypes=[("JSON Dosyası", "*.json")],
            title="Kayıtlı Paketi Aç",
        )
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # Şema doğrulaması
                if not isinstance(data, dict):
                    raise ValueError("JSON kök verisi nesne formatında olmalıdır.")
                raw_ids = data.get("app_ids")
                if not isinstance(raw_ids, list):
                    raise ValueError("'app_ids' geçerli bir liste formatında olmalıdır.")

                valid_app_ids = {a["id"] for a in APPLICATIONS}
                sanitized_ids = [str(aid) for aid in raw_ids if isinstance(aid, str) and aid in valid_app_ids]

                self.clear_selection()
                for aid in sanitized_ids:
                    row = self.app_rows.get(aid)
                    if row:
                        row.set_selected(True)
                self._update_selection_ui()
                messagebox.showinfo("Başarılı", f"{len(sanitized_ids)} program başarıyla yüklendi.")
            except Exception as e:
                messagebox.showerror("Hata", f"Paket dosyası açılamadı veya şema geçersiz: {e}")

    # ------------------ KURULU ALGILAMA VE KURULUM ------------------

    def _apply_installed_marks(self, app_ids: set):
        for aid in app_ids:
            row = self.app_rows.get(aid)
            if row:
                row.mark_installed(True)
        self._all_installed_found.update(app_ids)
        total = len(self._all_installed_found)
        if total > 0:
            self.status_label.configure(text=f"Sistem tarandı: {total} uygulama zaten kurulu.")

    def _detect_installed_background_worker(self):
        """
        Arka plan tarama motoru:
        Aşama 1: Hızlı Kayıt Defteri ve Dosya Taraması (UI'yi kilitlemeden ilk sonuçları anında iletir).
        Aşama 2: WinGet Paket Sorgusu (Genişletilmiş ek paketleri tespit eder).
        """
        # Aşama 1: Kayıt Defteri ve Dosya Kontrolü
        try:
            reg_names = get_all_installed_display_names()
        except Exception:
            reg_names = set()

        phase1_found = set()
        for app in APPLICATIONS:
            try:
                is_inst, _ = verify_application_installed(app, reg_names, allow_subprocess=False)
                if is_inst:
                    phase1_found.add(app["id"])
            except Exception:
                pass

        if phase1_found:
            self.dispatch_ui(self._apply_installed_marks, phase1_found)

        # Aşama 2: WinGet Paket Taraması (Düşük öncelikli arka plan thread'i)
        try:
            import ctypes
            from ctypes import wintypes
            k = ctypes.WinDLL("kernel32", use_last_error=True)
            k.GetCurrentThread.restype = wintypes.HANDLE
            k.SetThreadPriority.argtypes = [wintypes.HANDLE, ctypes.c_int]
            k.SetThreadPriority(k.GetCurrentThread(), -1)  # THREAD_PRIORITY_BELOW_NORMAL
        except Exception:
            pass

        try:
            self.installed_set = detect_installed_packages()
        except Exception:
            self.installed_set = set()

        phase2_found = set()
        if self.installed_set:
            for app in APPLICATIONS:
                aid = app["id"]
                if aid not in phase1_found:
                    wid = app.get("winget_id", "").lower()
                    if wid and wid in self.installed_set:
                        phase2_found.add(aid)

        if phase2_found:
            self.dispatch_ui(self._apply_installed_marks, phase2_found)

    def _toggle_theme(self):
        new_mode = "Light" if ctk.get_appearance_mode() == "Dark" else "Dark"
        self._theme_gen += 1
        ctk.set_appearance_mode(new_mode)
        is_dark = (new_mode == "Dark")
        for row in self.app_rows.values():
            if row.visible:
                row.refresh_theme_fast(is_dark, self._theme_gen)

    def _toggle_console(self):
        if self.console_visible:
            self.console_frame.pack_forget()
            self.log_toggle_btn.configure(text="İşlem Detayları")
            self.console_visible = False
        else:
            if self.console_text is None:
                self.console_text = ctk.CTkTextbox(
                    self.console_frame,
                    height=140,
                    font=ctk.CTkFont(family="Consolas", size=11),
                    wrap="word",
                    corner_radius=4,
                )
                self.console_text.pack(fill="both", expand=True, padx=16, pady=(0, 8))
                if self.log_history:
                    self.console_text.insert("end", "\n".join(self.log_history) + "\n")
                    self.console_text.see("end")
            self.console_frame.pack(fill="x", padx=0, pady=0)
            self.log_toggle_btn.configure(text="Detayları Gizle")
            self.console_visible = True

    def _elevate_admin(self):
        try:
            import main
            if hasattr(main, "GLOBAL_MUTEX") and main.GLOBAL_MUTEX:
                main.release_single_instance_mutex(main.GLOBAL_MUTEX)
                main.GLOBAL_MUTEX = None
        except Exception as e:
            logger.debug(f"Mutex serbest bırakılamadı: {e}")

        success = request_admin_elevation()
        if success:
            self.destroy()
        else:
            try:
                import main
                main.GLOBAL_MUTEX = main.ensure_single_instance()
            except Exception as e:
                logger.debug(f"Mutex yeniden alınamadı: {e}")
            self.append_log("[BİLGİ] Yönetici izni alma işlemi kullanıcı tarafından iptal edildi.\n")

    def append_log(self, text: str):
        """Her iş parçacığından (thread) çağrılması güvenlidir; doğrudan kuyruğa yazar."""
        self._log_q.put(text)

    def _poll_logs(self):
        """Yalnızca ana UI thread'inde çalışır; kuyruktaki logları topluca ekrana basar."""
        lines = []
        try:
            while True:
                lines.append(self._log_q.get_nowait())
        except queue.Empty:
            pass

        if lines:
            self.log_history.extend(lines)
            if len(self.log_history) > 2000:
                self.log_history = self.log_history[-2000:]
            if self.console_text:
                try:
                    self.console_text.insert("end", "\n".join(lines) + "\n")
                    self.console_text.see("end")
                except Exception as e:
                    logger.debug(f"console_text see hatası: {e}")

        try:
            self.after(100, self._poll_logs)
        except Exception as e:
            logger.debug(f"_poll_logs sonlandırıldı: {e}")

    def _check_resume_session(self):
        # Eğer sistem otomatik resume görevi ile açılmışsa görevin kalıcı kalmaması için derhal sil
        if "--resume" in sys.argv:
            SessionManager.remove_resume_task()

        interrupted = SessionManager.get_interrupted_session()
        if not interrupted:
            return

        pending_ids = interrupted.get("pending_app_ids", [])
        failed_ids = interrupted.get("failed_app_ids", [])
        # Yalnızca geçerli katalog uygulamalarını kabul et (sahte girdi önleme)
        all_candidate_ids = [aid for aid in dict.fromkeys(pending_ids + failed_ids) if aid in self.app_rows]

        if not all_candidate_ids:
            return

        is_cli_resume = "--resume" in sys.argv

        if is_cli_resume:
            self.clear_selection()
            for aid in all_candidate_ids:
                row = self.app_rows.get(aid)
                if row:
                    row.set_selected(True)
            self._update_selection_ui()
            self.status_label.configure(text=f"Oturum devam ettirildi: {len(all_candidate_ids)} program seçildi.")
            self.append_log(f"[DEVAM] Yeniden başlatma sonrası yarım kalan oturum geri yüklendi ({len(all_candidate_ids)} program).")
            # Kullanıcı onay kutusu ile otomatik başlatmayı sor
            if messagebox.askyesno("Oturuma Devam Et", f"Sistem yeniden başlatıldı.\nYarım kalan {len(all_candidate_ids)} programın kurulumuna şimdi devam edilsin mi?"):
                self.after(300, self._start_installation)
            return

        if pending_ids and failed_ids:
            prompt_text = f"Önceki oturumda henüz kurulmamış {len(pending_ids)} ve hata vermiş {len(failed_ids)} program bulundu (Toplam: {len(all_candidate_ids)})."
        elif pending_ids:
            prompt_text = f"Önceki oturumda tamamlanamamış {len(pending_ids)} program bulundu."
        else:
            prompt_text = f"Önceki oturumda kurulumu tamamlanamamış {len(failed_ids)} program bulundu."
        prompt_text += "\n\nKaldığınız yerden devam etmek ve bu programları seçili hale getirmek ister misiniz?"

        resume = messagebox.askyesno("Yarım Kalan Kurulum Tespit Edildi", prompt_text)
        if resume:
            self.clear_selection()
            for aid in all_candidate_ids:
                row = self.app_rows.get(aid)
                if row:
                    row.set_selected(True)
            self._update_selection_ui()
            self.status_label.configure(text=f"Önceki oturumdan {len(all_candidate_ids)} program seçildi.")
        else:
            SessionManager.clear_session()

    def _check_conflicts(self, selected_ids: set) -> list:
        conflicts = []
        # 1. apps_data.py conflict_group alanina gore dinamik grup kontrolu (archiver, office_suite, pdf_reader, codec_pack)
        grouped = {}
        for a in APPLICATIONS:
            if a["id"] in selected_ids and a.get("conflict_group"):
                grp = a["conflict_group"]
                grouped.setdefault(grp, []).append(a["name"])

        conflict_names = CONFLICT_GROUPS

        for grp_key, app_names in grouped.items():
            if len(app_names) > 1:
                grp_title = conflict_names.get(grp_key, grp_key)
                conflicts.append(f"Birden fazla {grp_title} ({', '.join(app_names)}) seçildi. Genellikle yalnızca birini kurmanız önerilir.")

        # 2. Visual Studio IDE Sürümleri (Build Tools ve VS Code hariç tutulur)
        vs_selected = [aid for aid in selected_ids if (aid.startswith("vs_") or aid.startswith("vs20")) and "code" not in aid and "buildtools" not in aid]
        if len(vs_selected) > 1:
            conflicts.append(f"Birden fazla Visual Studio IDE sürümü ({len(vs_selected)} adet) seçildi. Yalnızca tek bir edition (örn: Community veya Pro) kurmanız önerilir.")

        return conflicts

    def _start_installation(self):
        if not self.selected_apps:
            messagebox.showinfo("Seçim Yapılmadı", "Lütfen kurmak istediğiniz en az bir program seçin.")
            return

        to_install = [a for a in APPLICATIONS if a["id"] in self.selected_apps]
        has_winget_apps = any(a.get("install_type", "winget") == "winget" for a in to_install)

        # 1. Uygulama Çakışması Kontrolü
        conflicts = self._check_conflicts(self.selected_apps)
        if conflicts:
            conflict_msg = (
                "Aşağıdaki potansiyel uygulama çakışmaları tespit edildi:\n\n"
                + "\n".join(f"- {c}" for c in conflicts)
                + "\n\nYine de devam etmek istiyor musunuz?"
            )
            if not messagebox.askyesno("Uygulama Çakışması Uyarısı", conflict_msg):
                return

        # 2. Sistem Ön Kontrollerini Arka Planda Başlat (UI'yi dondurmaz)
        orig_btn_text = self.install_btn.cget("text")
        self.install_btn.configure(state="disabled", text="Sistem Kontrol Ediliyor...")
        self.status_label.configure(text="Sistem ön kontrolleri yapılıyor, lütfen bekleyin...")

        total_req_mb = sum(a.get("size_mb", 50) for a in to_install)

        def _preflight_worker():
            try:
                preflight = run_all_preflight_checks(required_mb=total_req_mb)
            except Exception as e:
                preflight = [{"name": "Ön Kontrol Motoru", "status": False, "detail": str(e), "critical": True}]
            self.dispatch_ui(self._on_preflight_finished, preflight, to_install, has_winget_apps, orig_btn_text)

        threading.Thread(target=_preflight_worker, daemon=True).start()

    def _on_preflight_finished(self, preflight, to_install, has_winget_apps, orig_btn_text):
        """Ön kontroller tamamlandığında ana iş parçacığında çalışarak sonuçları değerlendirir."""
        self.install_btn.configure(state="normal", text=orig_btn_text)
        self.status_label.configure(text="Hazır.")

        hard_critical_failures = []
        soft_critical_failures = []
        reboot_pending_warning = False
        report_lines = []

        for chk in preflight:
            tag = "[OK]" if chk["status"] else ("[HATA]" if chk["critical"] else "[UYARI]")
            report_lines.append(f"{tag} {chk['name']}: {chk['detail']}")
            if not chk["status"]:
                chk_name = chk["name"]
                if any(k in chk_name for k in ["Windows Sürümü", "Sistem Mimarisi", "Yönetici İzni"]):
                    hard_critical_failures.append(chk)
                elif "WinGet" in chk_name:
                    if has_winget_apps:
                        hard_critical_failures.append(chk)
                    else:
                        soft_critical_failures.append(chk)
                elif chk.get("critical", False):
                    soft_critical_failures.append(chk)
                elif "Bekleyen Yeniden Başlatma" in chk_name:
                    reboot_pending_warning = True

        # 1. Sert Güvenlik Engeli: Yönetici izni, OS sürümü, mimari veya gerekli WinGet motoru yoksa KESİNLİKLE durdur
        if hard_critical_failures:
            hard_reasons = "\n".join(f"- {c['name']}: {c['detail']}" for c in hard_critical_failures)
            msg = (
                "Sistem gereksinimleri ve temel platform uyumluluğu nedeniyle kurulum ENGELLENDİ:\n\n"
                f"{hard_reasons}\n\n"
                "Lütfen uygulamayı Yönetici olarak başlatın ve gerekli paket bileşenlerini sağlayın."
            )
            messagebox.showerror("Kritik Sistem Engeli", msg)
            return

        # 2. Esnek Engel: Ağ (Proxy / VPN arkası) veya Disk Alanı uyarısı (Kullanıcı onayına bağlı)
        if soft_critical_failures:
            soft_reasons = "\n".join(f"- {c['name']}: {c['detail']}" for c in soft_critical_failures)
            msg = (
                "Sistem ön kontrollerinde önemli uyarılar tespit edildi:\n\n"
                f"{soft_reasons}\n\n"
                "(Kurumsal bir ağ, VPN veya proxy arkasındaysanız sunucu erişim testi yanıltıcı olabilir.)\n\n"
                "Yine de devam etmek istiyor musunuz?"
            )
            if not messagebox.askyesno("Ön Kontrol Uyarısı", msg):
                return
        elif reboot_pending_warning:
            msg = (
                "Sistemde bekleyen bir Windows güncelleme/yeniden başlatma işlemi var:\n\n"
                + "\n".join(report_lines)
                + "\n\nKurulumların sağlıklı tamamlanması için sistemi yeniden başlatmanız önerilir. Yine de devam etmek istiyor musunuz?"
            )
            if not messagebox.askyesno("Bekleyen Yeniden Başlatma Uyarısı", msg):
                return

        # Sıklet ve Ağırlık Modeli: Küçükten büyüğe sırala (Hafif -> Orta -> Ağır)
        to_install.sort(key=lambda app: (app.get("weight", 2), app.get("size_mb", 50), app.get("name", "")))

        confirm = messagebox.askyesno(
            "Kurulum Onayı",
            f"Seçilen {len(to_install)} adet program dosya boyutuna göre optimize edilmiş sırayla (önce hafifler, en son büyük paketler) sessizce kurulacaktır.\n\nDevam etmek istiyor musunuz?",
        )
        if not confirm:
            return

        if not self.console_visible:
            self._toggle_console()

        self.install_btn.configure(state="disabled")
        self.cancel_btn.pack(side="left", padx=4)
        self.progress_bar.set(0)

        for row in self.app_rows.values():
            if row.app_data["id"] in self.selected_apps:
                row.set_status("Sırada", "normal")

        self.worker = InstallationWorker(
            app_list=to_install,
            on_log=self.append_log,
            on_progress=self._worker_progress,
            on_app_completed=self._worker_app_completed,
            on_finished=self._worker_finished,
        )
        self.worker.start()

    def _cancel_installation(self):
        if self.worker:
            self.cancel_btn.configure(state="disabled")
            self.status_label.configure(text="İptal ediliyor...")
            self.worker.cancel()

    def _worker_progress(self, index: int, total: int, app_name: str, status: str):
        def _update():
            ratio = (index - 1) / total
            self.progress_bar.set(ratio)
            self.status_label.configure(text=f"[{index}/{total}] {app_name} kuruluyor...")

        self.dispatch_ui(_update)

    def _worker_app_completed(self, app_id: str, success: bool, message: str):
        def _update():
            row = self.app_rows.get(app_id)
            if row:
                if success:
                    row.set_status("Tamamlandı", "success")
                else:
                    row.set_status("Hata", "error")

        self.dispatch_ui(_update)

    def _worker_finished(self, summary: dict):
        def _update():
            self.progress_bar.set(1.0)
            self.install_btn.configure(state="normal")
            self.cancel_btn.pack_forget()
            self.cancel_btn.configure(state="normal")

            if summary["cancelled"]:
                self.status_label.configure(text="Kurulum durduruldu.")
                failed_cnt = summary.get("failed", 0)
                remaining_cnt = max(0, summary["total"] - (summary["successful"] + failed_cnt))
                messagebox.showwarning(
                    "Durduruldu",
                    f"Kurulum durduruldu.\nTamamlanan: {summary['successful']}\nBaşarısız: {failed_cnt}\nKalan: {remaining_cnt}",
                )
            else:
                self.status_label.configure(text=f"İşlem bitti: {summary['successful']}/{summary['total']} program kuruldu.")
                reboot_notice = (
                    "\n\n[DİKKAT] Bazı bileşenler için sistemin yeniden başlatılması önerilmektedir. Lütfen sisteminizi yeniden başlatınız."
                    if summary.get("reboot_required")
                    else ""
                )
                msg = (
                    f"Tüm kurulum kuyruğu tamamlandı.\n\n"
                    f"Toplam Seçilen: {summary['total']}\n"
                    f"Başarıyla Kuruldu ve Doğrulandı: {summary.get('verified_count', 0)}\n"
                    f"Zaten Sistemde Mevcut: {summary.get('already_installed_count', 0)}\n"
                    f"Kuruldu (Doğrulanamadı): {summary.get('unverified_count', 0)}\n"
                    f"Hatalı / Başarısız: {summary['failed']}"
                    f"{reboot_notice}"
                )
                messagebox.showinfo("Kurulum ve Doğrulama Özeti", msg)
                if summary.get("failed", 0) > 0:
                    retry_ask = messagebox.askyesno(
                        "Başarısız Uygulamaları Yeniden Dene",
                        f"Kurulum tamamlandı fakat {summary['failed']} uygulama kurulamadı.\n\n"
                        f"Başarısız olan bu uygulamaları otomatik seçip tekrar denemek ister misiniz?",
                    )
                    if retry_ask:
                        self.load_failed_apps()

        self.dispatch_ui(_update)

    def load_failed_apps(self):
        """Mevcut veya son arşivlenmiş oturumdaki başarısız uygulamaları seçili hale getirir."""
        failed_ids = []
        # 1. Mevcut açık oturumdan oku
        session = SessionManager.get_current_session()
        if session and session.get("failed_app_ids"):
            failed_ids = session["failed_app_ids"]
        else:
            # 2. History dizinindeki en son oturumdan oku
            history_dir = os.path.join(SESSION_DIR, "history")
            if os.path.exists(history_dir):
                files = sorted([f for f in os.listdir(history_dir) if f.endswith(".json")])
                if files:
                    latest_hist = os.path.join(history_dir, files[-1])
                    try:
                        with open(latest_hist, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            failed_ids = data.get("failed_app_ids", [])
                    except Exception:
                        pass

        if not failed_ids:
            messagebox.showinfo("Bilgi", "Tekrar denenecek kayıtlı başarısız uygulama bulunamadı.")
            return

        self.clear_selection()
        selected_count = 0
        for aid in failed_ids:
            row = self.app_rows.get(aid)
            if row:
                row.set_selected(True)
                selected_count += 1
        self._update_selection_ui()
        self.status_label.configure(text=f"Başarısız olan {selected_count} uygulama tekrar denenmek üzere seçildi.")
        self.append_log(f"[BİLGİ] {selected_count} başarısız uygulama kuyruğa alındı.")

    def _export_logs(self):
        log_content = "\n".join(self.log_history).strip()
        if not log_content:
            messagebox.showinfo("Bilgi", "Dışa aktarılacak log kaydı bulunamadı.")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Metin Dosyası", "*.txt"), ("Log Dosyası", "*.log")],
            title="Kurulum Loglarını Kaydet",
            initialfile=f"Kurulum_Gunlugu_{int(time.time())}.txt",
        )
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(log_content)
                messagebox.showinfo("Başarılı", f"Loglar başarıyla kaydedildi:\n{path}")
            except Exception as e:
                messagebox.showerror("Hata", f"Log dosyası kaydedilemedi: {e}")

    def _on_tweak_scope_changed(self, choice_text):
        if "Mevcut" in choice_text:
            self.tweak_scope = "user"
            self.status_label.configure(text="İnce ayar kapsamı: Sadece Mevcut Kullanıcı (HKCU)")
        else:
            self.tweak_scope = "all"
            self.status_label.configure(text="İnce ayar kapsamı: Tüm Bilgisayar (Sistem Geneli)")

    def _apply_tweaks(self):
        if not self.console_visible:
            self._toggle_console()

        scope = getattr(self, "tweak_scope", "all")
        scope_text = "Sistem Geneli (Tüm Bilgisayar)" if scope == "all" else "Sadece Mevcut Kullanıcı"

        # Arayüzün kilitlenmesini önlemek için arka plan iş parçacığında çalıştırılır
        def _worker():
            applied = 0
            errors = []
            self.append_log(f"\n--- Windows İnce Ayarları Uygulanıyor [Kapsam: {scope_text}] ---")

            # İnce ayarlar öncesinde sistem geri yükleme noktası oluşturulur
            active_tweaks = [t_id for t_id, var in self.tweak_vars.items() if var.get()]
            if active_tweaks:
                self.append_log("  [BİLGİ] İnce ayarlar öncesinde sistem geri yükleme noktası oluşturuluyor...")
                try:
                    from tweaks import create_system_restore_point
                    rp_ok, rp_msg = create_system_restore_point()
                    if rp_ok:
                        self.append_log(f"  [OK] {rp_msg}")
                    else:
                        self.append_log(f"  [BİLGİ] {rp_msg}")
                except Exception as rp_err:
                    logger.debug(f"Geri yükleme noktası oluşturulamadı: {rp_err}")
                    self.append_log(f"  [BİLGİ] Geri yükleme noktası çağrısı atlandı: {rp_err}")

            for tweak_id, var in self.tweak_vars.items():
                if var.get():
                    action_func = TWEAK_ACTIONS.get(tweak_id)
                    if action_func:
                        try:
                            ok, msg = action_func(True, scope=scope)
                        except Exception as e:
                            ok, msg = False, str(e)
                        if ok:
                            applied += 1
                            self.append_log(f"  [OK] {msg}")
                        else:
                            errors.append(msg)
                            self.append_log(f"  [HATA] {msg}")

            self.append_log(f"--- Toplam {applied} ayar uygulandı ---\n")

            def _show_result():
                if errors:
                    messagebox.showwarning(
                        "İnce Ayarlar",
                        f"{applied} ayar uygulandı ({scope_text}).\nBazı ayarlar yönetici yetkisi gerektirebilir:\n" + "\n".join(errors),
                    )
                else:
                    messagebox.showinfo(
                        "İnce Ayarlar",
                        f"{applied} adet ayar başarıyla uygulandı ({scope_text}).\nDeğişikliklerin görünmesi için Gezgini Yeniden Başlat seçeneğini kullanabilirsiniz.",
                    )

            self.dispatch_ui(_show_result)

        threading.Thread(target=_worker, daemon=True).start()

    def _revert_tweaks(self):
        confirm = messagebox.askyesno(
            "Geri Alma Onayı",
            "Bu sihirbaz ile uygulanmış olan tüm Windows ince ayarları, değişiklik öncesindeki orijinal hallerine geri döndürülecektir.\n\nDevam etmek istiyor musunuz?",
        )
        if not confirm:
            return

        if not self.console_visible:
            self._toggle_console()

        scope = getattr(self, "tweak_scope", "all")

        def _worker():
            self.append_log("\n--- Windows İnce Ayarları Geri Alınıyor (Orijinal Duruma Dönüş) ---")
            results = revert_all_tweaks(scope=scope)
            reverted = 0
            for tid, ok, msg in results:
                if ok:
                    reverted += 1
                    self.append_log(f"  [OK] {msg}")
                else:
                    self.append_log(f"  [UYARI] {msg}")

            self.append_log(f"--- Toplam {reverted} ayar geri alındı ---\n")

            def _show_result():
                messagebox.showinfo(
                    "Geri Alındı",
                    f"{reverted} adet ayar başarıyla önceki durumuna geri döndürüldü.\nDeğişikliklerin etkili olması için Gezgini Yeniden Başlat seçeneğini kullanabilirsiniz.",
                )

            self.dispatch_ui(_show_result)

        threading.Thread(target=_worker, daemon=True).start()

    def _restart_explorer_action(self):
        def _worker():
            ok, msg = restart_explorer()
            def _show():
                if ok:
                    messagebox.showinfo("Bilgi", msg)
                else:
                    messagebox.showwarning("Uyarı", msg)
            self.dispatch_ui(_show)

        threading.Thread(target=_worker, daemon=True).start()
