import { useCallback, useEffect, useState } from "react";
import { api, errorMessage } from "../../lib/api";
import { apiBase, type Asset, type StoredFile } from "./models";

export default function useFileCatalog(collectionId: string) {
  const [files, setFiles] = useState<StoredFile[]>([]);
  const [assets, setAssets] = useState<Asset[]>([]);
  const [loadError, setLoadError] = useState("");
  const [loading, setLoading] = useState(true);
  const [filePage, setFilePage] = useState(1);
  const [fileTotal, setFileTotal] = useState(0);
  const [moreFiles, setMoreFiles] = useState(false);
  const [assetPage, setAssetPage] = useState(1);
  const [hasMore, setHasMore] = useState(false);

  const refresh = useCallback(async () => {
    const [uploads, rasters] = await Promise.all([
      api<{ data: StoredFile[]; total: number; has_more: boolean }>(
        `${apiBase}/datasets/${encodeURIComponent(collectionId)}/files?page=${filePage}`,
      ),
      api<{ data: Asset[]; has_more: boolean }>(
        `${apiBase}/datasets/${encodeURIComponent(collectionId)}/assets?page=${assetPage}`,
      ),
    ]);
    setFiles(uploads.data);
    setLoadError("");
    setLoading(false);
    setFileTotal(uploads.total);
    setMoreFiles(uploads.has_more);
    setAssets(rasters.data);
    setHasMore(rasters.has_more);
  }, [collectionId, assetPage, filePage]);

  useEffect(() => {
    let alive = true;
    const update = () =>
      void refresh().catch((error) => {
        if (alive) {
          setLoadError(errorMessage(error));
          setLoading(false);
        }
      });
    update();
    const timer = setInterval(update, 3000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [refresh]);

  return {
    files,
    assets,
    loadError,
    loading,
    filePage,
    setFilePage,
    fileTotal,
    moreFiles,
    assetPage,
    setAssetPage,
    hasMore,
    refresh,
  };
}
