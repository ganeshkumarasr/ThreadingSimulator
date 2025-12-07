

import tkinter as tk
from tkinter import ttk, messagebox
import random
import math


class ThreadControlBlock:
    _next_tid = 1
    def __init__(self, burst=5, priority=1, io_after=None):
        self.tid = ThreadControlBlock._next_tid; ThreadControlBlock._next_tid += 1
        self.burst = burst            
        self.total_burst = burst
        self.priority = priority
        self.io_after = io_after      
        self.executed = 0
        self.state = "NEW"            
        self.arrival_tick = None
        self.finish_tick = None
    def step(self):
        self.burst -= 1
        self.executed += 1

class ProcessControlBlock:
    _next_pid = 1
    def __init__(self, name="P"):
        self.pid = ProcessControlBlock._next_pid; ProcessControlBlock._next_pid += 1
        self.name = f"{name}{self.pid}"
        self.threads = []
    def add_thread(self, tcb):
        self.threads.append(tcb)


class Scheduler:
    def __init__(self, policy="FCFS", quantum=3):
        self.policy = policy
        self.quantum = quantum
        self.ready = []
    def add(self, tcb, current_tick):
        tcb.state = "READY"
        if tcb.arrival_tick is None:
            tcb.arrival_tick = current_tick
        
        if self.policy == "FCFS" or self.policy == "RR":
            self.ready.append(tcb)
        elif self.policy == "PRIORITY":
            
            self.ready.append(tcb)
            self.ready.sort(key=lambda x: x.priority)
    def pop_next(self):
        if not self.ready: return None
        if self.policy in ("FCFS","PRIORITY"):
            return self.ready.pop(0)
        elif self.policy == "RR":
            return self.ready.pop(0)
    def has_ready(self):
        return len(self.ready) > 0


