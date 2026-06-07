from __future__ import annotations

import threading
import tkinter as tk
from tkinter import ttk

from cheatpilot.errors import user_facing_error
from cheatpilot.factory import build_agent
from cheatpilot.formatter import format_response


class CheatPilotWindow(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("CheatPilot")
        self.geometry("420x660+40+60")
        self.minsize(360, 520)
        self.attributes("-topmost", True)
        self.agent = build_agent()
        self._busy = False
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        self.configure(bg="#101418")
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TButton", padding=8, font=("Segoe UI", 10))

        header = tk.Frame(self, bg="#101418")
        header.pack(fill=tk.X, padx=14, pady=(12, 8))

        title = tk.Label(
            header,
            text="CheatPilot",
            bg="#101418",
            fg="#E8EEF2",
            font=("Segoe UI Semibold", 15),
        )
        title.pack(side=tk.LEFT)

        status = tk.Label(
            header,
            text="Natural language + Cheat Engine MCP",
            bg="#101418",
            fg="#8EA0AA",
            font=("Segoe UI", 9),
        )
        status.pack(side=tk.RIGHT)

        self.history = tk.Text(
            self,
            wrap=tk.WORD,
            bg="#151B20",
            fg="#E8EEF2",
            insertbackground="#E8EEF2",
            relief=tk.FLAT,
            padx=12,
            pady=12,
            font=("Segoe UI", 10),
        )
        self.history.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 12))
        self.history.configure(state=tk.DISABLED)

        self.status_var = tk.StringVar(value="")
        self.status_label = tk.Label(
            self,
            textvariable=self.status_var,
            bg="#101418",
            fg="#8EA0AA",
            anchor="w",
            font=("Segoe UI", 9),
        )
        self.status_label.pack(fill=tk.X, padx=14, pady=(0, 8))

        input_frame = tk.Frame(self, bg="#101418")
        input_frame.pack(fill=tk.X, padx=14, pady=(0, 14))

        self.input_var = tk.StringVar()
        self.entry = tk.Entry(
            input_frame,
            textvariable=self.input_var,
            bg="#E8EEF2",
            fg="#101418",
            relief=tk.FLAT,
            font=("Segoe UI", 10),
        )
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=9)
        self.entry.bind("<Return>", lambda _event: self._send())

        self.send_button = ttk.Button(input_frame, text="发送", command=self._send)
        self.send_button.pack(side=tk.RIGHT, padx=(10, 0))

    def _send(self) -> None:
        message = self.input_var.get().strip()
        self._send_text(message)

    def _send_text(self, message: str) -> None:
        if not message or self._busy:
            return
        self._busy = True
        self.input_var.set("")
        self._append("user", message)
        self.send_button.configure(state=tk.DISABLED)
        self.entry.configure(state=tk.DISABLED)
        self.status_var.set("思考中...")
        threading.Thread(target=self._run_agent, args=(message,), daemon=True).start()

    def _run_agent(self, message: str) -> None:
        try:
            response = self.agent.handle(message)
            output = format_response(response)
        except Exception as exc:
            output = user_facing_error(exc)
        self.after(0, lambda: self._finish_agent_output(output))

    def _finish_agent_output(self, output: str) -> None:
        self._append("assistant", output)
        self.status_var.set("")
        self._busy = False
        self.entry.configure(state=tk.NORMAL)
        self.send_button.configure(state=tk.NORMAL)
        self.entry.focus_set()

    def _append(self, role: str, text: str) -> None:
        self.history.configure(state=tk.NORMAL)
        self.history.insert(tk.END, f"{role}> {text}\n\n")
        self.history.see(tk.END)
        self.history.configure(state=tk.DISABLED)

    def _on_close(self) -> None:
        self.agent.close()
        self.destroy()


def main() -> None:
    CheatPilotWindow().mainloop()


if __name__ == "__main__":
    main()
