import json
import os
import random
import time
import tkinter as tk
from tkinter import messagebox, ttk

# Manejo de audio con Pygame
try:
    import pygame

    PYGAME_AVAILABLE = True
except ImportError:
    PYGAME_AVAILABLE = False

# --- CONFIGURACIÓN DE PARÁMETROS ---
AUDIO_FILE = "musica_2.mp3"  # Nombre del archivo MP3 en la misma carpeta
TIEMPO_TOTAL_SEG = 180  # 3 minutos de duración
RANKING_FILE = "ranking_stroop.json"

COLORS = {
    "ROJO": "#E53935",
    "VERDE": "#43A047",
    "AZUL": "#1E88E5",
    "AMARILLO": "#FBC02D",
    "NARANJA": "#FB8C00",
    "VIOLETA": "#8E24AA",
}


class StroopTestApp:

    def __init__(self, root):
        self.root = root
        self.root.title("Desafío Stroop - Test de Estrés Mental")
        self.root.geometry("700x600")
        self.root.configure(bg="#1E1E1E")

        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.init()
            except Exception as e:
                print(f"No se pudo inicializar el mezclador de audio: {e}")

        self.nickname = ""
        self.score = 0
        self.aciertos = 0
        self.fallas = 0
        self.tiempo_restante = TIEMPO_TOTAL_SEG
        self.tiempo_inicio = 0
        self.running = False

        self.target_color_name = ""
        self.show_login_screen()

    def play_audio(self):
        """Reproduce la música de fondo en bucle infinito."""
        if PYGAME_AVAILABLE and os.path.exists(AUDIO_FILE):
            try:
                pygame.mixer.music.load(AUDIO_FILE)
                pygame.mixer.music.play(-1)  # -1 = bucle continuo
            except Exception as e:
                print(f"Error al reproducir el archivo de audio: {e}")

    def stop_audio(self):
        """Detiene la reproducción de música."""
        if PYGAME_AVAILABLE:
            try:
                pygame.mixer.music.stop()
            except Exception as e:
                print(f"Error al detener el audio: {e}")

    def clear_screen(self):
        for widget in self.root.winfo_children():
            widget.destroy()

    # --- PANTALLA 1: INGRESO DE SOBRENOMBRE ---
    def show_login_screen(self):
        self.stop_audio()
        self.clear_screen()

        frame = tk.Frame(self.root, bg="#1E1E1E")
        frame.pack(expand=True)

        tk.Label(
            frame,
            text="DESAFÍO DE STROOP",
            font=("Helvetica", 24, "bold"),
            fg="#00E676",
            bg="#1E1E1E",
        ).pack(pady=10)

        tk.Label(
            frame,
            text="Compite por el primer lugar en el Ranking de Agilidad Mental",
            font=("Helvetica", 11),
            fg="#CCCCCC",
            bg="#1E1E1E",
        ).pack(pady=5)

        tk.Label(
            frame,
            text="REGLA DEL JUEGO:\nHaz clic en el botón del COLOR CON EL QUE ESTÁ ESCRITA LA PALABRA\n(Ignora el texto leído).",
            font=("Helvetica", 11, "bold"),
            fg="#FFD54F",
            bg="#1E1E1E",
            justify="center",
        ).pack(pady=15)

        tk.Label(
            frame,
            text="Ingresa tu Sobrenombre / Nickname:",
            font=("Helvetica", 12),
            fg="#FFFFFF",
            bg="#1E1E1E",
        ).pack(pady=5)

        self.nick_entry = tk.Entry(
            frame,
            font=("Helvetica", 14),
            justify="center",
            bg="#333333",
            fg="#FFFFFF",
            insertbackground="white",
        )
        self.nick_entry.pack(pady=10)
        self.nick_entry.focus()

        btn_start = tk.Button(
            frame,
            text="¡COMENZAR PRUEBA!",
            font=("Helvetica", 14, "bold"),
            bg="#00C853",
            fg="white",
            padx=20,
            pady=10,
            relief="flat",
            command=self.start_game,
        )
        btn_start.pack(pady=20)

    # --- PANTALLA 2: JUEGO PRINCIPAL ---
    def start_game(self):
        nick = self.nick_entry.get().strip()
        if not nick:
            messagebox.showwarning(
                "Atención", "Por favor ingresa un sobrenombre para continuar."
            )
            return

        self.nickname = nick
        self.score = 0
        self.aciertos = 0
        self.fallas = 0
        self.tiempo_restante = TIEMPO_TOTAL_SEG
        self.tiempo_inicio = time.time()
        self.running = True

        self.clear_screen()
        self.play_audio()  # Inicia la música en bucle

        # Encabezado: Oculta el puntaje para evitar distracciones
        self.header_frame = tk.Frame(self.root, bg="#2D2D2D", height=60)
        self.header_frame.pack(fill="x")

        self.lbl_timer = tk.Label(
            self.header_frame,
            text="Tiempo: 03:00",
            font=("Helvetica", 14, "bold"),
            fg="#FF5252",
            bg="#2D2D2D",
        )
        self.lbl_timer.pack(side="left", padx=20, pady=10)

        self.lbl_nivel = tk.Label(
            self.header_frame,
            text="Nivel: 1 (Fácil)",
            font=("Helvetica", 12, "bold"),
            fg="#40C4FF",
            bg="#2D2D2D",
        )
        self.lbl_nivel.pack(side="right", padx=20, pady=10)

        # Estímulo visual (Palabra)
        self.word_frame = tk.Frame(self.root, bg="#1E1E1E", height=200)
        self.word_frame.pack(expand=True, fill="both")

        self.lbl_word = tk.Label(
            self.word_frame,
            text="",
            font=("Helvetica", 42, "bold"),
            bg="#1E1E1E",
        )
        self.lbl_word.pack(expand=True)

        # Botonera
        self.buttons_frame = tk.Frame(self.root, bg="#1E1E1E")
        self.buttons_frame.pack(pady=30)

        self.create_color_buttons()
        self.next_stimulus()
        self.update_timer()

    def create_color_buttons(self):
        for widget in self.buttons_frame.winfo_children():
            widget.destroy()

        color_keys = list(COLORS.keys())
        elapsed = TIEMPO_TOTAL_SEG - self.tiempo_restante
        if elapsed >= 105:
            random.shuffle(color_keys)

        for idx, color_name in enumerate(color_keys):
            row = idx // 3
            col = idx % 3
            btn = tk.Button(
                self.buttons_frame,
                text=color_name,
                font=("Helvetica", 12, "bold"),
                bg=COLORS[color_name],
                fg="white" if color_name != "AMARILLO" else "black",
                width=12,
                height=2,
                relief="raised",
                command=lambda c=color_name: self.check_answer(c),
            )
            btn.grid(row=row, column=col, padx=10, pady=10)

    def next_stimulus(self):
        elapsed = TIEMPO_TOTAL_SEG - self.tiempo_restante

        if elapsed < 45:
            self.lbl_nivel.config(
                text="Nivel: 1 (Fácil)", fg="#00E676"
            )
            es_congruente = random.random() < 0.70
        elif elapsed < 105:
            self.lbl_nivel.config(
                text="Nivel: 2 (Intermedio)", fg="#FFD54F"
            )
            es_congruente = random.random() < 0.20
        else:
            self.lbl_nivel.config(
                text="Nivel: 3 (MÁXIMO ESTRÉS)", fg="#FF5252"
            )
            es_congruente = False

        all_colors = list(COLORS.keys())
        self.target_color_name = random.choice(all_colors)

        if es_congruente:
            texto_palabra = self.target_color_name
        else:
            opciones_texto = [c for c in all_colors if c != self.target_color_name]
            texto_palabra = random.choice(opciones_texto)

        self.lbl_word.config(
            text=texto_palabra, fg=COLORS[self.target_color_name]
        )

        if elapsed >= 105:
            self.create_color_buttons()

    def check_answer(self, selected_color):
        if not self.running:
            return

        # Acumulación de puntos interna (sin mostrarse en pantalla)
        if selected_color == self.target_color_name:
            self.aciertos += 1
            self.score += 100
        else:
            self.fallas += 1
            self.score = max(0, self.score - 50)

        self.next_stimulus()

    def update_timer(self):
        if not self.running:
            return

        self.tiempo_restante = max(
            0, TIEMPO_TOTAL_SEG - int(time.time() - self.tiempo_inicio)
        )
        mins = self.tiempo_restante // 60
        secs = self.tiempo_restante % 60
        self.lbl_timer.config(text=f"Tiempo: {mins:02d}:{secs:02d}")

        if self.tiempo_restante <= 0:
            self.end_game()
        else:
            self.root.after(500, self.update_timer)

    # --- PANTALLA 3: RESULTADOS Y RANKING ---
    def end_game(self):
        self.running = False
        self.stop_audio()  # Detiene la música inmediatamente
        self.save_score()
        self.clear_screen()

        frame = tk.Frame(self.root, bg="#1E1E1E")
        frame.pack(expand=True, fill="both", padx=20, pady=20)

        tk.Label(
            frame,
            text="¡TIEMPO FINALIZADO!",
            font=("Helvetica", 22, "bold"),
            fg="#FF5252",
            bg="#1E1E1E",
        ).pack(pady=5)

        tk.Label(
            frame,
            text=f"Jugador: {self.nickname}",
            font=("Helvetica", 14),
            fg="#FFFFFF",
            bg="#1E1E1E",
        ).pack(pady=2)

        total_intentos = self.aciertos + self.fallas
        precision = (
            (self.aciertos / total_intentos * 100) if total_intentos > 0 else 0
        )

        # Muestra el puntaje acumulado recién al finalizar la prueba
        lbl_stats = tk.Label(
            frame,
            text=f"Puntaje Final: {self.score} pts | Aciertos: {self.aciertos} | Fallas: {self.fallas} | Precisión: {precision:.1f}%",
            font=("Helvetica", 11, "bold"),
            fg="#FFD54F",
            bg="#1E1E1E",
        )
        lbl_stats.pack(pady=10)

        tk.Label(
            frame,
            text="🏆 TABLA DE POSICIONES (TOP 10) 🏆",
            font=("Helvetica", 14, "bold"),
            fg="#00E676",
            bg="#1E1E1E",
        ).pack(pady=10)

        tree_frame = tk.Frame(frame, bg="#1E1E1E")
        tree_frame.pack(fill="both", expand=True)

        columns = ("pos", "nick", "score", "aciertos", "fallas")
        tree = ttk.Treeview(
            tree_frame, columns=columns, show="headings", height=8
        )

        tree.heading("pos", text="Pos")
        tree.heading("nick", text="Sobrenombre")
        tree.heading("score", text="Puntaje")
        tree.heading("aciertos", text="Aciertos")
        tree.heading("fallas", text="Fallas")

        tree.column("pos", width=40, anchor="center")
        tree.column("nick", width=150, anchor="center")
        tree.column("score", width=100, anchor="center")
        tree.column("aciertos", width=80, anchor="center")
        tree.column("fallas", width=80, anchor="center")

        tree.pack(side="left", fill="both", expand=True)

        ranking = self.load_ranking()
        for idx, item in enumerate(ranking[:10], start=1):
            tree.insert(
                "",
                "end",
                values=(
                    idx,
                    item["nick"],
                    item["score"],
                    item["aciertos"],
                    item["fallas"],
                ),
            )

        btn_restart = tk.Button(
            frame,
            text="Siguiente Voluntario",
            font=("Helvetica", 12, "bold"),
            bg="#1E88E5",
            fg="white",
            padx=15,
            pady=8,
            relief="flat",
            command=self.show_login_screen,
        )
        btn_restart.pack(pady=15)

    def load_ranking(self):
        if not os.path.exists(RANKING_FILE):
            return []
        try:
            with open(RANKING_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return sorted(data, key=lambda x: x["score"], reverse=True)
        except Exception:
            return []

    def save_score(self):
        ranking = self.load_ranking()
        ranking.append(
            {
                "nick": self.nickname,
                "score": self.score,
                "aciertos": self.aciertos,
                "fallas": self.fallas,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
        ranking = sorted(ranking, key=lambda x: x["score"], reverse=True)
        with open(RANKING_FILE, "w", encoding="utf-8") as f:
            json.dump(ranking, f, ensure_ascii=False, indent=4)


if __name__ == "__main__":
    root = tk.Tk()
    app = StroopTestApp(root)
    root.mainloop()