from __future__ import annotations

import math
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

STARCCM_RUN_TIMEOUT_SECONDS = 10 * 60

MACRO_TEMPLATE = """\
package macro;

import java.lang.reflect.Method;
import java.util.Collection;

import star.common.*;

public class extract_report extends StarMacro {

  private Simulation sim;

  public void execute() {
    sim = getActiveSimulation();
    sim.println("[report-extract] ===== Report Extraction Start =====");
    listAllReports();
    listAllRegionsAndBoundaries();
    sim.println("[report-extract] ===== Report Extraction End =====");
  }

  private void listAllReports() {
    try {
      Object rm = sim.getClass().getMethod("getReportManager").invoke(sim);
      Method getObjects = rm.getClass().getMethod("getObjects");
      Object result = getObjects.invoke(rm);
      if (result instanceof Collection) {
        Collection<?> reports = (Collection<?>) result;
        sim.println("[report-extract] Total reports found: " + reports.size());
        for (Object report : reports) {
          String name = "unknown";
          String className = report.getClass().getSimpleName();
          try {
            name = (String) report.getClass().getMethod("getPresentationName").invoke(report);
          } catch (Throwable ex) {
            name = report.toString();
          }
          String reportVal = readReportValue(report);
          String units = "N/A";
          try {
            Object u = report.getClass().getMethod("getUnits").invoke(report);
            units = String.valueOf(u);
          } catch (Throwable ex) {
            units = "no-units";
          }
          sim.println("[report-extract]   Report: \\"" + name
            + "\\" | Type: " + className
            + " | Value: " + reportVal
            + " | Units: " + units);
        }
      }
    } catch (Throwable ex) {
      sim.println("[report-extract] Report enumeration failed: " + ex.getMessage());
    }
  }

  private String readReportValue(Object report) {
    try {
      double val = (double) report.getClass().getMethod("getValue").invoke(report);
      return String.valueOf(val);
    } catch (Throwable ex) {
      return "err:" + ex.getMessage();
    }
  }

  private void listAllRegionsAndBoundaries() {
    sim.println("[report-extract] --- Regions and Boundaries ---");
    for (Region region : sim.getRegionManager().getObjects()) {
      sim.println("[report-extract]   Region: \\"" + region.getPresentationName() + "\\"");
      for (Boundary boundary : region.getBoundaryManager().getObjects()) {
        sim.println("[report-extract]     Boundary: \\"" + boundary.getPresentationName() + "\\"");
      }
    }
  }
}
"""

REPORT_PATTERN = re.compile(
    r'\[report-extract\]\s+Report:\s+"(.+?)"'
    r'\s*\|\s*Type:\s*(\S+)'
    r'\s*\|\s*Value:\s*(\S+)'
    r'\s*\|\s*Units:\s*(.+?)$'
)
REGION_PATTERN = re.compile(r'\[report-extract\]\s+Region:\s+"(.+?)"')
BOUNDARY_PATTERN = re.compile(r'\[report-extract\]\s+Boundary:\s+"(.+?)"')


@dataclass(frozen=True)
class ReportItem:
    name: str
    report_type: str
    value: float | None
    raw_value: str
    units: str


@dataclass(frozen=True)
class ReportExtractResult:
    reports: list[ReportItem] = field(default_factory=list)
    regions: dict[str, list[str]] = field(default_factory=dict)
    log_file: Path | None = None


def render_report_macro() -> str:
    return MACRO_TEMPLATE


def run_report_extraction(
    starccm_exe: Path,
    sim_file: Path,
    output_directory: Path,
) -> ReportExtractResult:
    output_directory.mkdir(parents=True, exist_ok=True)

    if not starccm_exe.exists():
        raise FileNotFoundError(f"STAR-CCM+ 程序不存在: {starccm_exe}")
    if not sim_file.exists():
        raise FileNotFoundError(f"仿真文件不存在: {sim_file}")

    macro_file = output_directory / "extract_report.java"
    macro_file.write_text(render_report_macro(), encoding="utf-8")

    log_file = output_directory / "starccm_report_extract.log"
    command = [str(starccm_exe), "-batch", str(macro_file.resolve()), str(sim_file.resolve())]

    with log_file.open("w", encoding="utf-8", errors="replace") as handle:
        handle.write("Command:\n")
        handle.write(" ".join(command))
        handle.write("\n\nOutput:\n")
        try:
            completed = subprocess.run(
                command,
                stdout=handle,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=STARCCM_RUN_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"STAR-CCM+ 运行超时（超过 {STARCCM_RUN_TIMEOUT_SECONDS} 秒）。"
                f"日志: {log_file.resolve()}"
            ) from exc

    if completed.returncode != 0:
        raise RuntimeError(
            f"STAR-CCM+ 运行失败（退出码 {completed.returncode}）。日志: {log_file.resolve()}"
        )

    return parse_report_log(log_file)


def parse_report_log(log_file: Path) -> ReportExtractResult:
    log_text = log_file.read_text(encoding="utf-8", errors="replace")
    lines = log_text.splitlines()

    reports: list[ReportItem] = []
    regions: dict[str, list[str]] = {}
    current_region: str | None = None

    for line in lines:
        m = REPORT_PATTERN.search(line)
        if m:
            raw_value = m.group(3).strip()
            numeric_value: float | None = None
            if not raw_value.startswith("err:"):
                try:
                    parsed = float(raw_value)
                    if not math.isnan(parsed):
                        numeric_value = parsed
                except ValueError:
                    pass
            reports.append(ReportItem(
                name=m.group(1),
                report_type=m.group(2),
                value=numeric_value,
                raw_value=raw_value,
                units=m.group(4).strip(),
            ))
            continue

        m = REGION_PATTERN.search(line)
        if m:
            current_region = m.group(1)
            regions[current_region] = []
            continue

        m = BOUNDARY_PATTERN.search(line)
        if m and current_region is not None:
            regions[current_region].append(m.group(1))

    return ReportExtractResult(reports=reports, regions=regions, log_file=log_file)
