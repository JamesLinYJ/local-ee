import type { Job } from "../types";

export function runTasks(jobs: Job[], parentId: string) {
  return jobs
    .filter((j) => j.id === parentId || j.context.source_job_id === parentId)
    .sort((a, b) =>
      a.id === parentId
        ? -1
        : b.id === parentId
          ? 1
          : a.created.localeCompare(b.created),
    );
}

export function runSummary(jobs: Job[]) {
  const parent = jobs.find((j) => j.kind === "script");
  if (!parent) return "尚未运行";
  if (parent.status === "queued") return "脚本等待运行";
  if (parent.status === "running") return "正在执行脚本";
  const computing = jobs.filter(
    (j) => j.kind === "batch" && ["queued", "running"].includes(j.status),
  ).length;
  const exports = jobs.filter((j) => j.status === "created").length;
  if (computing) return `${computing} 个结果正在计算`;
  if (jobs.some((j) => j.status === "error"))
    return "有任务失败，查看原因后重试";
  if (parent.status === "canceled") return "脚本已取消";
  if (exports) return `计算已完成 · ${exports} 个导出待启动`;
  return "本次运行已完成";
}

export interface Failure {
  title: string;
  detail: string;
  suggestion: string;
  doc: string;
  location?: { line: number; column: number };
}
export function failureInfo(log: string): Failure {
  const js = log.match(/\/job\/script\.js:(\d+)(?::(\d+))?/);
  const py = log.match(/File ["']\/job\/script\.py["'], line (\d+)/);
  const match = js || py;
  const location = match
    ? { line: Number(match[1]), column: Number(js?.[2] || 1) }
    : undefined;
  const message =
    log.match(
      /^(?:Error|TypeError|SyntaxError|ValueError|RuntimeError):\s*(.+)/m,
    )?.[1] || "";
  const band = message.match(
    /Band selector ['"]([^'"]+)['"] did not match; available: (.+)/,
  );
  if (band)
    return {
      title: `缺少波段 ${band[1]}`,
      detail: `当前影像可用波段：${band[2]}`,
      suggestion:
        "检查 select 的波段名。本地样本缺少 QA60/B11 等波段，不能直接套用需要这些波段的脚本。",
      doc: "gee-catalog",
      location,
    };
  if (
    /not locally (?:ingested|available)|not passed Earth Engine compatibility|CollectionNotFound/.test(
      message,
    )
  )
    return {
      title: "本地还没有这份数据",
      detail: message,
      suggestion:
        "在数据目录核对已入库的数据集、范围和时间；已有数据不会因换一个 GEE ID 自动变为全球目录。",
      doc: "gee-catalog",
      location,
    };
  if (
    /no locally available images|empty (?:local )?(?:ImageCollection|collection)|NoDataAvailable/.test(
      log,
    )
  )
    return {
      title: "这个范围或时间没有可计算影像",
      detail: message,
      suggestion:
        "检查日期和研究区。按月循环时，先判断集合 size()，再跳过空月份。",
      doc: "gee-filter",
      location,
    };
  if (/Unsupported|unsupported|not implemented|is not a function/.test(message))
    return {
      title: "这项写法尚未完全支持",
      detail: message,
      suggestion:
        "查看对应参数与兼容范围。不建议删掉掩膜、投影或算法来绕过错误，这会改变分析结果。",
      doc: "gee-levels",
      location,
    };
  if (/exceeds|limit exceeded|超限|执行超时|内存/.test(log))
    return {
      title: "任务超过本地限额",
      detail: message,
      suggestion:
        "缩小研究区、减少景数或分期计算；增大 maxPixels 不会提高服务器的内存和执行时间限额。",
      doc: "gee-export",
      location,
    };
  return {
    title: "脚本没有运行完成",
    detail: message || "查看完整日志中的第一条具体错误。",
    suggestion: location
      ? "先检查触发错误的位置，再重新运行。"
      : "展开完整日志查看原因；已有成功结果仍可在任务中下载。",
    doc: "gee-js",
    location,
  };
}

export function readableLog(log: string) {
  const warnings: string[] = [];
  const output = log
    .split("\n")
    .filter((line) => {
      if (!line.startsWith("[兼容提示]")) return true;
      if (!warnings.includes(line)) warnings.push(line);
      return false;
    })
    .join("\n");
  return { output, warnings };
}
