import { useState } from "react";
import { motion } from "motion/react";
import Icon from "../components/Icon";
import { errorMessage } from "../lib/api";
import AssetTable from "./files/AssetTable";
import IngestForm from "./files/IngestForm";
import StoredFilesTable from "./files/StoredFilesTable";
import UploadPanel from "./files/UploadPanel";
import useFileCatalog from "./files/useFileCatalog";
import useFileIngest from "./files/useFileIngest";
import useFileUpload from "./files/useFileUpload";
import "./files.css";

export default function FileManager({
  cid,
  title,
  onClose,
  onChanged,
}: {
  cid: string;
  title: string;
  onClose: () => void;
  onChanged: () => void;
}) {
  const [error, setError] = useState("");
  const catalog = useFileCatalog(cid);
  const upload = useFileUpload({
    collectionId: cid,
    refresh: catalog.refresh,
    onChanged,
    setFilePage: catalog.setFilePage,
    setError,
  });
  const ingest = useFileIngest({
    refresh: catalog.refresh,
    onChanged,
    setMessage: upload.setMessage,
    setError,
  });

  function handleDialogKeyDown(event: React.KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape" && !upload.busy) onClose();
    if (event.key !== "Tab") return;
    const elements = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>(
        "button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),a[href]",
      ),
    );
    if (event.shiftKey && document.activeElement === elements[0]) {
      event.preventDefault();
      elements.at(-1)?.focus();
    } else if (!event.shiftKey && document.activeElement === elements.at(-1)) {
      event.preventDefault();
      elements[0]?.focus();
    }
  }

  const refreshFiles = () =>
    void catalog.refresh().catch((reason) => setError(errorMessage(reason)));
  const complete = () => {
    onChanged();
    onClose();
  };

  return (
    <motion.div
      className="admin-dialog-backdrop"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      <motion.section
        className="admin-dialog file-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="file-dialog-title"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        exit={{ opacity: 0, y: 8 }}
        onKeyDown={handleDialogKeyDown}
      >
        <header>
          <div>
            <span className="admin-eyebrow">{cid}</span>
            <h2 id="file-dialog-title">{title} · 文件</h2>
          </div>
          <button
            autoFocus
            className="icon-button"
            aria-label="关闭文件管理"
            onClick={onClose}
            disabled={upload.busy}
          >
            <Icon name="x" />
          </button>
        </header>
        <UploadPanel
          input={upload.input}
          busy={upload.busy}
          message={upload.message}
          progress={upload.progress}
          onUpload={(file) => void upload.upload(file)}
          onPause={upload.abort}
        />
        {(error || catalog.loadError) && (
          <p className="error" role="alert">
            {error || catalog.loadError}
          </p>
        )}
        <StoredFilesTable
          files={catalog.files}
          loading={catalog.loading}
          busy={upload.busy}
          total={catalog.fileTotal}
          page={catalog.filePage}
          more={catalog.moreFiles}
          onRefresh={refreshFiles}
          onPageChange={catalog.setFilePage}
          onIngest={ingest.select}
        />
        {ingest.selected && (
          <IngestForm
            selected={ingest.selected}
            unit={ingest.unit}
            bands={ingest.bands}
            ingesting={ingest.ingesting}
            onUnitChange={ingest.setUnit}
            onBandsChange={ingest.setBands}
            onCancel={() => ingest.setSelected(null)}
            onSubmit={ingest.submitIngest}
          />
        )}
        <AssetTable
          collectionId={cid}
          assets={catalog.assets}
          page={catalog.assetPage}
          hasMore={catalog.hasMore}
          busy={upload.busy}
          onPageChange={catalog.setAssetPage}
          onDone={complete}
        />
      </motion.section>
    </motion.div>
  );
}
