import Icon from "../../components/Icon";
import { assetDownloadUrl, type Asset } from "./models";

export default function AssetTable({
  collectionId,
  assets,
  page,
  hasMore,
  busy,
  onPageChange,
  onDone,
}: {
  collectionId: string;
  assets: Asset[];
  page: number;
  hasMore: boolean;
  busy: boolean;
  onPageChange: (page: number) => void;
  onDone: () => void;
}) {
  return (
    <>
      <div className="file-section-heading">
        <h3>已入库影像资产</h3>
        <small>包括供应方同步和本地上传的 COG</small>
      </div>
      <div className="admin-table-wrap">
        <table className="admin-table">
          <thead>
            <tr>
              <th>影像 / 波段</th>
              <th>观测时间</th>
              <th>版本状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {assets.map((asset) => (
              <tr key={asset.item_id + asset.band}>
                <td>
                  <b>{asset.band}.tif</b>
                  <small>{asset.item_id}</small>
                </td>
                <td>{asset.datetime}</td>
                <td>
                  <span
                    className={
                      "admin-badge " + (asset.active ? "positive" : "")
                    }
                  >
                    {asset.active ? "当前版本" : "保留旧版"}
                  </span>
                </td>
                <td>
                  <a
                    className="file-download"
                    href={assetDownloadUrl(
                      collectionId,
                      asset.item_id,
                      asset.band,
                    )}
                    download
                  >
                    <Icon name="download" />
                    下载 COG
                  </a>
                </td>
              </tr>
            ))}
            {!assets.length && (
              <tr>
                <td colSpan={4} className="file-empty">
                  暂无入库资产
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <footer>
        <span>资产第 {page} 页</span>
        <button disabled={page === 1} onClick={() => onPageChange(page - 1)}>
          上一页
        </button>
        <button disabled={!hasMore} onClick={() => onPageChange(page + 1)}>
          下一页
        </button>
        <button disabled={busy} onClick={onDone}>
          完成
        </button>
      </footer>
    </>
  );
}
