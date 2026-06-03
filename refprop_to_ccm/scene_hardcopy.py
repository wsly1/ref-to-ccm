from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

STARCCM_RUN_TIMEOUT_SECONDS = 10 * 60

MACRO_TEMPLATE = """\
package macro;

import java.io.File;
import java.lang.reflect.Method;
import java.util.Collection;

import star.common.*;
import star.base.neo.*;

public class scene_hardcopy extends StarMacro {

  private Simulation sim;
  private static final double[] VIEW_DIR = new double[]{0.0, 0.0, 1.0};
  private static final double[] UP_VEC = new double[]{0.0, 1.0, 0.0};
  private static final double ZOOM_FORWARD = __ZOOM_FORWARD__;
  private static final int NUM_LABELS = __NUM_LABELS__;
  private static final int EXPORT_W = __EXPORT_W__;
  private static final int EXPORT_H = __EXPORT_H__;

  public void execute() {
    sim = getActiveSimulation();
    sim.println("[hardcopy] ===== Hardcopy Start =====");

    try {
      Object sm = sim.getClass().getMethod("getSceneManager").invoke(sim);
      Object result = sm.getClass().getMethod("getObjects").invoke(sm);
      if (!(result instanceof Collection)) return;
      Collection<?> scenes = (Collection<?>) result;
      sim.println("[hardcopy] Total scenes: " + scenes.size());

      int exportIndex = 0;
      for (Object scene : scenes) {
        String name = "unknown";
        try {
          name = (String) scene.getClass().getMethod("getPresentationName").invoke(scene);
        } catch (Throwable ex) {}

        if (shouldSkip(name)) {
          sim.println("[hardcopy] SKIP: " + name);
          continue;
        }

        sim.println("[hardcopy] --- Scene: \\"" + name + "\\" ---");

        setViewOrientation(scene, name);
        fitAll(scene, name);
        zoomForward(scene, name, ZOOM_FORWARD);
        configureLegend(scene, name, NUM_LABELS);
        doHardcopy(scene, name, exportIndex);
        exportIndex++;
      }
    } catch (Throwable ex) {
      sim.println("[hardcopy] ERROR: " + ex.getMessage());
    }

    sim.println("[hardcopy] ===== Hardcopy End =====");
  }

  private boolean shouldSkip(String name) {
    String lower = name.toLowerCase();
    return lower.contains("几何") || lower.contains("geometry")
        || lower.contains("网格") || lower.contains("mesh");
  }

  private void setViewOrientation(Object scene, String name) {
    try {
      Method m = findMethod(scene.getClass(), "setViewOrientation");
      if (m != null && m.getParameterCount() == 2) {
        m.invoke(scene, new DoubleVector(VIEW_DIR), new DoubleVector(UP_VEC));
        sim.println("[hardcopy]     setViewOrientation OK");
      }
    } catch (Throwable ex) {
      sim.println("[hardcopy]     setViewOrientation failed: " + ex.getMessage());
    }
  }

  private void fitAll(Object scene, String name) {
    try {
      Method m = findMethod(scene.getClass(), "updatePipelineAndResetClippingRange");
      if (m != null && m.getParameterCount() == 0) m.invoke(scene);
    } catch (Throwable ex) {}

    try {
      Method m = findMethod(scene.getClass(), "centerViewOn");
      if (m != null) {
        Class<?>[] params = m.getParameterTypes();
        if (params.length == 2 && params[0] == double[].class && params[1] == int.class) {
          m.invoke(scene, new double[]{0.0, 0.0, 0.0}, 1);
          sim.println("[hardcopy]     centerViewOn(origin,1) OK");
        } else if (params.length == 1 && params[0] == double[].class) {
          m.invoke(scene, new double[]{0.0, 0.0, 0.0});
          sim.println("[hardcopy]     centerViewOn(origin) OK");
        }
      }
    } catch (Throwable ex) {
      sim.println("[hardcopy]     centerViewOn failed: " + ex.getMessage());
    }
  }

  private void zoomForward(Object scene, String name, double distance) {
    if (Math.abs(distance) < 1e-12) {
      return;
    }
    try {
      Method m = findMethod(scene.getClass(), "translateCamera");
      if (m != null) {
        Class<?>[] params = m.getParameterTypes();
        if (params.length == 1 && params[0] == DoubleVector.class) {
          m.invoke(scene, new DoubleVector(new double[]{
            VIEW_DIR[0] * distance, VIEW_DIR[1] * distance, VIEW_DIR[2] * distance}));
          sim.println("[hardcopy]     translateCamera OK");
        } else if (params.length == 1 && params[0] == double[].class) {
          m.invoke(scene, (Object) new double[]{
            VIEW_DIR[0] * distance, VIEW_DIR[1] * distance, VIEW_DIR[2] * distance});
          sim.println("[hardcopy]     translateCamera OK");
        }
      }
    } catch (Throwable ex) {
      sim.println("[hardcopy]     translateCamera failed: " + ex.getMessage());
    }
  }

  private void configureLegend(Object scene, String name, int numLabels) {
    try {
      Object children = scene.getClass().getMethod("getChildren").invoke(scene);
      if (!(children instanceof Collection)) return;
      for (Object child : (Collection<?>) children) {
        try {
          Method getLegend = findMethod(child.getClass(), "getLegend");
          if (getLegend == null) continue;
          Object legend = getLegend.invoke(child);
          if (legend == null) continue;

          trySet(legend, "setNumLabels", numLabels);
          trySet(legend, "setNumberOfLabels", numLabels);
          trySet(legend, "setNumTicks", numLabels);
          sim.println("[hardcopy]     legend numLabels=" + numLabels + " OK");
          return;
        } catch (Throwable ex) {}
      }
    } catch (Throwable ex) {}
  }

  private void trySet(Object obj, String methodName, Object value) {
    try {
      Method m = findMethod(obj.getClass(), methodName);
      if (m == null) return;
      Class<?>[] params = m.getParameterTypes();
      if (params.length != 1) return;
      if (value instanceof DoubleVector && params[0] == DoubleVector.class) {
        m.invoke(obj, value);
      } else if (value instanceof String && params[0] == String.class) {
        m.invoke(obj, value);
      } else if (value instanceof Integer && params[0] == int.class) {
        m.invoke(obj, ((Integer) value).intValue());
      } else if (value instanceof Double && (params[0] == double.class || params[0] == Double.class)) {
        m.invoke(obj, ((Double) value).doubleValue());
      }
    } catch (Throwable ex) {}
  }

  private void doHardcopy(Object scene, String name, int index) {
    String safeName = name.replaceAll("[\\\\/:*?\\"<>|]", "_");
    String filePath = "__OUTPUT_DIR__/scene_" + index + "_" + safeName + ".png";
    sim.println("[hardcopy]     Exporting: " + filePath);

    try {
      File file = new File(filePath);
      file.getParentFile().mkdirs();
      try {
        scene.getClass().getMethod("printToFile", File.class, int.class, int.class)
          .invoke(scene, file, EXPORT_W, EXPORT_H);
        sim.println("[hardcopy]     OK");
        return;
      } catch (Throwable ex) {}
      try {
        scene.getClass().getMethod("printAndWait", File.class, int.class, int.class, int.class)
          .invoke(scene, file, EXPORT_W, EXPORT_H, 0);
        sim.println("[hardcopy]     OK via printAndWait");
      } catch (Throwable ex) {
        sim.println("[hardcopy]     FAILED: " + ex.getMessage());
      }
    } catch (Throwable ex) {
      sim.println("[hardcopy]     FAILED: " + ex.getMessage());
    }
  }

  private Method findMethod(Class<?> cls, String name) {
    for (Method m : cls.getMethods()) {
      if (m.getName().equals(name)) return m;
    }
    return null;
  }
}
"""


