"""
better_simulator.py
Improved Real-Time Multithreaded Application Simulator (single-file)

Key improvements:
- Tick-driven simulator running in a background thread
- Thread-safe GUI updates via queue
- Round-Robin (quantum) and Preemptive Priority schedulers
- Multi-core simulation
- Semaphore and Monitor primitives (simulation-level)
- Metrics, logging, CSV export
- Responsive Tkinter GUI with Start/Pause/Step/Reset
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import time
import uuid
import heapq
from collections import deque
from queue import Queue, Empty
import csv
import os

# -------------------- Simulation Data Models --------------------

class SimThread:
    """A simulated thread (not an OS thread) with properties for the sim."""
    def __init__(self, name, burst, priority=1, arrival=0):
        self.id = str(uuid.uuid4())[:8]
        self.name = name
        self.burst = int(burst)
        self.remaining = int(burst)
        self.priority = int(priority)
        self.arrival = int(arrival)
        self.state = "NEW"   # NEW, READY, RUNNING, WAITING, TERMINATED
        self.start_time = None
        self.finish_time = None
        self.wait_time = 0
        self.total_run = 0

    def __repr__(self):
        return f"{self.name}(r={self.remaining},p={self.priority},s={self.state})"

class SemaphoreSim:
    """Counting semaphore simulation with a FIFO wait queue."""
    def __init__(self, initial=1):
        self.count = int(initial)
        self.wait_queue = deque()

    def wait(self, thread):
        """Attempt to acquire. Returns True if acquired, False if blocked."""
        if self.count > 0:
            self.count -= 1
            return True
        else:
            self.wait_queue.append(thread)
            thread.state = "WAITING"
            return False

    def signal(self):
        """Release: if waiters exist, wake first; otherwise increment count."""
        if self.wait_queue:
            t = self.wait_queue.popleft()
            t.state = "READY"
            return t
        else:
            self.count += 1
            return None

class MonitorSim:
    """Simple monitor simulation (mutual exclusion + queue)."""
    def __init__(self):
        self.locked = False
        self.queue = deque()

    def enter(self, thread):
        if not self.locked:
            self.locked = True
            return True
        else:
            thread.state = "WAITING"
            self.queue.append(thread)
            return False

    def exit(self):
        if self.queue:
            t = self.queue.popleft()
            t.state = "READY"
            return t
        else:
            self.locked = False
            return None

# -------------------- Scheduler --------------------

class Scheduler:
    """Supports Round-Robin and Preemptive Priority scheduling."""
    def __init__(self, algo='RR', quantum=2):
        self.algo = algo  # 'RR' or 'PRIO'
        self.quantum = int(quantum)
        self.rr_queue = deque()
        self.prio_heap = []   # ( -priority, arrival_index, thread )
        self._arrival_counter = 0

    def set_algo(self, algo, quantum=None):
        self.algo = algo
        if quantum is not None:
            self.quantum = int(quantum)

    def add(self, thread):
        thread.state = "READY"
        if self.algo == 'RR':
            self.rr_queue.append(thread)
        else:
            heapq.heappush(self.prio_heap, (-thread.priority, self._arrival_counter, thread))
            self._arrival_counter += 1

    def pop_next(self):
        if self.algo == 'RR':
            return self.rr_queue.popleft() if self.rr_queue else None
        else:
            return heapq.heappop(self.prio_heap)[2] if self.prio_heap else None

    def has_ready(self):
        return bool(self.rr_queue) or bool(self.prio_heap)

    def requeue_rr(self, thread):
        if self.algo == 'RR' and thread.state == "READY":
            self.rr_queue.append(thread)

    def peek_highest_prio(self):
        if self.prio_heap:
            return self.prio_heap[0][2]
        return None

# -------------------- Core & Simulator --------------------

class Core:
    def __init__(self, core_id):
        self.id = core_id
        self.running = None
        self.quantum_used = 0

class Simulator:
    """Tick-driven simulator managing threads, scheduler, cores and sync primitives."""
    def __init__(self, num_cores=1, scheduler_algo='RR', quantum=2, tick_sec=0.5, gui_queue=None):
        self.tick = 0
        self.tick_sec = tick_sec
        self.cores = [Core(i) for i in range(num_cores)]
        self.threads = []       # all threads
        self.pending = []       # arrival-scheduled threads
        self.scheduler = Scheduler(algo=scheduler_algo, quantum=quantum)
        self.semaphores = {}    # name -> SemaphoreSim
        self.monitors = {}      # name -> MonitorSim
        self.lock = threading.Lock()
        self.running = False
        self.paused = True
        self.gui_queue = gui_queue or Queue()
        self.speed = 1.0

    # ---------- thread management ----------
    def create_thread(self, name, burst, priority=1, arrival=0):
        t = SimThread(name, burst, priority, arrival)
        self.threads.append(t)
        if t.arrival <= self.tick:
            self.scheduler.add(t)
            self._log(f"Thread {t.name} arrived and READY")
        else:
            t.state = "NEW"
            self.pending.append(t)
            self._log(f"Thread {t.name} scheduled to arrive at tick {t.arrival}")
        return t

    # ---------- sync primitives ----------
    def create_semaphore(self, name, initial=1):
        self.semaphores[name] = SemaphoreSim(initial)
        self._log(f"Semaphore '{name}' created (init={initial})")

    def create_monitor(self, name):
        self.monitors[name] = MonitorSim()
        self._log(f"Monitor '{name}' created")

    # ---------- simulation control ----------
    def start(self):
        if self.running:
            return
        self.running = True
        self.paused = False
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._log("Simulation started")

    def pause(self):
        self.paused = True
        self._log("Simulation paused")

    def resume(self):
        self.paused = False
        self._log("Simulation resumed")

    def stop(self):
        self.running = False
        self.paused = True
        self._log("Simulation stopped")

    def step_once(self):
        with self.lock:
            self._tick_once()

    def reset(self):
        with self.lock:
            self.tick = 0
            self.cores = [Core(i) for i in range(len(self.cores))]
            self.threads.clear()
            self.pending.clear()
            self.scheduler = Scheduler(algo=self.scheduler.algo, quantum=self.scheduler.quantum)
            self.semaphores.clear()
            self.monitors.clear()
            self._log("Simulation reset")

    def set_speed(self, speed):
        self.speed = float(speed)

    # ---------- internal run loop ----------
    def _run_loop(self):
        while self.running:
            if not self.paused:
                with self.lock:
                    self._tick_once()
            time.sleep(max(self.tick_sec / max(self.speed, 0.01), 0.001))

    def _tick_once(self):
        self.tick += 1
        # handle arrivals
        arrivals = [t for t in list(self.pending) if t.arrival <= self.tick]
        for t in arrivals:
            self.pending.remove(t)
            self.scheduler.add(t)
            t.state = "READY"
            self._log(f"Thread {t.name} arrived at tick {self.tick} and READY")

        # increment wait time for ready threads
        for t in self.threads:
            if t.state == "READY":
                t.wait_time += 1

        # fill idle cores
        for core in self.cores:
            if core.running is None:
                candidate = self.scheduler.pop_next()
                if candidate:
                    core.running = candidate
                    candidate.state = "RUNNING"
                    if candidate.start_time is None:
                        candidate.start_time = self.tick
                    core.quantum_used = 0
                    self._log(f"Core {core.id} START {candidate.name}")

        # execute one tick on each core
        for core in self.cores:
            t = core.running
            if t:
                t.remaining -= 1
                t.total_run += 1
                core.quantum_used += 1
                # finished?
                if t.remaining <= 0:
                    t.state = "TERMINATED"
                    t.finish_time = self.tick
                    self._log(f"Core {core.id} FINISH {t.name} (turnaround={t.finish_time - t.arrival})")
                    core.running = None
                    core.quantum_used = 0
                else:
                    # RR quantum expiry
                    if self.scheduler.algo == 'RR' and core.quantum_used >= self.scheduler.quantum:
                        t.state = "READY"
                        self.scheduler.requeue_rr(t)
                        self._log(f"Core {core.id} QUANTUM_EXPIRE preempt {t.name}")
                        core.running = None
                        core.quantum_used = 0

        # PRIO preemption: if a higher-priority ready thread exists, preempt lower-priority running ones
        if self.scheduler.algo == 'PRIO':
            # check top candidate
            candidate = self.scheduler.peek_highest_prio()
            if candidate:
                for core in self.cores:
                    r = core.running
                    if r and candidate.priority > r.priority:
                        # preempt
                        self._log(f"Core {core.id} PREEMPT {r.name} for {candidate.name}")
                        r.state = "READY"
                        heapq.heappush(self.scheduler.prio_heap, (-r.priority, self.scheduler._arrival_counter, r))
                        self.scheduler._arrival_counter += 1
                        core.running = None

        # send refresh event to GUI
        self._emit_gui('refresh', None)

    # ---------- helper functions ----------
    def _log(self, msg):
        entry = f"[t={self.tick}] {msg}"
        self._emit_gui('log', entry)

    def _emit_gui(self, kind, payload):
        # put (kind, payload, snapshot) into gui queue
        snapshot = self._snapshot()
        try:
            self.gui_queue.put_nowait((kind, payload, snapshot))
        except Exception:
            pass

    def _snapshot(self):
        # prepare a minimal snapshot for the GUI
        return {
            'tick': self.tick,
            'threads': [(t.id, t.name, t.state, t.remaining, t.priority, t.arrival) for t in self.threads],
            'cores': [(c.id, c.running.name if c.running else None) for c in self.cores],
            'scheduler': (self.scheduler.algo, self.scheduler.quantum),
            'semaphores': {k: (s.count, [x.name for x in s.wait_queue]) for k, s in self.semaphores.items()},
            'monitors': {k: (m.locked, [x.name for x in m.queue]) for k, m in self.monitors.items()}
        }

    # ---------- metrics & export ----------
    def metrics(self):
        finished = [t for t in self.threads if t.finish_time is not None]
        if not finished:
            return {}
        total_turnaround = sum((t.finish_time - t.arrival) for t in finished)
        total_wait = sum(t.wait_time for t in finished)
        return {
            'num_finished': len(finished),
            'avg_turnaround': total_turnaround / len(finished),
            'avg_wait': total_wait / len(finished)
        }

    def export_csv(self, path):
        fields = ['id', 'name', 'arrival', 'burst', 'remaining', 'priority', 'state', 'start_time', 'finish_time', 'wait_time', 'total_run']
        with open(path, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for t in self.threads:
                writer.writerow({
                    'id': t.id,
                    'name': t.name,
                    'arrival': t.arrival,
                    'burst': t.burst,
                    'remaining': t.remaining,
                    'priority': t.priority,
                    'state': t.state,
                    'start_time': t.start_time,
                    'finish_time': t.finish_time,
                    'wait_time': t.wait_time,
                    'total_run': t.total_run
                })

# -------------------- GUI --------------------

class SimulatorGUI:
    def __init__(self, root):
        self.root = root
        root.title("Better RT Multithreaded Simulator")
        self.gui_queue = Queue()
        self.sim = Simulator(num_cores=2, scheduler_algo='RR', quantum=2, tick_sec=0.5, gui_queue=self.gui_queue)

        # build UI
        self._build_controls()
        self._build_visuals()
        self._build_log()

        self._populate_defaults()
        self._running_gui = True
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._periodic_update()

    def _build_controls(self):
        frm = ttk.Frame(self.root)
        frm.pack(side='top', fill='x', padx=6, pady=6)

        ttk.Label(frm, text='Burst').grid(row=0, column=0)
        self.ent_burst = ttk.Entry(frm, width=6); self.ent_burst.insert(0, "5"); self.ent_burst.grid(row=0, column=1)
        ttk.Label(frm, text='Prio').grid(row=0, column=2)
        self.ent_prio = ttk.Entry(frm, width=4); self.ent_prio.insert(0, "1"); self.ent_prio.grid(row=0, column=3)
        ttk.Label(frm, text='Arrival').grid(row=0, column=4)
        self.ent_arr = ttk.Entry(frm, width=4); self.ent_arr.insert(0, "0"); self.ent_arr.grid(row=0, column=5)
        ttk.Button(frm, text='Create Thread', command=self.create_thread).grid(row=0, column=6, padx=6)

        ttk.Label(frm, text='Algorithm').grid(row=1, column=0)
        self.algo_var = tk.StringVar(value='RR')
        ttk.Radiobutton(frm, text='Round-Robin', variable=self.algo_var, value='RR', command=self._change_algo).grid(row=1, column=1)
        ttk.Radiobutton(frm, text='Priority', variable=self.algo_var, value='PRIO', command=self._change_algo).grid(row=1, column=2)
        ttk.Label(frm, text='Quantum').grid(row=1, column=3)
        self.ent_q = ttk.Entry(frm, width=4); self.ent_q.insert(0, "2"); self.ent_q.grid(row=1, column=4)

        ttk.Label(frm, text='Cores').grid(row=1, column=5)
        self.spin_cores = ttk.Spinbox(frm, from_=1, to=8, width=4, command=self._change_cores); self.spin_cores.set(2); self.spin_cores.grid(row=1, column=6)

        ttk.Button(frm, text='Start', command=self.start).grid(row=2, column=0, pady=6)
        ttk.Button(frm, text='Pause', command=self.pause).grid(row=2, column=1)
        ttk.Button(frm, text='Resume', command=self.resume).grid(row=2, column=2)
        ttk.Button(frm, text='Step', command=self.step).grid(row=2, column=3)
        ttk.Button(frm, text='Reset', command=self.reset).grid(row=2, column=4)

        ttk.Label(frm, text='Speed').grid(row=2, column=5)
        self.speed_var = tk.DoubleVar(value=1.0)
        self.spin_speed = ttk.Spinbox(frm, from_=0.1, to=10.0, increment=0.1, textvariable=self.speed_var, width=6, command=self._change_speed); self.spin_speed.grid(row=2, column=6)

        ttk.Button(frm, text='Create Semaphore', command=self._ui_create_semaphore).grid(row=3, column=0)
        self.ent_sem_name = ttk.Entry(frm, width=8); self.ent_sem_name.insert(0, "S1"); self.ent_sem_name.grid(row=3, column=1)

        ttk.Button(frm, text='Create Monitor', command=self._ui_create_monitor).grid(row=3, column=2)
        self.ent_mon_name = ttk.Entry(frm, width=8); self.ent_mon_name.insert(0, "M1"); self.ent_mon_name.grid(row=3, column=3)

        ttk.Button(frm, text='Export CSV', command=self._export_csv).grid(row=3, column=4)

    def _build_visuals(self):
        self.canvas = tk.Canvas(self.root, width=900, height=300, bg='white')
        self.canvas.pack(side='top', padx=6, pady=6)
        self.core_boxes = []

    def _build_log(self):
        self.log = scrolledtext.ScrolledText(self.root, height=12)
        self.log.pack(side='top', fill='both', expand=True, padx=6, pady=6)
        self.log.configure(state='disabled')

    def _populate_defaults(self):
        # populate cores display
        self._draw_cores()

    # ---------- UI handlers ----------
    def create_thread(self):
        try:
            burst = int(self.ent_burst.get())
            prio = int(self.ent_prio.get())
            arr = int(self.ent_arr.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Burst, Prio and Arrival must be integers")
            return
        name = f"T{len(self.sim.threads) + len(self.sim.pending) + 1}"
        with self.sim.lock:
            t = self.sim.create_thread(name, burst, prio, arr)
        self._append_log(f"Created {t.name} burst={burst} prio={prio} arrival={arr}")

    def _change_algo(self):
        algo = self.algo_var.get()
        try:
            q = int(self.ent_q.get())
        except ValueError:
            q = self.sim.scheduler.quantum
        with self.sim.lock:
            self.sim.scheduler.set_algo(algo, q)
        self._append_log(f"Scheduler changed to {algo} (quantum={q})")

    def _change_cores(self):
        try:
            n = int(self.spin_cores.get())
        except Exception:
            return
        with self.sim.lock:
            # preserve core count by creating new cores list
            self.sim.cores = [Core(i) for i in range(n)]
        self._draw_cores()
        self._append_log(f"Number of cores updated to {n}")

    def _change_speed(self):
        s = float(self.speed_var.get())
        with self.sim.lock:
            self.sim.set_speed(s)
        self._append_log(f"Simulation speed set to {s}x")

    def start(self):
        with self.sim.lock:
            self.sim.start()
        self._append_log("Start pressed")

    def pause(self):
        with self.sim.lock:
            self.sim.pause()

    def resume(self):
        with self.sim.lock:
            self.sim.resume()

    def step(self):
        with self.sim.lock:
            self.sim.step_once()

    def reset(self):
        if messagebox.askyesno("Reset", "Reset simulation (clears threads)?"):
            with self.sim.lock:
                self.sim.reset()
            self._draw_cores()
            self._append_log("Simulation reset")

    def _ui_create_semaphore(self):
        name = self.ent_sem_name.get().strip()
        if not name:
            name = f"S{len(self.sim.semaphores)+1}"
        with self.sim.lock:
            self.sim.create_semaphore(name, initial=1)
        self._append_log(f"Semaphore '{name}' created")

    def _ui_create_monitor(self):
        name = self.ent_mon_name.get().strip()
        if not name:
            name = f"M{len(self.sim.monitors)+1}"
        with self.sim.lock:
            self.sim.create_monitor(name)
        self._append_log(f"Monitor '{name}' created")

    def _export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files","*.csv")])
        if not path:
            return
        with self.sim.lock:
            self.sim.export_csv(path)
        self._append_log(f"Exported CSV to {path}")

    # ---------- drawing & log helpers ----------
    def _draw_cores(self):
        self.canvas.delete("all")
        n = len(self.sim.cores)
        if n == 0:
            return
        w = int(self.canvas.winfo_width() or 900)
        box_w = w // n
        self.core_boxes = []
        for i in range(n):
            x0 = i * box_w + 10
            y0 = 10
            x1 = x0 + box_w - 20
            y1 = y0 + 80
            rect = self.canvas.create_rectangle(x0, y0, x1, y1, fill="#f0f0f0")
            text = self.canvas.create_text((x0+x1)//2, y0+8, text=f"Core {i}", anchor='n')
            status = self.canvas.create_text((x0+x1)//2, y0+42, text="idle")
            self.core_boxes.append((rect, text, status))
        # area for thread list
        self.canvas.create_text(10, 110, anchor='w', text="Threads (state, rem, prio, arrival):")

    def _append_log(self, msg):
        self.log.configure(state='normal')
        self.log.insert('end', msg + "\n")
        self.log.see('end')
        self.log.configure(state='disabled')

    # ---------- GUI update loop ----------
    def _periodic_update(self):
        # process gui_queue messages
        processed = False
        try:
            while True:
                kind, payload, snapshot = self.gui_queue.get_nowait()
                processed = True
                if kind == 'log':
                    self._append_log(payload)
                if kind == 'refresh':
                    # redraw cores and thread list from snapshot
                    self._apply_snapshot(snapshot)
        except Empty:
            pass

        # also update periodically even if no events
        if not processed:
            # ensure core boxes reflect current state
            self._apply_snapshot(self.sim._snapshot())

        if self._running_gui:
            self.root.after(200, self._periodic_update)

    def _apply_snapshot(self, snap):
        # update title with tick and metrics
        tick = snap.get('tick', 0)
        self.root.title(f"Better RT Simulator - tick={tick}")
        # update cores
        for (rect, _, status), core_info in zip(self.core_boxes, snap.get('cores', [])):
            core_id, running_name = core_info
            status_text = running_name if running_name else "idle"
            self.canvas.itemconfigure(status, text=status_text)
            # color cores with green if busy
            color = "#cfeed6" if running_name else "#f0f0f0"
            self.canvas.itemconfigure(rect, fill=color)
        # threads list
        # remove old thread list area
        # we will rewrite thread text area starting at y=120
        # clear existing thread text items (naive: clear portion of canvas)
        self.canvas.delete("thread_text")
        y = 120
        for tid, name, state, rem, prio, arr in snap.get('threads', []):
            txt = f"{name}: {state}, rem={rem}, p={prio}, arr={arr}"
            self.canvas.create_text(10, y, anchor='w', text=txt, tags="thread_text")
            y += 18
        # semaphores and monitors info (right side)
        self.canvas.delete("sync_text")
        sx = 600
        y2 = 10
        self.canvas.create_text(sx, y2, anchor='nw', text="Semaphores / Monitors:", tags="sync_text")
        y2 += 18
        for k, v in snap.get('semaphores', {}).items():
            cnt, waiters = v
            txt = f"S:{k} cnt={cnt} waiters={waiters}"
            self.canvas.create_text(sx, y2, anchor='nw', text=txt, tags="sync_text")
            y2 += 16
        for k, v in snap.get('monitors', {}).items():
            locked, waiters = v
            txt = f"M:{k} locked={locked} waiters={waiters}"
            self.canvas.create_text(sx, y2, anchor='nw', text=txt, tags="sync_text")
            y2 += 16

    def _on_close(self):
        if messagebox.askokcancel("Quit", "Quit the simulator?"):
            self._running_gui = False
            with self.sim.lock:
                self.sim.stop()
            self.root.destroy()

# -------------------- ENTRY POINT --------------------

def main():
    root = tk.Tk()
    app = SimulatorGUI(root)
    root.geometry("920x700")
    root.mainloop()

if __name__ == "__main__":
    main()