class Simulator:
    def __init__(self, gui_update_callback):
        self.current_tick = 0
        self.scheduler = Scheduler("FCFS", quantum=3)
        self.running = None     
        self.waiting = []     
        self.finished = []
        self.all_threads = []
        self.gui_update_callback = gui_update_callback
        self.cpu_busy_ticks = 0
        self.num_cpus = 1
        self.auto_running = False
        self.step_delay_ms = 500
    def reset(self):
        self.current_tick = 0
        self.scheduler = Scheduler(self.scheduler.policy, self.scheduler.quantum)
        self.running = None
        self.waiting = []
        self.finished = []
        self.all_threads = []
        self.cpu_busy_ticks = 0
        ThreadControlBlock._next_tid = 1
        ProcessControlBlock._next_pid = 1
        self.gui_update_callback()
    def set_policy(self, policy):
        self.scheduler.policy = policy
        
        if policy == "PRIORITY":
            self.scheduler.ready.sort(key=lambda x: x.priority)
    def set_quantum(self, q):
        self.scheduler.quantum = q
    def set_num_cpus(self, n):
        self.num_cpus = max(1, int(n))
    def create_process(self, name, num_threads=1, min_burst=2, max_burst=10):
        p = ProcessControlBlock(name)
        for _ in range(int(num_threads)):
            burst = random.randint(int(min_burst), int(max_burst))
            # random small chance of IO at halfway
            io_after = None
            if random.random() < 0.4:
                io_after = max(1, burst // 2)
            priority = random.randint(1, 10)
            t = ThreadControlBlock(burst=burst, priority=priority, io_after=io_after)
            p.add_thread(t)
            self.all_threads.append(t)
            self.scheduler.add(t, self.current_tick)
        self.gui_update_callback()
    def tick(self):
        self.current_tick += 1
        # Advance waiting (I/O) list
        new_ready = []
        for (tcb, remaining) in list(self.waiting):
            remaining -= 1
            if remaining <= 0:
                self.waiting.remove((tcb, remaining+1)) if (tcb, remaining+1) in self.waiting else None
                # remove by scanning
                for w in list(self.waiting):
                    if w[0] == tcb:
                        self.waiting.remove(w)
                        break
                new_ready.append(tcb)
            else:
                # update tuple: remove old and append new
                for w in list(self.waiting):
                    if w[0] == tcb:
                        self.waiting.remove(w)
                        self.waiting.append((tcb, remaining))
                        break
        for tcb in new_ready:
            tcb.state = "READY"
            self.scheduler.add(tcb, self.current_tick)
        # Execute CPU(s) -- we simulate num_cpus but for simplicity do sequential picks
        cpus_executed = 0
        for cpu_id in range(self.num_cpus):
            # If there is running thread (previous tick) and policy allows continue, keep it (for single CPU we track running)
            if self.running is None:
                # fetch one
                t = self.scheduler.pop_next()
                if t:
                    t.state = "RUNNING"
                    remaining_quantum = self.scheduler.quantum if self.scheduler.policy == "RR" else None
                    self.running = (t, remaining_quantum)
            if self.running:
                tcb, remaining_quantum = self.running
                tcb.step()
                cpus_executed += 1
                self.cpu_busy_ticks += 1
                # check for IO event
                if tcb.io_after is not None and tcb.executed == tcb.io_after:
                    # move to waiting
                    tcb.state = "WAITING"
                    # simulate fixed IO wait
                    io_wait = max(1, random.randint(2,5))
                    self.waiting.append((tcb, io_wait))
                    self.running = None
                elif tcb.burst <= 0:
                    tcb.state = "FINISHED"
                    tcb.finish_tick = self.current_tick
                    self.finished.append(tcb)
                    self.running = None
                else:
                    # not finished, if RR maybe preempt
                    if self.scheduler.policy == "RR":
                        remaining_quantum -= 1
                        if remaining_quantum <= 0:
                            # preempt and put at end of ready queue
                            tcb.state = "READY"
                            self.scheduler.add(tcb, self.current_tick)
                            self.running = None
                        else:
                            self.running = (tcb, remaining_quantum)
                    else:
                        # for preemptive priority, check if new higher priority arrived
                        if self.scheduler.policy == "PRIORITY" and self.scheduler.has_ready():
                            # top ready has priority
                            top = self.scheduler.ready[0]
                            if top.priority < tcb.priority:
                                # preempt
                                tcb.state = "READY"
                                self.scheduler.add(tcb, self.current_tick)
                                self.running = None
            else:
                # no more ready threads
                pass
        # bookkeeping for threads that have no arrival tick set
        for t in self.all_threads:
            if t.arrival_tick is None and t.state in ("READY","RUNNING","WAITING"):
                t.arrival_tick = self.current_tick
        self.gui_update_callback()
    def step_once(self):
        self.tick()
    def run_auto(self, root):
        self.auto_running = True
        def loop():
            if not self.auto_running:
                return
            # stop if nothing to do
            more = self.scheduler.has_ready() or self.waiting or (self.running is not None)
            if not more:
                self.auto_running = False
                self.gui_update_callback()
                return
            self.tick()
            root.after(self.step_delay_ms, loop)
        root.after(self.step_delay_ms, loop)
    def stop_auto(self):
        self.auto_running = False

# ----------------------------
# GUI
# ----------------------------
class App:
    def __init__(self, root):
        self.root = root
        root.title("Real-time Multi-threaded OS Simulator")
        root.geometry("1100x700")
        self.sim = Simulator(self.update_gui)
        self.build_ui()
        self.update_gui()
    def build_ui(self):
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=6, pady=6)

        # Scheduler controls
        ttk.Label(top, text="Scheduler:").pack(side="left")
        self.policy_var = tk.StringVar(value="FCFS")
        policy_menu = ttk.OptionMenu(top, self.policy_var, "FCFS", "FCFS","RR","PRIORITY", command=self.change_policy)
        policy_menu.pack(side="left", padx=4)

        ttk.Label(top, text="Quantum:").pack(side="left")
        self.quantum_var = tk.IntVar(value=3)
        qspin = ttk.Spinbox(top, from_=1, to=20, textvariable=self.quantum_var, width=4, command=self.change_quantum)
        qspin.pack(side="left", padx=4)

        ttk.Label(top, text="CPUs:").pack(side="left")
        self.cpus_var = tk.IntVar(value=1)
        cpu_spin = ttk.Spinbox(top, from_=1, to=4, textvariable=self.cpus_var, width=3, command=self.change_cpus)
        cpu_spin.pack(side="left", padx=4)

        ttk.Button(top, text="Step", command=self.step).pack(side="left", padx=6)
        ttk.Button(top, text="Run", command=self.run).pack(side="left", padx=6)
        ttk.Button(top, text="Pause", command=self.pause).pack(side="left", padx=6)
        ttk.Button(top, text="Reset", command=self.reset).pack(side="left", padx=6)

        # Create process frame
        pframe = ttk.LabelFrame(self.root, text="Create Process / Threads")
        pframe.pack(fill="x", padx=6, pady=6)
        ttk.Label(pframe, text="Name prefix:").grid(row=0,column=0, sticky="w")
        self.name_entry = ttk.Entry(pframe); self.name_entry.insert(0,"P")
        self.name_entry.grid(row=0,column=1, sticky="w")
        ttk.Label(pframe, text="Threads:").grid(row=0,column=2, sticky="w")
        self.threads_spin = ttk.Spinbox(pframe, from_=1, to=8, width=4); self.threads_spin.set(2)
        self.threads_spin.grid(row=0,column=3, sticky="w")
        ttk.Label(pframe, text="Burst min:").grid(row=0,column=4, sticky="w")
        self.min_burst = ttk.Spinbox(pframe, from_=1, to=30, width=4); self.min_burst.set(2)
        self.min_burst.grid(row=0,column=5, sticky="w")
        ttk.Label(pframe, text="Burst max:").grid(row=0,column=6, sticky="w")
        self.max_burst = ttk.Spinbox(pframe, from_=1, to=60, width=4); self.max_burst.set(8)
        self.max_burst.grid(row=0,column=7, sticky="w")
        ttk.Button(pframe, text="Create Process", command=self.create_process).grid(row=0,column=8, padx=6)

        # Middle area: lists and stats
        middle = ttk.Frame(self.root)
        middle.pack(fill="both", expand=True, padx=6, pady=6)

        left = ttk.Frame(middle)
        left.pack(side="left", fill="both", expand=True)

        # Ready list
        rframe = ttk.LabelFrame(left, text="Ready Queue")
        rframe.pack(fill="both", expand=True, padx=4, pady=4)
        self.ready_list = tk.Listbox(rframe)
        self.ready_list.pack(fill="both", expand=True)

        # Waiting list
        wframe = ttk.LabelFrame(left, text="Waiting (I/O)")
        wframe.pack(fill="both", expand=True, padx=4, pady=4)
        self.wait_list = tk.Listbox(wframe)
        self.wait_list.pack(fill="both", expand=True)

        right = ttk.Frame(middle)
        right.pack(side="left", fill="both", expand=True)

        runframe = ttk.LabelFrame(right, text="Running")
        runframe.pack(fill="both", expand=True, padx=4, pady=4)
        self.running_list = tk.Listbox(runframe)
        self.running_list.pack(fill="both", expand=True)

        finish_frame = ttk.LabelFrame(right, text="Finished")
        finish_frame.pack(fill="both", expand=True, padx=4, pady=4)
        self.finish_list = tk.Listbox(finish_frame)
        self.finish_list.pack(fill="both", expand=True)

        # bottom stats
        bottom = ttk.Frame(self.root)
        bottom.pack(fill="x", padx=6, pady=6)
        self.tick_label = ttk.Label(bottom, text="Tick: 0")
        self.tick_label.pack(side="left")
        self.util_label = ttk.Label(bottom, text="CPU Utilization: 0%")
        self.util_label.pack(side="left", padx=12)
        self.info_label = ttk.Label(bottom, text="Threads total: 0")
        self.info_label.pack(side="left", padx=12)

    # GUI callbacks
    def change_policy(self, val):
        self.sim.set_policy(val)
        self.sim.scheduler.policy = val
        self.update_gui()
    def change_quantum(self):
        q = int(self.quantum_var.get())
        self.sim.set_quantum(q)
    def change_cpus(self):
        self.sim.set_num_cpus(self.cpus_var.get())
        self.update_gui()
    def create_process(self):
        name = self.name_entry.get() or "P"
        threads = int(self.threads_spin.get())
        min_b = int(self.min_burst.get()); max_b = int(self.max_burst.get())
        self.sim.create_process(name, num_threads=threads, min_burst=min_b, max_burst=max_b)
    def step(self):
        self.sim.step_once()
    def run(self):
        if not self.sim.auto_running:
            self.sim.run_auto(self.root)
    def pause(self):
        self.sim.stop_auto()
    def reset(self):
        if messagebox.askyesno("Reset", "Reset simulation?"):
            self.sim.reset()
    def update_gui(self):
        # Refresh lists
        self.ready_list.delete(0, tk.END)
        for t in self.sim.scheduler.ready:
            self.ready_list.insert(tk.END, f"T{t.tid} [{t.state}] burst={t.burst}/{t.total_burst} pr={t.priority}")

        self.wait_list.delete(0, tk.END)
        for (t, rem) in self.sim.waiting:
            self.wait_list.insert(tk.END, f"T{t.tid} WAIT rem={rem}")

        self.running_list.delete(0, tk.END)
        if self.sim.running:
            t, rq = self.sim.running
            self.running_list.insert(tk.END, f"T{t.tid} RUN burst={t.burst}/{t.total_burst} pr={t.priority} qrem={rq}")

        self.finish_list.delete(0, tk.END)
        for t in self.sim.finished:
            self.finish_list.insert(tk.END, f"T{t.tid} FIN finished@{t.finish_tick}")

        self.tick_label.config(text=f"Tick: {self.sim.current_tick}")
        # utilization
        total_ticks = max(1, self.sim.current_tick)
        util = (self.sim.cpu_busy_ticks / total_ticks) * 100 if total_ticks>0 else 0
        self.util_label.config(text=f"CPU Utilization: {util:.1f}%")
        self.info_label.config(text=f"Threads total: {len(self.sim.all_threads)}  Ready: {len(self.sim.scheduler.ready)}  Waiting: {len(self.sim.waiting)}  Finished: {len(self.sim.finished)}")

# ----------------------------
# Run App
# ----------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = App(root)
    root.mainloop()