def render_scene_hardcopy_macro(
    output_dir: str = "out/scenes",
    zoom_forward: float = 0.0,
    num_labels: int = 5,
    export_w: int = 1920,
    export_h: int = 1080,
) -> str:
    return (
        MACRO_TEMPLATE
        .replace("__OUTPUT_DIR__", output_dir)
        .replace("__ZOOM_FORWARD__", str(zoom_forward))
        .replace("__NUM_LABELS__", str(num_labels))
        .replace("__EXPORT_W__", str(export_w))
        .replace("__EXPORT_H__", str(export_h))
    )


def run_scene_hardcopy(
    starccm_exe: Path,
    sim_file: Path,
    output_directory: Path,
    zoom_forward: float = 0.0,
    num_labels: int = 5,
    export_w: int = 1920,
    export_h: int = 1080,
) -> list[str]:
    output_directory.mkdir(parents=True, exist_ok=True)

    if not starccm_exe.exists():
        raise FileNotFoundError(f"STAR-CCM+ 程序不存在: {starccm_exe}")
    if not sim_file.exists():
        raise FileNotFoundError(f"仿真文件不存在: {sim_file}")

    scenes_dir = output_directory / "scenes"
    scenes_dir.mkdir(parents=True, exist_ok=True)

    macro_file = output_directory / "scene_hardcopy.java"
    macro_file.write_text(
        render_scene_hardcopy_macro(
            output_dir=str(scenes_dir.resolve()).replace("\\", "/"),
            zoom_forward=zoom_forward,
            num_labels=num_labels,
            export_w=export_w,
            export_h=export_h,
        ),
        encoding="utf-8",
    )

    log_file = output_directory / "starccm_hardcopy.log"

    tmp_dir = Path(tempfile.mkdtemp(prefix="starccm_hardcopy_"))
    tmp_sim = tmp_dir / sim_file.name
    with open(sim_file, "rb") as src, open(tmp_sim, "wb") as dst:
        while True:
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)

    command = [str(starccm_exe), "-batch", str(macro_file.resolve()), str(tmp_sim.resolve())]

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
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    if completed.returncode != 0:
        raise RuntimeError(
            f"STAR-CCM+ 运行失败（退出码 {completed.returncode}）。日志: {log_file.resolve()}"
        )

    exported = sorted(str(p) for p in scenes_dir.glob("scene_*.png"))
    return exported
