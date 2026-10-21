import { describe, expect, it } from "vitest";
import { spawnSync } from "node:child_process";
import { parseGraph, referencedNodes, graphToPython } from "../processGraph";
import { assetUrl } from "../api";
import { readyMapEvents } from "../../hooks/useMapEvents";
import { runTasks, runSummary, failureInfo } from "../run";
import type { Job, ProcessGraph } from "../../types";
const job = (id: string, overrides: Partial<Job> = {}): Job => ({
  id,
  kind: "script",
  title: id,
  status: "finished",
  created: "2024-01-01",
  error: null,
  language: "javascript",
  events: [],
  assets: {},
  context: {},
  ...overrides,
});
describe("execution protocol contracts", () => {
  it("does not confuse callback-local graph references with global links", () => {
    expect(
      referencedNodes({
        data: { from_node: "source" },
        process: {
          process_graph: {
            source: {
              process_id: "mean",
              arguments: { data: { from_node: "private" } },
            },
          },
        },
      }),
    ).toEqual(["source"]);
  });
  it("preserves ordinary quotes, newlines and Chinese titles in official Python job submission", () => {
    const graph: ProcessGraph = {
      load: {
        process_id: "load_collection",
        arguments: { id: "sentinel-2-l2a", note: 'sensor "A"\\B\n测区' },
        result: true,
      },
    };
    const code = graphToPython(graph, '测区 "春季"\n合成');
    const stub = `import json\nclass Job:\n job_id='synthetic'\n def start_job(self): pass\nclass Connection:\n def create_job(self, process_graph, title):\n  print(json.dumps({'graph':process_graph,'title':title},ensure_ascii=False))\n  return Job()\nconnection=Connection()\n`;
    const output = spawnSync("python3", ["-c", stub + code], {
      encoding: "utf8",
    });
    expect(output.status).toBe(0);
    expect(JSON.parse(output.stdout.split("\n")[0]!)).toEqual({
      graph,
      title: '测区 "春季"\n合成',
    });
  });
  it("rejects malformed top-level arrays and incomplete process nodes", () => {
    expect(() => parseGraph("[]")).toThrow();
    expect(() => parseGraph('{"node":{"process_id":"mean"}}')).toThrow();
    expect(
      parseGraph(
        '{"process_graph":{"n":{"process_id":"mean","arguments":{"data":[1]},"result":true}}}',
      ),
    ).toHaveProperty("n.result", true);
  });
  it("keeps download names inside a same-origin encoded route", () => {
    expect(assetUrl("job-id", "result 01.nc")).toBe(
      "/workbench/jobs/job-id/files/result%2001.nc",
    );
  });
  it("waits for an earlier layer before consuming later map view or clear intents", () => {
    const parent = job("parent", {
      events: [
        {
          type: "map_layer",
          job_id: "child",
          name: "NDVI",
          vis_params: {},
          shown: true,
          opacity: 1,
        },
        { type: "map_view", center: [113, 22], zoom: 13 },
        { type: "map_clear" },
      ],
    });
    expect(
      readyMapEvents(
        [parent, job("child", { kind: "batch", status: "running" })],
        new Set(),
      ),
    ).toEqual([]);
    const ready = readyMapEvents(
      [parent, job("child", { kind: "batch" })],
      new Set(),
    );
    expect(ready.map((v) => v.event.type)).toEqual([
      "map_layer",
      "map_view",
      "map_clear",
    ]);
    expect(
      readyMapEvents(
        [parent, job("child", { kind: "batch" })],
        new Set(ready.map((v) => v.key)),
      ),
    ).toEqual([]);
  });
  it("does not replay a previous script map while a newly submitted script has no events", () => {
    const previous = job("previous", { events: [{ type: "map_clear" }] });
    expect(
      readyMapEvents(
        [job("new", { status: "queued" }), previous],
        new Set(),
        "new",
      ),
    ).toEqual([]);
  });
  it("groups only the selected script and its own results, with the script first", () => {
    const jobs = [
      job("other"),
      job("child", { kind: "batch", context: { source_job_id: "parent" } }),
      job("parent"),
      job("unrelated", { kind: "batch", context: { source_job_id: "other" } }),
    ];
    expect(runTasks(jobs, "parent").map((j) => j.id)).toEqual([
      "parent",
      "child",
    ]);
  });
  it("does not call a run completed while a child is still computing or awaiting export", () => {
    expect(
      runSummary([
        job("parent"),
        job("map", { kind: "batch", status: "running" }),
      ]),
    ).toContain("正在计算");
    expect(
      runSummary([
        job("parent"),
        job("export", { kind: "batch", status: "created" }),
      ]),
    ).toContain("导出待启动");
  });
  it("shows a missing-band explanation and the actual script request location", () => {
    const issue = failureInfo(
      "Error: Band selector 'QA60' did not match; available: ['B4','B8']\n at fn (/job/script.js:12:7)",
    );
    expect(issue.title).toBe("缺少波段 QA60");
    expect(issue.location).toEqual({ line: 12, column: 7 });
    expect(issue.doc).toBe("gee-catalog");
  });
  it("recognizes Python script locations without using runtime wrapper frames", () => {
    expect(
      failureInfo(
        'File "/app/gee/script_runner.py", line 20\nFile "/job/script.py", line 8\nValueError: bad input',
      ).location,
    ).toEqual({ line: 8, column: 1 });
  });
});
