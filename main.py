import customtkinter as ctk
from tkinter import filedialog, messagebox
import google.generativeai as genai
from docx import Document
import csv
import threading
import os
import time
import math

# --- Настройки ---
ctk.set_appearance_mode("Light")
ctk.set_default_color_theme("blue")

SYSTEM_INSTRUCTION = """You are a film director, anthropologist, and visual historian creating cinematic video prompts for Google Veo 3 (fast mode).
Your task is to generate 1 prompt in English from the provided paragraph of a script.
Focus on visual details, lighting, camera angles, and atmosphere.
Ensure the style is consistent with the provided 'Global Context'."""

# Список доступных моделей
AVAILABLE_MODELS = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-2.0-flash-lite",
    "gemini-3-pro-preview",
    "gemini-3-flash-preview"
]

class GeminiApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Настройка окна
        self.title("Gemini Video Prompt Generator (Chapter View)")
        self.geometry("1400x900")

        # Данные
        self.scenes_data = [] # Список словарей: {'text': str, 'prompt': str, 'status': str, 'chapter': str}
        self.chapters_list = [] # Список уникальных названий глав в порядке появления
        self.widget_refs = {} # Ссылки на активные виджеты {index: {'prompt_box': widget, 'status_btn': widget}}
        self.is_processing = False
        self.stop_processing = False

        # Пагинация
        self.current_page = 1 # Индекс главы (1-based)
        self.total_pages = 1

        self.load_env_vars()
        self.setup_ui()

    def load_env_vars(self):
        if os.path.exists(".env"):
            try:
                with open(".env", "r", encoding="utf-8") as f:
                    for line in f:
                        if "=" in line and not line.strip().startswith("#"):
                            k, v = line.strip().split("=", 1)
                            os.environ[k.strip()] = v.strip().strip("'").strip('"')
            except: pass

    def setup_ui(self):
        # Сетка: 0 - Сайдбар, 1 - Основной контент
        self.grid_columnconfigure(0, weight=0) # Sidebar fixed
        self.grid_columnconfigure(1, weight=1) # Main content expands
        self.grid_rowconfigure(0, weight=1)

        # === 1. SIDEBAR (Настройки) ===
        self.sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(12, weight=1)

        ctk.CTkLabel(self.sidebar, text="Генератор промптов", font=("Arial", 20, "bold")).pack(pady=20)

        # API Inputs
        ctk.CTkLabel(self.sidebar, text="Ключ Gemini API").pack(anchor="w", padx=15)
        self.api_entry = ctk.CTkEntry(self.sidebar, show="*")
        self.api_entry.pack(fill="x", padx=15, pady=5)
        if os.environ.get("GEMINI_API_KEY"): self.api_entry.insert(0, os.environ.get("GEMINI_API_KEY"))

        ctk.CTkLabel(self.sidebar, text="Proxy в формате ip:port:login:pass (если нужно):").pack(anchor="w", padx=15, pady=(10,0))
        self.proxy_entry = ctk.CTkEntry(self.sidebar, placeholder_text="ip:port:user:pass")
        self.proxy_entry.pack(fill="x", padx=15, pady=5)
        if os.environ.get("GEMINI_PROXY"): self.proxy_entry.insert(0, os.environ.get("GEMINI_PROXY"))

        # Model Selection
        ctk.CTkLabel(self.sidebar, text="Модель:").pack(anchor="w", padx=15, pady=(10, 0))
        self.model_menu = ctk.CTkOptionMenu(self.sidebar, values=AVAILABLE_MODELS)
        self.model_menu.pack(fill="x", padx=15, pady=5)
        self.model_menu.set("gemini-2.5-flash") # Значение по умолчанию

        # Actions
        ctk.CTkButton(self.sidebar, text="1. Загрузить DOCX", command=self.load_docx, fg_color="#2E7D32").pack(fill="x", padx=15, pady=(20, 10))
        self.btn_context = ctk.CTkButton(self.sidebar, text="2. Создать Контекст", command=self.generate_context_thread, state="disabled", fg_color="#7B1FA2")
        self.btn_context.pack(fill="x", padx=15, pady=5)

        self.btn_gen_all = ctk.CTkButton(self.sidebar, text="3. Генерировать ВСЕ", command=self.toggle_generation, state="disabled", fg_color="#1565C0")
        self.btn_gen_all.pack(fill="x", padx=15, pady=5)

        self.btn_save = ctk.CTkButton(self.sidebar, text="4. Сохранить CSV", command=self.save_csv, state="disabled", fg_color="#EF6C00")
        self.btn_save.pack(fill="x", padx=15, pady=5)

        self.progress_bar = ctk.CTkProgressBar(self.sidebar)
        self.progress_bar.pack(fill="x", padx=15, pady=(20, 5))
        self.progress_bar.set(0)

        self.status_label = ctk.CTkLabel(self.sidebar, text="Готов к работе", text_color="gray", wraplength=200)
        self.status_label.pack(padx=15, pady=5)

        # === 2. MAIN CONTENT AREA ===
        self.main_frame = ctk.CTkFrame(self, corner_radius=0, fg_color="transparent")
        self.main_frame.grid(row=0, column=1, sticky="nsew", padx=20, pady=10)
        self.main_frame.grid_rowconfigure(2, weight=1) # Scroll area expands
        self.main_frame.grid_columnconfigure(0, weight=1)

        # A. Context Area
        ctk.CTkLabel(self.main_frame, text="Глобальный контекст / визуальный стиль", font=("Arial", 12, "bold")).grid(row=0, column=0, sticky="w")
        # Увеличили высоту текстового поля
        self.context_text = ctk.CTkTextbox(self.main_frame, height=150)
        self.context_text.grid(row=1, column=0, sticky="ew", pady=(0, 10))

        # B. Pagination Control
        self.pagination_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent", height=40)
        self.pagination_frame.grid(row=3, column=0, sticky="ew", pady=(5, 5))

        self.btn_prev = ctk.CTkButton(self.pagination_frame, text="<< Глава", width=100, command=self.prev_page, state="disabled")
        self.btn_prev.pack(side="left")

        self.lbl_page = ctk.CTkLabel(self.pagination_frame, text="Загрузите файл...", font=("Arial", 14, "bold"))
        self.lbl_page.pack(side="left", expand=True)

        self.btn_next = ctk.CTkButton(self.pagination_frame, text="Глава >>", width=100, command=self.next_page, state="disabled")
        self.btn_next.pack(side="right")

        # C. Scrollable Card List
        self.scroll_frame = ctk.CTkScrollableFrame(self.main_frame, label_text="Сцены", label_font=("Arial", 14, "bold"))
        self.scroll_frame.grid(row=2, column=0, sticky="nsew")
        self.scroll_frame.grid_columnconfigure(0, weight=1)

    # --- ЛОГИКА ---

    def configure_proxy(self):
        raw = self.proxy_entry.get().strip()
        if raw:
            if "@" not in raw and len(raw.split(":")) == 4:
                ip, port, u, p = raw.split(":")
                url = f"http://{u}:{p}@{ip}:{port}"
            elif "://" not in raw:
                url = f"http://{raw}"
            else:
                url = raw
            os.environ['http_proxy'] = url
            os.environ['https_proxy'] = url
        else:
            os.environ.pop('http_proxy', None)
            os.environ.pop('https_proxy', None)

    def get_model(self):
        key = self.api_entry.get().strip()
        if not key:
            messagebox.showwarning("API Key", "Введите API Key!")
            return None
        self.configure_proxy()
        genai.configure(api_key=key)

        # Получаем выбранную модель из выпадающего списка
        selected_model = self.model_menu.get()
        return genai.GenerativeModel(selected_model, system_instruction=SYSTEM_INSTRUCTION)

    def parse_docx(self, path):
        # Парсит документ, разделяя его на главы. Возвращает список словарей.
        doc = Document(path)
        parsed_items = []
        current_header = "General / Introduction" # Глава по умолчанию

        for para in doc.paragraphs:
            text = para.text.strip()
            if not text: continue

            # Эвристика для определения заголовков
            is_header = False
            # Если строка короткая и содержит ключевые слова
            if len(text) < 100:
                text_lower = text.lower()
                if any(x in text_lower for x in ["chapter", "introduction", "conclusion", "part", "глава", "введение"]):
                    is_header = True

            if is_header:
                current_header = text # Обновляем текущую главу, но НЕ добавляем её как сцену для генерации
            else:
                # Добавляем текст, привязывая его к текущей главе
                parsed_items.append({
                    "text": text,
                    "chapter": current_header
                })

        return parsed_items

    def load_docx(self):
        path = filedialog.askopenfilename(filetypes=[("Word", "*.docx")])
        if not path: return

        try:
            items = self.parse_docx(path)
            if not items:
                messagebox.showwarning("Пусто", "Текст не найден.")
                return

            # Инициализация данных
            self.scenes_data = [{"text": item["text"], "prompt": "", "status": "wait", "chapter": item["chapter"]} for item in items]

            # Собираем уникальные главы, сохраняя порядок
            seen = set()
            self.chapters_list = []
            for item in self.scenes_data:
                if item["chapter"] not in seen:
                    self.chapters_list.append(item["chapter"])
                    seen.add(item["chapter"])

            # Настройка пагинации
            self.total_pages = len(self.chapters_list)
            self.current_page = 1

            # Обновление UI
            self.render_page()

            self.status_label.configure(text=f"Загружено: {len(items)} сцен, {self.total_pages} глав")
            self.btn_context.configure(state="normal")
            self.btn_gen_all.configure(state="normal")
            self.btn_save.configure(state="normal")

        except Exception as e:
            messagebox.showerror("Ошибка", str(e))

    def render_page(self):
        # 1. Очистка
        self.widget_refs.clear()
        for w in self.scroll_frame.winfo_children(): w.destroy()

        if not self.scenes_data or not self.chapters_list:
            self.lbl_page.configure(text="Нет данных")
            return

        # 2. Получаем текущую главу
        current_chapter_name = self.chapters_list[self.current_page - 1]

        # 3. Фильтруем сцены только для этой главы
        # Используем enumerate, чтобы сохранить глобальный индекс 'i' для генератора
        chapter_scenes = [(i, x) for i, x in enumerate(self.scenes_data) if x["chapter"] == current_chapter_name]

        # 4. Рендерим карточки
        for i, data in chapter_scenes:
            self.create_card(i, data)

        # 5. Обновляем элементы управления
        self.lbl_page.configure(text=f"Глава: {current_chapter_name} ({self.current_page}/{self.total_pages})")
        self.btn_prev.configure(state="normal" if self.current_page > 1 else "disabled")
        self.btn_next.configure(state="normal" if self.current_page < self.total_pages else "disabled")
        # Обновляем заголовок скролла, чтобы было видно сколько сцен в этой главе
        self.scroll_frame.configure(label_text=f"Сцены главы (всего {len(chapter_scenes)})")

    def create_card(self, index, data):
        # Card Container
        card = ctk.CTkFrame(self.scroll_frame, fg_color=("white", "gray20"), border_width=1, border_color="gray70")
        card.pack(fill="x", padx=5, pady=5)
        card.grid_columnconfigure(1, weight=1) # Text expand
        card.grid_columnconfigure(3, weight=1) # Prompt expand

        # ID
        ctk.CTkLabel(card, text=f"#{index + 1}", width=30, font=("Arial", 12, "bold")).grid(row=0, column=0, padx=5, sticky="n", pady=5)

        # Original Text
        txt_orig = ctk.CTkTextbox(card, height=100, font=("Arial", 11), text_color="gray40")
        txt_orig.grid(row=0, column=1, sticky="nsew", padx=5, pady=5)
        txt_orig.insert("0.0", data["text"])
        txt_orig.configure(state="disabled")

        # Controls (Middle)
        ctrl_frame = ctk.CTkFrame(card, fg_color="transparent")
        ctrl_frame.grid(row=0, column=2, padx=2, sticky="n", pady=5)

        btn_gen = ctk.CTkButton(ctrl_frame, text="Gen ➜", width=60, height=30, command=lambda idx=index: self.generate_single_thread(idx))
        btn_gen.pack(pady=5)

        # Color code status
        if data["status"] == "done": btn_gen.configure(fg_color="#388E3C", text="OK")
        elif data["status"] == "error": btn_gen.configure(fg_color="#D32F2F", text="Err")

        # Result Prompt
        txt_prompt = ctk.CTkTextbox(card, height=100, font=("Arial", 11), border_color="green", border_width=1)
        txt_prompt.grid(row=0, column=3, sticky="nsew", padx=5, pady=5)
        txt_prompt.insert("0.0", data["prompt"])

        # Bind edit event
        txt_prompt.bind("<KeyRelease>", lambda e, idx=index, w=txt_prompt: self.on_manual_edit(idx, w))

        # Store widget references for updates
        self.widget_refs[index] = {
            'prompt_box': txt_prompt,
            'status_btn': btn_gen
        }

    def on_manual_edit(self, index, widget):
        self.scenes_data[index]["prompt"] = widget.get("0.0", "end").strip()

    def prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.render_page()

    def next_page(self):
        if self.current_page < self.total_pages:
            self.current_page += 1
            self.render_page()

    # --- ГЕНЕРАЦИЯ ---

    def generate_context_thread(self):
        threading.Thread(target=self._gen_context).start()

    def _gen_context(self):
        model = self.get_model()
        if not model: return
        self.btn_context.configure(text="Анализ...", state="disabled")
        try:
            full_text = "\n".join([d["text"] for d in self.scenes_data])
            prompt = f"Analyze this script (first 15k chars) and ONLY describe 'Visual Style, Era, Atmosphere' (3-4 sentences), dont need to write prompt now.\n\n{full_text[:15000]}"
            resp = model.generate_content(prompt)
            self.context_text.delete("0.0", "end")
            self.context_text.insert("0.0", resp.text)
            self.btn_context.configure(text="2. Обновить контекст", state="normal")
        except Exception as e:
            self.status_label.configure(text=f"Err Context: {e}")
            self.btn_context.configure(text="Ошибка", state="normal")

    def generate_single_thread(self, idx):
        threading.Thread(target=self._gen_single, args=(idx,)).start()

    def _gen_single(self, idx):
        model = self.get_model()
        if not model: return

        # Update UI if visible
        if idx in self.widget_refs:
            self.widget_refs[idx]['status_btn'].configure(text="...", state="disabled")

        try:
            data = self.scenes_data[idx]
            context = self.context_text.get("0.0", "end")
            prompt = f"Global Context: {context}\n\nScene: {data['text']}\n\nTask: Generate video prompt."

            resp = model.generate_content(prompt)
            result = resp.text.strip()

            # Save Data
            self.scenes_data[idx]["prompt"] = result
            self.scenes_data[idx]["status"] = "done"

            # Update UI if visible
            if idx in self.widget_refs:
                 self.widget_refs[idx]['prompt_box'].delete("0.0", "end")
                 self.widget_refs[idx]['prompt_box'].insert("0.0", result)
                 self.widget_refs[idx]['status_btn'].configure(text="OK", fg_color="#388E3C", state="normal")

        except Exception as e:
            self.scenes_data[idx]["status"] = "error"
            if idx in self.widget_refs:
                self.widget_refs[idx]['prompt_box'].insert("0.0", f"Error: {e}")
                self.widget_refs[idx]['status_btn'].configure(text="Err", fg_color="#D32F2F", state="normal")

    def toggle_generation(self):
        if self.is_processing:
            self.stop_processing = True
            self.btn_gen_all.configure(text="Остановка...")
        else:
            self.stop_processing = False
            self.is_processing = True
            self.btn_gen_all.configure(text="Остановить", fg_color="#D32F2F")
            threading.Thread(target=self._process_queue).start()

    def _process_queue(self):
        model = self.get_model()
        if not model:
            self.is_processing = False
            self.after(0, lambda: self.btn_gen_all.configure(text="3. Генерировать ВСЕ", fg_color="#1565C0"))
            return

        context = self.context_text.get("0.0", "end")
        total = len(self.scenes_data)

        for i, data in enumerate(self.scenes_data):
            if self.stop_processing: break
            if data["status"] == "done": continue

            # UI Update
            self.after(0, lambda p=i/total: self.progress_bar.set(p))
            self.after(0, lambda txt=f"Обработка {i+1}/{total}": self.status_label.configure(text=txt))

            # Если элемент сейчас виден на экране, обновляем его статус визуально
            if i in self.widget_refs:
                 self.after(0, lambda idx=i: self.widget_refs[idx]['status_btn'].configure(text="...", state="disabled"))

            try:
                prompt = f"Global Context: {context}\n\nScene: {data['text']}\n\nTask: Generate video prompt."
                resp = model.generate_content(prompt)

                # Success Logic
                self.scenes_data[i]["prompt"] = resp.text.strip()
                self.scenes_data[i]["status"] = "done"

                # Если элемент виден, обновляем текстбокс
                if i in self.widget_refs:
                    self.after(0, lambda idx=i, t=resp.text.strip(): self._update_card_ui(idx, t, "done"))

                time.sleep(1.5) # Anti-spam

            except Exception as e:
                self.scenes_data[i]["status"] = "error"
                self.scenes_data[i]["prompt"] = f"Error: {e}"
                if i in self.widget_refs:
                    self.after(0, lambda idx=i, t=str(e): self._update_card_ui(idx, t, "error"))

        self.is_processing = False
        self.stop_processing = False
        self.after(0, lambda: self.btn_gen_all.configure(text="3. Генерировать ВСЕ", fg_color="#1565C0"))
        self.after(0, lambda: self.status_label.configure(text="Готово"))
        self.after(0, lambda: self.progress_bar.set(1.0))

    def _update_card_ui(self, idx, text, status):
        if idx not in self.widget_refs: return

        box = self.widget_refs[idx]['prompt_box']
        btn = self.widget_refs[idx]['status_btn']

        box.delete("0.0", "end")
        box.insert("0.0", text)

        if status == "done":
            btn.configure(text="OK", fg_color="#388E3C", state="normal")
        else:
             btn.configure(text="Err", fg_color="#D32F2F", state="normal")

    def save_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path: return
        try:
            with open(path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow(["ID", "Chapter", "Original Scene", "Generated Prompt"])
                for i, item in enumerate(self.scenes_data):
                    writer.writerow([i+1, item["chapter"], item["text"], item["prompt"]])
            messagebox.showinfo("Saved", "Файл успешно сохранен!")
        except Exception as e:
            messagebox.showerror("Error", str(e))

if __name__ == "__main__":
    app = GeminiApp()
    app.mainloop()