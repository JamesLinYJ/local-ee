/// <reference lib="webworker" />
import { sha256 } from "@noble/hashes/sha2.js";
self.onmessage = async (event: MessageEvent<File>) => {
  try {
    const file = event.data,
      hash = sha256.create();
    for (let offset = 0; offset < file.size; offset += 1024 * 1024) {
      hash.update(
        new Uint8Array(
          await file.slice(offset, offset + 1024 * 1024).arrayBuffer(),
        ),
      );
      self.postMessage({
        progress: Math.min(file.size, offset + 1024 * 1024) / file.size,
      });
    }
    self.postMessage({
      sha256: Array.from(hash.digest(), (v) =>
        v.toString(16).padStart(2, "0"),
      ).join(""),
    });
  } catch {
    self.postMessage({ error: "无法读取文件校验值" });
  }
};
