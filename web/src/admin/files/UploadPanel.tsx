import type { RefObject } from "react";
import Icon from "../../components/Icon";

export default function UploadPanel({
  input,
  busy,
  message,
  progress,
  onUpload,
  onPause,
}: {
  input: RefObject<HTMLInputElement | null>;
  busy: boolean;
  message: string;
  progress: number;
  onUpload: (file: File) => void;
  onPause: () => void;
}) {
  const chooseFile = (file?: File) => {
    if (file) onUpload(file);
  };

  return (
    <>
      <div
        className="file-upload-zone"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          chooseFile(event.dataTransfer.files[0]);
        }}
      >
        <Icon name="upload" />
        <div>
          <b>上传数据文件</b>
          <p>
            拖入或选择文件 · 单文件最多 512 MiB · 支持分块续传与 SHA-256 校验
          </p>
          <small>
            GeoTIFF 可标准化入库；NetCDF、CSV、GeoJSON、JSON 可先存储和下载。
          </small>
        </div>
        <label className="file-button">
          <input
            ref={input}
            type="file"
            aria-label="上传数据文件"
            accept=".tif,.tiff,.nc,.csv,.geojson,.json"
            disabled={busy}
            onChange={(event) => chooseFile(event.target.files?.[0])}
          />
          选择文件
        </label>
      </div>
      {(busy || message) && (
        <div className="file-progress">
          <span role="status">{message}</span>
          {busy && (
            <>
              <progress max={100} value={progress} />
              <span>{Math.round(progress)}%</span>
              <button onClick={onPause}>暂停</button>
            </>
          )}
        </div>
      )}
    </>
  );
}
