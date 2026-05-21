# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import json
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .config import ToolConfig
from .core import generate_outputs, resolve_saturation, validate_gas_temperature_range, validate_liquid_temperature_range
from .egasp_client import build_coolant_calculation, build_coolant_row
from .refprop_client import RefpropClient
from .tables import write_coolant_xlsx
from .units import k_to_c


DEFAULT_STARCCM_EXE = (
    r"E:\Program Files\STAR-CCM_202602\starccm_2026\21.02.007-R8"
    r"\STAR-CCM+21.02.007-R8\star\lib\win64\clang20.1vc14.2-r8\lib\starccm+.exe"
)
SATURATION_TABLE_OFFSET_C = 0.001


class RefpropToCcmApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("REFPROP 到 STAR-CCM+ 制冷剂物性工具")
        self.geometry("980x740")
        self.minsize(900, 660)

        self.saturation_type = tk.StringVar(value="pressure")
        self.use_saturation_pressure = tk.BooleanVar(value=True)
        self.gas_table_mode = tk.StringVar(value="temperature")
        self.gas_viscosity_model = tk.StringVar(value="cicchitti")
        self.vapor_specific_heat_source = tk.StringVar(value="cp_table")
        self.liquid_property_mode = tk.StringVar(value="saturation")
        self.run_star = tk.BooleanVar(value=False)
        self.last_saturation_temperature_c: float | None = None
        self.coolant_vars: dict[str, tk.StringVar] = {}
        self.coolant_mode_widgets: dict[str, list[tk.Widget]] = {}
        self.page_frames: dict[str, ttk.Frame] = {}
        self.current_page = "home"

        self.vars: dict[str, tk.StringVar] = {
            "fluid_name": tk.StringVar(value="R454C"),
            "saturation_value": tk.StringVar(value="0.8"),
            "gas_pressure": tk.StringVar(value=""),
            "temp_start": tk.StringVar(value="30"),
            "temp_end": tk.StringVar(value="120"),
            "temp_step": tk.StringVar(value="0.1"),
            "gas_quality_points": tk.StringVar(value="自动"),
            "liquid_temp_start": tk.StringVar(value="0"),
            "liquid_temp_end": tk.StringVar(value="9"),
            "liquid_temp_step": tk.StringVar(value="0.1"),
            "sim_file": tk.StringVar(value=""),
            "output_sim_file": tk.StringVar(value=""),
            "continuum_name": tk.StringVar(value="R454C"),
            "liquid_phase_name": tk.StringVar(value="liquid"),
            "vapor_phase_name": tk.StringVar(value="gas"),
            "starccm_exe": tk.StringVar(value=DEFAULT_STARCCM_EXE if Path(DEFAULT_STARCCM_EXE).exists() else ""),
            "output_dir": tk.StringVar(value=str(Path.cwd() / "out")),
        }

        self._build()
        self._sync_saturation_labels()
        self._sync_gas_pressure_state()
        self._sync_gas_table_mode_state()
        self._sync_liquid_table_state()
        self._wire_validation()

    def _build(self) -> None:
        self.container = ttk.Frame(self, padding=16)
        self.container.pack(fill="both", expand=True)
        self.container.columnconfigure(0, weight=1)
        self.container.rowconfigure(0, weight=1)

        self.page_frames["home"] = self._build_home_page()
        self.page_frames["refprop"] = self._build_refprop_page()
        self.page_frames["coolant"] = self._build_coolant_page()

        for frame in self.page_frames.values():
            frame.grid(row=0, column=0, sticky="nsew")

        self._show_home_page()

    def _build_home_page(self) -> ttk.Frame:
        frame = ttk.Frame(self.container)
        frame.columnconfigure(0, weight=1)

        content = ttk.Frame(frame, padding=(24, 40))
        content.grid(row=0, column=0, sticky="n")
        content.columnconfigure(0, weight=1)

        ttk.Label(content, text="功能选择", font=("", 20, "bold")).grid(row=0, column=0, sticky="w", pady=(0, 12))
        ttk.Label(content, text="请选择要进入的功能页面。", foreground="#555").grid(row=1, column=0, sticky="w", pady=(0, 24))
        ttk.Button(content, text="REFPROP 到 STAR-CCM+", command=self._show_refprop_page).grid(
            row=2, column=0, sticky="ew", pady=6
        )
        ttk.Button(content, text="防冻液物性计算", command=self._show_coolant_page).grid(
            row=3, column=0, sticky="ew", pady=6
        )
        return frame

    def _build_refprop_page(self) -> ttk.Frame:
        outer = ttk.Frame(self.container)
        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(0, weight=1)

        canvas = tk.Canvas(outer, highlightthickness=0)
        scrollbar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        root = ttk.Frame(canvas)
        canvas_window = canvas.create_window((0, 0), window=root, anchor="nw")
        root.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(canvas_window, width=event.width))

        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(5, weight=1)

        nav_frame = ttk.Frame(root)
        nav_frame.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        ttk.Button(nav_frame, text="返回主页", command=self._show_home_page).pack(side="left")

        fluid_frame = self._section(root, "制冷剂与饱和条件", 1, 0)
        self._entry(fluid_frame, 0, "制冷剂名称", "fluid_name", "例如 R454C、R134A")

        sat_row = ttk.Frame(fluid_frame)
        sat_row.grid(row=1, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Radiobutton(
            sat_row,
            text="输入饱和压力 MPa",
            value="pressure",
            variable=self.saturation_type,
            command=self._on_saturation_type_changed,
        ).pack(side="left", padx=(0, 18))
        ttk.Radiobutton(
            sat_row,
            text="输入饱和温度 C",
            value="temperature",
            variable=self.saturation_type,
            command=self._on_saturation_type_changed,
        ).pack(side="left")

        self.saturation_label = ttk.Label(fluid_frame, text="")
        self.saturation_label.grid(row=2, column=0, sticky="w", pady=6)
        ttk.Entry(fluid_frame, textvariable=self.vars["saturation_value"]).grid(row=2, column=1, sticky="ew", pady=6)
        ttk.Button(fluid_frame, text="计算饱和温度", command=self._calculate_saturation_temperature).grid(
            row=2, column=2, sticky="ew", padx=(8, 0), pady=6
        )
        self.saturation_result_var = tk.StringVar(value="尚未计算饱和温度")
        saturation_result_entry = ttk.Entry(
            fluid_frame,
            textvariable=self.saturation_result_var,
            state="readonly",
        )
        saturation_result_entry.grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(2, 6)
        )
        ttk.Button(fluid_frame, text="复制结果", command=self._copy_saturation_result).grid(
            row=3, column=2, sticky="ew", padx=(8, 0), pady=(2, 6)
        )

        gas_frame = self._section(root, "气态温度相关表", 2, 0)
        gas_mode_row = ttk.Frame(gas_frame)
        gas_mode_row.grid(row=0, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Label(gas_mode_row, text="气相表模式").pack(side="left", padx=(0, 12))
        ttk.Radiobutton(
            gas_mode_row,
            text="按温度表",
            value="temperature",
            variable=self.gas_table_mode,
            command=self._sync_gas_table_mode_state,
        ).pack(side="left", padx=(0, 18))
        ttk.Radiobutton(
            gas_mode_row,
            text="RefEquiv 等效干度表",
            value="equivalent_quality",
            variable=self.gas_table_mode,
            command=self._sync_gas_table_mode_state,
        ).pack(side="left")

        self.gas_temperature_range_widgets: list[tk.Widget] = []
        self.gas_temperature_range_widgets.extend(self._entry(gas_frame, 1, "温度起点 C", "temp_start", ""))
        self.gas_temperature_range_widgets.extend(self._entry(gas_frame, 2, "温度终点 C", "temp_end", ""))
        self._entry(gas_frame, 3, "温度步长 C", "temp_step", "")
        self.temp_warning_var = tk.StringVar(value="提示：温度起点必须大于饱和温度。")
        self.temp_warning_label = ttk.Label(gas_frame, textvariable=self.temp_warning_var, foreground="#9a5b00")
        self.temp_warning_label.grid(row=4, column=0, columnspan=3, sticky="w", pady=(2, 6))
        ttk.Checkbutton(
            gas_frame,
            text="气态压力默认等于饱和压力",
            variable=self.use_saturation_pressure,
            command=self._sync_gas_pressure_state,
        ).grid(row=5, column=0, columnspan=2, sticky="w", pady=6)
        self.gas_pressure_label = ttk.Label(gas_frame, text="气态压力 MPa")
        self.gas_pressure_label.grid(row=6, column=0, sticky="w", pady=6)
        self.gas_pressure_entry = ttk.Entry(gas_frame, textvariable=self.vars["gas_pressure"])
        self.gas_pressure_entry.grid(row=6, column=1, sticky="ew", pady=6)
        cp_source_row = ttk.Frame(gas_frame)
        cp_source_row.grid(row=7, column=0, columnspan=3, sticky="ew", pady=6)
        ttk.Label(cp_source_row, text="气态比热来源").pack(side="left", padx=(0, 12))
        ttk.Radiobutton(
            cp_source_row,
            text="Cp(T) 表",
            value="cp_table",
            variable=self.vapor_specific_heat_source,
        ).pack(side="left", padx=(0, 18))
        ttk.Radiobutton(
            cp_source_row,
            text="焓表",
            value="enthalpy_table",
            variable=self.vapor_specific_heat_source,
        ).pack(side="left")

        self.gas_quality_widgets: list[tk.Widget] = []
        self.gas_quality_widgets.extend(self._entry(gas_frame, 8, "干度点数", "gas_quality_points", "自动或整数"))
        ttk.Label(
            gas_frame,
            text=(
                "干度 Q 是质量含气率：Q=0 为饱和液，Q=1 为饱和气。"
                "填“自动”时，程序按直接 REFPROP 失败的温度点数量决定；也可以手动填整数。"
            ),
            foreground="#666",
            wraplength=420,
        ).grid(row=9, column=0, columnspan=3, sticky="w", pady=(0, 6))
        viscosity_row = ttk.Frame(gas_frame)
        viscosity_row.grid(row=10, column=0, columnspan=3, sticky="ew", pady=6)
        viscosity_label = ttk.Label(viscosity_row, text="等效粘度模型")
        viscosity_label.pack(side="left", padx=(0, 12))
        viscosity_combo = ttk.Combobox(
            viscosity_row,
            textvariable=self.gas_viscosity_model,
            values=("cicchitti", "mcadams"),
            state="readonly",
            width=14,
        )
        viscosity_combo.pack(side="left")
        self.gas_quality_widgets.extend([viscosity_label, viscosity_combo])
        ttk.Label(
            gas_frame,
            text=(
                "McAdams：调和平均，基于质量含气率 Q，适用于常规两相流压降计算。\n"
                "Cicchitti：体积加权算术平均，基于气相体积分数，适用于高流速均匀流动（RefEquiv 推荐）。"
            ),
            foreground="#666",
            wraplength=420,
        ).grid(row=11, column=0, columnspan=3, sticky="w", pady=(0, 6))

        liquid_table_frame = ttk.LabelFrame(gas_frame, text="液态材料属性", padding=8)
        liquid_table_frame.grid(row=12, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        liquid_table_frame.columnconfigure(1, weight=1)
        liquid_mode_row = ttk.Frame(liquid_table_frame)
        liquid_mode_row.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 6))
        ttk.Radiobutton(
            liquid_mode_row,
            text="按饱和状态填常数",
            value="saturation",
            variable=self.liquid_property_mode,
            command=self._sync_liquid_table_state,
        ).pack(side="left", padx=(0, 18))
        ttk.Radiobutton(
            liquid_mode_row,
            text="按温度表填",
            value="table",
            variable=self.liquid_property_mode,
            command=self._sync_liquid_table_state,
        ).pack(side="left")
        self.liquid_table_widgets: list[tk.Widget] = []
        for row, label, key in (
            (1, "液态温度起点 C", "liquid_temp_start"),
            (2, "液态温度终点 C", "liquid_temp_end"),
            (3, "液态温度步长 C", "liquid_temp_step"),
        ):
            label_widget = ttk.Label(liquid_table_frame, text=label)
            label_widget.grid(row=row, column=0, sticky="w", pady=4)
            entry_widget = ttk.Entry(liquid_table_frame, textvariable=self.vars[key])
            entry_widget.grid(row=row, column=1, sticky="ew", pady=4)
            self.liquid_table_widgets.extend([label_widget, entry_widget])

        star_frame = self._section(root, "STAR-CCM+ 项目", 1, 1)
        self._file_entry(star_frame, 0, "原始 sim 文件", "sim_file", [("STAR-CCM+ sim", "*.sim"), ("All files", "*.*")])
        self._file_entry(star_frame, 1, "另存为 sim 文件", "output_sim_file", [("STAR-CCM+ sim", "*.sim"), ("All files", "*.*")])
        self._entry(star_frame, 2, "目标连续体名称", "continuum_name", "")
        self._entry(star_frame, 3, "液相名称", "liquid_phase_name", "")
        self._entry(star_frame, 4, "气相名称", "vapor_phase_name", "")
        self._file_entry(star_frame, 5, "STAR-CCM+ 程序", "starccm_exe", [("Executable", "*.exe"), ("All files", "*.*")])
        ttk.Checkbutton(star_frame, text="生成后立即运行 STAR-CCM+", variable=self.run_star).grid(
            row=6, column=0, columnspan=3, sticky="w", pady=6
        )

        out_frame = self._section(root, "输出", 2, 1)
        self._directory_entry(out_frame, 0, "输出目录", "output_dir")

        action_frame = ttk.Frame(root)
        action_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(14, 10))
        ttk.Button(action_frame, text="生成物性文件和 STAR 宏", command=self._start).pack(side="left")
        ttk.Button(action_frame, text="打开输出目录", command=self._open_output_dir).pack(side="left", padx=8)
        ttk.Button(action_frame, text="保存配置", command=self._save_gui_config).pack(side="left", padx=(14, 0))
        ttk.Button(action_frame, text="载入配置", command=self._load_gui_config).pack(side="left", padx=8)

        self.status_var = tk.StringVar(value="等待输入")
        ttk.Label(root, textvariable=self.status_var).grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 6))

        log_frame = ttk.Frame(root)
        log_frame.grid(row=5, column=0, columnspan=2, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log = tk.Text(log_frame, wrap="word", height=16)
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)
        return outer

    def _build_coolant_page(self) -> ttk.Frame:
        root = ttk.Frame(self.container)
        root.columnconfigure(0, weight=1)

        self._init_coolant_vars()

        nav_frame = ttk.Frame(root)
        nav_frame.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        ttk.Button(nav_frame, text="返回主页", command=self._show_home_page).pack(side="left")

        form_frame = ttk.LabelFrame(root, text="防冻液物性计算", padding=16)
        form_frame.grid(row=1, column=0, sticky="nsew")
        form_frame.columnconfigure(1, weight=1)

        self._coolant_entry(form_frame, 0, "物性查询温度 C", "temperature_c")
        self._coolant_combo(form_frame, 1, "浓度类型", "query_type", ("volume", "mass"))
        self._coolant_entry(form_frame, 2, "浓度值", "query_value")
        self._coolant_combo(form_frame, 3, "计算方式", "solve_mode", ("heat", "outlet-temperature", "volume-flow"))
        self._coolant_entry(form_frame, 4, "体积流量 L/min", "volume_flow_l_min", group="volume_flow")
        self._coolant_entry(form_frame, 5, "入口温度 C", "inlet_temperature_c")
        self._coolant_entry(form_frame, 6, "出口温度 C", "outlet_temperature_c", group="outlet_temperature")
        self._coolant_entry(form_frame, 7, "换热量 W", "heat_transfer_w", group="heat_transfer")
        self._coolant_combo(form_frame, 8, "出口方向", "outlet_direction", ("heating", "cooling"), group="direction")
        self._coolant_entry(form_frame, 9, "板片数", "plate_count")
        self._coolant_output_entry(form_frame, 10, "输出文件", "output_path")

        action_row = ttk.Frame(form_frame)
        action_row.grid(row=11, column=0, columnspan=3, sticky="ew", pady=(16, 0))
        ttk.Button(action_row, text="生成防冻液表", command=self._generate_coolant_xlsx).pack(side="left")
        ttk.Button(action_row, text="打开输出目录", command=self._open_coolant_output_dir).pack(side="left", padx=8)

        ttk.Label(
            form_frame,
            text="物性参数固定按“物性查询温度”计算；其余输入随计算方式联动。",
            foreground="#666",
        ).grid(row=12, column=0, columnspan=3, sticky="w", pady=(12, 0))

        self.coolant_vars["solve_mode"].trace_add("write", lambda *_: self._sync_coolant_mode_state())
        self._sync_coolant_mode_state()
        return root

    def _show_page(self, page_name: str) -> None:
        self.page_frames[page_name].tkraise()
        self.current_page = page_name

    def _show_home_page(self) -> None:
        self._show_page("home")

    def _show_refprop_page(self) -> None:
        self._show_page("refprop")

    def _show_coolant_page(self) -> None:
        self._show_page("coolant")

    def _init_coolant_vars(self) -> None:
        if self.coolant_vars:
            return
        output_path = Path(self.vars["output_dir"].get().strip() or "out") / "coolant_properties.xlsx"
        self.coolant_vars = {
            "temperature_c": tk.StringVar(value="57"),
            "query_type": tk.StringVar(value="volume"),
            "query_value": tk.StringVar(value="0.5"),
            "solve_mode": tk.StringVar(value="heat"),
            "volume_flow_l_min": tk.StringVar(value="25"),
            "inlet_temperature_c": tk.StringVar(value="42"),
            "outlet_temperature_c": tk.StringVar(value="66.5"),
            "heat_transfer_w": tk.StringVar(value="36832.8048795"),
            "outlet_direction": tk.StringVar(value="heating"),
            "plate_count": tk.StringVar(value="32"),
            "output_path": tk.StringVar(value=str(output_path)),
        }
        self.coolant_mode_widgets = {"volume_flow": [], "outlet_temperature": [], "heat_transfer": [], "direction": []}

    def _section(self, parent: ttk.Frame, title: str, row: int, column: int) -> ttk.LabelFrame:
        frame = ttk.LabelFrame(parent, text=title, padding=12)
        frame.grid(row=row, column=column, sticky="nsew", padx=8, pady=8)
        frame.columnconfigure(1, weight=1)
        return frame

    def _entry(self, parent: ttk.Frame, row: int, label: str, key: str, hint: str) -> list[tk.Widget]:
        label_widget = ttk.Label(parent, text=label)
        label_widget.grid(row=row, column=0, sticky="w", pady=6)
        entry_widget = ttk.Entry(parent, textvariable=self.vars[key])
        entry_widget.grid(row=row, column=1, sticky="ew", pady=6)
        widgets: list[tk.Widget] = [label_widget, entry_widget]
        if hint:
            hint_widget = ttk.Label(parent, text=hint, foreground="#666")
            hint_widget.grid(row=row, column=2, sticky="w", padx=(8, 0))
            widgets.append(hint_widget)
        return widgets

    def _file_entry(self, parent: ttk.Frame, row: int, label: str, key: str, filetypes: list[tuple[str, str]]) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=6)
        ttk.Entry(parent, textvariable=self.vars[key]).grid(row=row, column=1, sticky="ew", pady=6)
        ttk.Button(parent, text="浏览", command=lambda: self._browse_file(key, filetypes)).grid(row=row, column=2, padx=(8, 0))

    def _directory_entry(self, parent: ttk.Frame, row: int, label: str, key: str) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=6)
        ttk.Entry(parent, textvariable=self.vars[key]).grid(row=row, column=1, sticky="ew", pady=6)
        ttk.Button(parent, text="浏览", command=lambda: self._browse_directory(key)).grid(row=row, column=2, padx=(8, 0))

    def _browse_file(self, key: str, filetypes: list[tuple[str, str]]) -> None:
        filename = filedialog.askopenfilename(filetypes=filetypes)
        if filename:
            self.vars[key].set(filename)
            if key == "sim_file" and not self.vars["output_sim_file"].get().strip():
                path = Path(filename)
                self.vars["output_sim_file"].set(str(path.with_name(path.stem + "_refprop.sim")))

    def _browse_directory(self, key: str) -> None:
        directory = filedialog.askdirectory()
        if directory:
            self.vars[key].set(directory)

    def _wire_validation(self) -> None:
        for key in ("fluid_name", "saturation_value", "temp_start", "gas_quality_points", "liquid_temp_start", "liquid_temp_end", "liquid_temp_step"):
            self.vars[key].trace_add("write", lambda *_: self._update_temperature_warning())
        self.gas_table_mode.trace_add("write", lambda *_: self._sync_gas_table_mode_state())

    def _on_saturation_type_changed(self) -> None:
        self._sync_saturation_labels()
        self._update_temperature_warning()

    def _sync_saturation_labels(self) -> None:
        if self.saturation_type.get() == "pressure":
            self.saturation_label.configure(text="饱和压力 MPa")
        else:
            self.saturation_label.configure(text="饱和温度 C")

    def _sync_gas_pressure_state(self) -> None:
        state = "disabled" if self.use_saturation_pressure.get() else "normal"
        self.gas_pressure_entry.configure(state=state)
        self.gas_pressure_label.configure(foreground="#777" if state == "disabled" else "#000")

    def _sync_gas_table_mode_state(self) -> None:
        self._update_temperature_warning()

    def _sync_liquid_table_state(self) -> None:
        state = "normal" if self.liquid_property_mode.get() == "table" else "disabled"
        for widget in getattr(self, "liquid_table_widgets", []):
            widget.configure(state=state)
        if self.liquid_property_mode.get() == "table" and self.last_saturation_temperature_c is not None:
            self._suggest_liquid_temperature_end(self.last_saturation_temperature_c)

    def _calculate_saturation_temperature(self) -> None:
        try:
            config = self._build_config(validate_range=False)
            refprop = RefpropClient()
            refprop.load_fluid(config.fluid_name, config.fluid_components)
            saturation = resolve_saturation(refprop, config)
        except Exception as exc:
            messagebox.showerror("计算失败", str(exc))
            return

        temp_c = k_to_c(saturation.temperature_k)
        self.last_saturation_temperature_c = temp_c
        self.saturation_result_var.set(
            f"饱和温度：{temp_c:.6g} C；饱和压力：{saturation.pressure_pa / 1.0e6:.6g} MPa"
        )
        self._suggest_gas_temperature_start(temp_c)
        if self.liquid_property_mode.get() == "table":
            self._suggest_liquid_temperature_end(temp_c)
        self._append_log(self.saturation_result_var.get())
        self._update_temperature_warning()

    def _copy_saturation_result(self) -> None:
        text = self.saturation_result_var.get()
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self.status_var.set("饱和温度结果已复制")

    def _update_temperature_warning(self) -> None:
        if self.gas_table_mode.get() == "equivalent_quality":
            self.temp_warning_var.set("混合模式会先按温度范围直接取表；失败的温度点再用 RefEquiv 等效数据替代。")
            self.temp_warning_label.configure(foreground="#1f5f8b")
            return

        try:
            start_c = float(self.vars["temp_start"].get().strip())
        except ValueError:
            self.temp_warning_var.set("提示：温度起点必须是数字，并且不能小于饱和温度。")
            self.temp_warning_label.configure(foreground="#b00020")
            return

        sat_c: float | None = None
        if self.saturation_type.get() == "temperature":
            try:
                sat_c = float(self.vars["saturation_value"].get().strip())
            except ValueError:
                pass
        elif self.last_saturation_temperature_c is not None:
            sat_c = self.last_saturation_temperature_c

        if sat_c is None:
            self.temp_warning_var.set("提示：先点击“计算饱和温度”，即可检查温度起点是否合格。")
            self.temp_warning_label.configure(foreground="#9a5b00")
            return

        if start_c < sat_c:
            self.temp_warning_var.set(f"错误：温度起点 {start_c:.6g} C 不能小于饱和温度 {sat_c:.6g} C。")
            self.temp_warning_label.configure(foreground="#b00020")
        else:
            self.temp_warning_var.set(f"合格：温度起点 {start_c:.6g} C 不小于饱和温度 {sat_c:.6g} C。")
            self.temp_warning_label.configure(foreground="#1f7a1f")

    def _start(self) -> None:
        try:
            config = self._build_config(validate_range=True)
        except Exception as exc:
            messagebox.showerror("输入错误", str(exc))
            return

        self.status_var.set("正在调用 REFPROP 生成物性...")
        self._append_log("开始生成。")
        thread = threading.Thread(target=self._run_worker, args=(config, self.run_star.get()), daemon=True)
        thread.start()

    def _run_worker(self, config: ToolConfig, run_star: bool) -> None:
        try:
            result = generate_outputs(config, run_star=run_star)
        except Exception as exc:
            self.after(0, self._finish_error, exc)
            return
        self.after(0, self._finish_success, result)

    def _finish_success(self, result) -> None:
        sat_c = result.summary["saturation"]["temperature_C"]
        self.last_saturation_temperature_c = sat_c
        used_quality_points = result.summary.get("gas_equivalent_quality_points_used")
        current_quality_points = self.vars["gas_quality_points"].get().strip().lower()
        if used_quality_points is not None and current_quality_points in {"", "auto", "自动"}:
            self.vars["gas_quality_points"].set(str(used_quality_points))
        self.saturation_result_var.set(
            f"饱和温度：{sat_c:.6g} C；饱和压力：{result.summary['saturation']['pressure_MPa']:.6g} MPa"
        )
        self._update_temperature_warning()
        self.status_var.set("完成")
        self._append_log(result.to_display_text())
        self._append_log(f"液相参数: {result.liquid_json}")
        if result.liquid_csv is not None:
            self._append_log(f"液相表格: {result.liquid_csv}")
        self._append_log(f"气相表格: {result.vapor_csv}")
        self._append_log(f"STAR宏: {result.macro_file}")
        if result.star_log is not None:
            self._append_log(f"STAR运行日志: {result.star_log}")
        messagebox.showinfo("完成", "物性文件和STAR宏已生成。")

    def _finish_error(self, exc: Exception) -> None:
        self.status_var.set("失败")
        self._append_log(f"失败: {exc}")
        messagebox.showerror("失败", str(exc))

    def _build_config(self, validate_range: bool) -> ToolConfig:
        fluid = self.vars["fluid_name"].get().strip()
        if not fluid:
            raise ValueError("请输入制冷剂名称。")

        sat_type = self.saturation_type.get()
        saturation_value = _float_value(self.vars["saturation_value"].get(), "饱和压力或饱和温度")
        gas_table_mode = self.gas_table_mode.get()
        if gas_table_mode not in {"temperature", "equivalent_quality"}:
            gas_table_mode = "temperature"
        temp_start = _float_value(self.vars["temp_start"].get(), "温度起点")
        temp_end = _float_value(self.vars["temp_end"].get(), "温度终点")
        temp_step = _float_value(self.vars["temp_step"].get(), "温度步长")
        if temp_step <= 0:
            raise ValueError("温度步长必须大于0。")
        if gas_table_mode == "temperature" and temp_end < temp_start:
            raise ValueError("温度终点不能小于温度起点。")
        gas_quality_points = _optional_int_value(self.vars["gas_quality_points"].get(), "干度点数")
        if gas_quality_points is not None and gas_quality_points < 2:
            raise ValueError("干度点数必须是“自动”或大于等于2的整数。")
        gas_viscosity_model = self.gas_viscosity_model.get()
        if gas_viscosity_model not in {"cicchitti", "mcadams"}:
            gas_viscosity_model = "cicchitti"
        liquid_mode = self.liquid_property_mode.get()
        if liquid_mode not in {"saturation", "table"}:
            liquid_mode = "saturation"
        if liquid_mode == "table":
            liquid_temp_start = _float_value(self.vars["liquid_temp_start"].get(), "液态温度起点")
            liquid_temp_end = _float_value(self.vars["liquid_temp_end"].get(), "液态温度终点")
            liquid_temp_step = _float_value(self.vars["liquid_temp_step"].get(), "液态温度步长")
            if liquid_temp_step <= 0:
                raise ValueError("液态温度步长必须大于0。")
            if liquid_temp_end < liquid_temp_start:
                raise ValueError("液态温度终点不能小于液态温度起点。")
        else:
            liquid_temp_start = 0.0
            liquid_temp_end = 0.0
            liquid_temp_step = 0.1

        gas_pressure = None
        if not self.use_saturation_pressure.get():
            gas_pressure = _float_value(self.vars["gas_pressure"].get(), "气态压力")

        sim_file = Path(self.vars["sim_file"].get().strip() or "input.sim")
        output_sim = Path(self.vars["output_sim_file"].get().strip() or sim_file.with_name(sim_file.stem + "_refprop.sim"))
        starccm_exe_text = self.vars["starccm_exe"].get().strip()
        continuum_name = self.vars["continuum_name"].get().strip()
        if not continuum_name:
            raise ValueError("请输入目标连续体名称。")

        config = ToolConfig(
            fluid_name=fluid,
            fluid_components=None,
            saturation_type=sat_type,
            saturation_value=saturation_value,
            saturation_unit="MPa" if sat_type == "pressure" else "C",
            gas_pressure_value=gas_pressure,
            gas_pressure_unit="MPa",
            gas_temperature_start=temp_start,
            gas_temperature_end=temp_end,
            gas_temperature_step=temp_step,
            gas_temperature_unit="C",
            liquid_property_mode=liquid_mode,
            liquid_temperature_start=liquid_temp_start,
            liquid_temperature_end=liquid_temp_end,
            liquid_temperature_step=liquid_temp_step,
            liquid_temperature_unit="C",
            sim_file=sim_file,
            output_sim_file=output_sim,
            continuum_name=continuum_name,
            liquid_phase_name=self.vars["liquid_phase_name"].get().strip() or f"{fluid} Liquid",
            vapor_phase_name=self.vars["vapor_phase_name"].get().strip() or f"{fluid} Vapor",
            vapor_specific_heat_source=self.vapor_specific_heat_source.get(),
            starccm_exe=Path(starccm_exe_text) if starccm_exe_text else None,
            output_directory=Path(self.vars["output_dir"].get().strip() or "out"),
            gas_table_mode=gas_table_mode,
            quality_points=gas_quality_points,
            viscosity_model=gas_viscosity_model,
        )

        if validate_range:
            refprop = RefpropClient()
            refprop.load_fluid(config.fluid_name, config.fluid_components)
            saturation = resolve_saturation(refprop, config)
            self.last_saturation_temperature_c = k_to_c(saturation.temperature_k)
            validate_gas_temperature_range(config, saturation.temperature_k)
            validate_liquid_temperature_range(config, saturation.temperature_k)

        self._update_temperature_warning()
        return config

    def _append_log(self, text: str) -> None:
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def _open_output_dir(self) -> None:
        directory = Path(self.vars["output_dir"].get().strip() or "out")
        directory.mkdir(parents=True, exist_ok=True)
        os.startfile(directory)

    def _coolant_entry(self, parent: ttk.Frame, row: int, label: str, key: str, group: str | None = None) -> None:
        label_widget = ttk.Label(parent, text=label)
        label_widget.grid(row=row, column=0, sticky="w", pady=6)
        entry_widget = ttk.Entry(parent, textvariable=self.coolant_vars[key])
        entry_widget.grid(row=row, column=1, sticky="ew", pady=6)
        if group:
            self.coolant_mode_widgets[group].extend([label_widget, entry_widget])

    def _coolant_combo(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        key: str,
        values: tuple[str, ...],
        group: str | None = None,
    ) -> None:
        label_widget = ttk.Label(parent, text=label)
        label_widget.grid(row=row, column=0, sticky="w", pady=6)
        combo_widget = ttk.Combobox(parent, textvariable=self.coolant_vars[key], values=values, state="readonly")
        combo_widget.grid(row=row, column=1, sticky="ew", pady=6)
        if group:
            self.coolant_mode_widgets[group].extend([label_widget, combo_widget])

    def _coolant_output_entry(self, parent: ttk.Frame, row: int, label: str, key: str) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=6)
        ttk.Entry(parent, textvariable=self.coolant_vars[key]).grid(row=row, column=1, sticky="ew", pady=6)
        ttk.Button(parent, text="浏览", command=self._browse_coolant_output).grid(row=row, column=2, padx=(8, 0))

    def _browse_coolant_output(self) -> None:
        current = self.coolant_vars.get("output_path")
        current_path = Path(current.get().strip()) if current and current.get().strip() else Path("out/coolant_properties.xlsx")
        filename = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel workbook", "*.xlsx"), ("All files", "*.*")],
            initialfile=current_path.name,
            initialdir=str(current_path.parent),
        )
        if filename:
            self.coolant_vars["output_path"].set(filename)

    def _sync_coolant_mode_state(self) -> None:
        if "solve_mode" not in self.coolant_vars:
            return
        solve_mode = self.coolant_vars["solve_mode"].get()
        enabled_groups = {
            "heat": {"volume_flow", "outlet_temperature"},
            "outlet-temperature": {"volume_flow", "heat_transfer", "direction"},
            "volume-flow": {"outlet_temperature", "heat_transfer"},
        }.get(solve_mode, {"volume_flow", "outlet_temperature", "heat_transfer", "direction"})

        for group, widgets in self.coolant_mode_widgets.items():
            enabled = group in enabled_groups
            for widget in widgets:
                if isinstance(widget, ttk.Label):
                    widget.configure(foreground="#000" if enabled else "#777")
                elif isinstance(widget, ttk.Combobox):
                    widget.configure(state="readonly" if enabled else "disabled")
                else:
                    widget.configure(state="normal" if enabled else "disabled")

    def _generate_coolant_xlsx(self) -> None:
        try:
            plate_count = int(_float_value(self.coolant_vars["plate_count"].get(), "板片数"))
            output_path = Path(self.coolant_vars["output_path"].get().strip() or "out/coolant_properties.xlsx")
            coolant_row = build_coolant_row(
                temperature_c=_float_value(self.coolant_vars["temperature_c"].get(), "物性查询温度"),
                query_type=self.coolant_vars["query_type"].get().strip() or "volume",
                query_value=_float_value(self.coolant_vars["query_value"].get(), "浓度值"),
            )
            calculation = build_coolant_calculation(
                coolant_row,
                solve_mode=self.coolant_vars["solve_mode"].get().strip() or "heat",
                volume_flow_l_min=self._coolant_optional_float("volume_flow_l_min"),
                inlet_temperature_c=_float_value(self.coolant_vars["inlet_temperature_c"].get(), "入口温度"),
                outlet_temperature_c=self._coolant_optional_float("outlet_temperature_c"),
                heat_transfer_w=self._coolant_optional_float("heat_transfer_w"),
                outlet_direction=self.coolant_vars["outlet_direction"].get().strip() or "heating",
                plate_count=plate_count,
            )
            write_coolant_xlsx(output_path, coolant_row, calculation)
        except Exception as exc:
            messagebox.showerror("生成失败", str(exc), parent=self)
            return

        summary = (
            f"防冻液参数表已生成: {output_path.resolve()}\n"
            f"质量流量: {calculation.mass_flow_kg_s:.10g} kg/s\n"
            f"出口温度: {calculation.outlet_temperature_c:.10g} C\n"
            f"换热量: {calculation.heat_transfer_w:.10g} W\n"
            f"体积流量: {calculation.volume_flow_l_min:.10g} L/min"
        )
        self.status_var.set("防冻液参数表已生成")
        self._append_log(summary)
        messagebox.showinfo("完成", summary, parent=self)

    def _coolant_optional_float(self, key: str) -> float | None:
        value = self.coolant_vars[key].get().strip()
        if not value:
            return None
        labels = {
            "volume_flow_l_min": "体积流量",
            "outlet_temperature_c": "出口温度",
            "heat_transfer_w": "换热量",
        }
        return _float_value(value, labels.get(key, key))

    def _open_coolant_output_dir(self) -> None:
        if "output_path" not in self.coolant_vars:
            return
        directory = Path(self.coolant_vars["output_path"].get().strip() or "out/coolant_properties.xlsx").parent
        directory.mkdir(parents=True, exist_ok=True)
        os.startfile(directory)

    def _suggest_gas_temperature_start(self, saturation_temperature_c: float) -> None:
        suggested = saturation_temperature_c + SATURATION_TABLE_OFFSET_C
        try:
            current = float(self.vars["temp_start"].get().strip())
        except ValueError:
            self.vars["temp_start"].set(f"{suggested:.6g}")
            return
        default_start_values = {"", "30"}
        if self.vars["temp_start"].get().strip() in default_start_values or current < saturation_temperature_c:
            self.vars["temp_start"].set(f"{suggested:.6g}")
            self._append_log(f"温度起点已自动调整为饱和温度上方 {suggested:.6g} C。")

    def _suggest_liquid_temperature_end(self, saturation_temperature_c: float) -> None:
        suggested = saturation_temperature_c - SATURATION_TABLE_OFFSET_C
        try:
            current = float(self.vars["liquid_temp_end"].get().strip())
        except ValueError:
            self.vars["liquid_temp_end"].set(f"{suggested:.6g}")
            return
        default_end_values = {"", "9"}
        if self.vars["liquid_temp_end"].get().strip() in default_end_values or current > saturation_temperature_c:
            self.vars["liquid_temp_end"].set(f"{suggested:.6g}")
            self._append_log(f"液态温度终点已自动调整为饱和温度下方 {suggested:.6g} C。")

    def _save_gui_config(self) -> None:
        filename = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON config", "*.json"), ("All files", "*.*")],
            initialfile="refprop_to_ccm_gui_config.json",
        )
        if not filename:
            return
        data = self._gui_state()
        Path(filename).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        self._append_log(f"界面配置已保存: {filename}")

    def _load_gui_config(self) -> None:
        filename = filedialog.askopenfilename(filetypes=[("JSON config", "*.json"), ("All files", "*.*")])
        if not filename:
            return
        try:
            data = json.loads(Path(filename).read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("配置文件格式不正确。")
            self._apply_gui_state(data)
        except Exception as exc:
            messagebox.showerror("载入失败", str(exc))
            return
        self._append_log(f"界面配置已载入: {filename}")

    def _gui_state(self) -> dict:
        return {
            "fields": {key: value.get() for key, value in self.vars.items()},
            "saturation_type": self.saturation_type.get(),
            "use_saturation_pressure": self.use_saturation_pressure.get(),
            "gas_table_mode": self.gas_table_mode.get(),
            "gas_viscosity_model": self.gas_viscosity_model.get(),
            "vapor_specific_heat_source": self.vapor_specific_heat_source.get(),
            "liquid_property_mode": self.liquid_property_mode.get(),
            "run_star": self.run_star.get(),
        }

    def _apply_gui_state(self, data: dict) -> None:
        fields = data.get("fields", {})
        if isinstance(fields, dict):
            for key, value in fields.items():
                if key in self.vars:
                    self.vars[key].set(str(value))
        if data.get("saturation_type") in {"pressure", "temperature"}:
            self.saturation_type.set(str(data["saturation_type"]))
        if data.get("vapor_specific_heat_source") in {"cp_table", "enthalpy_table"}:
            self.vapor_specific_heat_source.set(str(data["vapor_specific_heat_source"]))
        if data.get("gas_table_mode") in {"temperature", "equivalent_quality"}:
            self.gas_table_mode.set(str(data["gas_table_mode"]))
        if data.get("gas_viscosity_model") in {"cicchitti", "mcadams"}:
            self.gas_viscosity_model.set(str(data["gas_viscosity_model"]))
        if data.get("liquid_property_mode") in {"saturation", "table"}:
            self.liquid_property_mode.set(str(data["liquid_property_mode"]))
        if "use_saturation_pressure" in data:
            self.use_saturation_pressure.set(bool(data["use_saturation_pressure"]))
        if "run_star" in data:
            self.run_star.set(bool(data["run_star"]))
        self.last_saturation_temperature_c = None
        self.saturation_result_var.set("尚未计算饱和温度")
        self._sync_saturation_labels()
        self._sync_gas_pressure_state()
        self._sync_gas_table_mode_state()
        self._sync_liquid_table_state()
        self._update_temperature_warning()


def _float_value(text: str, label: str) -> float:
    try:
        return float(text.strip())
    except ValueError as exc:
        raise ValueError(f"{label}必须是数字。") from exc


def _int_value(text: str, label: str) -> int:
    value = text.strip()
    try:
        parsed = int(value)
    except ValueError as exc:
        raise ValueError(f"{label}必须是整数。") from exc
    return parsed


def _optional_int_value(text: str, label: str) -> int | None:
    value = text.strip().lower()
    if value in {"", "auto", "自动"}:
        return None
    return _int_value(text, label)


def main() -> int:
    app = RefpropToCcmApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
