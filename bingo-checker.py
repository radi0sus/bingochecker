import customtkinter as ctk
import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk, ImageEnhance, ImageFilter, ImageOps, ImageDraw
import requests
from bs4 import BeautifulSoup
import re
import threading
import numpy as np
from scipy import ndimage
import tempfile
import os
import gc
from urllib.parse import unquote

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
except ImportError:
    DND_FILES = None
    TkinterDnD = None

from Foundation import NSURL, NSAutoreleasePool
from Vision import (
    VNImageRequestHandler,
    VNRecognizeTextRequest,
    VNRequestTextRecognitionLevelAccurate,
    VNRequestTextRecognitionLevelFast,
)


# -----------------------------
# Konfiguration
# -----------------------------
ctk.set_appearance_mode("light")
ctk.set_default_color_theme("blue")

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:
    RESAMPLE = Image.LANCZOS


# -----------------------------
# Haupt-App
# -----------------------------
class BingoCheckerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Drag & Drop initialisieren, falls tkinterdnd2 installiert ist
        if TkinterDnD is not None:
            try:
                TkinterDnD._require(self)
            except Exception:
                pass

        self.title("BINGO Checker")
        self.geometry("1050x730")
        self.minsize(850, 600)

        self.image_path = None
        self.image_label = None
        self.preview_image = None

        self.ocr_result = None
        self.drawn_numbers = set()
        
        self.draw_date = None
        self.draw_date_var = ctk.StringVar(value="Ziehung: noch nicht geladen")

        self.rotation_angle = 0
        self.crop_box = None

        self.processing = False
        self.process_lock = threading.Lock()

        self.drawn_numbers_text = None
        self.crop_window = None

        self.build_ui()
        self.status_var.set("Bereit")

    # -----------------------------
    # UI
    # -----------------------------
    def build_ui(self):
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=10)

        title = ctk.CTkLabel(
            header,
            text="BINGO Checker",
            font=("Segoe UI", 24, "bold")
        )
        title.pack(side="left")

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=20, pady=10)

        left = ctk.CTkFrame(main, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=(0, 10))

        right = ctk.CTkFrame(main, fg_color="transparent")
        right.pack(side="right", fill="both", expand=True, padx=(10, 0))

        # Linke Seite
        upload_frame = ctk.CTkFrame(left, fg_color="#F0F0F0", corner_radius=12)
        upload_frame.pack(fill="both", expand=True, pady=10)

        # Drop-Zone
        self.drop_zone = ctk.CTkFrame(
            upload_frame,
            fg_color="#FFFFFF",
            border_width=2,
            border_color="#B0B0B0",
            corner_radius=14,
            height=115
        )
        self.drop_zone.pack(fill="x", padx=25, pady=(25, 10))
        self.drop_zone.pack_propagate(False)
        
        self.drop_label = ctk.CTkLabel(
            self.drop_zone,
            text="Bild hier ablegen\noder hier klicken zum Auswählen",
            font=("Segoe UI", 15, "bold"),
            justify="center",
            text_color="#555"
        )
        self.drop_label.pack(expand=True, fill="both")

        self.drop_zone.bind("<Button-1>", lambda e: self.select_image())
        self.drop_label.bind("<Button-1>", lambda e: self.select_image())

        self.enable_drop_target(self.drop_zone)
        self.enable_drop_target(self.drop_label)

        rotate_frame = ctk.CTkFrame(upload_frame, fg_color="transparent")
        rotate_frame.pack(pady=6)

        ctk.CTkButton(
            rotate_frame,
            text="↺ 90°",
            width=90,
            command=lambda: self.rotate_image(-90),
            fg_color="#777",
            hover_color="#555"
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            rotate_frame,
            text="↻ 90°",
            width=90,
            command=lambda: self.rotate_image(90),
            fg_color="#777",
            hover_color="#555"
        ).pack(side="left", padx=5)

        crop_frame = ctk.CTkFrame(upload_frame, fg_color="transparent")
        crop_frame.pack(pady=6)

        ctk.CTkButton(
            crop_frame,
            text="Zahlenfeld zuschneiden",
            width=190,
            command=self.open_crop_window,
            fg_color="#FF9500",
            hover_color="#e68000"
        ).pack(side="left", padx=5)

        self.image_label = ctk.CTkLabel(upload_frame, text="")
        self.image_label.pack(pady=10)

        # Rechte Seite
        result_frame = ctk.CTkFrame(right, fg_color="#F0F0F0", corner_radius=12)
        result_frame.pack(fill="both", expand=True, pady=10)

        self.status_var = ctk.StringVar(value="Starte...")

        status_label = ctk.CTkLabel(
            result_frame,
            textvariable=self.status_var,
            font=("Segoe UI", 12),
            text_color="#666"
        )
        status_label.pack(anchor="w", padx=20, pady=(10, 5))

        self.progress = ctk.CTkProgressBar(
            result_frame,
            mode="determinate",
            progress_color="#007AFF"
        )
        self.progress.pack(fill="x", padx=20, pady=5)
        self.progress.set(0)

        self.grid_frame = ctk.CTkFrame(result_frame, fg_color="transparent")
        self.grid_frame.pack(pady=18, fill="both", expand=True)

        drawn_frame = ctk.CTkFrame(result_frame, fg_color="transparent")
        drawn_frame.pack(fill="x", padx=20, pady=(0, 8))
        
        ctk.CTkLabel(
            drawn_frame,
            textvariable=self.draw_date_var,
            font=("Segoe UI", 12, "bold"),
            text_color="#444"
        ).pack(anchor="w", pady=(0, 4))
        
        ctk.CTkLabel(
            drawn_frame,
            text="Gezogene Zahlen:",
            font=("Segoe UI", 12, "bold")
        ).pack(anchor="w")

        self.drawn_numbers_text = ctk.CTkTextbox(
            drawn_frame,
            height=70,
            font=("Segoe UI", 12),
            wrap="word"
        )
        self.drawn_numbers_text.pack(fill="x", pady=(4, 0))
        self.drawn_numbers_text.insert("1.0", "Noch nicht geladen")
        self.drawn_numbers_text.configure(state="disabled")

        actions = ctk.CTkFrame(result_frame, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=10)

        ctk.CTkButton(
            actions,
            text="Ziehung simulieren",
            command=self.open_drawn_numbers_editor,
            fg_color="#34C759",
            hover_color="#248A3D"
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            actions,
            text="Export",
            command=self.export_result,
            fg_color="#777",
            hover_color="#555"
        ).pack(side="left", padx=5)

    def enable_drop_target(self, widget):
        if DND_FILES is None or TkinterDnD is None:
            return
    
        try:
            self.tk.call("tkdnd::drop_target", "register", widget._w, DND_FILES)
    
            drop_command = self.register(self.handle_drop_data)
            self.tk.call("bind", widget._w, "<<Drop>>", f"{drop_command} %D")
    
        except Exception:
            pass

    # -----------------------------
    # Bild laden / Drop / EXIF / Rotation
    # -----------------------------
    def load_selected_image_path(self, path):
        if not path:
            return

        path = path.strip()

        if path.startswith("file://"):
            path = unquote(path.replace("file://", ""))

        path = path.strip("{}")

        ext = os.path.splitext(path)[1].lower()

        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            messagebox.showwarning("Fehler", "Bitte eine Bilddatei auswählen.")
            return

        self.image_path = path
        self.rotation_angle = 0
        self.crop_box = None
        self.ocr_result = None
        self.drawn_numbers = set()
        self.draw_date = None
        self.draw_date_var.set("Ziehung: noch nicht geladen")

        self.show_preview()
        self.start_process()

    def handle_drop_data(self, data):
        try:
            files = self.tk.splitlist(data)
    
            if not files:
                return
    
            path = files[0]
    
            if path.startswith("file://"):
                path = unquote(path.replace("file://", ""))
    
            path = path.strip("{}")
    
            self.load_selected_image_path(path)
    
        except Exception as e:
            messagebox.showerror("Fehler", f"Drag & Drop fehlgeschlagen:\n{e}")

    def load_image_corrected(self):
        if not self.image_path:
            return None

        img = Image.open(self.image_path)
        img = ImageOps.exif_transpose(img)

        if self.rotation_angle != 0:
            img = img.rotate(self.rotation_angle, expand=True)

        return img

    def select_image(self):
        path = filedialog.askopenfilename(
            title="Bingo-Foto auswählen",
            filetypes=[
                ("Bilder", "*.jpg *.jpeg *.png *.webp"),
                ("Alle Dateien", "*.*")
            ]
        )

        if path:
            self.load_selected_image_path(path)

    def show_preview(self):
        if not self.image_path:
            return

        try:
            img = self.load_image_corrected()
            draw_img = img.copy()

            if self.crop_box:
                draw = ImageDraw.Draw(draw_img)
                draw.rectangle(self.crop_box, outline="red", width=6)

            draw_img.thumbnail((420, 310), RESAMPLE)

            self.preview_image = ctk.CTkImage(
                dark_image=draw_img,
                light_image=draw_img,
                size=draw_img.size
            )

            self.image_label.configure(image=self.preview_image, text="")

        except Exception as e:
            messagebox.showerror("Fehler", f"Bild konnte nicht geladen werden:\n{e}")

    def rotate_image(self, delta):
        if not self.image_path:
            messagebox.showwarning("Fehler", "Bitte zuerst ein Bild auswählen.")
            return

        self.rotation_angle = (self.rotation_angle + delta) % 360
        self.crop_box = None

        self.show_preview()
        self.start_process()

    # -----------------------------
    # Manuelles Zuschneiden
    # -----------------------------
    def open_crop_window(self):
        if self.crop_window is not None and self.crop_window.winfo_exists():
            self.crop_window.lift()
            self.crop_window.focus_force()
            return
    
        if not self.image_path:
            messagebox.showwarning("Fehler", "Bitte zuerst ein Bild auswählen.")
            return

        img = self.load_image_corrected()
        original_w, original_h = img.size

        max_w = 900
        max_h = 650
        scale = min(max_w / original_w, max_h / original_h, 1.0)

        display_w = int(original_w * scale)
        display_h = int(original_h * scale)

        display_img = img.resize((display_w, display_h), RESAMPLE)

        top = ctk.CTkToplevel(self)
        self.crop_window = top
        top.title("Zahlenfeld zuschneiden")
        top.geometry(f"{display_w + 40}x{display_h + 110}")
        top.resizable(False, False)

        def on_close():
            self.crop_window = None
            top.destroy()
        
        top.protocol("WM_DELETE_WINDOW", on_close)

        info = ctk.CTkLabel(
            top,
            text="Ziehe mit der Maus ein Rechteck um NUR das 5x5-Zahlenfeld.",
            font=("Segoe UI", 13)
        )
        info.pack(pady=8)

        canvas = tk.Canvas(top, width=display_w, height=display_h, bg="black", highlightthickness=0)
        canvas.pack(padx=20, pady=5)

        tk_img = ImageTk.PhotoImage(display_img)
        canvas.image = tk_img
        canvas.create_image(0, 0, anchor="nw", image=tk_img)

        state = {
            "start_x": 0,
            "start_y": 0,
            "rect": None,
            "coords": None
        }

        def on_mouse_down(event):
            state["start_x"] = event.x
            state["start_y"] = event.y

            if state["rect"] is not None:
                canvas.delete(state["rect"])

            state["rect"] = canvas.create_rectangle(
                event.x, event.y, event.x, event.y,
                outline="red",
                width=3
            )

        def on_mouse_drag(event):
            if state["rect"] is None:
                return

            x1 = state["start_x"]
            y1 = state["start_y"]
            x2 = max(0, min(event.x, display_w))
            y2 = max(0, min(event.y, display_h))

            canvas.coords(state["rect"], x1, y1, x2, y2)

        def on_mouse_up(event):
            x1 = state["start_x"]
            y1 = state["start_y"]
            x2 = max(0, min(event.x, display_w))
            y2 = max(0, min(event.y, display_h))

            left = min(x1, x2)
            top_y = min(y1, y2)
            right = max(x1, x2)
            bottom = max(y1, y2)

            state["coords"] = (left, top_y, right, bottom)

        canvas.bind("<ButtonPress-1>", on_mouse_down)
        canvas.bind("<B1-Motion>", on_mouse_drag)
        canvas.bind("<ButtonRelease-1>", on_mouse_up)

        btn_frame = ctk.CTkFrame(top, fg_color="transparent")
        btn_frame.pack(pady=8)

        def apply_crop():
            if not state["coords"]:
                messagebox.showwarning("Fehler", "Bitte zuerst ein Rechteck ziehen.")
                return

            left, top_y, right, bottom = state["coords"]

            if abs(right - left) < 50 or abs(bottom - top_y) < 50:
                messagebox.showwarning("Fehler", "Der Ausschnitt ist zu klein.")
                return

            self.crop_box = (
                int(left / scale),
                int(top_y / scale),
                int(right / scale),
                int(bottom / scale)
            )

            on_close()
            self.show_preview()
            self.start_process()

        ctk.CTkButton(
            btn_frame,
            text="Übernehmen",
            command=apply_crop,
            fg_color="#007AFF",
            hover_color="#0056b3"
        ).pack(side="left", padx=6)

        ctk.CTkButton(
            btn_frame,
            text="Abbrechen",
            command=on_close,
            fg_color="#777",
            hover_color="#555"
        ).pack(side="left", padx=6)

    # -----------------------------
    # OCR Start
    # -----------------------------
    def start_process(self):
        if not self.image_path:
            messagebox.showwarning("Fehler", "Bitte ein Foto auswählen!")
            return

        if self.processing:
            self.status_var.set("Analyse läuft bereits...")
            return

        self.processing = True
        self.status_var.set("Bild wird analysiert...")
        self.progress.set(0.15)
        self.update_idletasks()

        threading.Thread(target=self.process_image, daemon=True).start()

    def process_image(self):
        try:
            with self.process_lock:
                img = self.load_image_corrected()

                numbers = self.read_grid_with_macos_vision(img)
                del img

                drawn, draw_date = self.fetch_drawn_numbers()

                if not drawn:
                    raise RuntimeError("Offizielle Gewinnzahlen konnten nicht geladen werden.")

                hits = []
                for row in numbers:
                    hits.append([n in drawn for n in row])

                self.ocr_result = numbers
                self.drawn_numbers = drawn
                self.draw_date = draw_date

                self.after(0, lambda: self.render_result(hits))

        except Exception as e:
            err = str(e)
            self.after(0, lambda: self.status_var.set("Fehler bei der Analyse"))
            self.after(0, lambda: self.progress.set(0))
            self.after(0, lambda: messagebox.showerror("Fehler", f"OCR-Fehler:\n{err}"))

        finally:
            self.processing = False
            gc.collect()

    # -----------------------------
    # Grid finden
    # -----------------------------
    def get_grid_image(self, img):
        if self.crop_box:
            left, top, right, bottom = self.crop_box
            return img.crop((left, top, right, bottom)), "manueller Crop"

        box = self.auto_find_grid_box(img)
        if box:
            left, top, right, bottom = box
            return img.crop((left, top, right, bottom)), "automatisch erkannt"

        return img, "Fallback: ganzes Bild"

    def auto_find_grid_box(self, img):
        """
        Erkennt das 5x5-Zahlenfeld in zwei Schritten:

        1. Den größten zusammenhängenden HELLEN Bereich im Foto finden
           (Connected-Component-Analyse statt einfacher Zeilen-/Spalten-
           summen). Das ist der weiße Los-Schein selbst, robust getrennt
           von einem unruhigen Hintergrund (z.B. Bäume/Textur), weil echte
           2D-Zusammenhängigkeit geprüft wird statt unabhängiger Zeilen-
           und Spaltenhelligkeit (die bei texturiertem Hintergrund leicht
           in die Irre führt).
        2. Innerhalb dieses Bereichs den blauen BINGO-Kopf per Farbe finden
           (deutlich mehr Blau als Rot/Grün) und dessen Unterkante als
           obere Grenze des Zahlenfelds verwenden, damit der Header nie
           mit ins Feld gerät.

        Die Gitterlinien selbst eignen sich NICHT als verlässliches
        Trennmerkmal für die exakten Zellgrenzen, da die fetten Ziffern
        auf diesem Schein genauso dunkel/breit sind wie die Linien.
        Darum bleibt die Aufteilung in 5x5 Zellen nach dem Crop weiterhin
        gleichmäßig (siehe read_grid_with_macos_vision) – das passt gut,
        sobald der Crop selbst sauber ist.
        """
        small = img.copy()
        max_w = 900
        scale = min(max_w / small.width, 1.0)
        new_size = (int(small.width * scale), int(small.height * scale))
        small = small.resize(new_size, RESAMPLE)

        gray = np.array(small.convert("L"))
        bright = gray > 150

        # kleine dunkle Lücken (Ziffern, dünne Linien) innerhalb der Karte
        # schließen, damit sie den Zusammenhang nicht unterbrechen
        bright = ndimage.binary_closing(bright, structure=np.ones((9, 9)))

        labeled, n = ndimage.label(bright)

        if n == 0:
            return None

        sizes = ndimage.sum(bright, labeled, range(1, n + 1))
        biggest = int(np.argmax(sizes)) + 1

        ys, xs = np.where(labeled == biggest)

        if len(xs) == 0 or len(ys) == 0:
            return None

        cx1, cy1, cx2, cy2 = int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())

        if (cx2 - cx1) < small.width * 0.18 or (cy2 - cy1) < small.height * 0.18:
            return None

        # Innerhalb der gefundenen Karte: blauen Header abtrennen
        card_rgb = np.array(small.convert("RGB"))[cy1:cy2, cx1:cx2].astype(np.float32)
        ch, cw, _ = card_rgb.shape
        r, g, b = card_rgb[..., 0], card_rgb[..., 1], card_rgb[..., 2]

        blue_mask = (b > 90) & (b - r > 25) & (b - g > 15)
        blue_rows = np.where(blue_mask.mean(axis=1) > 0.25)[0]

        header_bottom = 0
        top_blue = blue_rows[blue_rows < ch * 0.5] if len(blue_rows) else blue_rows

        if len(top_blue) > 0:
            header_bottom = int(top_blue.max()) + 1

        y1 = cy1 + header_bottom
        y2 = cy2
        x1 = cx1
        x2 = cx2

        inv = 1.0 / scale

        return (
            int(x1 * inv),
            int(y1 * inv),
            int(x2 * inv),
            int(y2 * inv)
        )

    # -----------------------------
    # macOS Vision OCR
    # -----------------------------
    def macos_vision_ocr(self, pil_img, fast=True):
        pool = NSAutoreleasePool.alloc().init()
        tmp_path = None

        try:
            if pil_img.mode not in ("RGB", "L"):
                pil_img = pil_img.convert("RGB")

            fd, tmp_path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
            pil_img.save(tmp_path)

            url = NSURL.fileURLWithPath_(tmp_path)

            observations = []
            callback_error = {"error": None}

            def completion_handler(request, error):
                if error is not None:
                    callback_error["error"] = error
                    return
                results = request.results()
                if results:
                    observations.extend(results)

            request = VNRecognizeTextRequest.alloc().initWithCompletionHandler_(
                completion_handler
            )

            if fast:
                request.setRecognitionLevel_(VNRequestTextRecognitionLevelFast)
            else:
                request.setRecognitionLevel_(VNRequestTextRecognitionLevelAccurate)

            request.setUsesLanguageCorrection_(False)
            request.setRecognitionLanguages_(["en-US"])

            handler = VNImageRequestHandler.alloc().initWithURL_options_(url, {})

            result = handler.performRequests_error_([request], None)

            if isinstance(result, tuple):
                success, error = result
            else:
                success = result
                error = None

            if not success:
                raise RuntimeError(f"Vision OCR fehlgeschlagen: {error}")

            if callback_error["error"] is not None:
                raise RuntimeError(f"Vision OCR Callback-Fehler: {callback_error['error']}")

            w, h = pil_img.size
            output = []

            for obs in observations:
                candidates = obs.topCandidates_(1)

                if not candidates:
                    continue

                candidate = candidates[0]
                text = str(candidate.string())
                confidence = float(candidate.confidence())

                bb = obs.boundingBox()

                x = bb.origin.x * w
                y = bb.origin.y * h
                bw = bb.size.width * w
                bh = bb.size.height * h

                x1 = x
                x2 = x + bw

                y1 = h - (y + bh)
                y2 = h - y

                bbox = [(x1, y1), (x2, y1), (x2, y2), (x1, y2)]
                output.append((bbox, text, confidence))

            return output

        finally:
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            del pool
            gc.collect()

    def preprocess_grid_for_vision(self, grid_img):
        """
        Verbesserte, aber vorsichtige Vorverarbeitung:
        - keine Ränder hinzufügen
        - keine harte Schwarz/Weiß-Binarisierung
        - kleine Bilder hochskalieren
        - Kontrast und Schärfe moderat verbessern
        - etwas besser für graue Quittungen/Thermopapier
        """

        img = grid_img.convert("L")

        w, h = img.size

        target_width = 1300

        if w < target_width:
            scale = target_width / w
            img = img.resize(
                (int(w * scale), int(h * scale)),
                RESAMPLE
            )
        elif w > 1800:
            scale = 1800 / w
            img = img.resize(
                (int(w * scale), int(h * scale)),
                RESAMPLE
            )

        img = ImageOps.autocontrast(img, cutoff=1)
        img = ImageEnhance.Contrast(img).enhance(2.6)
        img = ImageEnhance.Brightness(img).enhance(1.10)
        img = ImageOps.autocontrast(img, cutoff=0)

        img = img.filter(
            ImageFilter.UnsharpMask(
                radius=1.1,
                percent=150,
                threshold=3
            )
        )

        return img

    def read_grid_with_macos_vision(self, img):
        grid_img, mode = self.get_grid_image(img)

        self.after(0, lambda: self.progress.set(0.25))

        proc = self.preprocess_grid_for_vision(grid_img)

        self.after(0, lambda: self.progress.set(0.35))

        # Für Bingo-Zahlen immer Accurate verwenden
        result = self.macos_vision_ocr(proc, fast=False)

        self.after(0, lambda: self.progress.set(0.75))

        proc_w, proc_h = proc.size
        cell_w = proc_w / 5
        cell_h = proc_h / 5

        cells = [[[] for _ in range(5)] for _ in range(5)]

        for bbox, text, confidence in result:
            text = str(text).strip()
            found = re.findall(r"\d{1,2}", text)

            if not found:
                continue

            xs = [p[0] for p in bbox]
            ys = [p[1] for p in bbox]

            cx = sum(xs) / len(xs)
            cy = sum(ys) / len(ys)

            col = max(0, min(4, int(cx / cell_w)))
            row = max(0, min(4, int(cy / cell_h)))

            for item in found:
                try:
                    value = int(item)
                except ValueError:
                    continue

                if 1 <= value <= 75:
                    cells[row][col].append((value, confidence, text))

        numbers = []

        for r in range(5):
            row_numbers = []

            for c in range(5):
                candidates = cells[r][c]

                if not candidates:
                    row_numbers.append(0)
                    continue

                candidates.sort(key=lambda x: x[1], reverse=True)
                row_numbers.append(candidates[0][0])

            numbers.append(row_numbers)

        self.after(0, lambda: self.progress.set(0.9))

        return numbers

    # -----------------------------
    # Gewinnzahlen holen
    # -----------------------------
    def fetch_drawn_numbers(self):
        url = "https://www.lotto-niedersachsen.de/bingo"

        def clean_draw_date(raw):
            if not raw:
                return None

            text = re.sub(r"\s+", " ", raw).strip()

            # Aus "Gewinnzahlen am Sonntag, 14.06.2026"
            # wird "Sonntag, 14.06.2026"
            text = re.sub(
                r"^Gewinnzahlen\s+am\s+",
                "",
                text,
                flags=re.IGNORECASE
            ).strip()

            match = re.search(
                r"(?:(Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag),\s*)?\d{1,2}\.\d{1,2}\.\d{4}",
                text
            )

            if match:
                return match.group(0)

            return text or None

        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 Chrome/120 Safari/537.36"
                ),
                "Accept-Language": "de-DE,de;q=0.9",
            }

            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, "html.parser")

            candidates = []

            # Über Bingo-Zahlencontainer laufen und die passende Datumszeile suchen
            for numbers_container in soup.select(".bingo-draw-numbers"):
                drawn = set()

                balls = numbers_container.select(".draw-number-ball.default")

                for ball in balls:
                    raw = ball.get("aria-label") or ball.get_text(strip=True)

                    if raw and raw.isdigit():
                        value = int(raw)
                        if 1 <= value <= 75:
                            drawn.add(value)

                draw_date = None

                # In deinem HTML liegt .draw-card__date-section direkt vor
                # .draw-card__numbers-section.
                numbers_section = numbers_container.find_parent(
                    "div",
                    class_="draw-card__numbers-section"
                )

                if numbers_section:
                    date_section = numbers_section.find_previous_sibling(
                        "div",
                        class_="draw-card__date-section"
                    )

                    if date_section:
                        date_line = date_section.select_one(".draw-card__date-line")
                        if date_line:
                            draw_date = clean_draw_date(
                                date_line.get_text(" ", strip=True)
                            )

                # Fallback: Suche im übergeordneten Card-Bereich
                if not draw_date:
                    parent = numbers_container.find_parent()

                    for _ in range(6):
                        if not parent:
                            break

                        date_line = parent.select_one(".draw-card__date-line")

                        if date_line:
                            draw_date = clean_draw_date(
                                date_line.get_text(" ", strip=True)
                            )
                            break

                        parent = parent.find_parent()

                if len(drawn) == 22:
                    candidates.append((drawn, draw_date))

            if candidates:
                return candidates[0]

            raise ValueError("Keine vollständige BINGO-Ziehung mit 22 Zahlen gefunden.")

        except Exception:
            return set(), None

    # -----------------------------
    # Gezogene Zahlen anzeigen / simulieren
    # -----------------------------
    def update_drawn_numbers_display(self):
        if not self.drawn_numbers_text:
            return

        if self.draw_date:
            self.draw_date_var.set(f"Ziehung: {self.draw_date}")
        elif self.drawn_numbers:
            self.draw_date_var.set("Ziehung: manuell/simuliert")
        else:
            self.draw_date_var.set("Ziehung: noch nicht geladen")

        if self.drawn_numbers:
            text = ", ".join(map(str, sorted(self.drawn_numbers)))
        else:
            text = "Keine gezogenen Zahlen geladen"

        self.drawn_numbers_text.configure(state="normal")
        self.drawn_numbers_text.delete("1.0", "end")
        self.drawn_numbers_text.insert("1.0", text)
        self.drawn_numbers_text.configure(state="disabled")

    def parse_drawn_numbers_input(self, raw):
        nums = re.findall(r"\b\d{1,2}\b", raw)

        drawn = set()

        for n in nums:
            value = int(n)
            if 1 <= value <= 75:
                drawn.add(value)

        return drawn

    def open_drawn_numbers_editor(self):
        top = ctk.CTkToplevel(self)
        top.title("Gezogene Zahlen simulieren")
        top.geometry("520x330")
        top.resizable(False, False)

        frame = ctk.CTkFrame(top)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            frame,
            text="Gezogene Zahlen eingeben",
            font=("Segoe UI", 16, "bold")
        ).pack(anchor="w", pady=(0, 8))

        ctk.CTkLabel(
            frame,
            text=(
                "Zahlen mit Leerzeichen, Komma oder Zeilenumbruch trennen.\n"
                "Zum Bingo-Test reicht z.B. eine komplette Reihe deines Scheins."
            ),
            font=("Segoe UI", 12),
            text_color="#777",
            justify="left"
        ).pack(anchor="w", pady=(0, 8))

        box = ctk.CTkTextbox(frame, height=120, font=("Segoe UI", 13))
        box.pack(fill="x", pady=8)

        if self.drawn_numbers:
            box.insert("1.0", " ".join(map(str, sorted(self.drawn_numbers))))

        def save():
            raw = box.get("1.0", "end")
            drawn = self.parse_drawn_numbers_input(raw)

            if not drawn:
                messagebox.showwarning(
                    "Fehler",
                    "Bitte mindestens eine gültige Zahl zwischen 1 und 75 eingeben."
                )
                return

            self.drawn_numbers = drawn

            # Bei Simulation kein offizielles Ziehungsdatum anzeigen
            self.draw_date = None
            self.draw_date_var.set("Ziehung: manuell/simuliert")

            self.update_drawn_numbers_display()

            if self.ocr_result:
                self.render_result(self.check_hits())

            top.destroy()

        btns = ctk.CTkFrame(frame, fg_color="transparent")
        btns.pack(fill="x", pady=10)

        ctk.CTkButton(
            btns,
            text="Übernehmen",
            command=save,
            fg_color="#007AFF",
            hover_color="#0056b3"
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            btns,
            text="Abbrechen",
            command=top.destroy,
            fg_color="#777",
            hover_color="#555"
        ).pack(side="left", padx=5)

    # -----------------------------
    # Einzelne Zelle korrigieren
    # -----------------------------
    def open_cell_editor(self, row, col):
        if not self.ocr_result:
            return

        top = ctk.CTkToplevel(self)
        top.title("Zahl korrigieren")
        top.geometry("260x175")
        top.resizable(False, False)

        frame = ctk.CTkFrame(top)
        frame.pack(fill="both", expand=True, padx=20, pady=20)

        ctk.CTkLabel(
            frame,
            text=f"Zelle {row + 1},{col + 1}",
            font=("Segoe UI", 15, "bold")
        ).pack(pady=(0, 10))

        entry = ctk.CTkEntry(
            frame,
            width=90,
            height=38,
            justify="center",
            font=("Segoe UI", 16, "bold")
        )
        entry.pack(pady=5)

        current = self.ocr_result[row][col]

        if current != 0:
            entry.insert(0, str(current))
            entry.select_range(0, "end")

        entry.focus_set()

        def save():
            raw = entry.get().strip()

            try:
                value = int(raw)
                if not 1 <= value <= 75:
                    value = 0
            except ValueError:
                value = 0

            self.ocr_result[row][col] = value
            top.destroy()
            self.render_result(self.check_hits())

        entry.bind("<Return>", lambda e: save())

        ctk.CTkButton(
            frame,
            text="Übernehmen",
            command=save,
            fg_color="#007AFF",
            hover_color="#0056b3"
        ).pack(pady=10)

    # -----------------------------
    # Ergebnis darstellen
    # -----------------------------
    def render_result(self, hits):
        self.status_var.set("Analyse abgeschlossen")
        self.progress.set(1.0)
        self.update_drawn_numbers_display()

        for child in self.grid_frame.winfo_children():
            child.destroy()

        bingo_cells = self.get_bingo_cells(hits)

        for r, row in enumerate(self.ocr_result):
            for c, num in enumerate(row):
                is_hit = hits[r][c]
                is_bingo_cell = (r, c) in bingo_cells

                bg = "#34C759" if is_hit else "#D9D9D9"
                text_color = "white" if is_hit else "#111111"

                cell_frame = ctk.CTkFrame(
                    self.grid_frame,
                    width=62,
                    height=54,
                    fg_color="#FF3B30" if is_bingo_cell else "transparent",
                    corner_radius=10
                )
                cell_frame.grid(row=r, column=c, padx=4, pady=4)
                cell_frame.pack_propagate(False)

                lbl = ctk.CTkLabel(
                    cell_frame,
                    text=str(num) if num != 0 else "?",
                    font=("Segoe UI", 15, "bold"),
                    fg_color=bg,
                    text_color=text_color,
                    corner_radius=8,
                    cursor="hand2"
                )

                if is_bingo_cell:
                    lbl.pack(fill="both", expand=True, padx=4, pady=4)
                else:
                    lbl.pack(fill="both", expand=True, padx=0, pady=0)

                cell_frame.bind(
                    "<Button-1>",
                    lambda e, rr=r, cc=c: self.open_cell_editor(rr, cc)
                )
                lbl.bind(
                    "<Button-1>",
                    lambda e, rr=r, cc=c: self.open_cell_editor(rr, cc)
                )

        hits_count = sum(sum(row) for row in hits)
        bingo = self.check_bingo(hits)

        date_part = f" | Ziehung: {self.draw_date}" if self.draw_date else ""
        self.status_var.set(f"Treffer: {hits_count} | {bingo}{date_part}")

    def count_bingos(self, hits):
        count = 0

        # Zeilen
        for r in range(5):
            if all(hits[r]):
                count += 1

        # Spalten
        for c in range(5):
            if all(hits[r][c] for r in range(5)):
                count += 1

        # Diagonale links oben -> rechts unten
        if all(hits[i][i] for i in range(5)):
            count += 1

        # Diagonale rechts oben -> links unten
        if all(hits[i][4 - i] for i in range(5)):
            count += 1

        return count

    def check_bingo(self, hits):
        count = self.count_bingos(hits)

        if count == 0:
            return "Kein Bingo"

        return f"Bingo! {count}x"

    def check_hits(self):
        if not self.ocr_result:
            return []
        return [[n in self.drawn_numbers for n in row] for row in self.ocr_result]

    def get_bingo_cells(self, hits):
        bingo_cells = set()

        # Zeilen
        for r in range(5):
            if all(hits[r]):
                for c in range(5):
                    bingo_cells.add((r, c))

        # Spalten
        for c in range(5):
            if all(hits[r][c] for r in range(5)):
                for r in range(5):
                    bingo_cells.add((r, c))

        # Diagonale links oben -> rechts unten
        if all(hits[i][i] for i in range(5)):
            for i in range(5):
                bingo_cells.add((i, i))

        # Diagonale rechts oben -> links unten
        if all(hits[i][4 - i] for i in range(5)):
            for i in range(5):
                bingo_cells.add((i, 4 - i))

        return bingo_cells

    # -----------------------------
    # Export
    # -----------------------------
    def export_result(self):
        if not self.ocr_result:
            messagebox.showwarning("Fehler", "Kein Ergebnis zum Exportieren!")
            return

        path = filedialog.asksaveasfilename(
            title="Ergebnis speichern",
            defaultextension=".txt",
            filetypes=[
                ("Text-Datei", "*.txt"),
                ("Alle Dateien", "*.*")
            ]
        )

        if path:
            hits = self.check_hits()

            with open(path, "w", encoding="utf-8") as f:
                f.write("BINGO Ergebnis\n")
                f.write("=" * 40 + "\n\n")
                
                if self.draw_date:
                    f.write(f"Ziehung: {self.draw_date}\n\n")

                f.write("Karte:\n")
                for row in self.ocr_result:
                    f.write(" ".join(f"{n:2}" if n != 0 else " ?" for n in row) + "\n")

                f.write("\nGezogene Zahlen:\n")
                f.write(", ".join(map(str, sorted(self.drawn_numbers))) + "\n")

                f.write(f"\nTreffer: {sum(sum(row) for row in hits)}\n")
                f.write(f"Bingo: {self.check_bingo(hits)}\n")

            messagebox.showinfo("Erfolg", f"Ergebnis gespeichert:\n{path}")


# -----------------------------
# Start
# -----------------------------
if __name__ == "__main__":
    app = BingoCheckerApp()
    app.mainloop()