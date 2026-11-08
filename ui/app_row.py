# -*- coding: utf-8 -*-
"""
Format Sonrası Kurulum Sihirbazı - Uygulama Satır Bileşeni (AppItemRow)
Yüksek performanslı, düz native Tk satırı.
"""

import tkinter as tk
from typing import Optional, Dict, Any, Callable
import customtkinter as ctk


class AppItemRow(tk.Frame):
    """
    Yüksek performanslı, düz native Tk satırı.
    Gereksiz ara çerçeve katmanları ve 1000+ olay bağlayıcısı kaldırılmış,
    doğrudan grid üzerinde çalışan ultra hızlı bileşen.
    """

    def __init__(self, master, app_data: Dict[str, Any], on_toggle_callback: Callable[[str, bool], None], fonts=None, **kwargs):
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
